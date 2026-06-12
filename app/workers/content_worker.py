import subprocess
from pathlib import Path
from datetime import datetime

from app.config import settings
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService
from app.services.social_publish_service import SocialPublishService
from app.services.stock_video_service import StockVideoService
from app.services.storage_service import StorageService
from app.services.subtitle_service import estimate_ass_from_text
from app.services.subtitle_service import srt_to_ass
from app.services.telegram_service import TelegramService
from app.services.video_compose_service import VideoComposeService
from app.services.voice_service import VoiceService


def main() -> None:
    queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
    llm = LLMService()
    storage = StorageService()
    voice = VoiceService()
    stock_video = StockVideoService()
    composer = VideoComposeService()
    social = SocialPublishService()
    telegram = TelegramService()

    while True:
        payload = queue.dequeue_blocking(timeout_seconds=0)
        if not payload:
            continue

        job_id = payload["job_id"]
        if queue.is_job_deleted(job_id):
            continue
        mode = payload["mode"]
        topic = payload["topic"]
        language = payload["language"]
        tone = payload["tone"]
        use_gemini_refine = payload["use_gemini_refine"]
        create_audio = payload["create_audio"]
        create_video = payload.get("create_video", False)
        video_source_type = payload.get("video_source_type", "internet")
        video_keyword = payload.get("video_keyword") or topic
        user_video_path = payload.get("user_video_path")
        notify_telegram = bool(payload.get("notify_telegram", False))
        notify_chat_id = payload.get("telegram_chat_id") or settings.telegram_chat_id

        def set_running_status(stage: str, percent: int, detail: str) -> None:
            queue.set_job_status(
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "status": "running",
                    "mode": mode,
                    "topic": topic,
                    "started_at": datetime.utcnow().isoformat(),
                    "current_stage": stage,
                    "progress_percent": percent,
                    "stage_detail": detail,
                    "payload": payload,
                },
            )

        try:
            content = ""
            markdown_path = ""
            audio_path = ""
            srt_content = ""
            audio_error = ""
            audio_duration_sec = None

            # === Step 1: Generate content ===
            set_running_status(stage="generating_content", percent=10, detail="Writing script")
            content = llm.generate(
                mode=mode,
                topic=topic,
                tone=tone,
                language=language,
                use_gemini_refine=use_gemini_refine,
                feedback_note=None,
            )
            markdown_path = storage.save_markdown(job_id=job_id, content=content)

            # === Step 2: Generate audio ===
            if create_audio:
                set_running_status(stage="generating_audio", percent=35, detail="Creating voiceover")
                tts_text = content[:5000]
                is_english = language.lower().startswith("en")
                kokoro_voice = payload.get("kokoro_voice") or "af_heart"

                try:
                    audio_path = voice.synthesize_kokoro(
                        text=tts_text,
                        output_name=f"{job_id}.mp3",
                        voice_name=kokoro_voice,
                    )
                except Exception as kokoro_exc:
                    audio_error = f"kokoro: {kokoro_exc}"
                    audio_path = ""

                # Get audio duration
                if audio_path:
                    try:
                        probe = subprocess.run(
                            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                            capture_output=True, text=True, timeout=15,
                        )
                        if probe.returncode == 0 and probe.stdout.strip():
                            audio_duration_sec = float(probe.stdout.strip())
                    except Exception:
                        pass
                    if not audio_duration_sec or audio_duration_sec <= 0:
                        speaking_rate = 5.0 if is_english else 6.0
                        audio_duration_sec = len(content) / speaking_rate

            # === Step 3: Auto-compose video immediately (no review step) ===
            video_path = ""
            video_source = ""
            if create_video:
                set_running_status(stage="preparing_video", percent=55, detail="Preparing video source")
                source_path = ""
                if video_source_type == "internet":
                    clip_path, clip_source = stock_video.fetch(
                        keyword=video_keyword,
                        job_id=job_id,
                        preferred_size=settings.video_size,
                    )
                    source_path = clip_path
                    video_source = clip_source
                else:
                    if not user_video_path or not Path(user_video_path).exists():
                        raise RuntimeError(
                            "video_source_type=self but user video is missing. Upload video first or choose internet"
                        )
                    source_path = user_video_path
                    video_source = "web-upload-user-video"

                # Generate subtitle ASS file
                subtitle_path: str | None = None
                if settings.video_burn_subtitles and audio_path:
                    ass_out = str(Path("/app/data/outputs") / f"{job_id}.ass")
                    try:
                        subtitle_path = estimate_ass_from_text(
                            text=content[:5000] if content else "",
                            audio_path=audio_path,
                            output_path=ass_out,
                        ) or None
                    except Exception:
                        subtitle_path = None

                set_running_status(stage="composing_video", percent=75, detail="Rendering final video")
                video_path = composer.compose(
                    job_id=job_id,
                    source_video_path=source_path,
                    audio_path=audio_path or None,
                    title=topic,
                    preserve_quality=settings.video_preserve_quality,
                    overlay_text=settings.video_text_overlay,
                    subtitle_path=subtitle_path,
                    audio_duration_sec=audio_duration_sec,
                )

            # === Final: Mark completed ===
            set_running_status(stage="completed", percent=100, detail="Done")
            queue.set_job_status(
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "status": "completed",
                    "mode": mode,
                    "topic": topic,
                    "completed_at": datetime.utcnow().isoformat(),
                    "current_stage": "completed",
                    "progress_percent": 100,
                    "stage_detail": "Done",
                    "outputs": {
                        "markdown_path": markdown_path,
                        "audio_path": audio_path or None,
                        "audio_error": audio_error or None,
                        "video_path": video_path or None,
                        "video_source": video_source or None,
                    },
                    "payload": payload,
                },
            )

            if notify_telegram and notify_chat_id and telegram.enabled:
                if video_path:
                    try:
                        telegram.send_file_to_chat(
                            chat_id=notify_chat_id,
                            file_path=video_path,
                            caption=f"[{job_id}] {topic}",
                        )
                    except Exception:
                        pass
                telegram.send_to_chat(
                    chat_id=notify_chat_id,
                    text=f"[{job_id}] Done\nTopic: {topic}",
                )

        except Exception as exc:
            queue.set_job_status(
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "status": "failed",
                    "mode": mode,
                    "topic": topic,
                    "failed_at": datetime.utcnow().isoformat(),
                    "error": str(exc),
                    "payload": payload,
                },
            )
            if notify_telegram and notify_chat_id and telegram.enabled:
                telegram.send_to_chat(
                    chat_id=notify_chat_id,
                    text=f"[{job_id}] Failed\nTopic: {topic}\nError: {exc}",
                )


if __name__ == "__main__":
    main()