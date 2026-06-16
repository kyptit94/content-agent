"""
Adaptive soundscape engine — analyzes story paragraphs for mood shifts
and layers appropriate ambient music + SFX. Works with user MP3 files
or generates synth sounds via ffmpeg when no cache files exist.
"""
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger("soundscape")

_OUTPUT_DIR = Path("/app/data/outputs")
_MUSIC_CACHE = Path("/app/data/music_cache")

# Mood synth profiles (ffmpeg lavfi) — used when no cached MP3 file exists
_MOOD_SYNTH: Dict[str, str] = {
    "horror": (
        "anoisesrc=d=9999:c=brown:a=0.7,"
        "aevalsrc='sin(35*2*PI*t)*0.35+sin(52*2*PI*t)*0.25+sin(70*2*PI*t)*0.2':d=9999:s=44100,"
        "amix=inputs=2:duration=first,"
        "volume=2.0,lowpass=f=350"
    ),
    "mystery": (
        "aevalsrc='sin(90*2*PI*t)*0.3+sin(150*2*PI*t)*0.2+sin(220*2*PI*t)*0.15':d=9999:s=44100,"
        "volume=2.0,lowpass=f=600,aecho=0.8:0.7:50:0.3"
    ),
    "action": (
        "aevalsrc='sin(60*2*PI*t)*0.4+sin(120*2*PI*t)*0.3+sin(250*2*PI*t)*0.2':d=9999:s=44100,"
        "volume=2.5,lowpass=f=800,"
        "anoisesrc=d=9999:c=brown:a=0.4,amix=inputs=2:duration=first"
    ),
    "calm": (
        "aevalsrc='sin(150*2*PI*t)*0.15+sin(220*2*PI*t)*0.10+sin(300*2*PI*t)*0.08':d=9999:s=44100,"
        "volume=1.5,lowpass=f=500"
    ),
    "sad": (
        "aevalsrc='sin(130*2*PI*t)*0.25+sin(200*2*PI*t)*0.15':d=9999:s=44100,"
        "volume=2.0,lowpass=f=400,aecho=0.8:0.7:80:0.4"
    ),
    "intense": (
        "aevalsrc='sin(55*2*PI*t)*0.5+sin(82*2*PI*t)*0.35+sin(110*2*PI*t)*0.25':d=9999:s=44100,"
        "anoisesrc=d=9999:c=brown:a=0.5,amix=inputs=2:duration=first,"
        "volume=2.5,lowpass=f=500"
    ),
}

# Paragraph mood keywords
_MOOD_KEYWORDS: Dict[str, List[str]] = {
    "horror": ["dead", "blood", "dark", "scream", "fear", "ghost", "kill", "night", "shadow", "creep", "monster", "terror", "evil", "die", "bone", "cry", "haunt", "spider", "grave", "corpse", "horror", "afraid", "cold"],
    "action": ["ran", "running", "chase", "fight", "punch", "shot", "explode", "crash", "jump", "flew", "speed", "rush", "charged", "battle", "attack", "defend"],
    "mystery": ["mystery", "secret", "unknown", "strange", "disappear", "vanished", "hidden", "clue", "puzzle", "curious", "suspect", "detective", "investigate"],
    "calm": ["peace", "quiet", "gentle", "soft", "sleep", "dream", "smile", "warm", "comfort", "safe", "home", "love", "kind", "happy"],
    "sad": ["tear", "cry", "sad", "alone", "lost", "miss", "grief", "pain", "sorrow", "funeral", "goodbye", "memory", "empty"],
    "intense": ["suddenly", "heartbeat", "tension", "anxiety", "pressure", "stressed", "panic", "chaos", "conflict"],
}

# SFX keyword matchers — map to cached files or synth
_SFX_KEYWORDS: List[str] = [
    "door", "creak", "thunder", "lightning", "heartbeat", "scream", "footstep",
    "whisper", "rain", "fire", "glass", "gun", "bell", "wind", "clock",
    "laugh", "cry", "explosion", "water", "bird", "wolf", "ghost",
    "knock", "bang", "slam", "crash", "ring", "buzz",
]

# Synth fallback for SFX (simple but effective)
_SFX_SYNTH: Dict[str, str] = {
    "door": "aevalsrc='(1-abs(mod(t*3,2)-1))*0.8*exp(-t*8)':d=1.5:s=44100,lowpass=f=200,volume=2.0",
    "thunder": "aevalsrc='random(0)*0.9*exp(-t*2)':d=3:s=44100,lowpass=f=120,volume=2.0",
    "scream": "aevalsrc='sin(500*2*PI*t*(1+mod(t*5,2)*0.4))*0.4*exp(-t*3)':d=2:s=44100,volume=2.0",
    "footstep": "aevalsrc='(1-abs(mod(t*2,1.5)-0.75))*0.2*exp(-t*10)':d=0.4:s=44100,lowpass=f=100,volume=2.0",
    "wind": "anoisesrc=d=2:c=white:a=0.4:s=44100,highpass=f=200,lowpass=f=2000,volume=1.5",
    "rain": "anoisesrc=d=3:c=white:a=0.5:s=44100,highpass=f=2000,lowpass=f=7000,volume=1.5",
    "fire": "anoisesrc=d=2:c=pink:a=0.4:s=44100,lowpass=f=300,volume=1.5",
    "heartbeat": "aevalsrc='(1-abs(mod(t*1.5,2)-1))*0.5*exp(-t*0.3)':d=2:s=44100,lowpass=f=60,volume=2.0",
}


class SoundscapeService:
    def __init__(self) -> None:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _MUSIC_CACHE.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def process(self, job_id: str, content: str, tts_path: str, user_music: Optional[str] = None) -> str:
        """Full pipeline: paragraph mood analysis → segment ambient → SFX → mix."""
        duration = self._get_audio_duration(tts_path)
        paragraphs = self._split_paragraphs(content)
        total_chars = max(len(content), 1)

        logger.info(f"[{job_id}] Soundscape: {len(paragraphs)} paragraphs, {duration:.1f}s")

        # Analyze mood per paragraph
        moods = [self._detect_mood(p) for p in paragraphs]

        # Generate ambient audio segments per mood
        ambient_segments = self._generate_mood_segments(job_id, paragraphs, moods, duration)

        # Generate SFX with timestamps
        sfx_entries = self._generate_timed_sfx(job_id, content, duration, total_chars)

        # User music as base layer
        music_base = self._get_user_music(user_music)
        if not music_base:
            music_base = self._generate_ambient(job_id, "mystery", duration)

        # Mix all layers
        return self._mix_multi_layer(job_id, tts_path, music_base, ambient_segments, sfx_entries, duration)

    # ------------------------------------------------------------------
    # Content analysis
    # ------------------------------------------------------------------
    @staticmethod
    def _split_paragraphs(content: str) -> List[str]:
        """Split content into paragraphs by double newlines or sentences."""
        # First clean the content
        clean = re.sub(r"###\s*|\s*---\s*", "", content)
        # Try splitting by double newlines
        parts = re.split(r"\n\s*\n", clean)
        if len(parts) >= 2:
            return [p.strip() for p in parts if len(p.strip()) > 20]
        # Fallback: split by sentences (every 2 sentences = 1 paragraph)
        sentences = re.split(r"(?<=[.!?])\s+", clean)
        groups = []
        for i in range(0, len(sentences), 3):
            chunk = " ".join(sentences[i:i+3]).strip()
            if len(chunk) > 20:
                groups.append(chunk)
        return groups if groups else [clean[:200]]

    def _detect_mood(self, text: str) -> str:
        """Score mood keywords and return the dominant mood."""
        lower = text.lower()
        scores = {}
        for mood, words in _MOOD_KEYWORDS.items():
            scores[mood] = sum(1 for w in words if w in lower)
        if not scores or max(scores.values()) == 0:
            return "mystery"  # default
        return max(scores, key=scores.get)

    # ------------------------------------------------------------------
    # Ambient generation
    # ------------------------------------------------------------------
    def _generate_mood_segments(self, job_id: str, paragraphs: List[str], moods: List[str], total_duration: float) -> List[Dict]:
        """Generate ambient audio for each mood segment. Returns [{path, start_time_s, end_time_s, mood}]."""
        total_chars = max(1, sum(len(p) for p in paragraphs))
        segments = []
        time_cursor = 0.0

        for i, (para, mood) in enumerate(zip(paragraphs, moods)):
            # Calculate duration for this paragraph based on text length ratio
            para_dur = (len(para) / total_chars) * total_duration
            if i == len(paragraphs) - 1:
                para_dur = total_duration - time_cursor  # last segment fills remainder
            para_dur = max(2.0, para_dur)

            # Check cache for user-provided mood music
            cached = _MUSIC_CACHE / f"{mood}_bg.mp3"
            if cached.exists() and cached.stat().st_size > 1000:
                ambient_path = str(cached)
            else:
                ambient_path = self._generate_ambient(job_id, mood, para_dur)

            if ambient_path:
                segments.append({
                    "path": ambient_path,
                    "start": time_cursor,
                    "end": time_cursor + para_dur,
                    "mood": mood,
                })
            time_cursor += para_dur

        return segments

    def _generate_ambient(self, job_id: str, mood: str, duration: float) -> Optional[str]:
        """Generate ambient synth for a mood. Returns file path."""
        synth = _MOOD_SYNTH.get(mood, _MOOD_SYNTH["mystery"])
        output = str(_OUTPUT_DIR / f"{job_id}_{mood}.mp3")
        cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", synth, "-t", str(duration), "-c:a", "libmp3lame", "-b:a", "96k", output]
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
        return output if Path(output).exists() and Path(output).stat().st_size > 500 else None

    # ------------------------------------------------------------------
    # User music
    # ------------------------------------------------------------------
    def _get_user_music(self, user_path: Optional[str]) -> Optional[str]:
        """Check user-uploaded music path."""
        if user_path and Path(user_path).exists():
            return user_path
        # Check any uploaded file
        for f in _MUSIC_CACHE.glob("uploaded_*"):
            if f.stat().st_size > 1000:
                return str(f)
        return None

    # ------------------------------------------------------------------
    # SFX (timed)
    # ------------------------------------------------------------------
    def _generate_timed_sfx(self, job_id: str, content: str, total_duration: float, total_chars: int) -> List[Dict]:
        """Generate SFX at timestamps matching keyword positions."""
        lower = content.lower()
        entries = []
        used_files = set()
        count = 0

        for keyword in _SFX_KEYWORDS:
            if count >= 8:
                break
            for match in re.finditer(rf"\b{keyword}\b", lower):
                if count >= 8:
                    break
                sfx_file = self._get_sfx_file(keyword, job_id, count, used_files)
                if not sfx_file:
                    continue
                char_pos = match.start()
                delay_ms = int((char_pos / total_chars) * total_duration * 1000)
                entries.append({"path": sfx_file, "delay_ms": delay_ms, "type": keyword})
                used_files.add(sfx_file)
                count += 1
        return entries

    def _get_sfx_file(self, keyword: str, job_id: str, idx: int, used: set) -> Optional[str]:
        """Get SFX: cache > synth. Returns file path."""
        # Check cache for user-uploaded file
        for ext in [".mp3", ".wav", ".ogg"]:
            for candidate in _MUSIC_CACHE.glob(f"{keyword}*{ext}"):
                if str(candidate) not in used and candidate.stat().st_size > 500:
                    return str(candidate)
        # Fallback: synth generation
        synth = _SFX_SYNTH.get(keyword)
        if synth:
            output = str(_OUTPUT_DIR / f"{job_id}_sfx_{idx}.mp3")
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", synth, "-t", "3", "-c:a", "libmp3lame", "-b:a", "64k", output]
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=10)
            if Path(output).exists() and Path(output).stat().st_size > 300:
                return output
        return None

    # ------------------------------------------------------------------
    # Multi-layer mixing
    # ------------------------------------------------------------------
    def _mix_multi_layer(self, job_id: str, tts_path: str, base_music: Optional[str], mood_segments: List[Dict], sfx_entries: List[Dict], total_duration: float) -> str:
        """Mix TTS + mood_segments + SFX into final audio."""
        output = str(_OUTPUT_DIR / f"{job_id}_final.mp3")

        # For complex multi-layer mixing, use a concat approach:
        # 1. First generate a "mood track" that concatenates mood ambient segments
        # 2. Then mix TTS + mood track + SFX

        # Step 1: Build mood track
        mood_track = self._build_mood_track(job_id, mood_segments, total_duration)

        # Step 2: Mix TTS + mood_track + SFX
        inputs = ["ffmpeg", "-y"]
        filter_parts = []
        count = 0

        inputs += ["-i", tts_path]
        filter_parts.append(f"[{count}:a]adelay=0|0[a{count}]")
        count += 1

        if mood_track and Path(mood_track).exists():
            inputs += ["-i", mood_track]
            filter_parts.append(f"[{count}:a]adelay=0|0,volume=0.5[a{count}]")
            count += 1

        for i, sfx in enumerate(sfx_entries):
            delay = max(0, min(sfx["delay_ms"], int(total_duration * 1000)))
            inputs += ["-i", sfx["path"]]
            filter_parts.append(f"[{count}:a]adelay={delay}|{delay},volume=0.9[a{count}]")
            count += 1

        if count == 1:
            cmd = inputs + ["-c:a", "libmp3lame", "-b:a", "128k", output]
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
            return output if Path(output).exists() else tts_path

        mix_inputs = "".join(f"[a{i}]" for i in range(count))
        filter_complex = ";".join(filter_parts) + f";{mix_inputs}amix=inputs={count}:duration=first:normalize=0[aout]"
        cmd = inputs + ["-filter_complex", filter_complex, "-map", "[aout]", "-c:a", "libmp3lame", "-b:a", "128k", "-t", str(total_duration), output]
        try:
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=180)
        except Exception:
            pass
        return output if Path(output).exists() else tts_path

    def _build_mood_track(self, job_id: str, segments: List[Dict], total_duration: float) -> Optional[str]:
        """Concatenate mood ambient segments into one track that matches story duration."""
        if not segments:
            return None

        # If only one segment, just use it directly
        if len(segments) == 1 and abs(segments[0]["end"] - segments[0]["start"] - total_duration) < 1.0:
            return segments[0]["path"]

        # Build concat file
        concat_list = str(_OUTPUT_DIR / f"{job_id}_concat.txt")
        output = str(_OUTPUT_DIR / f"{job_id}_moodtrack.mp3")

        with open(concat_list, "w") as f:
            for seg in segments:
                dur = seg["end"] - seg["start"]
                f.write(f"file '{seg['path']}'\n")
                f.write(f"duration {dur:.3f}\n")

        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c:a", "libmp3lame", "-b:a", "96k", output]
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=30)
        return output if Path(output).exists() else None

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