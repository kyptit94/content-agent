import asyncio
import time
from pathlib import Path

import requests

from app.config import settings

# Vietnamese voices tried in order when primary voice gives 403
_VI_FALLBACK_VOICES = [
    "vi-VN-HoaiMyNeural",
    "vi-VN-NamMinhNeural",
]


class VoiceService:
    def __init__(self) -> None:
        self.base_url = settings.voice_api_url.rstrip("/")
        self.output_dir = Path("/app/data/outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def synthesize(self, text: str, language: str, speaker_wav: str, output_name: str) -> str:
        response = requests.post(
            f"{self.base_url}/synthesize",
            json={
                "text": text,
                "language": language,
                "speaker_wav": speaker_wav,
                "output_name": output_name,
            },
            timeout=300,
        )
        response.raise_for_status()
        return response.json().get("audio_path", "")

    def synthesize_edge(self, text: str, output_name: str, voice_name: str | None = None) -> str:
        try:
            import edge_tts  # noqa: F401
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "edge_tts not installed. Rebuild image with latest requirements-app.txt"
            ) from exc

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
