import asyncio
from pathlib import Path

import edge_tts
import requests

from app.config import settings


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
        output_path = self.output_dir / output_name

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice_name or settings.edge_tts_voice,
                rate=settings.edge_tts_rate,
            )
            await communicate.save(str(output_path))

        asyncio.run(_run())
        return str(output_path)
