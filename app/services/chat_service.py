import json
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import requests

from redis import Redis

from app.config import settings
from app.services.llm_service import LLMService
from app.services.queue_service import QueueService


_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_FINETUNE_DIR = Path("/app/data/finetune")


class ChatService:
    def __init__(self, redis: Redis, llm: LLMService, queue: QueueService) -> None:
        self.redis = redis
        self.llm = llm
        self.queue = queue
        self._system_prompt = (_PROMPT_DIR / "chat_system.txt").read_text(encoding="utf-8")
        self._ollama_url = settings.ollama_base_url.rstrip("/")
        _FINETUNE_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process_message(self, session_id: str, user_message: str) -> dict:
        """Handle one user message and return the full response."""
        session = self._load_session(session_id)
        session["messages"].append({"role": "user", "content": user_message, "time": datetime.utcnow().isoformat()})

        # Build context
        context = self._build_context(session)
        system = self._system_prompt.replace("{context}", context)

        # Call LLM
        raw_response = self._call_chat(system, session["messages"])

        # Parse actions
        clean_text, actions = self._parse_actions(raw_response)

        # Execute actions
        action_results = []
        for action_type, action_arg in actions:
            result = self._execute_action(session, action_type, action_arg, clean_text)
            action_results.append(result)

        # Save assistant message
        session["messages"].append({
            "role": "assistant",
            "content": clean_text,
            "time": datetime.utcnow().isoformat(),
            "actions": actions,
        })
        self._save_session(session_id, session)

        # Auto-save to JSONL for fine-tuning
        self._auto_save_finetune(session_id, session["messages"][-2:])

        return {
            "message": clean_text,
            "actions": actions,
            "action_results": action_results,
            "state": session.get("state", {}),
            "session_id": session_id,
        }

    def get_session(self, session_id: str) -> dict:
        return self._load_session(session_id)

    def create_session(self) -> str:
        sid = str(uuid4())[:8]
        self.redis.setex(
            f"chat:session:{sid}",
            86400 * 7,
            json.dumps({"messages": [], "state": {}, "created": datetime.utcnow().isoformat()}, ensure_ascii=False),
        )
        return sid

    def export_chat(self, session_id: str) -> str:
        """Export session as JSONL for fine-tuning."""
        session = self._load_session(session_id)
        lines = []
        for msg in session["messages"]:
            lines.append(json.dumps({"role": msg["role"], "content": msg["content"]}, ensure_ascii=False))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _auto_save_finetune(self, session_id: str, new_messages: list) -> None:
        """Append new messages to the fine-tuning JSONL file."""
        try:
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            path = _FINETUNE_DIR / f"chat_{date_str}.jsonl"
            with open(path, "a", encoding="utf-8") as f:
                for msg in new_messages:
                    f.write(json.dumps({"role": msg["role"], "content": msg["content"]}, ensure_ascii=False) + "\n")
        except Exception:
            pass  # Don't fail on training data save

    def _load_session(self, session_id: str) -> dict:
        raw = self.redis.get(f"chat:session:{session_id}")
        if raw:
            return json.loads(raw)
        return {"messages": [], "state": {}, "created": datetime.utcnow().isoformat()}

    def _save_session(self, session_id: str, session: dict) -> None:
        self.redis.setex(f"chat:session:{session_id}", 86400 * 7, json.dumps(session, ensure_ascii=False))

    def _build_context(self, session: dict) -> str:
        state = session.get("state", {})
        parts = ["Writing style: " + state.get("style", "not set yet — you are writing freely")]
        if state.get("voice"):
            parts.append(f"Voice: {state['voice']}")
        if state.get("video_source"):
            parts.append(f"Video source: {state['video_source']}")
        if state.get("last_content"):
            preview = state["last_content"][:200] + "..."
            parts.append(f"Last written content (will be used for submit): {preview}")
        if state.get("job_id"):
            parts.append(f"Last job: {state['job_id']}")
        return "\n".join(parts)

    def _call_chat(self, system: str, messages: list) -> str:
        chat_messages = [{"role": "system", "content": system}]
        recent = messages[-15:]
        for msg in recent:
            role = msg["role"]
            content = msg["content"]
            clean, _ = self._parse_actions(content)
            if clean:
                chat_messages.append({"role": role, "content": clean})

        try:
            resp = requests.post(
                f"{self._ollama_url}/api/chat",
                json={
                    "model": settings.local_llm_model,
                    "messages": chat_messages,
                    "stream": False,
                    "options": {
                        "temperature": 0.8,
                        "num_predict": 800,
                        "top_p": 0.9,
                        "stop": ["\nUSER:", "\nASSISTANT:", "!!ACTION:"],
                    },
                },
                timeout=180,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "").strip()
        except Exception:
            prompt = self._build_llm_prompt(system, messages)
            raw = self.llm._call_ollama(prompt, num_predict=800, temperature=0.8)
            return self._clean_repetition(raw)

    def _build_llm_prompt(self, system: str, messages: list) -> str:
        recent = messages[-10:]
        parts = [system, ""]
        for msg in recent:
            role = msg["role"].upper()
            clean, _ = self._parse_actions(msg["content"])
            if clean:
                parts.append(f"{role}: {clean}")
        parts.append("ASSISTANT:")
        return "\n\n".join(parts)

    @staticmethod
    def _clean_repetition(text: str) -> str:
        if not text:
            return text
        lines = text.splitlines()
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) >= 2:
            last = lines[-1].strip()
            prev = lines[-2].strip()
            if last and last in prev and len(last) < len(prev) / 2:
                lines.pop()
        return "\n".join(lines).strip()

    def _parse_actions(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        actions = []
        clean_lines = []
        for line in text.splitlines():
            match = re.match(r'^!!ACTION:\s*(\S+)\s*(.*)', line.strip(), re.IGNORECASE)
            if match:
                action_type = match.group(1).lower()
                action_arg = match.group(2).strip()
                actions.append((action_type, action_arg))
            else:
                clean_lines.append(line)
        return "\n".join(clean_lines).strip(), actions

    def _execute_action(self, session: dict, action_type: str, arg: str, assistant_content: str = "") -> dict:
        state = session.setdefault("state", {})

        if action_type == "set_voice":
            valid = {"af_heart", "af_bella", "af_nicole", "am_adam", "am_michael"}
            voice = arg if arg in valid else "af_heart"
            state["voice"] = voice
            return {"type": "voice", "voice": voice}

        elif action_type == "set_video_source":
            src = arg if arg in ("internet", "self") else "internet"
            state["video_source"] = src
            return {"type": "video_source", "source": src}

        elif action_type == "set_keyword":
            state["video_keyword"] = arg
            return {"type": "keyword", "keyword": arg}

        elif action_type == "set_telegram":
            state["telegram_chat_id"] = arg
            return {"type": "telegram", "chat_id": arg}

        elif action_type == "submit":
            return self._submit_job(session)

        elif action_type == "check_jobs":
            jobs = self.queue.list_recent_jobs(limit=10)
            return {"type": "jobs", "data": jobs}

        elif action_type == "export_chat":
            return {"type": "export_ready", "note": "Auto-saved to /app/data/finetune/"}

        # Track writing style from user feedback
        if action_type == "" and assistant_content and len(assistant_content) > 100:
            state["last_content"] = assistant_content

        return {"type": "ok"}

    def _submit_job(self, session: dict) -> dict:
        """Build job from the last AI-written content."""
        state = session.get("state", {})
        content = state.get("last_content", "")

        # If no tracked content, find last assistant message
        if not content:
            for msg in reversed(session["messages"]):
                if msg["role"] == "assistant" and len(msg["content"]) > 100:
                    content = msg["content"]
                    break

        if not content or len(content) < 50:
            return {"type": "error", "message": "No content to submit. Write something first!"}

        # Generate title from first sentence
        title = content.split(".")[0].strip()[:120]

        from app.schemas import JobPayload

        job_id = str(uuid4())
        payload = JobPayload(
            job_id=job_id,
            created_at=datetime.utcnow().isoformat(),
            mode="horror",
            title=title,
            content=content,
            language="en",
            tone="friendly",
            use_gemini_refine=False,
            create_audio=True,
            create_video=True,
            video_source_type=state.get("video_source", "internet"),
            video_keyword=state.get("video_keyword"),
            user_image_path=state.get("image_path"),
            kokoro_voice=state.get("voice", "af_heart"),
            notify_telegram=bool(state.get("telegram_chat_id")),
            telegram_chat_id=state.get("telegram_chat_id"),
        )

        self.queue.enqueue(payload.model_dump())
        self.queue.set_job_status(
            job_id=job_id,
            payload={
                "job_id": job_id, "status": "queued", "title": title,
                "mode": payload.mode, "queued_at": datetime.utcnow().isoformat(),
                "payload": payload.model_dump(),
            },
        )

        state["job_id"] = job_id
        return {"type": "job_submitted", "job_id": job_id, "title": title}