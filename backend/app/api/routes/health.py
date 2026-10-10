from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.auth.deps import current_user
from app.core.config import get_settings
from app.schemas.api import HealthOut
from app.services.erpnext.client import get_client
from app.services.erpnext.context import get_site_context, load_site_context
from app.services.erpnext.registry import get_registry

router = APIRouter(tags=["health"])


async def _optional_user(request: Request) -> dict[str, Any] | None:
    try:
        return await current_user(request)
    except Exception:  # noqa: BLE001 - anonymous callers get a reduced payload
        return None


@router.get("/health", response_model=HealthOut)
async def health(request: Request) -> HealthOut:
    settings = get_settings()
    erp: dict = {"connected": False}
    try:
        info = await get_client().ping()
        ctx = get_site_context()
        if not ctx.loaded:
            ctx = await load_site_context()
        erp = {
            "connected": True,
            "user": info.get("user"),
            "versions": info.get("versions"),
            "company": ctx.default_company,
            "currency": ctx.currency,
            "time_zone": ctx.time_zone,
        }
    except Exception as exc:  # noqa: BLE001
        erp = {"connected": False, "error": str(exc)}
    reg = get_registry()
    user = await _optional_user(request)
    # Tool/module inventory is only shown to administrators.
    show_detail = bool(user and user.get("is_admin"))
    if not show_detail:
        erp = {k: v for k, v in erp.items() if k in ("connected", "company", "currency", "time_zone", "error")}
    return HealthOut(
        status="ok" if erp.get("connected") else "degraded",
        erpnext=erp,
        model=settings.openai_model if show_detail else "",
        tools=len(reg.tools) if show_detail else 0,
        modules=reg.modules() if show_detail else {},
    )
