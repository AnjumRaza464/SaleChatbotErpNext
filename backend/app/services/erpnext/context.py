"""Cached facts about the connected ERPNext site (company, currency, timezone).

Loaded once at startup and injected into the AI system prompt so the model
never has to guess company names or currency.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.erpnext.client import get_client

log = logging.getLogger(__name__)


@dataclass
class SiteContext:
    companies: list[dict] = field(default_factory=list)
    default_company: str | None = None
    currency: str = ""
    time_zone: str = "UTC"
    erpnext_version: str = ""
    branches: list[str] = field(default_factory=list)
    cost_centers: list[str] = field(default_factory=list)
    warehouses: list[str] = field(default_factory=list)
    pos_profiles: list[str] = field(default_factory=list)
    department_count: int = 0
    loaded: bool = False
    error: str | None = None

    def now(self) -> datetime:
        try:
            return datetime.now(ZoneInfo(self.time_zone))
        except Exception:
            return datetime.now()

    def today(self) -> str:
        return self.now().strftime("%Y-%m-%d")


_ctx = SiteContext()


async def load_site_context(force: bool = False) -> SiteContext:
    global _ctx
    if _ctx.loaded and not force:
        return _ctx
    client = get_client()
    ctx = SiteContext()
    try:
        companies = await client.get_list("Company", ["name", "default_currency", "country"], limit=50)
        ctx.companies = companies
        if companies:
            ctx.default_company = companies[0]["name"]
            ctx.currency = companies[0].get("default_currency") or ""
        sys_settings = await client.get_value("System Settings", ["time_zone"])
        if isinstance(sys_settings, dict) and sys_settings.get("time_zone"):
            ctx.time_zone = sys_settings["time_zone"]
        try:
            versions = await client.call_method("frappe.utils.change_log.get_versions")
            ctx.erpnext_version = (versions or {}).get("erpnext", {}).get("version", "")
        except Exception:
            pass
        ctx.branches = [r["name"] for r in await client.get_list("Branch", ["name"], limit=200)]
        ctx.cost_centers = [
            r["name"] for r in await client.get_list("Cost Center", ["name"], [["is_group", "=", 0]], limit=200)
        ]
        ctx.warehouses = [
            r["name"] for r in await client.get_list("Warehouse", ["name"], [["is_group", "=", 0]], limit=200)
        ]
        ctx.pos_profiles = [r["name"] for r in await client.get_list("POS Profile", ["name"], limit=200)]
        ctx.department_count = await client.get_count("Department")
        ctx.loaded = True
    except Exception as exc:  # keep the app usable even if ERPNext is down
        log.warning("Could not load ERPNext site context: %s", exc)
        ctx.error = str(exc)
    _ctx = ctx
    return _ctx


def get_site_context() -> SiteContext:
    return _ctx
