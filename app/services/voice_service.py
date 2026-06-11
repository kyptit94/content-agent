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
