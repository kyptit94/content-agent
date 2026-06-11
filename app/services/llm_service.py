import hashlib
import random

import requests
from redis import Redis

from app.config import settings


class LLMService:
    def __init__(self) -> None:
        self.ollama_base_url = settings.ollama_base_url.rstrip("/")
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)

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

    def _call_ollama(self, prompt: str) -> str:
        response = requests.post(
            f"{self.ollama_base_url}/api/generate",
            json={
                "model": settings.local_llm_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.8, "num_predict": 900},
            },
            timeout=180,
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
            # Fail-open to avoid blocking normal operation when Gemini is temporarily unavailable.
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
                "Yeu cau nay khong vuot qua lop kiem duyet an toan truoc khi tao noi dung. "
                f"Ly do: {reason}."
            )

        if mode == "sales":
            local_prompt = (
                "Ban la copywriter ban sach. Tao noi dung ban sach co cau truc: "
                "hook, diem dau, loi ich, CTA ro rang."
                f"\nNgon ngu: {language}; Giong van: {tone}; Chu de sach: {topic}"
            )
        else:
            local_prompt = (
                "Ban la tac gia ke chuyen. Viet mot cau chuyen ngan co mo bai, cao trao, ket."
                f"\nNgon ngu: {language}; Giong van: {tone}; Chu de: {topic}"
            )

        if feedback_note:
            local_prompt += (
                "\n\nYeu cau chinh sua ngan gon tu nguoi dung (uu tien lam dung): "
                f"{feedback_note}"
            )

        local_output = self._call_ollama(local_prompt)

        if not use_gemini_refine or not settings.gemini_api_key:
            return local_output

        refine_prompt = (
            "Refine noi dung sau de tu nhien hon, hap dan hon va dung chinh ta. "
            "Giu nguyen y nghia va muc tieu ban dau.\n\n"
            f"Noi dung goc:\n{local_output}"
        )

        refine_key_seed = f"{settings.gemini_model}|{language}|{mode}|{local_output}"
        refine_cache_key = f"gemini:refine:{self._hash_text(refine_key_seed)}"
        cached_refine = self._cache_get(refine_cache_key)
        if cached_refine:
            return cached_refine

        try:
            refined = self._call_gemini(refine_prompt)
            self._cache_set(
                key=refine_cache_key,
                value=refined,
                ttl=settings.gemini_refine_cache_ttl_sec,
            )
            return refined
        except Exception:
            return local_output

    def suggest_topic(self, mode: str, language: str = "vi") -> str:
        recent_topics = self._recent_topics_get(mode=mode, language=language)
        avoid_block = ""
        if recent_topics:
            avoid_block = "\nKhong duoc lap lai hoac qua giong cac chu de sau: " + " | ".join(recent_topics)

        prompt = (
            "De xuat DUY NHAT 1 chu de video ngan, viet 1 dong duy nhat, khong danh sach. "
            "Chu de phai cu the, de lam noi dung ngan 30-60s. "
            "Moi lan phai doi goc tiep can, khong lap lai mot mo-tip cu."
            f"\nMode: {mode}; Language: {language}"
            f"{avoid_block}"
        )
        try:
            result = self._call_ollama(prompt)
            line = self._normalize_topic_line(result) if result else ""
            topic = line or self._fallback_topic(mode=mode, language=language, recent_topics=recent_topics)
            self._recent_topics_push(mode=mode, language=language, topic=topic)
            return topic
        except Exception:
            topic = self._fallback_topic(mode=mode, language=language, recent_topics=recent_topics)
            self._recent_topics_push(mode=mode, language=language, topic=topic)
            return topic

    @staticmethod
    def _fallback_topic(mode: str, language: str = "vi", recent_topics: list[str] | None = None) -> str:
        recent_topics = recent_topics or []
        if mode == "story":
            candidates = [
                "Cuon sach cu trong tiem do ve mo ra mot loi hua bi mat",
                "Co gai de quen mot tam buu thiep trong sach thu vien va 7 nam sau co nguoi hoi am",
                "Nguoi ban sach ven duong gap lai vi khach cu mang theo mot bi mat gia dinh",
                "Mot trang sach rot ra trong ngay mua dan toi cuoc gap doi doi",
            ]
        elif language.lower().startswith("vi"):
            candidates = [
                "Vi sao 10 phut doc sach truoc khi ngu co the doi cach ban nghi ca ngay hom sau",
                "3 dau hieu ban dang chon sai cuon sach cho muc tieu phat trien ban than",
                "Cach doc 1 chuong sach ma van nho duoc y chinh de ap dung ngay",
                "1 thoi quen nho giup ban doc deu hon ma khong can ep ban than",
                "Tai sao nguoi ban ron van co the doc het 12 cuon sach moi nam",
            ]
        else:
            candidates = [
                "Why reading 10 minutes before bed can change your next day focus",
                "3 signs you are picking the wrong book for your current goal",
                "A simple way to remember more from every chapter you read",
                "One tiny reading habit that busy people can actually keep",
            ]

        available = [candidate for candidate in candidates if candidate not in recent_topics]
        pool = available or candidates
        return random.choice(pool)
