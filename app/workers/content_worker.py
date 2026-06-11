from pathlib import Path
from datetime import datetime

from app.config import settings
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService
from app.services.social_publish_service import SocialPublishService
from app.services.stock_video_service import StockVideoService
from app.services.storage_service import StorageService
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
        feedback_note = payload.get("feedback_note")
        feedback_round = payload.get("feedback_round", 0)
        revision_of_job_id = payload.get("revision_of_job_id")
        notify_telegram = bool(payload.get("notify_telegram", False))
        notify_chat_id = payload.get("telegram_chat_id") or settings.telegram_chat_id
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
                "payload": payload,
            },
        )

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
            if create_audio:
                if voice_sample:
                    audio_path = voice.synthesize(
                        text=content[:2200],
                        language=language,
                        speaker_wav=f"/app/data/voices/{voice_sample}",
                        output_name=f"{job_id}.wav",
                    )
                else:
                    audio_path = voice.synthesize_edge(
                        text=content[:2200],
                        output_name=f"{job_id}.mp3",
                    )

            video_path = ""
            video_source = ""
            if create_video:
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

                if (
                    source_path == user_video_path
                    and settings.video_preserve_quality
                    and not audio_path
                    and not settings.video_text_overlay
                ):
                    video_path = source_path
                else:
                    video_path = composer.compose(
                        job_id=job_id,
                        source_video_path=source_path,
                        audio_path=audio_path or None,
                        title=topic,
                        preserve_quality=settings.video_preserve_quality,
                        overlay_text=settings.video_text_overlay,
                    )

            publish_results: list[str] = []
            if video_path and settings.auto_publish_enabled:
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
                    "outputs": {
                        "markdown_path": markdown_path,
                        "audio_path": audio_path or None,
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
