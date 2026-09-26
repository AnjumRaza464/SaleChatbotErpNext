from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.api import HealthOut
from app.services.erpnext.client import get_client
from app.services.erpnext.context import get_site_context, load_site_context
from app.services.erpnext.registry import get_registry

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
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
    return HealthOut(status="ok" if erp.get("connected") else "degraded", erpnext=erp, model=settings.openai_model, tools=len(reg.tools), modules=reg.modules())
