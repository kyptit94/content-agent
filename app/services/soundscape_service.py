"""
Auto background music & sound effects mixed into TTS audio.
SFX plays at exact timestamp matching keyword position in text.
Uses REAL user-uploaded SFX files from /app/data/music_cache/.
Falls back to synth only if no real file found.
"""
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("soundscape")

_OUTPUT_DIR = Path("/app/data/outputs")
_MUSIC_CACHE = Path("/app/data/music_cache")

# Keyword → find matching cached file in music_cache/
# Example: "door" → music_cache/door.mp3, music_cache/slam.mp3
# Upload files via 🎵 button in web UI

_MOOD_SYNTH: dict[str, str] = {
    "horror": (
        "anoisesrc=d=9999:c=brown:a=0.6,"
        "aevalsrc='sin(35*2*PI*t)*0.3+sin(52*2*PI*t)*0.2+sin(70*2*PI*t)*0.15':d=9999:s=44100,"
        "amix=inputs=2:duration=first,"
        "volume=1.5,lowpass=f=400"
    ),
    "mystery": (
        "aevalsrc='sin(90*2*PI*t)*0.25+sin(150*2*PI*t)*0.15+sin(220*2*PI*t)*0.10':d=9999:s=44100,"
        "volume=1.5,lowpass=f=600,aecho=0.8:0.7:50:0.3"
    ),
}

_SFX_KEYWORDS: list[str] = [
    "door", "creak", "thunder", "lightning", "heartbeat", "scream", "footstep",
    "whisper", "rain", "fire", "glass", "gun", "bell", "wind", "clock",
    "laugh", "cry", "explosion", "water", "bird", "wolf", "ghost",
]


class SoundscapeService:
    def __init__(self) -> None:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

    def process(self, job_id: str, content: str, tts_path: str, user_music: Optional[str] = None) -> str:
        mood = self._detect_mood(content)
        duration = self._get_audio_duration(tts_path)
        logger.info(f"[{job_id}] Soundscape: mood={mood}, duration={duration:.1f}s")
        music_path = self._get_music(user_music, mood, job_id, duration)
        sfx_entries = self._find_timed_sfx(job_id, content, duration, len(content))
        logger.info(f"[{job_id}] SFX: {len(sfx_entries)} effects from cache")
        return self._mix(job_id, tts_path, music_path, sfx_entries, duration)

    def _get_music(self, user_path: Optional[str], mood: str, job_id: str, duration: float) -> Optional[str]:
        if user_path and Path(user_path).exists():
            return user_path
        cached = _MUSIC_CACHE / f"{mood}_bg.mp3"
        if cached.exists() and cached.stat().st_size > 1000:
            return str(cached)
        # Check any uploaded file as ambient
        for f in _MUSIC_CACHE.glob("uploaded_*"):
            if f.stat().st_size > 1000:
                return str(f)
        return self._generate_ambient(job_id, mood, duration)

    @staticmethod
    def _detect_mood(content: str) -> str:
        lower = content.lower()
        horror = sum(1 for w in "dead blood dark scream fear ghost kill horror night shadow creep monster terror evil die bone cry haunt".split() if w in lower)
        mystery = sum(1 for w in "mystery secret unknown strange disappear vanished unsolved conspiracy hidden clue puzzle curious".split() if w in lower)
        if horror >= mystery and horror > 0:
            return "horror"
        return "mystery"

    def _generate_ambient(self, job_id: str, mood: str, duration: float) -> Optional[str]:
        synth = _MOOD_SYNTH.get(mood, _MOOD_SYNTH["mystery"])
        output = str(_OUTPUT_DIR / f"{job_id}_ambient.mp3")
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", synth, "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "96k", output]
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
        return output if Path(output).exists() and Path(output).stat().st_size > 500 else None

    def _find_timed_sfx(self, job_id: str, content: str, total_duration: float, total_chars: int) -> list[dict]:
        """Find real SFX files in cache matching text keywords. Return {path, delay_ms}."""
        import re
        lower = content.lower()
        entries = []
        count = 0
        used_files = set()

        for keyword in _SFX_KEYWORDS:
            if count >= 5:
                break
            # Find all matches for this keyword
            for match in re.finditer(rf"\b{keyword}\b", lower):
                if count >= 5:
                    break
                # Try to find a cached SFX file
                sfx_file = self._find_cached_sfx(keyword, used_files)
                if not sfx_file:
                    continue

                char_pos = match.start()
                fraction = char_pos / max(total_chars, 1)
                delay_ms = int(fraction * total_duration * 1000)
                entries.append({"path": sfx_file, "delay_ms": delay_ms, "type": keyword})
                logger.info(f"[{job_id}] SFX '{keyword}' → {Path(sfx_file).name} at {delay_ms}ms")
                used_files.add(sfx_file)
                count += 1

        return entries

    def _find_cached_sfx(self, keyword: str, used: set) -> Optional[str]:
        """Look for {keyword}*.mp3 in music_cache. Return first match not already used."""
        for ext in [".mp3", ".wav", ".ogg"]:
            for candidate in _MUSIC_CACHE.glob(f"{keyword}*{ext}"):
                if str(candidate) not in used and candidate.stat().st_size > 500:
                    return str(candidate)
        return None

    def _mix(self, job_id: str, tts_path: str, music_path: Optional[str], sfx_entries: list[dict], duration: float) -> str:
        output = str(_OUTPUT_DIR / f"{job_id}_final.mp3")
        inputs = ["ffmpeg", "-y"]
        filter_parts = []
        count = 0

        inputs += ["-i", tts_path]
        filter_parts.append(f"[{count}:a]adelay=0|0[a{count}]")
        count += 1

        if music_path and Path(music_path).exists():
            dur = self._get_audio_duration(music_path)
            if dur < duration:
                inputs += ["-stream_loop", "-1", "-i", str(music_path)]
            else:
                inputs += ["-i", str(music_path)]
            filter_parts.append(f"[{count}:a]atrim=0:{duration},adelay=0|0,volume=0.6[a{count}]")
            count += 1

        for i, sfx in enumerate(sfx_entries):
            delay = max(0, min(sfx["delay_ms"], int(duration * 1000)))
            inputs += ["-i", sfx["path"]]
            filter_parts.append(f"[{count}:a]adelay={delay}|{delay},volume=1.0[a{count}]")
            count += 1

        if count == 1:
            cmd = inputs + ["-c:a", "libmp3lame", "-b:a", "128k", output]
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            return output if Path(output).exists() else tts_path

        mix_inputs = "".join(f"[a{i}]" for i in range(count))
        filter_complex = ";".join(filter_parts) + f";{mix_inputs}amix=inputs={count}:duration=first:normalize=0[aout]"
        cmd = inputs + ["-filter_complex", filter_complex, "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "128k", "-t", str(duration), output]
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
        except Exception:
            pass
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