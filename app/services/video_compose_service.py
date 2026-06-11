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
    ) -> str:
        source = Path(source_video_path)
        if not source.exists():
            raise RuntimeError(f"Source video not found: {source_video_path}")

        has_audio = bool(audio_path and Path(audio_path).exists())
        has_sub = bool(subtitle_path and Path(subtitle_path).exists())

        output_path = self.output_dir / f"{job_id}.mp4"
        safe_title = title.replace("'", " ").replace(":", " ")[:90]

        # Fast path: copy video stream, add audio, no filters needed
        if preserve_quality and has_audio and not overlay_text and not has_sub:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(source),
                "-i", audio_path,
                "-map", "0:v:0", "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                str(output_path),
            ]
            completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if completed.returncode == 0:
                return str(output_path)
            # Fall through to re-encode path if copy fails

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
            # Escape path for ffmpeg filter (Windows backslash and colons need escaping)
            sub_escaped = str(subtitle_path).replace("\\", "/").replace(":", "\\:")
            vf_parts.append(f"ass={sub_escaped}")

        vf = ",".join(vf_parts)

        if has_audio:
            cmd = [
                "ffmpeg", "-y",
                "-i", str(source),
                "-i", audio_path,
                "-shortest",
                "-vf", vf,
                "-c:v", "libx264",
                "-crf", str(settings.video_reencode_crf),
                "-preset", settings.video_reencode_preset,
                "-c:a", "aac", "-b:a", "192k",
                str(output_path),
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1",
                "-i", str(source),
                "-t", "30",
                "-vf", vf,
                "-c:v", "libx264",
                "-crf", str(settings.video_reencode_crf),
                "-preset", settings.video_reencode_preset,
                str(output_path),
            ]

        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"Video compose failed: {completed.stderr[-1000:]}")

        return str(output_path)

        source = Path(source_video_path)
        if not source.exists():
            raise RuntimeError(f"Source video not found: {source_video_path}")

        output_path = self.output_dir / f"{job_id}.mp4"
        safe_title = title.replace("'", " ").replace(":", " ")[:90]

        if preserve_quality and audio_path and Path(audio_path).exists() and not overlay_text:
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-i",
                audio_path,
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-shortest",
                str(output_path),
            ]
            completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
            if completed.returncode == 0:
                return str(output_path)

        if audio_path and Path(audio_path).exists():
            vf_parts = [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
            ]
            if overlay_text:
                vf_parts.append(
                    (
                        "drawtext=text='{}':x=(w-text_w)/2:y=h-170:"
                        "fontsize=46:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=14"
                    ).format(safe_title)
                )

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-i",
                audio_path,
                "-shortest",
                "-vf",
                ",".join(vf_parts),
                "-c:v",
                "libx264",
                "-crf",
                str(settings.video_reencode_crf),
                "-preset",
                settings.video_reencode_preset,
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                str(output_path),
            ]
        else:
            vf_parts = [
                "scale=1080:1920:force_original_aspect_ratio=increase",
                "crop=1080:1920",
            ]
            if overlay_text:
                vf_parts.append(
                    (
                        "drawtext=text='{}':x=(w-text_w)/2:y=h-170:"
                        "fontsize=46:fontcolor=white:box=1:boxcolor=black@0.45:boxborderw=14"
                    ).format(safe_title)
                )

            cmd = [
                "ffmpeg",
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(source),
                "-t",
                "30",
                "-vf",
                ",".join(vf_parts),
                "-c:v",
                "libx264",
                "-crf",
                str(settings.video_reencode_crf),
                "-preset",
                settings.video_reencode_preset,
                str(output_path),
            ]

        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            stderr = completed.stderr[-1000:]
            raise RuntimeError(f"Video compose failed: {stderr}")

        return str(output_path)
