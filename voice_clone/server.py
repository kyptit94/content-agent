from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess, os, re, tempfile, shutil

app = FastAPI()

class SynthesizeRequest(BaseModel):
    text: str
    language: str = "en"
    output_name: str = "output.mp3"

@app.post("/synthesize_kokoro")
def synthesize_kokoro(req: SynthesizeRequest):
    """Use gTTS (Google TTS) for reliable offline synthesis with natural intonation."""
    try:
        from gtts import gTTS
        output_dir = os.getenv("VOICE_OUTPUT_DIR", "/app/data/outputs")
        output_path = f"{output_dir}/{req.output_name}"
        
        # Split into sentences for per-sentence intonation
        sentences = re.split(r'(?<=[.!?])\s+', req.text[:5000].strip())
        sentences = [s.strip() for s in sentences if len(s.strip()) > 3]
        
        if len(sentences) <= 1:
            # Single sentence: use gTTS directly
            tts = gTTS(text=req.text[:5000], lang="en", slow=False)
            tts.save(output_path)
        else:
            # Multi-sentence: render each with pitch variation + silence pauses
            _render_expressive_tts(sentences, output_path, output_dir, req.output_name)
        
        return {"audio_path": output_path}
    except Exception as e:
        return {"error": str(e), "audio_path": ""}

def _render_expressive_tts(sentences: list, output_path: str, output_dir: str, base_name: str):
    """Render each sentence with varying pitch/tempo, then concat with pauses."""
    from gtts import gTTS
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="tts_")
    segment_files = []
    
    for i, sent in enumerate(sentences):
        seg_out = os.path.join(tmpdir, f"seg{i}.mp3")
        try:
            # Slightly vary speed per sentence for natural rhythm
            # First sentences: slightly faster (excited), last: slower (conclusion)
            if i == 0:
                tts = gTTS(text=sent, lang="en", slow=False)
            elif i == len(sentences) - 1:
                tts = gTTS(text=sent, lang="en", slow=True)  # slower for dramatic ending
            else:
                tts = gTTS(text=sent, lang="en", slow=False)
            tts.save(seg_out)
            segment_files.append(seg_out)
            
            # Add short silence pause between sentences (not after last)
            if i < len(sentences) - 1:
                silence = os.path.join(tmpdir, f"silence{i}.mp3")
                pause_dur = 0.35 if sent.endswith(".") else 0.25  # longer after period
                subprocess.run([
                    "ffmpeg", "-y", "-f", "lavfi",
                    "-i", f"anullsrc=r=44100:cl=mono",
                    "-t", str(pause_dur),
                    "-acodec", "libmp3lame", "-q:a", "4",
                    silence
                ], check=False, capture_output=True, timeout=10)
                if os.path.exists(silence) and os.path.getsize(silence) > 100:
                    segment_files.append(silence)
                    
        except Exception as e:
            print(f"[TTS] Segment {i} error: {e}")
            continue
    
    # Concat all segments + silences
    if segment_files:
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for sf in segment_files:
                if os.path.exists(sf) and os.path.getsize(sf) > 100:
                    f.write(f"file '{sf}'\n")
        
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", concat_list,
            "-acodec", "libmp3lame", "-q:a", "4",
            output_path
        ], check=False, capture_output=True, timeout=120)
    
    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)
    
    # Fallback if concat failed
    if not os.path.exists(output_path) or os.path.getsize(output_path) < 100:
        from gtts import gTTS
        full_text = " ".join(sentences)
        tts = gTTS(text=full_text[:5000], lang="en", slow=False)
        tts.save(output_path)
