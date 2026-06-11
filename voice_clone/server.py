import os
import logging
from functools import lru_cache
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from TTS.api import TTS

app = FastAPI(title="Voice Clone Service", version="1.0.0")
logger = logging.getLogger(__name__)

os.environ.setdefault("COQUI_TOS_AGREED", "1")
MODEL_NAME = os.getenv("COQUI_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
OUTPUT_DIR = Path(os.getenv("VOICE_OUTPUT_DIR", "/app/data/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
VOICE_SAMPLE_DIR = Path(os.getenv("VOICE_SAMPLE_DIR", "/app/data/voices"))


def _load_tts() -> TTS:
    use_gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "") != ""
    return TTS(model_name=MODEL_NAME, progress_bar=False, gpu=use_gpu)


@lru_cache(maxsize=1)
def get_tts_engine() -> TTS:
    return _load_tts()


@app.on_event("startup")
def warmup_tts() -> None:
    try:
        tts_engine = get_tts_engine()
        sample_voice = _find_sample_voice()
        if sample_voice is None:
            logger.warning("No voice sample found in %s; model loaded but not warmed up", VOICE_SAMPLE_DIR)
            return

        with NamedTemporaryFile(suffix=".wav", delete=True, dir=str(OUTPUT_DIR)) as temp_file:
            tts_engine.tts_to_file(
                text="xin chao",
                speaker_wav=str(sample_voice),
                language="vi",
                file_path=temp_file.name,
            )

        logger.info("XTTS model loaded and warmed up successfully: %s", MODEL_NAME)
    except Exception:
        logger.exception("Failed to load XTTS model: %s", MODEL_NAME)
        raise


class SynthesizePayload(BaseModel):
    text: str
    language: str = "vi"
    speaker_wav: str
    output_name: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME}


def _find_sample_voice() -> Path | None:
    if not VOICE_SAMPLE_DIR.exists():
        return None

    allowed_ext = {".wav", ".mp3", ".m4a", ".ogg", ".flac"}
    for path in sorted(VOICE_SAMPLE_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in allowed_ext:
            return path
    return None


@app.post("/synthesize")
def synthesize(payload: SynthesizePayload) -> dict:
    try:
        tts_engine = get_tts_engine()
    except Exception as exc:
        logger.exception("voice model unavailable during synthesize")
        raise HTTPException(status_code=503, detail=f"voice model unavailable: {exc}") from exc

    output_path = OUTPUT_DIR / payload.output_name
    tts_engine.tts_to_file(
        text=payload.text,
        speaker_wav=payload.speaker_wav,
        language=payload.language,
        file_path=str(output_path),
    )
    return {"audio_path": str(output_path)}
