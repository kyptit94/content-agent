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
from app.services.soundscape_service import SoundscapeService


def _clean_content_for_tts(content: str) -> str:
    """Remove AI conversational wrapper phrases and markdown from content for TTS."""
    import re
    lines = content.splitlines()
    cleaned_lines = []
    # Patterns that indicate AI chat wrapper (skip these lines entirely)
    chat_wrapper_re = re.compile(
        r"^(Of course!|Here'?s a|Let me|I'?ll|I will|Sure!|Absolutely!|"
        r"Got it|Great!|Perfect!|Certainly!|Here you go|Check this out|"
        r"Here is|Allow me|I hope|Feel free|Let me know|Would you like|"
        r"What do you think|I'?m happy|Happy to|Glad to|No problem|"
        r"My pleasure|You'?re welcome|I think|I believe|"
        r"Rất tốt!|Tôi sẽ|Bạn muốn|Rất vui|Đây là|Tuyệt vời|Được rồi)",
        re.IGNORECASE
    )
    for line in lines:
        stripped = line.strip()
        # Skip empty lines
        if not stripped:
            continue
        # Skip AI chat wrapper lines
        if chat_wrapper_re.match(stripped):
            continue
        # Skip markdown headers (### Title)
        if re.match(r"^#{1,6}\s", stripped):
            continue
        # Skip separator lines (---, ***, ___)
        if re.match(r"^[-*_]{3,}$", stripped):
            continue
        # Skip "--- IDEA ---" markers
        if re.match(r"^---\s*IDEA\s*---", stripped, re.IGNORECASE):
            continue
        cleaned_lines.append(line)
    # Re-join and trim leading/trailing empty lines
    result = "\n".join(cleaned_lines).strip()
    # If after cleaning we still have "###" as the first meaningful line, strip it
    result = re.sub(r"^###\s*[^\n]*\n?", "", result)
    return result.strip()


def main() -> None:
    queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
    llm = LLMService()
    storage = StorageService()
    voice = VoiceService()
    stock_video = StockVideoService()
    composer = VideoComposeService()
    soundscape = SoundscapeService()
    social = SocialPublishService()
    telegram = TelegramService()

    while True:
        payload = queue.dequeue_blocking(timeout_seconds=0)
        if not payload:
            continue

        job_id = payload["job_id"]
        if queue.is_job_deleted(job_id):
            continue

        mode = payload.get("mode", "horror")
        title = payload.get("title", payload.get("topic", ""))
        content = payload.get("content", "")
        language = payload.get("language", "en")
        tone = payload.get("tone", "friendly")
        use_gemini_refine = payload.get("use_gemini_refine", False)
        create_audio = payload.get("create_audio", True)
        create_video = payload.get("create_video", False)
        video_source_type = payload.get("video_source_type", "internet")
        video_keyword = payload.get("video_keyword") or title
        user_video_path = payload.get("user_video_path")
        user_image_path = payload.get("user_image_path")
        notify_telegram = bool(payload.get("notify_telegram", False))
        notify_chat_id = payload.get("telegram_chat_id") or settings.telegram_chat_id

        def set_running_status(stage: str, percent: int, detail: str) -> None:
            queue.set_job_status(
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "status": "running",
                    "mode": mode,
                    "title": title,
                    "started_at": datetime.utcnow().isoformat(),
                    "current_stage": stage,
                    "progress_percent": percent,
                    "stage_detail": detail,
                    "payload": payload,
                },
            )

        try:
            markdown_path = ""
            audio_path = ""
            srt_content = ""
            audio_error = ""
            audio_duration_sec = None

            # === Notify Telegram on start ===
            if notify_telegram and notify_chat_id and telegram.enabled:
                telegram.send_to_chat(
                    chat_id=notify_chat_id,
                    text=f"🚀 Job started: [{job_id}] {title}\nMode: {mode}",
                )

            # === Save pre-generated content to markdown ===
            set_running_status(stage="saving_content", percent=10, detail="Saving selected script")
            if not content:
                raise RuntimeError("No content provided — please select a content option first")
            markdown_path = storage.save_markdown(job_id=job_id, content=content)

            # === Generate audio ===
            if create_audio:
                set_running_status(stage="generating_audio", percent=35, detail="Creating voiceover")
                # Strip AI conversational wrapper from TTS content
                tts_text = _clean_content_for_tts(content)
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

                # === Add background music + sound effects (works for audio-only AND video) ===
                if audio_path and Path(audio_path).exists():
                    set_running_status(stage="adding_soundscape", percent=50, detail="Adding music & sound effects")
                    try:
                        mixed = soundscape.process(job_id, content, audio_path)
                        if mixed and mixed != audio_path:
                            audio_path = mixed
                    except Exception:
                        pass

            # === Auto-compose video ===
            video_path = ""
            video_source = ""
            if create_video:
                set_running_status(stage="preparing_video", percent=55, detail="Preparing video source")
                source_path = ""
                if user_image_path and Path(user_image_path).exists():
                    source_path = user_image_path
                    video_source = "web-upload-user-image"
                elif video_source_type == "internet":
                    keywords = llm.extract_video_keywords(content, language)
                    clip_paths = stock_video.fetch_multiple(
                        keywords=keywords,
                        job_id=job_id,
                        preferred_size=settings.video_size,
                    )
                    concat_out = Path("/app/data/outputs") / f"{job_id}_concat.mp4"
                    target_dur = audio_duration_sec or 45.0
                    source_path = StockVideoService.concat_clips(clip_paths, concat_out, target_dur)
                    video_source = f"pexels/pixabay: {', '.join(keywords)}"
                else:
                    if not user_video_path or not Path(user_video_path).exists():
                        raise RuntimeError(
                            "video_source_type=self but user video is missing. Upload video/image first or choose internet"
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
                    title=title,
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
                    "title": title,
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
                            caption=f"[{job_id}] {title}",
                        )
                    except Exception:
                        pass
                telegram.send_to_chat(
                    chat_id=notify_chat_id,
                    text=f"[{job_id}] Done\nTitle: {title}",
                )

        except Exception as exc:
            queue.set_job_status(
                job_id=job_id,
                payload={
                    "job_id": job_id,
                    "status": "failed",
                    "mode": mode,
                    "title": title,
                    "failed_at": datetime.utcnow().isoformat(),
                    "error": str(exc),
                    "payload": payload,
                },
            )
            if notify_telegram and notify_chat_id and telegram.enabled:
                telegram.send_to_chat(
                    chat_id=notify_chat_id,
                    text=f"[{job_id}] Failed\nTitle: {title}\nError: {exc}",
                )


if __name__ == "__main__":
    main()