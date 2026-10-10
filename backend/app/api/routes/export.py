"""Excel export endpoints. Exports are limited to the signed-in user's own
conversations and to modules they still hold; HR exports are audit-logged."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from app.auth.deps import assert_module, current_user
from app.core.errors import NotFoundError, ValidationError
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


def _owned(conv: dict[str, Any] | None, user: dict[str, Any]) -> dict[str, Any]:
    if not conv or conv.get("user_id") != user["id"]:
        raise NotFoundError("Export not found")
    assert_module(user, conv.get("module"))
    return conv


@router.get("/dataset/{dataset_id}")
async def export_dataset(dataset_id: str, user: dict[str, Any] = Depends(current_user)) -> Response:
    db = get_db()
    conv = _owned(await run_in_threadpool(db.conversation_for_dataset, dataset_id), user)
    ds = await run_in_threadpool(db.get_dataset, dataset_id)
    data = await run_in_threadpool(build_workbook, [ds], get_site_context().currency)
    await run_in_threadpool(db.add_audit, user["id"], conv.get("module"), "export", f"dataset {dataset_id}: {ds['title']}")
    return _xlsx_response(data, ds["title"])


@router.get("/message/{message_id}")
async def export_message(message_id: str, user: dict[str, Any] = Depends(current_user)) -> Response:
    db = get_db()
    conv = _owned(await run_in_threadpool(db.conversation_for_message, message_id), user)
    datasets = await run_in_threadpool(db.get_datasets_for_message, message_id)
    if not datasets:
        raise ValidationError("This message has no exportable data.")
    data = await run_in_threadpool(build_workbook, datasets, get_site_context().currency)
    title = datasets[0]["title"] if len(datasets) == 1 else "ERPNext_Export"
    await run_in_threadpool(db.add_audit, user["id"], conv.get("module"), "export", f"message {message_id}: {title}")
    return _xlsx_response(data, title)


@router.post("")
async def export_adhoc(body: ExportRequest, user: dict[str, Any] = Depends(current_user)) -> Response:
    if not body.rows:
        raise ValidationError("rows must not be empty")
    ds = {"title": body.title, "columns": body.columns or list(body.rows[0].keys()), "rows": body.rows, "summary": body.summary}
    data = await run_in_threadpool(build_workbook, [ds], get_site_context().currency)
    return _xlsx_response(data, body.title)
