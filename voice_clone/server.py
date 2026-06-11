import os
import logging
import threading
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
import torch
from TTS.api import TTS
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import XttsArgs, XttsAudioConfig

app = FastAPI(title="Voice Clone Service", version="1.0.0")
logger = logging.getLogger(__name__)
_tts_lock = threading.Lock()
_tts_ready = threading.Event()
_tts_error: Exception | None = None
_tts_engine: TTS | None = None

os.environ.setdefault("COQUI_TOS_AGREED", "1")
MODEL_NAME = os.getenv("COQUI_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "vi-VN-HoaiMyNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+0%")
OUTPUT_DIR = Path(os.getenv("VOICE_OUTPUT_DIR", "/app/data/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
VOICE_SAMPLE_DIR = Path(os.getenv("VOICE_SAMPLE_DIR", "/app/data/voices"))


def _load_tts() -> TTS:
    use_gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "") != ""
    if hasattr(torch.serialization, "add_safe_globals"):
        torch.serialization.add_safe_globals([BaseDatasetConfig, XttsConfig, XttsArgs, XttsAudioConfig])
    return TTS(model_name=MODEL_NAME, progress_bar=False, gpu=use_gpu)


@lru_cache(maxsize=1)
def get_tts_engine() -> TTS:
    global _tts_engine, _tts_error

    if _tts_engine is not None:
        return _tts_engine

    with _tts_lock:
        if _tts_engine is not None:
            return _tts_engine
        try:
            _tts_engine = _load_tts()
            _tts_ready.set()
            logger.info("XTTS model loaded successfully: %s", MODEL_NAME)
            return _tts_engine
        except Exception as exc:
            _tts_error = exc
            _tts_ready.set()
            raise


@app.on_event("startup")
def warmup_tts() -> None:
    def _load_in_background() -> None:
        try:
            get_tts_engine()
        except Exception:
            logger.exception("Failed to load XTTS model: %s", MODEL_NAME)

    threading.Thread(target=_load_in_background, daemon=True).start()


class SynthesizePayload(BaseModel):
    text: str
    language: str = "vi"
    speaker_wav: str
    output_name: str


@app.get("/health")
def health() -> dict:
    if _tts_engine is not None:
        return {"status": "ok", "ready": True, "model": MODEL_NAME}
    if _tts_error is not None:
        return {"status": "failed", "ready": False, "model": MODEL_NAME, "error": str(_tts_error)}
    if _tts_ready.is_set():
        return {"status": "ok", "ready": True, "model": MODEL_NAME}
    return {"status": "loading", "ready": False, "model": MODEL_NAME}


@app.post("/synthesize")
def synthesize(payload: SynthesizePayload) -> dict:
    try:
        tts_engine = get_tts_engine()
    except Exception as exc:
        logger.exception("voice model unavailable during synthesize")
        raise HTTPException(status_code=503, detail=f"voice model unavailable: {exc}") from exc

    output_path = OUTPUT_DIR / payload.output_name

    try:
        tts_engine.tts_to_file(
            text=payload.text,
            speaker_wav=payload.speaker_wav,
            language=payload.language,
            file_path=str(output_path),
        )
    except AssertionError as exc:
        if "Language" not in str(exc) and "supported" not in str(exc):
            raise

        logger.warning(
            "XTTS does not support language %s, falling back to Edge TTS voice %s",
            payload.language,
            EDGE_TTS_VOICE,
        )

        try:
            import asyncio
            import edge_tts

            async def _run() -> None:
                communicate = edge_tts.Communicate(
                    text=payload.text,
                    voice=EDGE_TTS_VOICE,
                    rate=EDGE_TTS_RATE,
                )
                await communicate.save(str(output_path))

            asyncio.run(_run())
        except Exception as fallback_exc:
            raise HTTPException(
                status_code=500,
                detail=f"XTTS failed and Edge TTS fallback failed: {fallback_exc}",
            ) from fallback_exc

    return {"audio_path": str(output_path)}
