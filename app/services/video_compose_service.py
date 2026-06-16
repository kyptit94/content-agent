import subprocess
from pathlib import Path

from app.config import settings


class VideoComposeService:
    def __init__(self) -> None:
        self.output_dir = Path("/app/data/outputs")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _detect_encoder() -> tuple[str, list[str]]:
        """Returns (video_codec, extra_args) preferring NVENC GPU, falling back to CPU."""
        try:
            probe = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=10,
            )
            if "h264_nvenc" in probe.stdout:
                # GTX 1070 = NVENC, use GPU encoding
                return ("h264_nvenc", ["-preset", "p1", "-tune", "ll"])
        except Exception:
            pass
        # Fallback: CPU with veryfast preset
        return ("libx264", ["-preset", "veryfast"])

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
        is_image = source.suffix.lower() in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
        has_audio = bool(audio_path and Path(audio_path).exists())
        has_sub = bool(subtitle_path and Path(subtitle_path).exists())

        output_path = self.output_dir / f"{job_id}.mp4"
        safe_title = title.replace("'", " ").replace(":", " ")[:90]

        # --- Get actual audio duration via ffprobe ---
        duration_sec = 30.0
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

        # No upper limit — supports 1-hour+ content
        duration_sec = max(10.0, duration_sec)

        # Detect best encoder
        vcodec, vcodec_opts = self._detect_encoder()

        # Build video filter chain
        if is_image:
            # Image → use slow Ken Burns zoom for static image background
            vf_parts = [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
                "zoompan=z='min(zoom+0.00015,1.04)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30",
            ]
        else:
            vf_parts = [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
                "fps=30",
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

        cmd = ["ffmpeg", "-y", "-hwaccel", "auto"]
        if is_image:
            # For images, loop the single frame
            cmd += ["-loop", "1", "-i", str(source)]
        else:
            cmd += ["-stream_loop", "-1", "-i", str(source)]
        if has_audio:
            cmd += ["-i", audio_path]

        cmd += [
            "-t", str(duration_sec),
            "-vf", vf,
            "-c:v", vcodec,
            *vcodec_opts,
        ]

        if vcodec == "h264_nvenc":
            cmd += ["-qp", str(settings.video_reencode_crf)]
        else:
            cmd += ["-crf", str(settings.video_reencode_crf)]

        if has_audio:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]

        cmd += [str(output_path)]

        # No timeout — supports very long videos
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"Video compose failed: {completed.stderr[-1000:]}")

        return str(output_path)
