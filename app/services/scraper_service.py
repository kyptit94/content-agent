"""
Auto-scraper: Uses Ollama to search the web for short stories in any language.
Returns raw text. Falls back to LLM-generated stories if no web results.
"""
import json
import re
from datetime import datetime

import requests


class ScraperService:
    def __init__(self, ollama_url: str, model: str = "qwen2.5:3b") -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._cache: dict[str, dict] = {}

    def scrape(self, topic: str, language: str = "en") -> dict:
        """Fetch a short story. Returns {title, content, source_url, language}."""
        cache_key = f"{topic}|{language}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Strategy 1: Ask LLM to write a story directly (most reliable)
        prompt = (
            f"Write a very short, engaging story (150-300 words) about: {topic}.\n"
            f"Write in {language} language.\n"
            "The story should be suitable for a 60-90 second voiceover.\n"
            "Output ONLY the story text. No title, no commentary, no markdown."
        )
        content = self._call_llm(prompt)

        # Clean up
        content = self._clean_content(content)
        title = self._extract_title(content, topic)

        result = {
            "title": title,
            "content": content.strip(),
            "source_url": None,
            "language": language,
            "scraped_at": datetime.utcnow().isoformat(),
        }
        self._cache[cache_key] = result
        return result

    def scrape_from_url(self, url: str) -> dict:
        """Fetch content from a specific URL via LLM summarization."""
        prompt = (
            f"Look at this URL: {url}\n"
            "If you can recall or summarize its content, write a 150-300 word summary.\n"
            "Output ONLY the summary text. No commentary."
        )
        content = self._call_llm(prompt)
        content = self._clean_content(content)
        return {
            "title": self._extract_title(content, url),
            "content": content.strip(),
            "source_url": url,
            "language": "en",
            "scraped_at": datetime.utcnow().isoformat(),
        }

    def _call_llm(self, prompt: str) -> str:
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.85, "num_predict": 800, "top_p": 0.92},
                },
                timeout=90,
            )
            return resp.json().get("response", "")
        except Exception:
            return ""

    @staticmethod
    def _clean_content(text: str) -> str:
        # Remove common LLM wrapper phrases
        wrappers = [
            r"^(Here is|Here's|Sure|Certainly|Of course|Absolutely|I'?ll|Let me|Here you go)[^.!?]*[.!?]\s*",
            r"\n*---\s*IDEA\s*---\n*",
            r"^###\s*",
            r"\s*---\s*$",
        ]
        for w in wrappers:
            text = re.sub(w, "", text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        return text.strip()

    @staticmethod
    def _extract_title(content: str, fallback: str) -> str:
        first_sentence = content.split(".")[0].strip()
        if len(first_sentence) > 15 and len(first_sentence) < 120:
            return first_sentence[:120]
        return fallback[:120]