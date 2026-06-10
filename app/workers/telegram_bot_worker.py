import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from app.config import settings
from app.schemas import JobPayload
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService
from app.services.telegram_service import TelegramService


HELP_TEXT = (
    "Lenh chatbot:\n"
    "/start - bat dau\n"
    "/new - tao job theo tung buoc\n"
    "/task <sales|story> | <topic> | <tone tuy chon>\n"
    "/ok - duyet chu de goi y de chay\n"
    "/skip - bo qua chu de goi y hien tai\n"
    "/autotopic <on|off> - bat/tat gui chu de dinh ky\n"
    "/autotopicmode <sales|story> - kieu chu de dinh ky\n"
    "/feedback <ghi chu ngan> - sua 1 vong tu job gan nhat\n"
    "Gui file video (.mp4/.mov) truc tiep cho bot de dung video ban quay\n"
    "/clearvideo - xoa video nguon da tai len\n"
    "/voice <file.wav> - dat file giong mac dinh trong /data/voices\n"
    "/audio <on|off> - bat/tat tao audio\n"
    "/video <on|off> - bat/tat tao video\n"
    "/videokw <keyword> - tu khoa tim video stock\n"
    "/gemini <on|off> - bat/tat refine Gemini\n"
    "/lang <vi|en|...> - dat ngon ngu\n"
    "/settings - xem cau hinh hien tai\n"
    "/cancel - huy tac vu dang nhap"
)


def _default_profile() -> dict:
    return {
        "language": "vi",
        "tone": "friendly",
        "create_audio": True,
        "create_video": False,
        "use_gemini_refine": False,
        "voice_sample_filename": None,
        "video_keyword": None,
        "last_job": None,
        "auto_topic_enabled": True,
        "auto_topic_mode": settings.auto_topic_default_mode,
        "next_topic_at": int(time.time()) + max(60, settings.auto_topic_interval_minutes * 60),
        "pending_topic": None,
        "uploaded_video_path": None,
    }


def _parse_bool(raw: str) -> bool | None:
    value = raw.strip().lower()
    if value in {"on", "true", "1", "yes"}:
        return True
    if value in {"off", "false", "0", "no"}:
        return False
    return None


def _normalize_mode(raw: str) -> str | None:
    text = raw.strip().lower()
    if text in {"sales", "ban sach", "bansach"}:
        return "sales"
    if text in {"story", "ke chuyen", "kechuyen"}:
        return "story"
    return None


def _enqueue_job(
    queue: QueueService,
    profile: dict,
    chat_id: int,
    mode: str,
    topic: str,
    tone: str | None = None,
    feedback_note: str | None = None,
    revision_of_job_id: str | None = None,
    feedback_round: int = 0,
) -> str:
    payload = JobPayload(
        job_id=str(uuid4()),
        created_at=datetime.utcnow().isoformat(),
        mode=mode,
        topic=topic,
        language=profile["language"],
        tone=tone or profile["tone"],
        use_gemini_refine=profile["use_gemini_refine"],
        create_audio=profile["create_audio"],
        create_video=profile["create_video"],
        user_video_path=profile.get("uploaded_video_path"),
        voice_sample_filename=profile["voice_sample_filename"],
        video_keyword=profile["video_keyword"],
        feedback_note=feedback_note,
        revision_of_job_id=revision_of_job_id,
        feedback_round=feedback_round,
    ).model_dump()
    payload["telegram_chat_id"] = str(chat_id)

    if payload["create_audio"] and not payload["voice_sample_filename"]:
        payload["create_audio"] = False

    queue.enqueue(payload)
    return payload["job_id"]


def main() -> None:
    queue = QueueService(redis_url=settings.redis_url, queue_name=settings.job_queue_name)
    telegram = TelegramService()
    llm = LLMService()

    if not telegram.enabled:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required for telegram bot worker")

    profiles: dict[int, dict] = {}
    sessions: dict[int, dict] = {}
    offset: int | None = None

    def schedule_topics() -> None:
        now = int(time.time())
        interval_sec = max(60, settings.auto_topic_interval_minutes * 60)

        for chat_id, profile in profiles.items():
            if not profile.get("auto_topic_enabled", True):
                continue
            if profile.get("pending_topic"):
                continue
            if now < int(profile.get("next_topic_at", 0)):
                continue

            mode = profile.get("auto_topic_mode", settings.auto_topic_default_mode)
            if mode not in {"sales", "story"}:
                mode = settings.auto_topic_default_mode

            topic = llm.suggest_topic(mode=mode, language=profile.get("language", "vi"))
            profile["pending_topic"] = {
                "mode": mode,
                "topic": topic,
                "tone": profile.get("tone", "friendly"),
            }
            profile["next_topic_at"] = now + interval_sec

            telegram.send_to_chat(
                chat_id,
                "Chu de goi y moi (chu ky 15p):\n"
                f"- mode: {mode}\n"
                f"- topic: {topic}\n\n"
                "Tra loi /ok de lam ngay hoac /skip de bo qua.",
            )

    while True:
        schedule_topics()
        updates = telegram.get_updates(offset=offset, timeout_seconds=30)
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1

            message = update.get("message", {})
            chat = message.get("chat", {})
            chat_id = chat.get("id")
            if not chat_id:
                continue

            if chat_id not in profiles:
                profiles[chat_id] = _default_profile()
            profile = profiles[chat_id]

            # Accept user-shot video uploads from Telegram (video or document).
            video_obj = message.get("video")
            document_obj = message.get("document")
            file_id = ""
            filename = ""
            if isinstance(video_obj, dict):
                file_id = video_obj.get("file_id", "")
                filename = f"{chat_id}_{int(time.time())}.mp4"
            elif isinstance(document_obj, dict):
                mime_type = str(document_obj.get("mime_type", "")).lower()
                document_name = str(document_obj.get("file_name", ""))
                is_video_doc = mime_type.startswith("video/") or document_name.lower().endswith((".mp4", ".mov", ".mkv"))
                if is_video_doc:
                    file_id = document_obj.get("file_id", "")
                    filename = document_name or f"{chat_id}_{int(time.time())}.mp4"

            if file_id:
                safe_name = Path(filename).name
                local_target = f"/app/data/uploads/{chat_id}/{int(time.time())}_{safe_name}"
                tg_file_path = telegram.get_file_path(file_id=file_id)
                local_path = telegram.download_file(file_path=tg_file_path, destination_path=local_target)
                profile["uploaded_video_path"] = local_path
                profile["create_video"] = True
                telegram.send_to_chat(
                    chat_id,
                    "Da nhan video cua ban. Tu gio job se uu tien dung video nay de tranh rui ro ban quyen."
                    "\nNeu muon bo video nay, gui /clearvideo",
                )
                continue

            text = (message.get("text") or "").strip()
            if not text:
                continue

            if text.startswith("/start"):
                telegram.send_to_chat(chat_id, "Chao ban. Day la AI agent nhan viec qua chat.\n\n" + HELP_TEXT)
                continue

            if text.startswith("/settings"):
                telegram.send_to_chat(
                    chat_id,
                    "Cau hinh hien tai:\n"
                    f"- language: {profile['language']}\n"
                    f"- tone: {profile['tone']}\n"
                    f"- create_audio: {profile['create_audio']}\n"
                    f"- create_video: {profile['create_video']}\n"
                    f"- use_gemini_refine: {profile['use_gemini_refine']}\n"
                    f"- voice_sample_filename: {profile['voice_sample_filename'] or 'none'}\n"
                    f"- video_keyword: {profile['video_keyword'] or 'auto topic'}\n"
                    f"- feedback_max_rounds: {settings.feedback_max_rounds}\n"
                    f"- auto_topic_enabled: {profile['auto_topic_enabled']}\n"
                    f"- auto_topic_mode: {profile['auto_topic_mode']}\n"
                    f"- auto_topic_interval_minutes: {settings.auto_topic_interval_minutes}\n"
                    f"- uploaded_video_path: {profile.get('uploaded_video_path') or 'none'}",
                )
                continue

            if text.startswith("/clearvideo"):
                profile["uploaded_video_path"] = None
                telegram.send_to_chat(chat_id, "Da bo video nguon. Job sau se quay lai che do video stock (neu /video on).")
                continue

            if text.startswith("/ok"):
                pending = profile.get("pending_topic")
                if not pending:
                    telegram.send_to_chat(chat_id, "Khong co chu de dang cho duyet.")
                    continue

                job_id = _enqueue_job(
                    queue=queue,
                    profile=profile,
                    chat_id=chat_id,
                    mode=pending["mode"],
                    topic=pending["topic"],
                    tone=pending.get("tone") or profile["tone"],
                )
                profile["last_job"] = {
                    "job_id": job_id,
                    "root_job_id": job_id,
                    "mode": pending["mode"],
                    "topic": pending["topic"],
                    "tone": pending.get("tone") or profile["tone"],
                    "feedback_round": 0,
                }
                profile["pending_topic"] = None
                profile["next_topic_at"] = int(time.time()) + max(60, settings.auto_topic_interval_minutes * 60)
                telegram.send_to_chat(chat_id, f"Da duyet chu de. Job ID: {job_id}")
                continue

            if text.startswith("/skip"):
                if profile.get("pending_topic"):
                    profile["pending_topic"] = None
                    profile["next_topic_at"] = int(time.time()) + max(60, settings.auto_topic_interval_minutes * 60)
                    telegram.send_to_chat(chat_id, "Da bo qua chu de hien tai.")
                else:
                    telegram.send_to_chat(chat_id, "Khong co chu de dang cho duyet.")
                continue

            if text.startswith("/autotopicmode"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /autotopicmode sales hoac /autotopicmode story")
                    continue
                mode = _normalize_mode(parts[1])
                if not mode:
                    telegram.send_to_chat(chat_id, "Mode khong hop le. Dung sales hoac story")
                    continue
                profile["auto_topic_mode"] = mode
                telegram.send_to_chat(chat_id, f"auto_topic_mode = {mode}")
                continue

            if text.startswith("/autotopic"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /autotopic on hoac /autotopic off")
                    continue
                value = _parse_bool(parts[1])
                if value is None:
                    telegram.send_to_chat(chat_id, "Gia tri khong hop le. Dung on/off")
                    continue
                profile["auto_topic_enabled"] = value
                if value:
                    profile["next_topic_at"] = int(time.time()) + max(60, settings.auto_topic_interval_minutes * 60)
                telegram.send_to_chat(chat_id, f"auto_topic_enabled = {value}")
                continue

            if text.startswith("/feedback"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /feedback ngan gon, vi du: /feedback gan gui hon")
                    continue

                note = parts[1].strip()
                if len(note) > settings.feedback_note_max_chars:
                    telegram.send_to_chat(
                        chat_id,
                        f"Feedback qua dai. Toi da {settings.feedback_note_max_chars} ky tu.",
                    )
                    continue

                last_job = profile.get("last_job")
                if not last_job:
                    telegram.send_to_chat(chat_id, "Chua co job gan nhat de feedback. Hay giao 1 job truoc.")
                    continue

                current_round = int(last_job.get("feedback_round", 0))
                if current_round >= settings.feedback_max_rounds:
                    telegram.send_to_chat(
                        chat_id,
                        f"Da het so vong feedback ({settings.feedback_max_rounds}). Hay giao job moi.",
                    )
                    continue

                new_round = current_round + 1
                job_id = _enqueue_job(
                    queue=queue,
                    profile=profile,
                    chat_id=chat_id,
                    mode=last_job["mode"],
                    topic=last_job["topic"],
                    tone=last_job.get("tone") or profile["tone"],
                    feedback_note=note,
                    revision_of_job_id=last_job.get("root_job_id") or last_job["job_id"],
                    feedback_round=new_round,
                )
                profile["last_job"] = {
                    "job_id": job_id,
                    "root_job_id": last_job.get("root_job_id") or last_job["job_id"],
                    "mode": last_job["mode"],
                    "topic": last_job["topic"],
                    "tone": last_job.get("tone") or profile["tone"],
                    "feedback_round": new_round,
                }
                telegram.send_to_chat(chat_id, f"Da tao ban sua feedback (vong {new_round}). Job ID: {job_id}")
                continue

            if text.startswith("/voice"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /voice my_voice.wav")
                    continue
                profile["voice_sample_filename"] = parts[1].strip()
                telegram.send_to_chat(chat_id, f"Da dat voice sample: {profile['voice_sample_filename']}")
                continue

            if text.startswith("/audio"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /audio on hoac /audio off")
                    continue
                value = _parse_bool(parts[1])
                if value is None:
                    telegram.send_to_chat(chat_id, "Gia tri khong hop le. Dung on/off")
                    continue
                profile["create_audio"] = value
                telegram.send_to_chat(chat_id, f"create_audio = {value}")
                continue

            if text.startswith("/video"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /video on hoac /video off")
                    continue
                value = _parse_bool(parts[1])
                if value is None:
                    telegram.send_to_chat(chat_id, "Gia tri khong hop le. Dung on/off")
                    continue
                profile["create_video"] = value
                telegram.send_to_chat(chat_id, f"create_video = {value}")
                continue

            if text.startswith("/videokw"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /videokw book reading")
                    continue
                profile["video_keyword"] = parts[1].strip()
                telegram.send_to_chat(chat_id, f"video_keyword = {profile['video_keyword']}")
                continue

            if text.startswith("/gemini"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /gemini on hoac /gemini off")
                    continue
                value = _parse_bool(parts[1])
                if value is None:
                    telegram.send_to_chat(chat_id, "Gia tri khong hop le. Dung on/off")
                    continue
                profile["use_gemini_refine"] = value
                telegram.send_to_chat(chat_id, f"use_gemini_refine = {value}")
                continue

            if text.startswith("/lang"):
                parts = text.split(maxsplit=1)
                if len(parts) < 2:
                    telegram.send_to_chat(chat_id, "Dung: /lang vi")
                    continue
                profile["language"] = parts[1].strip().lower()
                telegram.send_to_chat(chat_id, f"language = {profile['language']}")
                continue

            if text.startswith("/cancel"):
                sessions.pop(chat_id, None)
                telegram.send_to_chat(chat_id, "Da huy phien tao job.")
                continue

            if text.startswith("/new"):
                sessions[chat_id] = {"step": "mode"}
                telegram.send_to_chat(chat_id, "Ban muon tao loai nao? Tra loi: sales hoac story")
                continue

            if text.startswith("/task"):
                parts = text[len("/task") :].strip().split("|")
                if len(parts) < 2:
                    telegram.send_to_chat(
                        chat_id,
                        "Dung: /task sales | Chu de cua ban | tone tuy chon",
                    )
                    continue
                mode = _normalize_mode(parts[0])
                if not mode:
                    telegram.send_to_chat(chat_id, "Mode khong hop le. Dung sales hoac story")
                    continue
                topic = parts[1].strip()
                tone = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
                job_id = _enqueue_job(
                    queue=queue,
                    profile=profile,
                    chat_id=chat_id,
                    mode=mode,
                    topic=topic,
                    tone=tone,
                )
                profile["last_job"] = {
                    "job_id": job_id,
                    "root_job_id": job_id,
                    "mode": mode,
                    "topic": topic,
                    "tone": tone or profile["tone"],
                    "feedback_round": 0,
                }
                telegram.send_to_chat(chat_id, f"Da nhan viec. Job ID: {job_id}")
                continue

            session = sessions.get(chat_id)
            if session:
                if session["step"] == "mode":
                    mode = _normalize_mode(text)
                    if not mode:
                        telegram.send_to_chat(chat_id, "Chi nhan sales hoac story. Moi ban nhap lai.")
                        continue
                    session["mode"] = mode
                    session["step"] = "topic"
                    telegram.send_to_chat(chat_id, "Nhap chu de ban muon giao:")
                    continue

                if session["step"] == "topic":
                    session["topic"] = text
                    session["step"] = "tone"
                    telegram.send_to_chat(chat_id, "Nhap tone (hoac /skip de dung mac dinh):")
                    continue

                if session["step"] == "tone":
                    tone = profile["tone"] if text == "/skip" else text
                    job_id = _enqueue_job(
                        queue=queue,
                        profile=profile,
                        chat_id=chat_id,
                        mode=session["mode"],
                        topic=session["topic"],
                        tone=tone,
                    )
                    profile["last_job"] = {
                        "job_id": job_id,
                        "root_job_id": job_id,
                        "mode": session["mode"],
                        "topic": session["topic"],
                        "tone": tone,
                        "feedback_round": 0,
                    }
                    sessions.pop(chat_id, None)
                    telegram.send_to_chat(chat_id, f"Da tao job thanh cong. Job ID: {job_id}")
                    continue

            mode_inline = None
            topic_inline = ""
            lowered = text.lower()
            if lowered.startswith("ban sach:"):
                mode_inline = "sales"
                topic_inline = text.split(":", maxsplit=1)[1].strip()
            elif lowered.startswith("ke chuyen:"):
                mode_inline = "story"
                topic_inline = text.split(":", maxsplit=1)[1].strip()

            if mode_inline and topic_inline:
                job_id = _enqueue_job(
                    queue=queue,
                    profile=profile,
                    chat_id=chat_id,
                    mode=mode_inline,
                    topic=topic_inline,
                )
                profile["last_job"] = {
                    "job_id": job_id,
                    "root_job_id": job_id,
                    "mode": mode_inline,
                    "topic": topic_inline,
                    "tone": profile["tone"],
                    "feedback_round": 0,
                }
                telegram.send_to_chat(chat_id, f"Da nhan viec nhanh. Job ID: {job_id}")
                continue

            telegram.send_to_chat(chat_id, "Khong hieu lenh. Gui /start de xem huong dan.")


if __name__ == "__main__":
    main()
