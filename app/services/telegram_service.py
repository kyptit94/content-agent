from pathlib import Path

import requests

from app.config import settings


class TelegramService:
    MAX_VIDEO_UPLOAD_BYTES = 45 * 1024 * 1024

    def __init__(self) -> None:
        self.enabled = settings.telegram_enabled
        self.token = settings.telegram_bot_token
        self.chat_id = settings.telegram_chat_id

    def send_to_chat(self, chat_id: str | int, text: str) -> None:
        if not self.enabled:
            return

        endpoint = f"https://api.telegram.org/bot{self.token}/sendMessage"
        requests.post(
            endpoint,
            json={
                "chat_id": chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )

    def send_file_to_chat(self, chat_id: str | int, file_path: str, caption: str | None = None) -> None:
        if not self.enabled:
            return

        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Telegram upload file not found: {file_path}")

        suffix = path.suffix.lower()
        if suffix in {".mp3", ".wav", ".m4a", ".ogg"}:
            endpoint = f"https://api.telegram.org/bot{self.token}/sendAudio"
            field_name = "audio"
        else:
            endpoint = f"https://api.telegram.org/bot{self.token}/sendDocument"
            field_name = "document"

        if suffix in {".mp4", ".mov", ".mkv"}:
            endpoint = f"https://api.telegram.org/bot{self.token}/sendVideo"
            field_name = "video"
            if path.stat().st_size > self.MAX_VIDEO_UPLOAD_BYTES:
                endpoint = f"https://api.telegram.org/bot{self.token}/sendDocument"
                field_name = "document"

        with path.open("rb") as file_handle:
            response = requests.post(
                endpoint,
                data={"chat_id": chat_id, "caption": caption or ""},
                files={field_name: file_handle},
                timeout=300,
            )

        try:
            response.raise_for_status()
        except requests.HTTPError:
            if endpoint.endswith("/sendVideo") and suffix in {".mp4", ".mov", ".mkv"}:
                with path.open("rb") as file_handle:
                    retry_response = requests.post(
                        f"https://api.telegram.org/bot{self.token}/sendDocument",
                        data={"chat_id": chat_id, "caption": caption or ""},
                        files={"document": file_handle},
                        timeout=300,
                    )
                retry_response.raise_for_status()
                return
            raise

    def send_message(self, text: str) -> None:
        if not self.enabled or not self.chat_id:
            return
        self.send_to_chat(chat_id=self.chat_id, text=text)

    def get_updates(self, offset: int | None = None, timeout_seconds: int = 30) -> list[dict]:
        if not self.enabled:
            return []

        endpoint = f"https://api.telegram.org/bot{self.token}/getUpdates"
        payload = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        response = requests.get(endpoint, params=payload, timeout=timeout_seconds + 10)
        response.raise_for_status()
        result = response.json().get("result", [])
        return result if isinstance(result, list) else []

    def get_file_path(self, file_id: str) -> str:
        if not self.enabled:
            raise RuntimeError("Telegram is not enabled")

        endpoint = f"https://api.telegram.org/bot{self.token}/getFile"
        response = requests.get(endpoint, params={"file_id": file_id}, timeout=30)
        response.raise_for_status()

        result = response.json().get("result", {})
        file_path = result.get("file_path")
        if not file_path:
            raise RuntimeError("Telegram file_path missing")
        return str(file_path)

    def download_file(self, file_path: str, destination_path: str) -> str:
        if not self.enabled:
            raise RuntimeError("Telegram is not enabled")

        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        with requests.get(url, stream=True, timeout=180) as response:
            response.raise_for_status()
            with destination.open("wb") as file_handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        file_handle.write(chunk)
        return str(destination)
