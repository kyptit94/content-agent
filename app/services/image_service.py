"""Generate background images using Ollama + Pexels/Pixabay search.
Falls back to solid color if no results found.
"""
import requests
from pathlib import Path

_OUTPUT_DIR = Path("/app/data/outputs")


import urllib.parse

class ImageService:
    def __init__(self, pexels_key: str = "", pixabay_key: str = "", ollama_url: str = "") -> None:
        self.pexels_key = pexels_key
        self.pixabay_key = pixabay_key
        self.ollama_url = ollama_url.rstrip("/")
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def generate_background(self, job_id: str, story_text: str) -> str:
        """Generate AI image matching story mood, fallback to stock/color."""
        # Strategy 1: AI-generated image via Pollinations.ai (free, no GPU needed)
        img_path = self._generate_ai_image(story_text, job_id)
        if img_path:
            return img_path
        
        # Strategy 2: Stock photo (Pexels/Pixabay)
        keywords = self._extract_keywords(story_text)
        img_path = self._search_stock(keywords, job_id)
        if img_path:
            return img_path
        
        # Strategy 3: Solid color fallback
        return self._create_fallback(job_id)

    def generate_images_for_sentences(self, job_id: str, story_text: str) -> list[str]:
        """Generate one AI image per sentence. Returns list of image paths."""
        import re
        # Split into sentences (on . ! ? followed by space/newline)
        sentences = re.split(r'(?<=[.!?])\s+', story_text.strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 15]
        
        image_paths = []
        for i, sentence in enumerate(sentences):
            img_job_id = f"{job_id}_img{i}"
            
            # Try AI generation first
            img_path = self._generate_ai_image(sentence, img_job_id)
            
            # Fallback: stock photo
            if not img_path:
                keywords = self._extract_keywords(sentence)
                img_path = self._search_stock(keywords, img_job_id)
            
            # Last resort: solid color
            if not img_path:
                img_path = self._create_fallback(img_job_id)
            
            image_paths.append(img_path)
            print(f"[IMAGE] Sentence {i+1}/{len(sentences)}: {img_path}")
        
        return image_paths

    def _generate_ai_image(self, story_text: str, job_id: str) -> str | None:
        """Generate image using Pollinations.ai free API based on story content."""
        try:
            # Extract a visual prompt from the first 2 sentences
            prompt = self._build_visual_prompt(story_text)
            safe_prompt = urllib.parse.quote(prompt)
            url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1080&height=1920&nologo=true"
            
            resp = requests.get(url, timeout=120)
            if resp.status_code == 200 and len(resp.content) > 1000:
                out = str(_OUTPUT_DIR / f"{job_id}.jpg")
                Path(out).write_bytes(resp.content)
                print(f"[IMAGE] AI generated: {out} ({len(resp.content)} bytes)")
                return out
        except Exception as e:
            print(f"[IMAGE] AI generation failed: {e}")
        return None

    def _build_visual_prompt(self, text: str) -> str:
        """Build a cinematic visual prompt from story text."""
        # Take first ~300 chars as context, extract mood keywords
        snippet = text[:400].replace("\n", " ").strip()
        
        # Use LLM to generate a concise image prompt if available
        if self.ollama_url:
            try:
                resp = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": "qwen2.5:3b",
                        "prompt": (
                            "Write a SHORT visual image prompt (max 10 words) in English "
                            "describing a cinematic, moody scene for this story. "
                            "Include lighting style (cinematic, dark, moody). "
                            "Output ONLY the prompt:\n\n" + snippet
                        ),
                        "stream": False,
                        "options": {"temperature": 0.7, "num_predict": 40},
                    },
                    timeout=30,
                )
                prompt = resp.json().get("response", "").strip()
                if prompt and len(prompt) > 5:
                    return prompt
            except Exception:
                pass
        
        # Fallback: use first sentence as prompt
        first_sentence = snippet.split(".")[0].strip()
        return f"cinematic dark moody {first_sentence[:80]}"

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
