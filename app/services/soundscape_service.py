"""
Auto-generates background music & sound effects matched to story mood.
Uses ffmpeg audio synthesis — no external audio files needed.
"""
import subprocess
from pathlib import Path
from typing import Optional


# Mood profiles → ffmpeg audio synthesis commands
_MOOD_AMBIENT: dict[str, str] = {
    "horror": (
        "anoisesrc=d=9999:c=brown:a=0.40,"
        "aevalsrc='sin(40*2*PI*t)*0.20+sin(55*2*PI*t)*0.15+sin(80*2*PI*t)*0.10':d=9999,"
        "amix=inputs=2:duration=first,"
        "lowpass=f=300"
    ),
    "mystery": (
        "aevalsrc='sin(120*2*PI*t)*0.15+sin(180*2*PI*t)*0.10+sin(250*2*PI*t)*0.08':d=9999:s=44100,"
        "highpass=f=80,lowpass=f=600,"
        "aecho=0.8:0.7:40:0.3"
    ),
    "wealth": (
        "aevalsrc='sin(200*2*PI*t)*0.10+sin(300*2*PI*t)*0.08+sin(400*2*PI*t)*0.06':d=9999:s=44100,"
        "lowpass=f=500"
    ),
    "softskills": (
        "aevalsrc='sin(150*2*PI*t)*0.08+sin(220*2*PI*t)*0.06+sin(330*2*PI*t)*0.04':d=9999:s=44100,"
        "lowpass=f=400"
    ),
}

# Keyword → SFX (simple ffmpeg synthesis)
_SFX_TRIGGERS: dict[str, str] = {
    "door": "aevalsrc='(1-abs(mod(t*3,2)-1))*0.3*exp(-t*10)':d=1.5:s=44100,lowpass=f=200",
    "thunder|lightning|storm": "aevalsrc='random(0)*0.4*exp(-t*3)':d=3:s=44100,lowpass=f=150",
    "heartbeat|heart": "aevalsrc='(1-abs(mod(t*1.5,2)-1))*0.2*exp(-t*0.5)':d=2:s=44100,lowpass=f=80",
    "scream|shouted|yelled": "aevalsrc='sin(800*2*PI*t*(1+mod(t*5,2)*0.5))*0.15*exp(-t*3)':d=2:s=44100",
    "footstep|walked|ran|running": "aevalsrc='(1-abs(mod(t*2,1.5)-0.75))*0.05*exp(-t*20)':d=0.3:s=44100,lowpass=f=100",
    "whisper|whispered|quietly": "anoisesrc=d=2:c=pink:a=0.08:s=44100,highpass=f=1000,lowpass=f=3000",
    "water|rain|raining": "anoisesrc=d=4:c=white:a=0.15:s=44100,highpass=f=2000,lowpass=f=6000",
    "fire|burned|flames": "anoisesrc=d=2:c=pink:a=0.12:s=44100,lowpass=f=300,aevalsrc='sin(20*2*PI*t)*0.05':d=2,amix=inputs=2:duration=first",
}

_OUTPUT_DIR = Path("/app/data/outputs")


class SoundscapeService:
    def __init__(self) -> None:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def detect_mood(self, content: str) -> str:
        """Detect story mood from keywords in content."""
        lower = content.lower()
        horror_score = sum(1 for w in ["dead", "blood", "dark", "scream", "fear", "ghost", "kill", "horror", "night", "shadow", "creep", "monster", "terror", "evil", "die", "bone", "cry"] if w in lower)
        mystery_score = sum(1 for w in ["mystery", "secret", "unknown", "strange", "disappear", "vanished", "unsolved", "conspiracy", "hidden", "clue", "puzzle", "curious"] if w in lower)
        wealth_score = sum(1 for w in ["money", "rich", "wealth", "success", "million", "invest", "business", "profit", "income", "asset", "financial"] if w in lower)
        soft_score = sum(1 for w in ["skill", "communicate", "leader", "confidence", "speak", "friend", "relationship", "coach", "learn", "grow"] if w in lower)
        max_score = max(horror_score, mystery_score, wealth_score, soft_score)
        if max_score == 0:
            return "mystery"  # default
        if horror_score == max_score:
            return "horror"
        if mystery_score == max_score:
            return "mystery"
        if wealth_score == max_score:
            return "wealth"
        return "softskills"

    def detect_sfx_triggers(self, content: str) -> list[dict]:
        """Find sound effect triggers in the text. Returns list of {type, position, duration}."""
        import re
        lower = content.lower()
        sfx_list = []
        for pattern, synth in _SFX_TRIGGERS.items():
            for match in re.finditer(pattern, lower):
                # Position in text (as fraction 0-1)
                pos = match.start() / max(len(lower), 1)
                sfx_list.append({
                    "type": pattern.split("|")[0],
                    "position": pos,
                    "synth": synth,
                })
        return sfx_list

    def generate_ambient(self, job_id: str, mood: str, duration_sec: float) -> Optional[str]:
        """Generate ambient background audio for given mood and duration."""
        synth = _MOOD_AMBIENT.get(mood)
        if not synth:
            return None

        output = str(_OUTPUT_DIR / f"{job_id}_ambient.mp3")
        # Generate 9999-second ambient, then trim to actual duration
        cmd = [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", synth,
            "-t", str(duration_sec),
            "-c:a", "libmp3lame", "-b:a", "64k",
            output,
        ]
        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and Path(output).exists():
                return output
        except Exception:
            pass
        return None

    def generate_sfx(self, job_id: str, sfx_triggers: list[dict]) -> list[str]:
        """Generate individual sound effect files. Returns list of file paths."""
        sfx_files = []
        for i, sfx in enumerate(sfx_triggers[:5]):  # Max 5 SFX
            output = str(_OUTPUT_DIR / f"{job_id}_sfx_{i}.mp3")
            cmd = [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", sfx["synth"],
                "-t", "2",
                "-c:a", "libmp3lame", "-b:a", "48k",
                output,
            ]
            try:
                result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and Path(output).exists():
                    sfx_files.append({"path": output, "position": sfx["position"]})
            except Exception:
                pass
        return sfx_files

    def mix_with_tts(self, job_id: str, tts_path: str, ambient_path: Optional[str], sfx_files: list[dict]) -> str:
        """Mix TTS audio + ambient background + SFX into final MP3."""
        output = str(_OUTPUT_DIR / f"{job_id}_final.mp3")

        cmd = ["ffmpeg", "-y"]
        inputs = ["-i", tts_path]
        input_count = 1

        # Add ambient as second input
        if ambient_path and Path(ambient_path).exists():
            inputs += ["-i", ambient_path]
            input_count += 1
        else:
            ambient_path = None

        # Add SFX files as additional inputs
        sfx_data = []
        for sfx in sfx_files:
            if Path(sfx["path"]).exists():
                inputs += ["-i", sfx["path"]]
                sfx_data.append({"index": input_count, "position": sfx["position"]})
                input_count += 1

        # Build filter graph
        filter_parts = []
        for i in range(input_count):
            filter_parts.append(f"[{i}:a]")

        if input_count == 1:
            # Just TTS, no mixing needed — copy
            cmd = [
                "ffmpeg", "-y",
                "-i", tts_path,
                "-c:a", "libmp3lame", "-b:a", "128k",
                output,
            ]
        elif input_count == 2:
            # TTS + ambient: simple mix
            filter_complex = f"[0:a][1:a]amix=inputs=2:duration=first:weights=1 0.6[a];[a]volume=1.2[aout]"
            cmd = inputs + [
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-c:a", "libmp3lame", "-b:a", "128k",
                output,
            ]
        else:
            # TTS + ambient + SFX: complex mix
            weights = "1"  # TTS weight
            for _ in range(1, input_count):
                weights += f" {0.2}"  # Lower weight for ambient + SFX
            filter_complex = f"{''.join(filter_parts)}amix=inputs={input_count}:duration=first:weights={weights}[a];[a]volume=1.3[aout]"
            cmd = inputs + [
                "-filter_complex", filter_complex,
                "-map", "[aout]",
                "-c:a", "libmp3lame", "-b:a", "128k",
                "-t", str(self._get_audio_duration(tts_path)),
                output,
            ]

        try:
            result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and Path(output).exists():
                return output
        except Exception:
            pass
        # Fallback: return original TTS
        return tts_path

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

    def process(self, job_id: str, content: str, tts_path: str) -> str:
        """Full pipeline: detect mood → generate ambient → detect SFX → mix all with TTS."""
        mood = self.detect_mood(content)
        duration = self._get_audio_duration(tts_path)

        # Generate ambient background
        ambient_path = self.generate_ambient(job_id, mood, duration)

        # Generate SFX from text triggers
        sfx_triggers = self.detect_sfx_triggers(content)
        sfx_files = self.generate_sfx(job_id, sfx_triggers)

        # Mix everything together
        return self.mix_with_tts(job_id, tts_path, ambient_path, sfx_files)