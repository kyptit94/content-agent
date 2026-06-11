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
        video_source_type = payload.get("video_source_type", "self")
        video_keyword = payload.get("video_keyword") or topic
        user_video_path = payload.get("user_video_path")
        voice_sample = payload.get("voice_sample_filename")
        edge_tts_voice = payload.get("edge_tts_voice") or settings.edge_tts_voice
        feedback_note = payload.get("feedback_note")
        feedback_round = payload.get("feedback_round", 0)
        revision_of_job_id = payload.get("revision_of_job_id")
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
                    "feedback_round": feedback_round,
                    "revision_of_job_id": revision_of_job_id,
                    "started_at": datetime.utcnow().isoformat(),
                    "current_stage": stage,
                    "progress_percent": percent,
                    "stage_detail": detail,
                    "payload": payload,
                },
            )

        set_running_status(stage="generating_content", percent=10, detail="Đang viết nội dung")

        try:
            content = llm.generate(
                mode=mode,
                topic=topic,
                tone=tone,
                language=language,
                use_gemini_refine=use_gemini_refine,
                feedback_note=feedback_note,
            )
            markdown_path = storage.save_markdown(job_id=job_id, content=content)

            audio_path = ""
            srt_content = ""
            audio_error = ""
            audio_duration_sec = None
            if create_audio:
                set_running_status(stage="generating_audio", percent=45, detail="Đang tạo audio")
                # Truncate content if too long for TTS (safety limit)
                tts_text = content[:5000]

                # Determine which TTS engine to use
                use_xtts = bool(voice_sample)  # if user has voice sample, try XTTS first
                use_edge = True  # always fallback to edge-tts

                if use_xtts:
                    try:
                        audio_path = voice.synthesize(
                            text=tts_text,
                            language=language,
                            speaker_wav=f"/app/data/voices/{voice_sample}",
                            output_name=f"{job_id}.wav",
                        )
                    except Exception as audio_exc:
                        audio_error = str(audio_exc)
                        audio_path = ""

                if not audio_path:
                    # Fallback to edge-tts (with or without voice sample)
                    try:
                        audio_path, srt_content = voice.synthesize_edge_with_subs(
                            text=tts_text,
                            output_name=f"{job_id}.mp3",
                            voice_name=edge_tts_voice,
                        )
                    except Exception as audio_exc:
                        audio_error = f"{audio_error} | edge_tts: {audio_exc}" if audio_error else str(audio_exc)
                        audio_path = ""

                # Compute audio duration from content (rough estimate)
                # Vietnamese ~6 chars/sec speaking rate, English ~5 chars/sec
                if audio_path:
                    speaking_rate = 5.0 if language.lower().startswith("en") else 6.0
                    # Use audio file duration if possible
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
                        # Fallback to rough estimate
                        audio_duration_sec = len(content) / speaking_rate

            video_path = ""
            video_source = ""
            if create_video:
                set_running_status(stage="preparing_video", percent=65, detail="Đang chuẩn bị video")
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
                        if srt_content:
                            subtitle_path = srt_to_ass(srt_content, ass_out)
                        else:
                            subtitle_path = estimate_ass_from_text(
                                text=content[:5000],
                                audio_path=audio_path,
                                output_path=ass_out,
                            ) or None
                    except Exception:
                        subtitle_path = None

                if (
                    source_path == user_video_path
                    and settings.video_preserve_quality
                    and not audio_path
                    and not settings.video_text_overlay
                    and not subtitle_path
                ):
                    video_path = source_path
                else:
                    set_running_status(stage="composing_video", percent=82, detail="Đang ghép video và audio")
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

            publish_results: list[str] = []
            if video_path and settings.auto_publish_enabled:
                set_running_status(stage="publishing", percent=92, detail="Đang đẩy video đi publish")
                publish_description = (
                    f"{topic}\n\n"
                    f"{content[:800]}\n\n"
                    f"#shorts #book #story"
                )
                publish_results = social.publish_video(
                    job_id=job_id,
                    title=topic,
                    description=publish_description,
                    video_path=video_path,
                )

            queue.set_job_status(
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "status": "completed",
                    "mode": mode,
                    "topic": topic,
                    "feedback_round": feedback_round,
                    "revision_of_job_id": revision_of_job_id,
                    "completed_at": datetime.utcnow().isoformat(),
                    "current_stage": "completed",
                    "progress_percent": 100,
                    "stage_detail": "Đã hoàn tất",
                    "outputs": {
                        "markdown_path": markdown_path,
                        "audio_path": audio_path or None,
                        "audio_error": audio_error or None,
                        "video_path": video_path or None,
                        "video_source": video_source or None,
                    },
                    "auto_publish": publish_results,
                    "payload": payload,
                },
            )

            if notify_telegram and notify_chat_id and telegram.enabled:
                telegram_error = None
                if video_path:
                    try:
                        telegram.send_file_to_chat(
                            chat_id=notify_chat_id,
                            file_path=video_path,
                            caption=f"[{job_id}] Video hoàn tất\nTopic: {topic}",
                        )
                    except Exception as exc:
                        telegram_error = exc
                telegram.send_to_chat(
                    chat_id=notify_chat_id,
                    text=(
                        f"[{job_id}] Completed\n"
                        f"Topic: {topic}\n"
                        f"Video: {video_path or 'n/a'}\n"
                        f"Audio: {audio_path or 'n/a'}"
                    ),
                )
                if telegram_error:
                    telegram.send_to_chat(
                        chat_id=notify_chat_id,
                        text=f"[{job_id}] Video xong nhưng không gửi được file: {telegram_error}",
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
