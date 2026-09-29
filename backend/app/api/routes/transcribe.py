"""Voice input: converts a recorded audio clip to text with OpenAI speech-to-text.

The text is returned to the composer so the user can review it before sending;
it never goes to the agent directly.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from openai import APIError

from app.agent.agent import get_openai
from app.core.config import get_settings
from app.core.errors import AppError, ValidationError
from app.schemas.api import TranscriptionOut
from app.services.erpnext.context import get_site_context

router = APIRouter(prefix="/transcribe", tags=["transcribe"])
log = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # OpenAI's per-request limit
AUDIO_EXTENSIONS = {".webm", ".ogg", ".mp4", ".m4a", ".mp3", ".mpeg", ".mpga", ".wav", ".flac"}


def _vocabulary_prompt() -> str:
    """Biases recognition towards ERPNext and site-specific terms.

    The Urdu example matters: without it, spoken Urdu is often transcribed in
    Hindi (Devanagari) script because the two sound almost the same.
    """
    ctx = get_site_context()
    terms = ["ERPNext", "sales invoice", "POS", "stock", "warehouse", "customer", "supplier", "purchase order"]
    if ctx.default_company:
        terms.append(ctx.default_company)
    terms += ctx.warehouses[:5]
    return (
        "A business question about ERPNext data: " + ", ".join(terms) + ". "
        "Urdu questions are written in Urdu script, e.g. پچھلے مہینے کی کل سیل کتنی تھی؟"
    )


@router.post("", response_model=TranscriptionOut)
async def transcribe(file: UploadFile = File(...)) -> TranscriptionOut:
    filename = Path(file.filename or "voice.webm").name
    if Path(filename).suffix.lower() not in AUDIO_EXTENSIONS:
        raise ValidationError("Unsupported audio format.")
    data = await file.read()
    if not data:
        raise ValidationError("No audio was recorded.")
    if len(data) > MAX_AUDIO_BYTES:
        raise ValidationError("Recording is too long. Please keep it under a few minutes.")

    try:
        result = await get_openai().audio.transcriptions.create(
            model=get_settings().openai_transcribe_model,
            file=(filename, data, file.content_type or "application/octet-stream"),
            prompt=_vocabulary_prompt(),
        )
    except APIError as exc:
        log.exception("Transcription failed")
        raise AppError(f"Speech-to-text error: {getattr(exc, 'message', str(exc))}", 502) from exc

    text = (result.text or "").strip()
    if not text:
        raise ValidationError("Could not hear any speech. Please try again.")
    return TranscriptionOut(text=text)
