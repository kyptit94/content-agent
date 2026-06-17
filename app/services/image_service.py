"""Generate background images using Ollama + Pexels/Pixabay search.
Falls back to solid color if no results found.
"""
import requests
from pathlib import Path

_OUTPUT_DIR = Path("/app/data/outputs")


class ImageService:
    def __init__(self, pexels_key: str = "", pixabay_key: str = "", ollama_url: str = "") -> None:
        self.pexels_key = pexels_key
        self.pixabay_key = pixabay_key
        self.ollama_url = ollama_url.rstrip("/")
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def generate_background(self, job_id: str, story_text: str) -> str:
        """Generate/download a background image matching the story mood."""
        keywords = self._extract_keywords(story_text)
        img_path = self._search_stock(keywords, job_id)
        if img_path:
            return img_path
        return self._create_fallback(job_id)

    def _extract_keywords(self, text: str) -> str:
        """Use LLM to extract 3 visual keywords from story."""
        if not self.ollama_url:
            return "dark horror night"
        try:
            resp = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": "qwen2.5:3b",
                    "prompt": f"Extract 3 English keywords for finding background images matching this story. Output ONLY comma-separated words:\n\n{text[:500]}",
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 30},
                },
                timeout=30,
            )
            return resp.json().get("response", "dark moody cinematic").strip()
        except Exception:
            return "dark moody cinematic"

    def _search_stock(self, keywords: str, job_id: str) -> str | None:
        """Search Pexels then Pixabay for matching image."""
        headers = {"Authorization": self.pexels_key} if self.pexels_key else None
        if headers:
            try:
                resp = requests.get(
                    "https://api.pexels.com/v1/search",
                    headers=headers,
                    params={"query": keywords, "per_page": 1, "orientation": "portrait"},
                    timeout=15,
                )
                photos = resp.json().get("photos", [])
                if photos:
                    url = photos[0]["src"]["portrait"]
                    return self._download(job_id, url, "pexels")
            except Exception:
                pass

        # Fallback: Pixabay
        if self.pixabay_key:
            try:
                resp = requests.get(
                    "https://pixabay.com/api/",
                    params={"key": self.pixabay_key, "q": keywords, "per_page": 3},
                    timeout=15,
                )
                hits = resp.json().get("hits", [])
                if hits:
                    url = hits[0]["largeImageURL"]
                    return self._download(job_id, url, "pixabay")
            except Exception:
                pass
        return None

    def _download(self, job_id: str, url: str, source: str) -> str:
        out = str(_OUTPUT_DIR / f"{job_id}.jpg")
        try:
            data = requests.get(url, timeout=20).content
            Path(out).write_bytes(data)
            return out
        except Exception:
            return ""

    def _create_fallback(self, job_id: str) -> str:
        """Create a solid dark background image via ffmpeg."""
        import subprocess
        out = str(_OUTPUT_DIR / f"{job_id}.jpg")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=0x0b0d14:s=1080x1920:d=1,drawtext=text='StoryTime':fontcolor=white:fontsize=60:x=(w-text_w)/2:y=(h-text_h)/2",
            "-frames:v", "1", out,
        ], check=False, capture_output=True, timeout=10)
        return out