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

    def _build_local_generation(self, mode: str, topic: str, tone: str, language: str, feedback_note: str | None) -> str:
        if mode == "story":
            lines = [
                f"Mo bai: {topic}.",
                f"Than bai: Ke cau chuyen theo giong {tone}, tap trung vao xung dot va cam xuc ro rang.",
                "Cao trao: day lanh chuyen bien bat ngo nhung van giu dung y nghia ban dau.",
                "Ket: dong lai bang 1 cau nhan thuc hoac bai hoc de nguoi xem nho lau hon.",
            ]
        else:
            lines = [
                f"Hook: {topic}.",
                f"Van de: Neu ban con do du hay bo lo viec doc sach, day la phan ban can nghe.",
                f"Loi ich: Cach tiep can nay giup ban duy tri thoi quen doc deu hon voi giong van {tone}.",
                "CTA: Thu ngay hom nay voi 10 phut doc sach truoc khi ngu.",
            ]

        if feedback_note:
            lines.append(f"Dieu chinh: {feedback_note}")

        lines.append(f"Ngon ngu: {language}")
        return "\n".join(lines)

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
                "Yêu cầu này không vượt qua lớp kiểm duyệt an toàn trước khi tạo nội dung. "
                f"Lý do: {reason}."
            )

        if mode == "sales":
            local_prompt = (
                "Bạn là copywriter bán sách. Hãy tạo nội dung bán sách có cấu trúc: "
                "hook, vấn đề, lợi ích, CTA rõ ràng."
                f"\nNgôn ngữ: {language}; Giọng văn: {tone}; Chủ đề sách: {topic}"
            )
        else:
            local_prompt = (
                "Bạn là tác giả kể chuyện. Viết một câu chuyện ngắn có mở bài, cao trào và kết."
                f"\nNgôn ngữ: {language}; Giọng văn: {tone}; Chủ đề: {topic}"
            )

        if feedback_note:
            local_prompt += (
                "\n\nYêu cầu chỉnh sửa ngắn gọn từ người dùng (ưu tiên làm đúng): "
                f"{feedback_note}"
            )

        try:
            local_output = self._call_ollama(local_prompt)
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

        if not use_gemini_refine or not settings.gemini_api_key:
            return local_output

        refine_prompt = (
            "Hãy tinh chỉnh nội dung sau để tự nhiên hơn, hấp dẫn hơn và đúng chính tả. "
            "Giữ nguyên ý nghĩa và mục tiêu ban đầu.\n\n"
            f"Nội dung gốc:\n{local_output}"
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
            avoid_block = "\nKhông được lặp lại hoặc quá giống các chủ đề sau: " + " | ".join(recent_topics)

        prompt = (
            "Đề xuất DUY NHẤT 1 chủ đề video ngắn, viết đúng 1 dòng, không danh sách. "
            "Chủ đề phải cụ thể, đủ hay để làm nội dung 30-60 giây. "
            "Mỗi lần phải đổi góc tiếp cận, không lặp lại mô-típ cũ."
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
                "Cuốn sách cũ trong tiệm đồ ve chai mở ra một lời hứa bí mật",
                "Cô gái để quên một tấm bưu thiếp trong sách thư viện và 7 năm sau có người hồi âm",
                "Người bán sách ven đường gặp lại vị khách cũ mang theo một bí mật gia đình",
                "Một trang sách rơi ra trong ngày mưa dẫn tới cuộc gặp đổi đời",
            ]
        elif language.lower().startswith("vi"):
            candidates = [
                "Vì sao 10 phút đọc sách trước khi ngủ có thể đổi cách bạn nghĩ cả ngày hôm sau",
                "3 dấu hiệu bạn đang chọn sai cuốn sách cho mục tiêu phát triển bản thân",
                "Cách đọc 1 chương sách mà vẫn nhớ được ý chính để áp dụng ngay",
                "1 thói quen nhỏ giúp bạn đọc đều hơn mà không cần ép bản thân",
                "Tại sao người bận rộn vẫn có thể đọc hết 12 cuốn sách mỗi năm",
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
