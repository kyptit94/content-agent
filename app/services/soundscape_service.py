"""
Auto background music & sound effects mixed into TTS audio.
Uses ffmpeg synthesis for ambient bed + text-triggered SFX.
"""
import logging
import subprocess
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger("soundscape")

_OUTPUT_DIR = Path("/app/data/outputs")

# Mood → ffmpeg ambient synth (amplified for audibility)
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
    "thunder|lightning|storm": (
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process(self, job_id: str, content: str, tts_path: str) -> str:
        """Full pipeline: detect mood → synth ambient → detect SFX → mix all with TTS."""
        mood = self._detect_mood(content)
        duration = self._get_audio_duration(tts_path)
        logger.info(f"[{job_id}] Soundscape: mood={mood}, duration={duration:.1f}s")

        # Generate ambient background
        ambient_path = self._generate_ambient(job_id, mood, duration)
        logger.info(f"[{job_id}] Ambient: {ambient_path or 'FAILED'}")

        # Generate SFX from text triggers
        sfx_files = self._generate_sfx(job_id, content)
        logger.info(f"[{job_id}] SFX: {len(sfx_files)} files")

        # Mix everything together
        result = self._mix(job_id, tts_path, ambient_path, sfx_files, duration)
        logger.info(f"[{job_id}] Mix result: {result}")
        return result

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
    # ffmpeg synthesis
    # ------------------------------------------------------------------
    def _generate_ambient(self, job_id: str, mood: str, duration: float) -> Optional[str]:
        """Generate ambient background audio for given mood and duration."""
        synth = _MOOD_SYNTH.get(mood, _MOOD_SYNTH["mystery"])
        output = str(_OUTPUT_DIR / f"{job_id}_ambient.mp3")

        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", synth,
            "-t", str(duration),
            "-c:a", "libmp3lame", "-b:a", "96k",
            output,
        ]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                logger.error(f"[{job_id}] Ambient synth failed: {result.stderr[-300:]}")
            if Path(output).exists() and Path(output).stat().st_size > 500:
                return output
        except Exception as e:
            logger.error(f"[{job_id}] Ambient exception: {e}")
        return None

    def _generate_sfx(self, job_id: str, content: str) -> list[str]:
        """Generate individual sound effect files from text triggers."""
        import re
        lower = content.lower()
        sfx_files = []
        for i, (pattern, synth) in enumerate(_SFX_TRIGGERS.items()):
            if i >= 4:  # Max 4 SFX
                break
            if not re.search(pattern, lower):
                continue
            output = str(_OUTPUT_DIR / f"{job_id}_sfx_{i}.mp3")
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", synth,
                "-t", "3",
                "-c:a", "libmp3lame", "-b:a", "64k",
                output,
            ]
            try:
                result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and Path(output).exists() and Path(output).stat().st_size > 300:
                    sfx_files.append(output)
                    logger.info(f"[{job_id}] SFX generated: {pattern}")
            except Exception as e:
                logger.error(f"[{job_id}] SFX error: {e}")
        return sfx_files

    # ------------------------------------------------------------------
    # Mixing
    # ------------------------------------------------------------------
    def _mix(self, job_id: str, tts_path: str, ambient_path: Optional[str], sfx_files: list[str], duration: float) -> str:
        output = str(_OUTPUT_DIR / f"{job_id}_final.mp3")
        inputs = ["ffmpeg", "-y"]
        count = 0

        inputs += ["-i", tts_path]
        idx_tts = count
        count += 1

        idx_ambient = -1
        if ambient_path and Path(ambient_path).exists():
            inputs += ["-stream_loop", "-1", "-i", str(ambient_path)]
            idx_ambient = count
            count += 1

        sfx_indices = []
        for sfx in sfx_files:
            if Path(sfx).exists():
                inputs += ["-i", str(sfx)]
                sfx_indices.append(count)
                count += 1

        if count == 1:
            # No ambient/SFX — just copy TTS
            logger.info(f"[{job_id}] Mix: TTS only (no ambient/SFX)")
            cmd = inputs + ["-c:a", "libmp3lame", "-b:a", "128k", output]
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            return output if Path(output).exists() else tts_path

        # Build filter: TTS (weight 1) + ambient (weight 0.8) + SFX (weight 0.6 each)
        weights = "1"
        input_labels = [f"[{idx_tts}:a]"]
        if idx_ambient >= 0:
            weights += " 0.8"
            input_labels.append(f"[{idx_ambient}:a]")
        for idx in sfx_indices:
            weights += " 0.6"
            input_labels.append(f"[{idx}:a]")

        filter_complex = (
            f"{''.join(input_labels)}"
            f"amix=inputs={count}:duration=first:weights={weights}"
            f"[a];[a]volume=1.3[aout]"
        )
        cmd = inputs + [
            "-filter_complex", filter_complex,
            "-map", "[aout]",
            "-c:a", "libmp3lame", "-b:a", "128k",
            "-t", str(duration),
            output,
        ]

        logger.info(f"[{job_id}] Mix: {count} tracks, weights={weights}")
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
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