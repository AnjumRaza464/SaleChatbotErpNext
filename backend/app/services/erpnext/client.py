"""Thin async client for the ERPNext / Frappe REST API.

Only read operations are exposed. Credentials never leave the backend.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.core.errors import ERPNextError

log = logging.getLogger(__name__)

Filter = list[Any]


def _clean_exception(text: str) -> str:
    """Extract a human readable message from a Frappe error payload."""
    try:
        data = json.loads(text)
    except Exception:
        return text[:300]
    if isinstance(data, dict):
        for key in ("exception", "message", "_server_messages", "exc_type"):
            val = data.get(key)
            if not val:
                continue
            if key == "_server_messages":
                try:
                    msgs = json.loads(val)
                    parts = []
                    for m in msgs:
                        try:
                            parts.append(json.loads(m).get("message", m))
                        except Exception:
                            parts.append(str(m))
                    val = "; ".join(parts)
                except Exception:
                    pass
            val = re.sub(r"<[^>]+>", "", str(val))
            return val[:400]
    return text[:300]


class ERPNextClient:
    """Async HTTP client with token auth. One instance is shared per app."""

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.erpnext_url
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"token {s.erpnext_api_key}:{s.erpnext_api_secret}",
                "Accept": "application/json",
            },
            timeout=s.erpnext_timeout_seconds,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ core
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        clean: dict[str, Any] = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            clean[k] = json.dumps(v) if isinstance(v, (list, dict)) else v
        try:
            resp = await self._client.get(path, params=clean)
        except httpx.HTTPError as exc:  # network level
            raise ERPNextError(f"Could not reach ERPNext: {exc}") from exc
        if resp.status_code >= 400:
            msg = _clean_exception(resp.text)
            log.warning("ERPNext %s %s -> %s: %s", path, clean, resp.status_code, msg)
            raise ERPNextError(f"ERPNext returned {resp.status_code}: {msg}", status_code=502)
        try:
            return resp.json()
        except ValueError as exc:
            raise ERPNextError("ERPNext returned a non-JSON response") from exc

    async def call_method(self, method: str, **params: Any) -> Any:
        data = await self._get(f"/api/method/{method}", params)
        return data.get("message") if isinstance(data, dict) else data

    # --------------------------------------------------------------- queries
    async def get_list(
        self,
        doctype: str,
        fields: list[str] | None = None,
        filters: list[Filter] | dict[str, Any] | None = None,
        or_filters: list[Filter] | None = None,
        group_by: str | None = None,
        order_by: str | None = None,
        limit: int | None = 100,
        start: int = 0,
    ) -> list[dict[str, Any]]:
        """Query a doctype via ``frappe.desk.reportview.get``.

        Supports aggregates (``sum(x) as total``), ``group_by`` and child-table
        joins using the backtick ``tabChild``.field syntax, which the plain
        ``/api/resource`` endpoint cannot do reliably on every server.
        """
        params: dict[str, Any] = {
            "doctype": doctype,
            "fields": fields or ["name"],
            "filters": filters or [],
            "start": start,
            "page_length": limit if limit is not None else 0,
        }
        if or_filters:
            params["or_filters"] = or_filters
        if group_by:
            params["group_by"] = group_by
        if order_by:
            params["order_by"] = order_by
        data = await self._get("/api/method/frappe.desk.reportview.get", params)
        msg = data.get("message") if isinstance(data, dict) else data
        if not msg:
            return []
        if isinstance(msg, dict) and "keys" in msg:
            keys = msg.get("keys") or []
            return [dict(zip(keys, row)) for row in msg.get("values") or []]
        if isinstance(msg, list):
            return msg
        return []

    async def get_count(self, doctype: str, filters: list[Filter] | None = None) -> int:
        rows = await self.get_list(doctype, ["count(name) as cnt"], filters, limit=1)
        return int(rows[0].get("cnt") or 0) if rows else 0

    async def get_doc(self, doctype: str, name: str) -> dict[str, Any]:
        data = await self._get(f"/api/resource/{quote(doctype)}/{quote(name)}")
        return data.get("data", {}) if isinstance(data, dict) else {}

    async def get_value(self, doctype: str, fieldname: str | list[str], filters: Any = None) -> Any:
        params: dict[str, Any] = {"doctype": doctype, "fieldname": fieldname}
        if filters is not None:
            params["filters"] = filters
        return await self.call_method("frappe.client.get_value", **params)

    async def run_report(self, report_name: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Run a standard Frappe query report and return {columns, result}."""
        msg = await self.call_method(
            "frappe.desk.query_report.run",
            report_name=report_name,
            filters=filters or {},
            ignore_prepared_report=1,
        )
        if not isinstance(msg, dict):
            return {"columns": [], "result": []}
        if msg.get("prepared_report") and not msg.get("result"):
            raise ERPNextError(
                f"Report '{report_name}' runs as a prepared (background) report and cannot be fetched live."
            )
        return {"columns": msg.get("columns") or [], "result": msg.get("result") or []}

    async def get_doctype_meta(self, doctype: str) -> dict[str, Any]:
        data = await self._get("/api/method/frappe.desk.form.load.getdoctype", {"doctype": doctype})
        for doc in (data or {}).get("docs", []):
            if doc.get("name") == doctype:
                return doc
        raise ERPNextError(f"DocType '{doctype}' not found", status_code=404)

    async def ping(self) -> dict[str, Any]:
        user = await self.call_method("frappe.auth.get_logged_user")
        versions = await self.call_method("frappe.utils.change_log.get_versions")
        return {"user": user, "versions": {k: v.get("version") for k, v in (versions or {}).items()}}


_client: ERPNextClient | None = None


def get_client() -> ERPNextClient:
    global _client
    if _client is None:
        _client = ERPNextClient()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
