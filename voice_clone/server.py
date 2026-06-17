from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import subprocess, os

app = FastAPI()

class SynthesizeRequest(BaseModel):
    text: str
    language: str = "en"
    output_name: str = "output.mp3"

@app.post("/synthesize_kokoro")
def synthesize_kokoro(req: SynthesizeRequest):
    """Use gTTS (Google TTS) for reliable offline synthesis."""
    import tempfile
    try:
        from gtts import gTTS
        output_dir = os.getenv("VOICE_OUTPUT_DIR", "/app/data/outputs")
        output_path = f"{output_dir}/{req.output_name}"
        tts = gTTS(text=req.text[:5000], lang="en", slow=False)
        tts.save(output_path)
        return {"audio_path": output_path}
    except Exception as e:
        return {"error": str(e), "audio_path": ""}
