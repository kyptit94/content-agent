"""Translate any language to English using Ollama."""
import requests


class TranslatorService:
    def __init__(self, ollama_url: str, model: str = "mistral:7b") -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model

    def translate_to_english(self, text: str, source_lang: str = "auto") -> str:
        """Translate text to English. Returns translated text."""
        prompt = (
            f"Translate the following {source_lang} text to English.\n"
            "Preserve the tone, emotion, and pacing. Make it sound natural in English.\n"
            "Output ONLY the translated text. No commentary.\n\n"
            f"Text:\n{text[:2000]}"
        )
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 800},
                },
                timeout=90,
            )
            return resp.json().get("response", "").strip()
        except Exception:
            return text  # Fallback: return original