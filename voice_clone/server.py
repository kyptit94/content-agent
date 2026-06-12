import asyncio
import os
import re
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
import torch
from TTS.api import TTS
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import XttsArgs, XttsAudioConfig

# Kokoro TTS imports
from kokoro import KPipeline
from misaki import en
import soundfile as sf
import numpy as np

app = FastAPI(title="Voice Clone Service", version="1.0.0")
logger = logging.getLogger(__name__)
_tts_lock = threading.Lock()
_tts_ready = threading.Event()
_tts_error: Exception | None = None
_tts_engine: TTS | None = None
_kokoro_pipeline: KPipeline | None = None

os.environ.setdefault("COQUI_TOS_AGREED", "1")
MODEL_NAME = os.getenv("COQUI_MODEL_NAME", "tts_models/multilingual/multi-dataset/xtts_v2")
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "vi-VN-HoaiMyNeural")
EDGE_TTS_RATE = os.getenv("EDGE_TTS_RATE", "+0%")
KOKORO_VOICE_EN = os.getenv("KOKORO_VOICE_EN", "af_heart")  # kokoro EN voices
OUTPUT_DIR = Path(os.getenv("VOICE_OUTPUT_DIR", "/app/data/outputs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
VOICE_SAMPLE_DIR = Path(os.getenv("VOICE_SAMPLE_DIR", "/app/data/voices"))

# Regex for text preprocessing
_RE_NEWLINE = re.compile(r"\n{2,}")
_RE_ELLIPSIS = re.compile(r"\.{3,}")
_RE_CONSECUTIVE_DOT = re.compile(r"\.{2,}")

# Default Vietnamese speaker sample for XTTS if none provided
_DEFAULT_VI_SPEAKER = VOICE_SAMPLE_DIR / "default_vi_speaker.wav"


def _load_tts() -> TTS:
    use_gpu = os.environ.get("CUDA_VISIBLE_DEVICES", "") != ""
    if hasattr(torch.serialization, "add_safe_globals"):
        torch.serialization.add_safe_globals([BaseDatasetConfig, XttsConfig, XttsArgs, XttsAudioConfig])
    return TTS(model_name=MODEL_NAME, progress_bar=False, gpu=use_gpu)


def _get_kokoro_pipeline() -> KPipeline:
    """Lazy-load Kokoro pipeline (EN)."""
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        logger.info("Initializing Kokoro EN pipeline...")
        try:
            # Use the Kokoro EN fallback tokenizer (misaki en)
            _kokoro_pipeline = KPipeline(lang_code='a', model='kokoro-v0_19')
        except Exception as exc:
            logger.error("Failed to load Kokoro: %s", exc)
            raise
    return _kokoro_pipeline


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


def _preprocess_vi_text(text: str) -> str:
    """Preprocess Vietnamese text for better XTTS pronunciation."""
    if not text:
        return text

    # Normalize whitespace
    text = text.strip()
    text = _RE_NEWLINE.sub("\n", text)

    # Ensure sentence-ending punctuation
    lines = text.split("\n")
    processed_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line and line[-1] not in ".!?":
            line += "."
        processed_lines.append(line)
    text = "\n".join(processed_lines)

    # Clean up punctuation spacing for Vietnamese
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)   # remove space before punct
    text = re.sub(r"([,.;:!?])(?!\s|$)", r"\1 ", text)  # ensure space after
    # Replace 3+ dots with three dots
    text = _RE_ELLIPSIS.sub("... ", text)
    text = _RE_CONSECUTIVE_DOT.sub(".", text)
    # Collapse spaces
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def _resolve_speaker_wav(speaker_wav: str) -> str:
    """Resolve speaker_wav path; use default if not found."""
    path = Path(speaker_wav)
    if path.exists() and path.is_file():
        return speaker_wav
    # Try under VOICE_SAMPLE_DIR
    alt_path = VOICE_SAMPLE_DIR / path.name
    if alt_path.exists():
        return str(alt_path)
    # Fallback to default
    if _DEFAULT_VI_SPEAKER.exists():
        logger.warning(
            "Speaker wav %s not found, using default: %s",
            speaker_wav,
            _DEFAULT_VI_SPEAKER,
        )
        return str(_DEFAULT_VI_SPEAKER)
    # If no default exists, create a basic silent one or just return empty
    logger.warning("Speaker wav %s not found and no default available", speaker_wav)
    return speaker_wav


@app.post("/synthesize")
def synthesize(payload: SynthesizePayload) -> dict:
    try:
        tts_engine = get_tts_engine()
    except Exception as exc:
        logger.exception("voice model unavailable during synthesize")
        raise HTTPException(status_code=503, detail=f"voice model unavailable: {exc}") from exc

    # Preprocess text for natural pronunciation
    processed_text = _preprocess_vi_text(payload.text)
    # Resolve speaker wav
    speaker_wav = _resolve_speaker_wav(payload.speaker_wav)

    output_path = OUTPUT_DIR / payload.output_name

    # --- Try XTTS with Vietnamese ---
    # XTTS supports 'vi' but sometimes needs exact language code
    # Try "vi" first, fallback to multilingual empty string
    tried_languages = [payload.language]
    if payload.language.lower() == "vi":
        tried_languages.append("")
        tried_languages.append("en")

    last_xtts_error: Optional[Exception] = None
    for lang in tried_languages:
        try:
            tts_engine.tts_to_file(
                text=processed_text,
                speaker_wav=speaker_wav,
                language=lang,
                file_path=str(output_path),
            )
            logger.info(
                "XTTS synthesis succeeded: lang=%s, output=%s",
                lang or "<empty>",
                output_path,
            )
            return {"audio_path": str(output_path)}
        except Exception as exc:
            last_xtts_error = exc
            logger.warning("XTTS failed with lang='%s': %s", lang, exc)
            # Don't abort on Language assertion, try next
            if "Language" not in str(exc) and "supported" not in str(exc):
                break  # Non-language error, stop trying

    # --- Fallback to Edge TTS ---
    logger.warning(
        "XTTS failed for all language attempts, falling back to Edge TTS voice %s",
        EDGE_TTS_VOICE,
    )
    try:
        import asyncio
        import edge_tts

        async def _run() -> None:
            communicate = edge_tts.Communicate(
                text=processed_text,
                voice=EDGE_TTS_VOICE,
                rate=EDGE_TTS_RATE,
            )
            await communicate.save(str(output_path))

        asyncio.run(_run())
        logger.info("Edge TTS fallback succeeded: %s", output_path)
        return {"audio_path": str(output_path)}
    except Exception as fallback_exc:
        raise HTTPException(
            status_code=500,
            detail=f"XTTS failed and Edge TTS fallback failed: {fallback_exc}",
        ) from fallback_exc


@app.post("/synthesize_kokoro")
def synthesize_kokoro(payload: SynthesizePayload) -> dict:
    """Synthesize English text using Kokoro (local, emotional TTS)."""
    pipeline = _get_kokoro_pipeline()
    voice = payload.speaker_wav or KOKORO_VOICE_EN
    text = payload.text

    output_path = OUTPUT_DIR / payload.output_name
    output_path_wav = output_path.with_suffix(".wav")
    output_path_mp3 = output_path if output_path.suffix == ".mp3" else output_path.with_suffix(".mp3")

    try:
        # Generate audio via Kokoro
        all_audio = []
        generator = pipeline(text, voice=voice, speed=1.0)
        for _gs, _ps, audio in generator:
            if audio is not None and len(audio) > 0:
                all_audio.append(audio)

        if not all_audio:
            raise RuntimeError("Kokoro generated no audio")

        # Concatenate all audio chunks
        combined = np.concatenate(all_audio)

        # Save as WAV first
        sf.write(str(output_path_wav), combined, 24000)

        # Convert to MP3 if needed via ffmpeg
        if output_path_mp3.suffix == ".mp3":
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(output_path_wav),
                 "-codec:a", "libmp3lame", "-qscale:a", "2",
                 str(output_path_mp3)],
                check=True, capture_output=True, text=True, timeout=30,
            )
            output_path_wav.unlink(missing_ok=True)
            return {"audio_path": str(output_path_mp3)}

        return {"audio_path": str(output_path_wav)}
    except Exception as exc:
        logger.exception("Kokoro synthesis failed")
        raise HTTPException(status_code=500, detail=f"Kokoro TTS failed: {exc}")
