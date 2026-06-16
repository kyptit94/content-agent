"""
Auto background music & sound effects mixed into TTS audio.
SFX plays at exact timestamp matching keyword position in text.
Supports uploaded user music from /app/data/music_cache/.
"""
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("soundscape")

_OUTPUT_DIR = Path("/app/data/outputs")
_MUSIC_CACHE = Path("/app/data/music_cache")

# Mood → ffmpeg ambient synth
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
    "wealth": (
        "aevalsrc='sin(180*2*PI*t)*0.2+sin(260*2*PI*t)*0.12+sin(350*2*PI*t)*0.08':d=9999:s=44100,"
        "volume=1.5,lowpass=f=600"
    ),
    "softskills": (
        "aevalsrc='sin(150*2*PI*t)*0.15+sin(220*2*PI*t)*0.10+sin(300*2*PI*t)*0.06':d=9999:s=44100,"
        "volume=1.5,lowpass=f=500"
    ),
}

# Text triggers → ffmpeg SFX synth
_SFX_TRIGGERS: dict[str, str] = {
    "door|creaked|creak": (
        "aevalsrc='(1-abs(mod(t*3,2)-1))*0.6*exp(-t*8)':d=1.5:s=44100,lowpass=f=200,volume=1.5"
    ),
    "thunder|lightning": (
        "aevalsrc='random(0)*0.8*exp(-t*2)':d=3:s=44100,lowpass=f=150,volume=1.3"
    ),
    "heartbeat|heart": (
        "aevalsrc='(1-abs(mod(t*1.5,2)-1))*0.4*exp(-t*0.3)':d=2:s=44100,lowpass=f=80,volume=1.3"
    ),
    "scream|shouted|yelled|shattered": (
        "aevalsrc='sin(600*2*PI*t*(1+mod(t*5,2)*0.4))*0.3*exp(-t*3)':d=2:s=44100,volume=1.3"
    ),
    "footstep|footsteps|walked|ran|running|echoed": (
        "aevalsrc='(1-abs(mod(t*2,1.5)-0.75))*0.15*exp(-t*15)':d=0.5:s=44100,lowpass=f=120,volume=1.5"
    ),
    "whisper|whispered": (
        "anoisesrc=d=2:c=pink:a=0.2:s=44100,highpass=f=800,lowpass=f=3000,volume=1.5"
    ),
    "rain|raining|water|storm": (
        "anoisesrc=d=4:c=white:a=0.3:s=44100,highpass=f=2000,lowpass=f=7000,volume=1.3"
    ),
    "fire|burned|flames": (
        "anoisesrc=d=2:c=pink:a=0.25:s=44100,lowpass=f=350,volume=1.3"
    ),
}


class SoundscapeService:
    def __init__(self) -> None:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process(self, job_id: str, content: str, tts_path: str, user_music: Optional[str] = None) -> str:
        """Full pipeline: detect mood → synth ambient → detect SFX (with timing) → mix all with TTS."""
        mood = self._detect_mood(content)
        duration = self._get_audio_duration(tts_path)
        logger.info(f"[{job_id}] Soundscape: mood={mood}, duration={duration:.1f}s")

        # Music: user upload > cache > synth
        music_path = self._get_music(user_music, mood, job_id, duration)

        # SFX with timestamps
        sfx_entries = self._generate_timed_sfx(job_id, content, duration, len(content))
        logger.info(f"[{job_id}] SFX: {len(sfx_entries)} timed effects")

        # Mix everything
        return self._mix(job_id, tts_path, music_path, sfx_entries, duration)

    # ------------------------------------------------------------------
    # Music source
    # ------------------------------------------------------------------
    def _get_music(self, user_path: Optional[str], mood: str, job_id: str, duration: float) -> Optional[str]:
        """Get background music: user upload > cached > synth."""
        # 1. User-uploaded music
        if user_path and Path(user_path).exists():
            return user_path

        # 2. Cached music for this mood
        cached = _MUSIC_CACHE / f"{mood}_bg.mp3"
        if cached.exists() and cached.stat().st_size > 1000:
            return str(cached)

        # 3. Synth fallback
        return self._generate_ambient(job_id, mood, duration)

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
    # ffmpeg ambient synth
    # ------------------------------------------------------------------
    def _generate_ambient(self, job_id: str, mood: str, duration: float) -> Optional[str]:
        synth = _MOOD_SYNTH.get(mood, _MOOD_SYNTH["mystery"])
        output = str(_OUTPUT_DIR / f"{job_id}_ambient.mp3")
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi", "-i", synth,
            "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "96k", output,
        ]
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            if Path(output).exists() and Path(output).stat().st_size > 500:
                return output
        except Exception as e:
            logger.error(f"[{job_id}] Ambient exception: {e}")
        return None

    # ------------------------------------------------------------------
    # Timed SFX generation
    # ------------------------------------------------------------------
    def _generate_timed_sfx(self, job_id: str, content: str, total_duration: float, total_chars: int) -> list[dict]:
        """Generate SFX at the right timestamp based on keyword position in text.
        Returns list of {path, delay_ms}.
        """
        import re
        lower = content.lower()
        entries = []
        count = 0

        for pattern, synth in _SFX_TRIGGERS.items():
            if count >= 5:
                break
            for match in re.finditer(pattern, lower):
                if count >= 5:
                    break
                # Calculate timestamp: position_in_text / total_chars * total_duration
                char_pos = match.start()
                fraction = char_pos / max(total_chars, 1)
                delay_ms = int(fraction * total_duration * 1000)

                # Generate SFX file
                sfx_path = str(_OUTPUT_DIR / f"{job_id}_sfx_{count}.mp3")
                cmd = [
                    "ffmpeg", "-y", "-f", "lavfi", "-i", synth,
                    "-t", "3", "-c:a", "libmp3lame", "-b:a", "64k", sfx_path,
                ]
                try:
                    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0 and Path(sfx_path).exists() and Path(sfx_path).stat().st_size > 300:
                        entries.append({"path": sfx_path, "delay_ms": delay_ms, "type": pattern.split("|")[0]})
                        logger.info(f"[{job_id}] SFX '{pattern.split('|')[0]}' at {delay_ms}ms")
                        count += 1
                except Exception as e:
                    logger.error(f"[{job_id}] Timed SFX error: {e}")

        return entries

    # ------------------------------------------------------------------
    # Mixing with timed SFX
    # ------------------------------------------------------------------
    def _mix(self, job_id: str, tts_path: str, music_path: Optional[str], sfx_entries: list[dict], duration: float) -> str:
        output = str(_OUTPUT_DIR / f"{job_id}_final.mp3")
        inputs = ["ffmpeg", "-y"]
        filter_parts = []
        count = 0

        # Track 0: TTS
        inputs += ["-i", tts_path]
        filter_parts.append(f"[{count}:a]adelay=0|0[a{count}]")
        count += 1

        # Track 1: Music (ambient or user-uploaded)
        if music_path and Path(music_path).exists():
            dur = self._get_audio_duration(music_path)
            if dur < duration:
                inputs += ["-stream_loop", "-1", "-i", str(music_path)]
            else:
                inputs += ["-i", str(music_path)]
            filter_parts.append(f"[{count}:a]atrim=0:{duration},adelay=0|0,volume=0.6[a{count}]")
            count += 1

        # Tracks 2+: SFX with adelay
        sfx_labels = []
        for i, sfx in enumerate(sfx_entries):
            delay = max(0, min(sfx["delay_ms"], int(duration * 1000)))
            inputs += ["-i", sfx["path"]]
            filter_parts.append(f"[{count}:a]adelay={delay}|{delay},volume=0.9[a{count}]")
            sfx_labels.append(f"[a{count}]")
            count += 1

        if count == 1:
            # No music/SFX
            cmd = inputs + ["-c:a", "libmp3lame", "-b:a", "128k", output]
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            return output if Path(output).exists() else tts_path

        # Build final amix
        mix_inputs = "".join(f"[a{i}]" for i in range(count))
        filter_complex = ";".join(filter_parts) + f";{mix_inputs}amix=inputs={count}:duration=first:normalize=0[aout]"
        cmd = inputs + ["-filter_complex", filter_complex, "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "128k", "-t", str(duration), output]

        logger.info(f"[{job_id}] Mix: {count} tracks with timed SFX")
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error(f"[{job_id}] Mix failed: {result.stderr[-300:]}")
                return tts_path
        except Exception as e:
            logger.error(f"[{job_id}] Mix exception: {e}")
            return tts_path

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