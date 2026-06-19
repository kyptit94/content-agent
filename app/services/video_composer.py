"""Video composer: Single image or multi-image slideshow + MC PIP overlay + NVENC encode."""
import subprocess
import os
import tempfile
from pathlib import Path

_OUTPUT_DIR = Path("/app/data/outputs")

class VideoComposer:
    def __init__(self, crf=28, preset="p1"):
        self.crf = crf; self.preset = preset
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def compose(self, job_id, bg_image, audio_path, mc_video="", mc_scale=1.4, mc_x="W-w-10", mc_y="H-h-10"):
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

    def compose_slideshow(self, job_id, images: list, audio_path, mc_video="", mc_scale=1.8, mc_x="W-w-10", mc_y="H-h-10"):
        """
        Create a slideshow video: each image gets equal time slice of audio duration.
        Images are cross-faded with Ken Burns zoom effect + MC PIP overlay.
        """
        if not images:
            return self.compose(job_id, self._create_black(), audio_path, mc_video, mc_scale, mc_x, mc_y)
        
        output = str(_OUTPUT_DIR / f"{job_id}.mp4")
        total_duration = self._dur(audio_path)
        num_images = len(images)
        slide_duration = total_duration / num_images
        fps = 30
        
        # Build ffmpeg concat with per-image filters
        # Strategy: concat video segments, each with zoompan + overlay
        concat_file = str(_OUTPUT_DIR / f"{job_id}_concat.txt")
        segment_files = []
        
        for i, img_path in enumerate(images):
            seg_out = str(_OUTPUT_DIR / f"{job_id}_seg{i}.mp4")
            segment_files.append(seg_out)
            
            # Build per-segment filter
            has_mc = mc_video and Path(mc_video).exists()
            if has_mc:
                filter_complex = (
                    f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"fps=30[vbg];"
                    f"[1:v]scale=w=iw*{mc_scale}:h=ih*{mc_scale},setsar=1,format=rgba,colorchannelmixer=aa=0.9[vpip];"
                    f"[vbg][vpip]overlay={mc_x}:{mc_y}[vout]"
                )
                seg_cmd = [
                    "ffmpeg", "-y", "-hwaccel", "auto",
                    "-loop", "1", "-t", str(slide_duration), "-i", img_path,
                    "-stream_loop", "-1", "-i", mc_video,
                    "-filter_complex", filter_complex,
                    "-map", "[vout]", "-t", str(slide_duration),
                    "-c:v", "h264_nvenc", "-preset", self.preset, "-qp", str(self.crf),
                    seg_out
                ]
            else:
                filter_complex = (
                    f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                    f"fps=30[vout]"
                )
                seg_cmd = [
                    "ffmpeg", "-y", "-hwaccel", "auto",
                    "-loop", "1", "-t", str(slide_duration), "-i", img_path,
                    "-filter_complex", filter_complex,
                    "-map", "[vout]", "-t", str(slide_duration),
                    "-c:v", "h264_nvenc", "-preset", self.preset, "-qp", str(self.crf),
                    seg_out
                ]
            
            subprocess.run(seg_cmd, check=False, capture_output=True, text=True, timeout=300)
            print(f"[SLIDESHOW] Segment {i+1}/{num_images}: {seg_out} {'OK' if Path(seg_out).exists() else 'FAIL'}")
        
        # Crossfade all segments with xfade transition (VISIBLE IMAGE CHANGES!)
        valid_segs = [sf for sf in segment_files if Path(sf).exists()]
        
        if len(valid_segs) == 1:
            cmd = ["ffmpeg", "-y", "-hwaccel", "auto", "-i", valid_segs[0],
                   "-i", audio_path, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                   "-shortest", output]
            subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=300)
        elif len(valid_segs) > 1:
            xfade_cmd = ["ffmpeg", "-y", "-hwaccel", "auto"]
            for sf in valid_segs:
                xfade_cmd += ["-i", sf]
            xfade_cmd += ["-i", audio_path]
            
            # Build xfade chain: each image fades into the next (0.6s transition)
            xfade_dur = 0.6
            filters = []
            prev = "0"
            for i in range(1, len(valid_segs)):
                label = f"x{i-1}"
                offset = i * slide_duration - i * xfade_dur
                filters.append(f"[{prev}][{i}]xfade=transition=fade:duration={xfade_dur}:offset={offset}[{label}]")
                prev = label
            
            filter_str = ";".join(filters)
            audio_idx = len(valid_segs)
            xfade_cmd += [
                "-filter_complex", filter_str,
                "-map", f"[{prev}]",
                "-map", f"{audio_idx}:a",
                "-c:v", "h264_nvenc", "-preset", self.preset, "-qp", str(self.crf),
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", output
            ]
            subprocess.run(xfade_cmd, check=False, capture_output=True, text=True, timeout=600)

        # Cleanup segments
        for sf in segment_files:
            try:
                if os.path.exists(sf):
                    os.remove(sf)
            except:
                pass
        try:
            if os.path.exists(concat_file):
                os.remove(concat_file)
        except:
            pass
        
        return output if Path(output).exists() else ""

    def _create_black(self):
        """Create a black fallback image."""
        out = str(_OUTPUT_DIR / "_black.jpg")
        subprocess.run([
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=0x0b0d14:s=1080x1920:d=1",
            "-frames:v", "1", out,
        ], check=False, capture_output=True, timeout=10)
        return out if Path(out).exists() else ""

    @staticmethod
    def _dur(p):
        try:
            r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",p], capture_output=True, text=True, timeout=10)
            return float(r.stdout.strip()) if r.returncode == 0 else 60
        except: return 60
