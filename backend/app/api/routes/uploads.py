from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.errors import ValidationError
from app.files.parser import detect_kind, parse_file, save_bytes
from app.schemas.api import UploadOut
from app.storage.db import get_db, new_id

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadOut, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    filename = Path(file.filename or "upload").name
    kind = detect_kind(filename)
    data = await file.read()
    if not data:
        raise ValidationError("The uploaded file is empty.")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ValidationError(f"File exceeds the {settings.max_upload_mb} MB limit.")
    uid = new_id()
    dest = settings.upload_dir / f"{uid}{Path(filename).suffix.lower()}"

    def _process() -> dict:
        save_bytes(data, dest)
        try:
            parsed = parse_file(dest, filename)
        except ValidationError:
            dest.unlink(missing_ok=True)
            raise
        except Exception as exc:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            raise ValidationError(f"Could not read '{filename}': {exc}") from exc
        row = get_db().save_upload(filename, str(dest), parsed.kind, len(data), parsed.preview, parsed.context)
        # keep the id stable with the file name on disk
        return row

    return await run_in_threadpool(_process)
