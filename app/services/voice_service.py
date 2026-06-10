import requests

from app.config import settings


class VoiceService:
    def __init__(self) -> None:
        self.base_url = settings.voice_api_url.rstrip("/")

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
