"""Excel export endpoints."""
from __future__ import annotations

import re
from datetime import datetime

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.core.errors import ValidationError
from app.export.excel import build_workbook
from app.schemas.api import ExportRequest
from app.services.erpnext.context import get_site_context
from app.storage.db import get_db

router = APIRouter(prefix="/export", tags=["export"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _filename(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:40] or "export"
    return f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"


def _xlsx_response(data: bytes, title: str) -> Response:
    return Response(content=data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{_filename(title)}"'})


@router.get("/dataset/{dataset_id}")
async def export_dataset(dataset_id: str) -> Response:
    ds = await run_in_threadpool(get_db().get_dataset, dataset_id)
    data = await run_in_threadpool(build_workbook, [ds], get_site_context().currency)
    return _xlsx_response(data, ds["title"])


@router.get("/message/{message_id}")
async def export_message(message_id: str) -> Response:
    db = get_db()
    datasets = await run_in_threadpool(db.get_datasets_for_message, message_id)
    if not datasets:
        raise ValidationError("This message has no exportable data.")
    data = await run_in_threadpool(build_workbook, datasets, get_site_context().currency)
    title = datasets[0]["title"] if len(datasets) == 1 else "ERPNext_Export"
    return _xlsx_response(data, title)


@router.post("")
async def export_adhoc(body: ExportRequest) -> Response:
    if not body.rows:
        raise ValidationError("rows must not be empty")
    ds = {"title": body.title, "columns": body.columns or list(body.rows[0].keys()), "rows": body.rows, "summary": body.summary}
    data = await run_in_threadpool(build_workbook, [ds], get_site_context().currency)
    return _xlsx_response(data, body.title)
