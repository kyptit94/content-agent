"""Video composer: Image BG (Ken Burns zoom) + MC PIP overlay + NVENC encode."""
import subprocess
from pathlib import Path

_OUTPUT_DIR = Path("/app/data/outputs")

class VideoComposer:
    def __init__(self, crf=28, preset="p1"):
        self.crf = crf; self.preset = preset
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def compose(self, job_id, bg_image, audio_path, mc_video="", mc_scale=0.5, mc_x="10", mc_y="H-h-10"):
        output = str(_OUTPUT_DIR / f"{job_id}.mp4")
        duration = self._dur(audio_path)
        inputs = ["ffmpeg", "-y", "-hwaccel", "auto", "-loop", "1", "-i", bg_image]
        filters = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,zoompan=z='min(zoom+0.0002,1.04)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps=30[vbg]"]
        oi = 1
        if mc_video and Path(mc_video).exists():
            inputs += ["-stream_loop", "-1", "-i", mc_video]
            filters.append(f"[{oi}:v]scale=w=iw*{mc_scale}:h=ih*{mc_scale},setsar=1,format=rgba,colorchannelmixer=aa=0.9[vpip]")
            filters.append(f"[vbg][vpip]overlay={mc_x}:{mc_y}[vout]")
            oi += 1
        else:
            filters.append("[vbg]null[vout]")
        inputs += ["-i", audio_path]
        cmd = inputs + ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", f"{oi}:a", "-t", str(duration), "-c:v", "h264_nvenc", "-preset", self.preset, "-qp", str(self.crf), "-c:a", "aac", "-b:a", "192k", output]
        subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
        return output if Path(output).exists() else ""

    @staticmethod
    def _dur(p):
        try:
            r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",p], capture_output=True, text=True, timeout=10)
            return float(r.stdout.strip()) if r.returncode == 0 else 60
        except: return 60
