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


class ChatService:
    def __init__(self, redis: Redis, llm: LLMService, queue: QueueService) -> None:
        self.redis = redis
        self.llm = llm
        self.queue = queue
        self._system_prompt = (_PROMPT_DIR / "chat_system.txt").read_text(encoding="utf-8")
        self._ollama_url = settings.ollama_base_url.rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process_message(self, session_id: str, user_message: str) -> dict:
        """Handle one user message and return the full response."""
        # Load session
        session = self._load_session(session_id)
        session["messages"].append({"role": "user", "content": user_message, "time": datetime.utcnow().isoformat()})

        # Build context with current state
        context = self._build_context(session)
        system = self._system_prompt.replace("{context}", context)

        # Call LLM using Chat API (prevents token repetition from text completion)
        raw_response = self._call_chat(system, session["messages"])

        # Parse actions from response
        clean_text, actions = self._parse_actions(raw_response)

        # Execute actions and collect results
        action_results = []
        for action_type, action_arg in actions:
            result = self._execute_action(session, action_type, action_arg)
            action_results.append(result)

        # Save assistant message (store raw for context, but strip actions)
        session["messages"].append({
            "role": "assistant",
            "content": clean_text,
            "time": datetime.utcnow().isoformat(),
            "actions": actions,
        })
        self._save_session(session_id, session)

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
            86400 * 7,  # 7 day TTL
            json.dumps({"messages": [], "state": {}, "created": datetime.utcnow().isoformat()}, ensure_ascii=False),
        )
        return sid

    def export_chat(self, session_id: str) -> str:
        """Export session as JSONL for fine-tuning."""
        session = self._load_session(session_id)
        lines = []
        for msg in session["messages"]:
            lines.append(json.dumps({
                "role": msg["role"],
                "content": msg["content"],
            }, ensure_ascii=False))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _load_session(self, session_id: str) -> dict:
        raw = self.redis.get(f"chat:session:{session_id}")
        if raw:
            return json.loads(raw)
        return {"messages": [], "state": {}, "created": datetime.utcnow().isoformat()}

    def _save_session(self, session_id: str, session: dict) -> None:
        self.redis.setex(f"chat:session:{session_id}", 86400 * 7, json.dumps(session, ensure_ascii=False))

    def _build_context(self, session: dict) -> str:
        """Build current state context for the system prompt."""
        state = session.get("state", {})
        parts = []
        if state.get("mode"):
            parts.append(f"Current mode: {state['mode']}")
        if state.get("options"):
            parts.append(f"Options available: {len(state['options'])} options generated, user to pick index 0-{len(state['options'])-1}")
        if state.get("selected_option") is not None:
            opt = state.get("selected_title", "")
            parts.append(f"User selected option #{state['selected_option']}: {opt}")
        if state.get("voice"):
            parts.append(f"Voice set: {state['voice']}")
        if state.get("video_source"):
            parts.append(f"Video source: {state['video_source']}")
        if state.get("job_id"):
            parts.append(f"Last submitted job: {state['job_id']}")
        if not parts:
            parts.append("No state yet. Start a natural conversation with the user.")
        return "\n".join(parts)

    def _call_chat(self, system: str, messages: list) -> str:
        """Call Ollama Chat API - much cleaner than text completion for conversations."""
        # Build ChatML format messages
        chat_messages = [{"role": "system", "content": system}]

        # Only include last 10 conversation turns, stripping action lines
        recent = messages[-12:]
        for msg in recent:
            role = msg["role"]
            content = msg["content"]
            # Strip !!ACTION: lines so LLM doesn't repeat them
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
                        "num_predict": 300,
                        "top_p": 0.9,
                        "stop": ["\nUSER:", "\nASSISTANT:", "!!ACTION:"],
                    },
                },
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data.get("message", {}).get("content", "").strip()

            # Clean up common qwen2.5 repetition artifacts
            content = self._clean_repetition(content)

            return content
        except Exception:
            # Fallback to text completion
            prompt = self._build_llm_prompt(system, messages)
            raw = self.llm._call_ollama(prompt, num_predict=300, temperature=0.8)
            return self._clean_repetition(raw)

    def _build_llm_prompt(self, system: str, messages: list) -> str:
        """Fallback: build text completion prompt."""
        recent = messages[-10:]
        parts = [system, ""]
        for msg in recent:
            role = msg["role"].upper()
            content = msg["content"]
            clean, _ = self._parse_actions(content)
            if clean:
                parts.append(f"{role}: {clean}")
        parts.append("ASSISTANT:")
        return "\n\n".join(parts)

    @staticmethod
    def _clean_repetition(text: str) -> str:
        """Remove common LLM repetition artifacts (trailing word repeats, etc)."""
        if not text:
            return text
        lines = text.splitlines()
        if not lines:
            return text

        # Remove empty trailing lines
        while lines and not lines[-1].strip():
            lines.pop()

        # If the last line is a single word/phrase that appears in the previous line, drop it
        if len(lines) >= 2:
            last = lines[-1].strip()
            prev = lines[-2].strip()
            if last and last in prev and len(last) < len(prev) / 2:
                lines.pop()

        return "\n".join(lines).strip()

    def _parse_actions(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Extract !!ACTION: commands from text, return cleaned text + action list."""
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

    def _execute_action(self, session: dict, action_type: str, arg: str) -> dict:
        """Execute an action and update session state. Returns result dict."""
        state = session.setdefault("state", {})

        if action_type == "generate_options":
            mode = arg or state.get("mode", "horror")
            state["mode"] = mode
            try:
                options = self.llm.generate_options(mode=mode, language="en", tone="friendly", count=3)
                state["options"] = options
                return {"type": "options", "data": options}
            except Exception as e:
                return {"type": "error", "message": f"Failed to generate: {e}"}

        elif action_type == "select_option":
            try:
                idx = int(arg)
            except ValueError:
                return {"type": "error", "message": f"Invalid option index: {arg}"}
            options = state.get("options", [])
            if 0 <= idx < len(options):
                state["selected_option"] = idx
                state["selected_title"] = options[idx]["title"]
                state["selected_content"] = options[idx]["content"]
                return {"type": "selected", "index": idx, "title": options[idx]["title"]}
            return {"type": "error", "message": f"Option {idx} out of range (0-{len(options)-1})"}

        elif action_type == "set_voice":
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
            return {"type": "export_ready", "note": "Call /web/chat/export endpoint to download"}

        return {"type": "unknown", "action": action_type}

    def _submit_job(self, session: dict) -> dict:
        """Build and submit a job from current session state."""
        state = session.get("state", {})
        title = state.get("selected_title", "")
        content = state.get("selected_content", "")

        if not title or not content:
            return {"type": "error", "message": "No content selected. Generate options and pick one first."}

        from app.schemas import JobPayload

        job_id = str(uuid4())
        payload = JobPayload(
            job_id=job_id,
            created_at=datetime.utcnow().isoformat(),
            mode=state.get("mode", "horror"),
            title=title,
            content=content,
            language="en",
            tone="friendly",
            use_gemini_refine=False,
            create_audio=True,
            create_video=True,
            video_source_type=state.get("video_source", "internet"),
            video_keyword=state.get("video_keyword"),
            kokoro_voice=state.get("voice", "af_heart"),
            notify_telegram=bool(state.get("telegram_chat_id")),
            telegram_chat_id=state.get("telegram_chat_id"),
        )

        self.queue.enqueue(payload.model_dump())
        self.queue.set_job_status(
            job_id=job_id,
            payload={
                "job_id": job_id,
                "status": "queued",
                "title": title,
                "mode": payload.mode,
                "queued_at": datetime.utcnow().isoformat(),
                "payload": payload.model_dump(),
            },
        )

        state["job_id"] = job_id
        state["last_job_id"] = job_id
        return {"type": "job_submitted", "job_id": job_id, "title": title}