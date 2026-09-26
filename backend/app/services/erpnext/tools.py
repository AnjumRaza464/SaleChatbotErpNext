"""Tool abstraction shared by all ERPNext modules.

A module is any file in ``app/services/erpnext/modules`` that defines
``TOOLS: list[Tool]``. The registry converts them to OpenAI function schemas
and dispatches calls.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.services.erpnext.client import ERPNextClient


@dataclass
class ToolResult:
    """Structured result returned by every tool.

    ``rows``/``columns`` are tabular data that the UI can export to Excel.
    ``summary`` holds scalar KPIs. ``note`` explains data sources/caveats to
    the model so it can describe them faithfully.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    note: str | None = None
    title: str | None = None
    truncated: bool = False

    def to_model_payload(self, max_rows: int) -> dict[str, Any]:
        rows = self.rows[:max_rows]
        payload: dict[str, Any] = {"row_count": len(self.rows), "rows": rows}
        if self.columns:
            payload["columns"] = self.columns
        if self.summary:
            payload["summary"] = self.summary
        if self.note:
            payload["note"] = self.note
        if len(self.rows) > max_rows or self.truncated:
            payload["truncated"] = True
            payload["note"] = (payload.get("note") or "") + (
                f" Only the first {len(rows)} of {len(self.rows)} rows are shown to you; "
                "the full data set is available to the user via Excel export."
            )
        return payload


Handler = Callable[..., Awaitable[ToolResult]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    module: str = ""

    def openai_schema(self) -> dict[str, Any]:
        params = dict(self.parameters)
        params.setdefault("type", "object")
        params.setdefault("properties", {})
        params.setdefault("additionalProperties", False)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": params},
        }

    async def run(self, client: ERPNextClient, **kwargs: Any) -> ToolResult:
        sig = inspect.signature(self.handler)
        accepted = {k: v for k, v in kwargs.items() if k in sig.parameters and v is not None}
        return await self.handler(client, **accepted)


# --------------------------------------------------------------------------
# Helpers shared by modules
# --------------------------------------------------------------------------

def date_param(desc: str) -> dict[str, Any]:
    return {"type": "string", "description": f"{desc} (YYYY-MM-DD)"}


def int_param(desc: str, default: int | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"type": "integer", "description": desc}
    if default is not None:
        p["description"] += f" Default {default}."
    return p


def str_param(desc: str, enum: list[str] | None = None) -> dict[str, Any]:
    p: dict[str, Any] = {"type": "string", "description": desc}
    if enum:
        p["enum"] = enum
    return p


def bool_param(desc: str) -> dict[str, Any]:
    return {"type": "boolean", "description": desc}


def round_rows(rows: list[dict[str, Any]], digits: int = 2) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        out.append({k: (round(v, digits) if isinstance(v, float) else v) for k, v in r.items()})
    return out


def like(value: str) -> str:
    v = value.strip()
    return v if "%" in v else f"%{v}%"


def clamp_limit(limit: int | None, default: int = 50, maximum: int = 500) -> int:
    if not limit or limit < 1:
        return default
    return min(int(limit), maximum)
