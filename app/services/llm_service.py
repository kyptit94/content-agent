import hashlib
import random
from pathlib import Path

import requests

from redis import Redis

from app.config import settings


_PROMPT_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# Map new mode names to prompt file names
_MODE_PROMPT_FILE: dict[str, str] = {
    "horror": "horror_prompt",
    "wealth": "wealth_prompt",
    "softskills": "softskills_prompt",
    "mystery": "mystery_prompt",
    # backward compat
    "sales": "wealth_prompt",
    "story": "horror_prompt",
}

# Human-friendly labels for modes
_MODE_LABELS: dict[str, str] = {
    "horror": "Horror Story",
    "wealth": "Wealth & Success",
    "softskills": "Soft Skills",
    "mystery": "World Mysteries",
}


class LLMService:
    def __init__(self) -> None:
        self.ollama_base_url = settings.ollama_base_url.rstrip("/")
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    @staticmethod
    def _load_prompt(mode: str, language: str = "en") -> str:
        # Map mode to prompt base filename
        prompt_base = _MODE_PROMPT_FILE.get(mode)
        if not prompt_base:
            return ""

        # English-only for these content types
        filename = f"{prompt_base}_en.txt"
        filepath = _PROMPT_DIR / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8").strip()

        # Try with language suffix if not en
        lang_suffix = "en" if language.lower().startswith("en") else "vi"
        fallback = _PROMPT_DIR / f"{prompt_base}_{lang_suffix}.txt"
        if fallback.exists():
            return fallback.read_text(encoding="utf-8").strip()

        return ""

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _cache_get(self, key: str) -> str | None:
        try:
            return self.redis.get(key)
        except Exception:
            return None

    def _cache_set(self, key: str, value: str, ttl: int) -> None:
        try:
            self.redis.setex(key, ttl, value)
        except Exception:
            return

    def _recent_topics_key(self, mode: str, language: str) -> str:
        return f"topic_suggestions:recent:{mode}:{language}"

    def _recent_topics_get(self, mode: str, language: str, limit: int = 8) -> list[str]:
        try:
            items = self.redis.lrange(self._recent_topics_key(mode, language), 0, max(0, limit - 1))
            return [item.strip() for item in items if item and item.strip()]
        except Exception:
            return []

    def _recent_topics_push(self, mode: str, language: str, topic: str) -> None:
        cleaned = topic.strip()
        if not cleaned:
            return

        key = self._recent_topics_key(mode, language)
        try:
            self.redis.lrem(key, 0, cleaned)
            self.redis.lpush(key, cleaned)
            self.redis.ltrim(key, 0, 7)
            self.redis.expire(key, 60 * 60 * 24 * 7)
        except Exception:
            return

    def extract_video_keywords(self, content: str, language: str = "en") -> list[str]:
        """Extract 3-5 visual keywords from content for stock video search."""
        prompt = (
            "From the text below, extract 3-5 English keywords "
            "that would find relevant stock footage videos. "
            "Return only comma-separated keywords, no explanation.\n\n"
            f"Text: {content[:1000]}"
        )
        try:
            result = self._call_ollama(
                prompt=prompt,
                temperature=0.3,
                max_tokens=50,
            )
            keywords = [kw.strip().lower() for kw in result.split(",") if kw.strip()]
            return keywords[:5] if keywords else ["abstract", "background"]
        except Exception:
            return ["abstract", "ambient", "landscape"]

    @staticmethod
    def _normalize_topic_line(value: str) -> str:
        return value.splitlines()[0].strip().strip("-•1234567890. ")[:180]

    @staticmethod
    def _is_risky_topic(topic: str) -> bool:
        risky_tokens = {
            "18+",
            "sex",
            "sexual",
            "violence",
            "kill",
            "bomb",
            "drug",
            "hate",
            "racist",
            "suicide",
            "hack",
            "exploit",
        }
        lowered = topic.lower()
        return any(token in lowered for token in risky_tokens)

    def _should_run_precheck(self, topic: str) -> bool:
        mode = settings.gemini_precheck_mode.strip().lower()
        if mode == "off":
            return False
        if mode == "always":
            return True
        return self._is_risky_topic(topic)

    def _call_ollama(self, prompt: str, num_predict: int = 2000, temperature: float = 0.85, max_tokens: int = 2000) -> str:
        response = requests.post(
            f"{self.ollama_base_url}/api/generate",
            json={
                "model": settings.local_llm_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": num_predict, "top_p": 0.92},
            },
            timeout=300,
        )
        response.raise_for_status()
        return response.json().get("response", "").strip()

    def _call_gemini(self, prompt: str) -> str:
        if not settings.gemini_api_key:
            raise RuntimeError("Missing GEMINI_API_KEY")

        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
        )
        response = requests.post(
            endpoint,
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=180,
        )
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidate")

        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(part.get("text", "") for part in parts).strip()

    def _gemini_precheck(self, mode: str, topic: str, tone: str, language: str) -> tuple[bool, str]:
        if not settings.gemini_api_key:
            return True, "gemini-disabled"

        if not self._should_run_precheck(topic=topic):
            return True, "skipped-low-risk"

        cache_seed = f"{mode}|{topic}|{tone}|{language}|{settings.gemini_model}"
        cache_key = f"gemini:precheck:{self._hash_text(cache_seed)}"
        cached_verdict = self._cache_get(cache_key)
        if cached_verdict:
            first_line = cached_verdict.splitlines()[0].strip()
            if first_line.upper().startswith("BLOCK|"):
                reason = first_line.split("|", maxsplit=1)[1].strip() if "|" in first_line else "policy"
                return False, reason or "policy"
            return True, "ok-cached"

        guard_prompt = (
            "You are a content safety gate. Decide if the user request is safe to generate. "
            "Return exactly one line in this format: ALLOW|short_reason or BLOCK|short_reason.\n"
            f"mode={mode}; language={language}; tone={tone}; topic={topic}"
        )
        try:
            verdict = self._call_gemini(guard_prompt)
        except Exception:
            return True, "gemini-check-failed"

        self._cache_set(
            key=cache_key,
            value=verdict,
            ttl=settings.gemini_precheck_cache_ttl_sec,
        )

        first_line = verdict.splitlines()[0].strip() if verdict else ""
        if first_line.upper().startswith("BLOCK|"):
            reason = first_line.split("|", maxsplit=1)[1].strip() if "|" in first_line else "policy"
            return False, reason or "policy"
        return True, "ok"

    # ------------------------------------------------------------------
    # STEP 1: Generate multiple title+content options for user to choose
    # ------------------------------------------------------------------
    def generate_options(
        self,
        mode: str,
        language: str = "en",
        tone: str = "friendly",
        count: int = 3,
    ) -> list[dict[str, str]]:
        """
        Generate `count` pairs of (title, content) so the user can pick one.
        Returns list of {"title": "...", "content": "..."}
        """
        # Normalize mode
        resolved_mode = _MODE_PROMPT_FILE.get(mode) and mode or "horror"
        mode_label = _MODE_LABELS.get(resolved_mode, resolved_mode.title())

        base_prompt = self._load_prompt(mode=resolved_mode, language=language)
        if not base_prompt:
            # Build a simple fallback prompt
            base_prompt = (
                f"You are a short-form content creator for {mode_label} videos.\n"
                "Write a compelling 250-400 word narrative.\n"
                "Language: {language}; Tone: {tone}; Topic: {topic}"
            )

        # Build a single prompt that asks for multiple options
        prompt = (
            f"Generate {count} DIFFERENT short video content ideas for {mode_label}.\n\n"
            "For each idea, output exactly in this format:\n"
            "---IDEA---\n"
            "TITLE: <a catchy, scroll-stopping title for the video>\n"
            "CONTENT:\n"
            "<the full narrative script>\n\n"
            f"{base_prompt}\n"
            f"Language: {language}\n"
            f"Tone: {tone}\n\n"
            f"IMPORTANT: Generate exactly {count} ideas. Each must start with ---IDEA--- on its own line.\n"
            "Make each idea completely different — different angles, different hooks.\n"
            "Titles should be in English, short, and highly clickable (max 12 words)."
        )

        try:
            result = self._call_ollama(prompt, num_predict=4000, temperature=0.9)
        except Exception:
            # Fallback: generate one option at a time
            return self._fallback_generate_options_single(
                mode=resolved_mode, language=language, tone=tone, count=count
            )

        options = self._parse_multi_idea(result)
        if len(options) < 2:
            # Not enough parsed, do single fallback
            return self._fallback_generate_options_single(
                mode=resolved_mode, language=language, tone=tone, count=count
            )

        # Trim to requested count
        return options[:count]

    def _parse_multi_idea(self, text: str) -> list[dict[str, str]]:
        """Parse LLM output with ---IDEA--- delimiters into title+content pairs."""
        blocks = text.split("---IDEA---")
        options: list[dict[str, str]] = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            title = ""
            content = ""

            # Try to extract TITLE: line
            lines = block.splitlines()
            content_start_idx = 0
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped.lower().startswith("title:"):
                    title = stripped.split(":", maxsplit=1)[1].strip().strip('"')
                    content_start_idx = i + 1
                    break

            # Content starts after "CONTENT:" if present
            for i in range(content_start_idx, len(lines)):
                if lines[i].strip().lower().startswith("content:"):
                    content_start_idx = i + 1
                    break

            content = "\n".join(lines[content_start_idx:]).strip()

            if content and len(content) > 50:
                if not title:
                    # Generate title from first sentence
                    title = content.split(".")[0].strip()[:100]
                options.append({"title": title, "content": content})

        return options

    def _fallback_generate_options_single(
        self, mode: str, language: str, tone: str, count: int
    ) -> list[dict[str, str]]:
        """Fallback: generate one option at a time via suggest_topic + generate."""
        mode_label = _MODE_LABELS.get(mode, mode.title())
        options: list[dict[str, str]] = []
        seen_titles: set[str] = set()

        for _ in range(count):
            topic = self.suggest_topic(mode=mode, language=language)
            # Avoid duplicate topics
            retries = 0
            while topic in seen_titles and retries < 3:
                topic = self.suggest_topic(mode=mode, language=language)
                retries += 1
            seen_titles.add(topic)

            try:
                content = self.generate(
                    mode=mode,
                    topic=topic,
                    tone=tone,
                    language=language,
                    use_gemini_refine=False,
                )
                options.append({"title": topic, "content": content})
            except Exception:
                options.append({
                    "title": topic,
                    "content": f"Content for: {topic}\n\n[Generation failed, please retry]",
                })

        return options

    # ------------------------------------------------------------------
    # STEP 2 (after user picks): Generate from selected option
    # ------------------------------------------------------------------
    def generate(
        self,
        mode: str,
        topic: str,
        tone: str,
        language: str,
        use_gemini_refine: bool,
        feedback_note: str | None = None,
    ) -> str:
        allowed, reason = self._gemini_precheck(mode=mode, topic=topic, tone=tone, language=language)
        if not allowed:
            return (
                "This request did not pass the content safety precheck. "
                f"Reason: {reason}."
            )

        # Normalize mode
        resolved_mode = _MODE_PROMPT_FILE.get(mode) and mode or "horror"

        # --- Build prompt from file ---
        base_prompt = self._load_prompt(mode=resolved_mode, language=language)
        if base_prompt:
            local_prompt = (
                base_prompt
                .replace("{language}", language)
                .replace("{tone}", tone)
                .replace("{topic}", topic)
            )
        else:
            mode_label = _MODE_LABELS.get(resolved_mode, resolved_mode.title())
            local_prompt = (
                f"You are a short-form content creator for {mode_label} videos.\n"
                "Write a compelling, natural narrative for voiceover.\n"
                f"Language: {language}; Tone: {tone}; Topic: {topic}\n"
                "200-400 words, continuous prose, no labels or markdown."
            )

        if feedback_note:
            local_prompt += (
                f"\n\nUser revision request (follow this carefully): {feedback_note}"
            )

        # --- First pass: generate initial content ---
        try:
            local_output = self._call_ollama(local_prompt, num_predict=2500)
        except requests.HTTPError as exc:
            if getattr(exc.response, "status_code", None) == 404:
                local_output = self._build_local_generation(
                    mode=mode,
                    topic=topic,
                    tone=tone,
                    language=language,
                    feedback_note=feedback_note,
                )
            else:
                raise
        except Exception:
            local_output = self._build_local_generation(
                mode=mode,
                topic=topic,
                tone=tone,
                language=language,
                feedback_note=feedback_note,
            )

        # --- If no Gemini refine, return as-is ---
        if not use_gemini_refine or not settings.gemini_api_key:
            return local_output

        # --- Second pass: Gemini refine + expand ---
        refine_instruction = (
            "Polish and expand the short-form social media content below.\n"
            "Requirements: keep the original message, tone, and hook intact.\n"
            "Add richer sensory details, stronger emotional beats, and smoother flow.\n"
            "Write longer than the original (minimum 300 characters).\n"
            "Keep it continuous prose — no labels, no bullet points, no markdown.\n\n"
            f"Original content:\n{local_output}"
        )

        refine_key_seed = f"expand|{settings.gemini_model}|{language}|{mode}|{local_output}"
        refine_cache_key = f"gemini:refine:{self._hash_text(refine_key_seed)}"
        cached_refine = self._cache_get(refine_cache_key)
        if cached_refine:
            return cached_refine

        try:
            refined = self._call_gemini(refine_instruction)
            refined = refined or local_output
            self._cache_set(
                key=refine_cache_key,
                value=refined,
                ttl=settings.gemini_refine_cache_ttl_sec,
            )
            return refined
        except Exception:
            return local_output

    def _build_local_generation(
        self, mode: str, topic: str, tone: str, language: str, feedback_note: str | None
    ) -> str:
        mode_label = _MODE_LABELS.get(mode, mode.title())
        lines = [
            f"Opening hook for {mode_label}: {topic}.",
            f"Main body with tone: {tone}. Engage the viewer with a compelling narrative.",
            f"Strong payoff or twist ending that leaves an impression.",
            f"Language: {language}.",
        ]
        if feedback_note:
            lines.append(f"Revision: {feedback_note}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Topic suggestion for each mode
    # ------------------------------------------------------------------
    def suggest_topic(self, mode: str, language: str = "en") -> str:
        resolved_mode = _MODE_PROMPT_FILE.get(mode) and mode or "horror"
        mode_label = _MODE_LABELS.get(resolved_mode, resolved_mode.title())

        recent_topics = self._recent_topics_get(mode=resolved_mode, language=language)
        avoid_block = ""
        if recent_topics:
            avoid_block = "\nDo NOT repeat or closely resemble these recent topics: " + " | ".join(recent_topics)

        prompt = (
            f"Suggest ONE unique short video topic for {mode_label} content.\n"
            "Write exactly 1 line, no lists, no explanations.\n"
            "The topic must be specific, engaging, and suitable for a 30-60 second video.\n"
            "Each time, pick a fresh angle — do not repeat patterns.\n"
            f"Language: {language} (but the topic/title should be in English)\n"
            f"{avoid_block}"
        )
        try:
            result = self._call_ollama(prompt, num_predict=80, temperature=0.95)
            line = self._normalize_topic_line(result) if result else ""
            topic = line or self._fallback_topic(mode=resolved_mode, language=language, recent_topics=recent_topics)
            self._recent_topics_push(mode=resolved_mode, language=language, topic=topic)
            return topic
        except Exception:
            topic = self._fallback_topic(mode=resolved_mode, language=language, recent_topics=recent_topics)
            self._recent_topics_push(mode=resolved_mode, language=language, topic=topic)
            return topic

    @staticmethod
    def _fallback_topic(mode: str, language: str = "en", recent_topics: list[str] | None = None) -> str:
        recent_topics = recent_topics or []

        fallbacks: dict[str, list[str]] = {
            "horror": [
                "The Shadow That Didn't Belong to Anyone",
                "She Woke Up to Find Her Reflection Smiling First",
                "The Last Voicemail He Sent Before He Vanished",
                "Something Was Living in the Walls of Room 304",
                "The Baby Monitor Picked Up a Voice That Wasn't Hers",
            ],
            "wealth": [
                "The 5-AM Rule That Built Millionaires",
                "Why Your Savings Account Is Making You Poorer",
                "The One Asset Nobody Told You to Buy at 20",
                "How to Make Money While You Sleep — The Real Way",
                "Stop Trading Time for Money: The Framework That Works",
            ],
            "softskills": [
                "How to Say No Without Feeling Guilty — Ever Again",
                "The 3-Second Pause That Makes You Sound Twice as Smart",
                "Why People Forget What You Say But Remember How You Made Them Feel",
                "The Listening Trick That Makes Anyone Trust You Instantly",
                "How to Handle Criticism Without Getting Defensive",
            ],
            "mystery": [
                "The Village Where Everyone Shared the Same Nightmare",
                "The Radio Signal From Space That Science Can't Explain",
                "They Found a City Under the Ice — Then Never Spoke of It Again",
                "The Missing 411 Cases: People Who Vanished Without a Trace",
                "A Door That Hadn't Been Opened in 400 Years — Until Now",
            ],
        }

        candidates = fallbacks.get(mode, fallbacks["horror"])
        available = [c for c in candidates if c not in recent_topics]
        pool = available or candidates
        return random.choice(pool)