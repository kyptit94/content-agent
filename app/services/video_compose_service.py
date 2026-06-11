import subprocess
from pathlib import Path

from app.config import settings


class VideoComposeService:
    def __init__(self) -> None:
        self.output_dir = Path("/app/data/outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def compose(
        self,
        job_id: str,
        source_video_path: str,
        audio_path: str | None,
        title: str,
        preserve_quality: bool = True,
        overlay_text: bool = False,
        subtitle_path: str | None = None,
        audio_duration_sec: float | None = None,
    ) -> str:
        source = Path(source_video_path)
        if not source.exists():
            raise RuntimeError(f"Source video not found: {source_video_path}")

        has_audio = bool(audio_path and Path(audio_path).exists())
        has_sub = bool(subtitle_path and Path(subtitle_path).exists())

        output_path = self.output_dir / f"{job_id}.mp4"
        safe_title = title.replace("'", " ").replace(":", " ")[:90]

        # --- Get actual audio duration via ffprobe ---
        duration_sec = 30.0  # default fallback
        if has_audio:
            try:
                probe = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                    capture_output=True, text=True, timeout=15,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    duration_sec = float(probe.stdout.strip())
            except Exception:
                duration_sec = audio_duration_sec or 30.0
        else:
            duration_sec = audio_duration_sec or 30.0

        # Duration must be reasonable
        duration_sec = max(10.0, min(duration_sec, 60.0))  # clamp 10s-60s

        # Build video filter chain
        vf_parts = [
            "scale=1080:1920:force_original_aspect_ratio=increase",
            "crop=1080:1920",
        ]
        if overlay_text:
            vf_parts.append(
                "drawtext=text='{}':x=(w-text_w)/2:y=h-170:"
                "fontsize=46:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=14".format(safe_title)
            )
        if has_sub:
            sub_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
            vf_parts.append(f"ass={sub_escaped}")

        vf = ",".join(vf_parts)

        # Always loop video to match audio length
        # ALWAYS use re-encode path because copy path CANNOT loop
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(source),
        ]
        if has_audio:
            cmd += ["-i", audio_path]
        cmd += [
            "-t", str(duration_sec),
            "-vf", vf,
            "-c:v", "libx264",
            "-crf", str(settings.video_reencode_crf),
            "-preset", settings.video_reencode_preset,
        ]
        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            # map audio
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        cmd += [str(output_path)]

        completed = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
        if completed.returncode != 0:
            raise RuntimeError(f"Video compose failed: {completed.stderr[-1000:]}")

        return str(output_path)