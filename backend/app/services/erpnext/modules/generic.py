"""Generic read-only access for ERPNext doctypes not covered by a dedicated module.

Lets the assistant answer questions about any module (HR, Projects, CRM, ...)
while keeping sensitive doctypes off limits.
"""
from __future__ import annotations

import re
from typing import Any

from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, int_param, round_rows, str_param

BLOCKED_DOCTYPES = {
    "User", "API Key", "OAuth Client", "OAuth Bearer Token", "Password Reset", "Email Account", "Integration Request",
    "Access Log", "Activity Log", "Error Log", "System Settings", "Webhook", "Connected App", "Token Cache", "LDAP Settings",
    "Social Login Key", "Session Default Settings", "Email Domain", "Push Notification Settings",
}
SAFE_FIELD = re.compile(r"^[A-Za-z0-9_`. ()*,'+\-/<>=]+$")
LAYOUT_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Image", "Fold", "Heading", "Barcode", "Geolocation", "Table", "Table MultiSelect"}


def _check_doctype(doctype: str) -> None:
    if doctype in BLOCKED_DOCTYPES or doctype.endswith("Settings"):
        raise ValidationError(f"Access to doctype '{doctype}' is not allowed.")


async def query_doctype(
    client: ERPNextClient,
    doctype: str,
    fields: list[str] | None = None,
    filters: list[list[Any]] | None = None,
    group_by: str | None = None,
    order_by: str | None = None,
    limit: int = 50,
) -> ToolResult:
    _check_doctype(doctype)
    fields = fields or ["name"]
    for f in fields:
        if not SAFE_FIELD.match(f):
            raise ValidationError(f"Invalid field expression: {f}")
    for flt in filters or []:
        if not isinstance(flt, list) or len(flt) not in (3, 4):
            raise ValidationError("Each filter must be [field, operator, value] or [doctype, field, operator, value].")
    rows = await client.get_list(doctype, fields, filters, group_by=group_by, order_by=order_by, limit=clamp_limit(limit, 50, 500))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "doctype": doctype}, title=f"{doctype} query")


async def get_doctype_fields(client: ERPNextClient, doctype: str) -> ToolResult:
    _check_doctype(doctype)
    meta = await client.get_doctype_meta(doctype)
    rows = []
    for f in meta.get("fields", []):
        if f.get("fieldtype") in LAYOUT_TYPES and f.get("fieldtype") not in ("Table",):
            continue
        rows.append({"fieldname": f.get("fieldname"), "label": f.get("label"), "fieldtype": f.get("fieldtype"), "options": (f.get("options") or "")[:60] if f.get("fieldtype") in ("Link", "Select", "Table") else None})
    rows.insert(0, {"fieldname": "name", "label": "ID", "fieldtype": "Data", "options": None})
    summary = {"doctype": doctype, "is_submittable": bool(meta.get("is_submittable")), "field_count": len(rows), "child_tables": [f.get("options") for f in meta.get("fields", []) if f.get("fieldtype") == "Table"]}
    return ToolResult(rows=rows, summary=summary, title=f"{doctype} fields")


async def run_erpnext_report(client: ERPNextClient, report_name: str, filters: dict[str, Any] | None = None, limit: int = 100) -> ToolResult:
    report = await client.run_report(report_name, filters or {})
    cols = report["columns"]
    labels: dict[str, str] = {}
    for c in cols:
        if isinstance(c, dict):
            labels[c.get("fieldname") or c.get("label")] = c.get("label") or c.get("fieldname")
        elif isinstance(c, str):
            label = c.split(":")[0]
            labels[label] = label
    rows: list[dict[str, Any]] = []
    for r in report["result"][: clamp_limit(limit, 100, 1000)]:
        if isinstance(r, dict):
            rows.append({labels.get(k, k): v for k, v in r.items() if k in labels or not labels})
        elif isinstance(r, list):
            keys = list(labels.keys())
            rows.append({keys[i] if i < len(keys) else f"col{i}": v for i, v in enumerate(r)})
    return ToolResult(rows=round_rows(rows), summary={"report": report_name, "rows": len(report["result"])}, title=report_name, truncated=len(report["result"]) > len(rows))


TOOLS: list[Tool] = [
    Tool(
        name="query_doctype",
        description=(
            "Read-only query on ANY ERPNext doctype (e.g. Employee, Project, Task, Lead, Opportunity, Asset, Material Request, "
            "Sales Order, Item Price). Supports aggregate fields like 'sum(grand_total) as total' with group_by, and filters "
            "[[field, operator, value]] with operators =, !=, >, <, >=, <=, like, in, between. Call get_doctype_fields first if unsure of field names."
        ),
        parameters={
            "type": "object",
            "properties": {
                "doctype": str_param("ERPNext DocType name, e.g. 'Material Request'."),
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Field names or aggregates. Default ['name']."},
                "filters": {"type": "array", "items": {"type": "array", "items": {}}, "description": "List of [field, operator, value] filters."},
                "group_by": str_param("Group by field."),
                "order_by": str_param("e.g. 'modified desc'."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["doctype"],
        },
        handler=query_doctype,
    ),
    Tool(
        name="get_doctype_fields",
        description="Discover the fields (name, label, type) of an ERPNext doctype before querying it.",
        parameters={"type": "object", "properties": {"doctype": str_param("DocType name.")}, "required": ["doctype"]},
        handler=get_doctype_fields,
    ),
    Tool(
        name="run_erpnext_report",
        description="Run a standard ERPNext query report by name with filters (e.g. 'Gross Profit', 'Sales Analytics', 'Stock Ledger', 'Accounts Receivable Summary', 'Item-wise Sales Register'). Filters usually need company/from_date/to_date.",
        parameters={
            "type": "object",
            "properties": {
                "report_name": str_param("Exact ERPNext report name."),
                "filters": {"type": "object", "description": "Report filters as key/value pairs.", "additionalProperties": True},
                "limit": int_param("Max rows.", 100),
            },
            "required": ["report_name"],
        },
        handler=run_erpnext_report,
    ),
]
