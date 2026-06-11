import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from TTS.api import TTS

app = FastAPI(title="Voice Clone Service", version="1.0.0")

os.environ.setdefault("COQUI_TOS_AGREED", "1")
MODEL_NAME = os.getenv("COQUI_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
OUTPUT_DIR = Path(os.getenv("VOICE_OUTPUT_DIR", "/app/data/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _load_tts() -> TTS:
    use_gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "") != ""
    return TTS(model_name=MODEL_NAME, progress_bar=False, gpu=use_gpu)


@lru_cache(maxsize=1)
def get_tts_engine() -> TTS:
    return _load_tts()


class SynthesizePayload(BaseModel):
    text: str
    language: str = "vi"
    speaker_wav: str
    output_name: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME}


@app.post("/synthesize")
def synthesize(payload: SynthesizePayload) -> dict:
    try:
        tts_engine = get_tts_engine()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"voice model unavailable: {exc}") from exc

    output_path = OUTPUT_DIR / payload.output_name
    tts_engine.tts_to_file(
        text=payload.text,
        speaker_wav=payload.speaker_wav,
        language=payload.language,
        file_path=str(output_path),
    )
    return {"audio_path": str(output_path)}
