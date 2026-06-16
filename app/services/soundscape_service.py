"""
Auto background music & sound effects from Pixabay Music (free API) with ffmpeg fallback.
"""
import hashlib
import subprocess
from pathlib import Path
from typing import Optional

import requests

from app.config import settings

_OUTPUT_DIR = Path("/app/data/outputs")
_MUSIC_CACHE = Path("/app/data/music_cache")

# Mood → Pixabay music search queries
_MOOD_QUERIES: dict[str, str] = {
    "horror": "dark+ambient+horror+cinematic",
    "mystery": "mystery+suspense+cinematic",
    "wealth": "corporate+motivational+uplifting",
    "softskills": "inspirational+calm+ambient",
}

# Mood → Pixabay SFX search queries  
_SFX_QUERIES: dict[str, list[str]] = {
    "horror": ["creepy+atmosphere", "horror+stinger", "suspense+drone"],
    "mystery": ["mystery+suspense", "eerie+pad"],
}


class SoundscapeService:
    def __init__(self) -> None:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process(self, job_id: str, content: str, tts_path: str) -> str:
        """Full pipeline: download music + SFX → mix with TTS."""
        mood = self._detect_mood(content)
        duration = self._get_audio_duration(tts_path)

        # Try Pixabay music first, fall back to synth
        music_path = self._download_music(mood) or self._generate_synth_ambient(job_id, mood, duration)

        # Try Pixabay SFX
        sfx_files = self._download_sfx(mood, job_id)

        return self._mix(job_id, tts_path, music_path, sfx_files, duration)

    # ------------------------------------------------------------------
    # Mood detection
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_mood(content: str) -> str:
        lower = content.lower()
        scores = {
            "horror": sum(1 for w in [
                "dead", "blood", "dark", "scream", "fear", "ghost", "kill",
                "horror", "night", "shadow", "creep", "monster", "terror",
                "evil", "die", "bone", "cry", "haunt", "spider", "grave",
            ] if w in lower),
            "mystery": sum(1 for w in [
                "mystery", "secret", "unknown", "strange", "disappear",
                "vanished", "unsolved", "conspiracy", "hidden", "clue",
                "puzzle", "curious",
            ] if w in lower),
            "wealth": sum(1 for w in [
                "money", "rich", "wealth", "success", "million", "invest",
                "business", "profit", "income", "asset", "financial",
            ] if w in lower),
            "softskills": sum(1 for w in [
                "skill", "communicate", "leader", "confidence", "speak",
                "friend", "relationship", "coach", "learn", "grow",
            ] if w in lower),
        }
        max_score = max(scores.values()) if scores else 0
        if max_score == 0:
            return "mystery"
        return max(scores, key=scores.get)

    # ------------------------------------------------------------------
    # Pixabay Music API
    # ------------------------------------------------------------------
    def _download_music(self, mood: str) -> Optional[str]:
        """Download free background music from Pixabay Music API."""
        key = getattr(settings, "pixabay_api_key", None)
        if not key:
            return None

        query = _MOOD_QUERIES.get(mood, "cinematic+ambient")
        cache_key = f"{mood}_{hashlib.md5(query.encode()).hexdigest()[:8]}"
        cached = _MUSIC_CACHE / f"{cache_key}.mp3"
        if cached.exists() and cached.stat().st_size > 1000:
            return str(cached)

        try:
            resp = requests.get(
                "https://pixabay.com/api/music/",
                params={"key": key, "q": query, "per_page": 3},
                timeout=10,
            )
            hits = resp.json().get("hits", [])
            if not hits:
                return None

            # Pick the shortest track (free previews are ~30s)
            track = min(hits, key=lambda h: h.get("duration", 999))
            preview_url = track.get("preview_url") or track.get("audio")
            if not preview_url:
                return None

            audio_data = requests.get(preview_url, timeout=30).content
            cached.write_bytes(audio_data)
            return str(cached) if cached.stat().st_size > 1000 else None
        except Exception:
            return None

    def _download_sfx(self, mood: str, job_id: str) -> list[str]:
        """Download SFX from Pixabay SFX API. Returns list of file paths."""
        key = getattr(settings, "pixabay_api_key", None)
        if not key:
            return []

        queries = _SFX_QUERIES.get(mood, ["suspense+stinger"])
        sfx_files = []
        for q in queries[:2]:  # Max 2 queries
            try:
                resp = requests.get(
                    "https://pixabay.com/api/sfx/",
                    params={"key": key, "q": q, "per_page": 2},
                    timeout=10,
                )
                hits = resp.json().get("hits", [])
                for hit in hits[:2]:
                    url = hit.get("preview_url") or hit.get("audio")
                    if not url:
                        continue
                    fpath = _OUTPUT_DIR / f"{job_id}_sfx_{len(sfx_files)}.mp3"
                    fpath.write_bytes(requests.get(url, timeout=20).content)
                    if fpath.stat().st_size > 500:
                        sfx_files.append(str(fpath))
            except Exception:
                pass
        return sfx_files

    # ------------------------------------------------------------------
    # ffmpeg synthesis (fallback)
    # ------------------------------------------------------------------
    def _generate_synth_ambient(self, job_id: str, mood: str, duration: float) -> str:
        synth_map = {
            "horror": (
                "anoisesrc=d=9999:c=brown:a=0.35,"
                "aevalsrc='sin(35*2*PI*t)*0.15+sin(50*2*PI*t)*0.10':d=9999,"
                "amix=inputs=2:duration=first,lowpass=f=300"
            ),
            "mystery": (
                "aevalsrc='sin(100*2*PI*t)*0.10+sin(160*2*PI*t)*0.06':d=9999:s=44100,"
                "aecho=0.8:0.7:60:0.3,lowpass=f=500"
            ),
            "wealth": (
                "aevalsrc='sin(200*2*PI*t)*0.08+sin(300*2*PI*t)*0.05':d=9999:s=44100,lowpass=f=500"
            ),
            "softskills": (
                "aevalsrc='sin(150*2*PI*t)*0.06+sin(220*2*PI*t)*0.04':d=9999:s=44100,lowpass=f=400"
            ),
        }
        synth = synth_map.get(mood, synth_map["mystery"])
        output = str(_OUTPUT_DIR / f"{job_id}_ambient.mp3")
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", synth, "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "64k", output]
        subprocess.run(cmd, check=False, capture_output=True, timeout=30)
        return output if Path(output).exists() else ""

    # ------------------------------------------------------------------
    # Mixing
    # ------------------------------------------------------------------
    def _mix(self, job_id: str, tts_path: str, music_path: Optional[str], sfx_files: list[str], duration: float) -> str:
        output = str(_OUTPUT_DIR / f"{job_id}_final.mp3")
        inputs = ["ffmpeg", "-y"]
        count = 0

        inputs += ["-i", tts_path]
        idx_tts = count; count += 1

        idx_music = -1
        if music_path and Path(music_path).exists():
            inputs += ["-stream_loop", "-1", "-i", music_path]
            idx_music = count; count += 1

        sfx_indices = []
        for sfx in sfx_files:
            if Path(sfx).exists():
                inputs += ["-i", sfx]
                sfx_indices.append(count)
                count += 1

        if count == 1:
            # No music/SFX — just copy TTS
            subprocess.run(["ffmpeg", "-y", "-i", tts_path, "-c:a", "libmp3lame", "-b:a", "128k", output], check=False, capture_output=True, timeout=30)
            return output if Path(output).exists() else tts_path

        # Build filter: TTS + music(0.5) + SFX(0.3 each) → normalize
        weights = "1"  # TTS
        inputs_str = f"[{idx_tts}:a]"
        if idx_music >= 0:
            weights += " 0.5"
            inputs_str += f"[{idx_music}:a]"
        for _ in sfx_indices:
            weights += " 0.3"
            inputs_str += f"[{_}:a]"

        filter_complex = f"{inputs_str}amix=inputs={count}:duration=first:weights={weights}[a];[a]volume=1.2[aout]"
        cmd = inputs + [
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "libmp3lame", "-b:a", "128k",
            "-t", str(duration),
            output,
        ]
        subprocess.run(cmd, check=False, capture_output=True, timeout=60)
        return output if Path(output).exists() else tts_path

    @staticmethod
    def _get_audio_duration(path: str) -> float:
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True, timeout=10,
            )
            if probe.returncode == 0:
                return float(probe.stdout.strip())
        except Exception:
            pass
        return 60.0