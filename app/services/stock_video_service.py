import json
import time
from pathlib import Path

import requests

from app.config import settings


class StockVideoService:
    def __init__(self) -> None:
        self.cache_dir = Path("/app/data/stock_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.cache_dir / "index.json"
        self.index = self._load_index()

    def _load_index(self) -> dict:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_index(self) -> None:
        self.index_path.write_text(json.dumps(self.index, ensure_ascii=False, indent=2), encoding="utf-8")

    def _cache_key(self, keyword: str, preferred_size: str) -> str:
        normalized = " ".join(keyword.lower().split())
        return f"{preferred_size}|{normalized}"

    def _try_cached_clip(self, cache_key: str) -> tuple[str, str] | None:
        record = self.index.get(cache_key)
        if not isinstance(record, dict):
            return None

        clip_path = record.get("clip_path", "")
        source = record.get("source", "")
        created_at = int(record.get("created_at", 0))
        if not clip_path or not Path(clip_path).exists():
            return None

        if (int(time.time()) - created_at) > settings.stock_video_cache_ttl_sec:
            return None

        return clip_path, source

    def _store_cache(self, cache_key: str, clip_path: str, source: str) -> None:
        self.index[cache_key] = {
            "clip_path": clip_path,
            "source": source,
            "created_at": int(time.time()),
        }
        self._save_index()

    def fetch(self, keyword: str, job_id: str, preferred_size: str = "portrait") -> tuple[str, str]:
        key = self._cache_key(keyword=keyword, preferred_size=preferred_size)
        cached = self._try_cached_clip(cache_key=key)
        if cached:
            return cached

        if settings.pexels_api_key:
            clip = self._fetch_from_pexels(keyword=keyword, job_id=job_id, preferred_size=preferred_size)
            if clip:
                self._store_cache(cache_key=key, clip_path=clip[0], source=clip[1])
                return clip

        if settings.pixabay_api_key:
            clip = self._fetch_from_pixabay(keyword=keyword, job_id=job_id)
            if clip:
                self._store_cache(cache_key=key, clip_path=clip[0], source=clip[1])
                return clip

        raise RuntimeError("No stock video source available. Set PEXELS_API_KEY or PIXABAY_API_KEY")

    def _fetch_from_pexels(self, keyword: str, job_id: str, preferred_size: str) -> tuple[str, str] | None:
        response = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": keyword, "per_page": 10, "orientation": preferred_size},
            headers={"Authorization": settings.pexels_api_key},
            timeout=45,
        )
        response.raise_for_status()
        videos = response.json().get("videos", [])
        if not videos:
            return None

        for item in videos:
            files = item.get("video_files", [])
            if not files:
                continue
            selected = sorted(files, key=lambda x: x.get("width", 0), reverse=True)[0]
            video_url = selected.get("link")
            if not video_url:
                continue
            out_path = self.cache_dir / f"{job_id}.mp4"
            self._download_file(video_url, out_path)
            source = item.get("url", video_url)
            return str(out_path), source
        return None

    def _fetch_from_pixabay(self, keyword: str, job_id: str) -> tuple[str, str] | None:
        response = requests.get(
            "https://pixabay.com/api/videos/",
            params={"key": settings.pixabay_api_key, "q": keyword, "per_page": 10},
            timeout=45,
        )
        response.raise_for_status()
        hits = response.json().get("hits", [])
        if not hits:
            return None

        for item in hits:
            variants = item.get("videos", {})
            selected = variants.get("large") or variants.get("medium") or variants.get("small")
            if not selected:
                continue
            video_url = selected.get("url")
            if not video_url:
                continue
            out_path = self.cache_dir / f"{job_id}.mp4"
            self._download_file(video_url, out_path)
            source = item.get("pageURL", video_url)
            return str(out_path), source
        return None

    @staticmethod
    def _download_file(url: str, out_path: Path) -> None:
        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with out_path.open("wb") as file_handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        file_handle.write(chunk)
