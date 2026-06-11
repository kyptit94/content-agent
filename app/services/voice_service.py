import asyncio
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import requests

from app.config import settings

# Vietnamese voices tried in order when primary voice gives 403
_VI_FALLBACK_VOICES = [
    "vi-VN-HoaiMyNeural",
    "vi-VN-NamMinhNeural",
]

# Regex patterns for text preprocessing
_RE_HOOK_END = re.compile(r"([.!?])\s+(.*?)\s*[,;:]\s*$", re.MULTILINE)
_RE_QUESTION = re.compile(r"([^.!?]*\?)\s*")
_RE_EXCLAMATION = re.compile(r"([^.!?]*!)\s*")
_RE_ELLIPSIS = re.compile(r"\.{3,}")
_RE_NEWLINE = re.compile(r"\n{2,}")
_RE_CONSECUTIVE_DOT = re.compile(r"\.{2,}")


class VoiceService:
    def __init__(self) -> None:
        self.base_url = settings.voice_api_url.rstrip("/")
        self.output_dir = Path("/app/data/outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _preprocess_for_tts(text: str, language: str = "vi") -> str:
        """
        Preprocess text to make TTS output more natural:
        1. Ensure sentences end with proper punctuation
        2. Add prosody markers (pauses, emphasis) via text patterns
        3. Clean up whitespace
        """
        if not text:
            return text

        # --- Step 1: Normalize whitespace ---
        text = text.strip()
        text = _RE_NEWLINE.sub("\n", text)

        # --- Step 2: Ensure sentence-ending punctuation ---
        # Split into lines, process each line
        lines = text.split("\n")
        processed_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Ensure line ends with sentence-ending punctuation
            if line and not line[-1] in ".!?":
                line += "."

            processed_lines.append(line)

        # Join lines - each line gets a natural pause (like a paragraph break)
        text = "\n".join(processed_lines)

        # --- Step 3: Add natural rhythm markers ---
        # Between hook/CTA sections: mark for pause
        text = text.replace(".\n", ". \n")

        # --- Step 4: Clean up ---
        # Replace 3+ dots with "... "
        text = _RE_ELLIPSIS.sub("... ", text)
        # Replace consecutive dots
        text = _RE_CONSECUTIVE_DOT.sub(".", text)
        # Fix common Vietnamese punctuation spacing
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # remove space before punctuation
        text = re.sub(r"([,.;:!?])(?!\s|$)", r"\1 ", text)  # ensure space after punctuation
        # Collapse multiple spaces
        text = re.sub(r" {2,}", " ", text)

        return text.strip()

    def synthesize(self, text: str, language: str, speaker_wav: str, output_name: str) -> str:
        # Preprocess text for better TTS output
        processed_text = self._preprocess_for_tts(text, language)

        payload = {
            "text": processed_text,
            "language": language,
            "speaker_wav": speaker_wav,
            "output_name": output_name,
        }

        last_error: Exception | None = None
        self._wait_for_service_ready()
        for base_url in self._candidate_base_urls():
            try:
                response = requests.post(
                    f"{base_url}/synthesize",
                    json=payload,
                    timeout=300,
                )
                response.raise_for_status()
                return response.json().get("audio_path", "")
            except requests.exceptions.RequestException as exc:
                last_error = exc

        if last_error:
            raise last_error
        return ""

    def _wait_for_service_ready(self) -> None:
        health_url = f"{self.base_url}/health"
        deadline = time.time() + 900
        delay = 2.0

        while time.time() < deadline:
            try:
                response = requests.get(health_url, timeout=10)
                if response.ok:
                    payload = response.json()
                    if payload.get("ready") is True or payload.get("status") == "ok":
                        return
                    if payload.get("status") == "failed":
                        raise RuntimeError(f"voice service failed to start: {payload.get('error', 'unknown error')}")
            except requests.exceptions.RequestException:
                pass

            time.sleep(delay)
            delay = min(delay * 1.5, 15.0)

        raise RuntimeError(f"voice service not ready after waiting for {health_url}")

    def _candidate_base_urls(self) -> list[str]:
        urls = [self.base_url]
        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()
        running_in_container = Path("/.dockerenv").exists() or os.environ.get("container") is not None

        if not running_in_container and hostname in {"voice", "ai_agent_voice"}:
            scheme = parsed.scheme or "http"
            port = f":{parsed.port}" if parsed.port else ""
            fallback_urls = [
                f"{scheme}://127.0.0.1{port}",
                f"{scheme}://localhost{port}",
            ]
            for fallback_url in fallback_urls:
                if fallback_url not in urls:
                    urls.append(fallback_url)

        return urls

    def synthesize_edge(self, text: str, output_name: str, voice_name: str | None = None) -> str:
        try:
            import edge_tts  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "edge_tts not installed. Rebuild image with latest requirements-app.txt"
            ) from exc

        # Preprocess text for natural voice
        text = self._preprocess_for_tts(text)

        output_path = self.output_dir / output_name
        primary = voice_name or settings.edge_tts_voice

        # Build candidate list: primary first, then remaining fallbacks excluding primary
        candidates = [primary] + [v for v in _VI_FALLBACK_VOICES if v != primary]

        last_error: Exception | None = None
        for attempt, voice in enumerate(candidates):
            try:
                self._edge_save(text=text, voice=voice, output_path=output_path)
                return str(output_path)
            except Exception as exc:
                last_error = exc
                if attempt < len(candidates) - 1:
                    time.sleep(2 ** attempt)  # 1s, 2s backoff before next voice

        raise RuntimeError(f"edge_tts failed all voices: {last_error}")

    def synthesize_edge_with_subs(
        self, text: str, output_name: str, voice_name: str | None = None
    ) -> tuple[str, str]:
        """Returns (audio_path, srt_content). Falls back to gTTS if edge_tts fails."""
        # Preprocess text for natural voice
        text = self._preprocess_for_tts(text)

        output_path = self.output_dir / output_name
        attempt_log: list[str] = []

        # --- Try edge_tts first ---
        try:
            import edge_tts  # noqa: F401

            primary = voice_name or settings.edge_tts_voice
            candidates = [primary] + [v for v in _VI_FALLBACK_VOICES if v != primary]

            for attempt, voice in enumerate(candidates):
                try:
                    srt_content = self._edge_save_with_timing(
                        text=text, voice=voice, output_path=output_path
                    )
                    return str(output_path), srt_content
                except Exception as exc:
                    err_str = str(exc)
                    if "403" in err_str:
                        reason = (
                            "403 Forbidden – Microsoft chặn request "
                            "(edge-tts dùng token không chính thức, bị chặn theo IP/session)"
                        )
                    elif "404" in err_str:
                        reason = f"404 – voice '{voice}' không khả dụng"
                    elif "timeout" in err_str.lower() or "timed out" in err_str.lower():
                        reason = "Timeout – kết nối Bing TTS quá chậm"
                    elif "ConnectionRefused" in err_str or "ConnectionReset" in err_str:
                        reason = "Connection refused/reset – endpoint bị chặn"
                    else:
                        reason = err_str[:120]
                    attempt_log.append(f"edge/{voice}: {reason}")
                    if attempt < len(candidates) - 1:
                        time.sleep(2 ** attempt)

        except ModuleNotFoundError:
            attempt_log.append("edge_tts: not installed")

        # --- Fallback: gTTS ---
        gtts_path = output_path.with_suffix(".mp3")
        try:
            audio_path_gtts = self._gtts_save(text=text, output_path=gtts_path)
            attempt_log.append("gtts: ok")
            return audio_path_gtts, ""   # gTTS has no word timing
        except Exception as exc:
            attempt_log.append(f"gtts: {str(exc)[:120]}")

        detail = " | ".join(attempt_log)
        raise RuntimeError(f"All TTS engines failed: {detail}")

    @staticmethod
    def _gtts_save(text: str, output_path: Path) -> str:
        from gtts import gTTS  # type: ignore

        lang = "vi"
        tts = gTTS(text=text, lang=lang, slow=False)
        tts.save(str(output_path))
        return str(output_path)

    @staticmethod
    def _edge_save(text: str, voice: str, output_path: Path) -> None:
        import edge_tts

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=settings.edge_tts_rate,
            )
            await communicate.save(str(output_path))

        asyncio.run(_run())

    @staticmethod
    def _edge_save_with_timing(text: str, voice: str, output_path: Path) -> str:
        """Save audio and return SRT content with word-level timing."""
        import edge_tts

        srt_lines: list[str] = []

        async def _run() -> None:
            sub_maker = edge_tts.SubMaker()
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=settings.edge_tts_rate,
            )
            with output_path.open("wb") as audio_file:
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_file.write(chunk["data"])
                    elif chunk["type"] == "WordBoundary":
                        sub_maker.feed(chunk)
            srt_lines.append(sub_maker.get_srt())

        asyncio.run(_run())
        return srt_lines[0] if srt_lines else ""
