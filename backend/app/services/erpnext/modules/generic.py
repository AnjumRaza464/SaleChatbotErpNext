"""Generic read-only access to the whole ERPNext site.

The dedicated modules (sales, stock, accounts, ...) cover the common questions
with tuned queries. Everything else (HR, Payroll, Projects, CRM, Assets, Support,
Quality, Subscriptions, custom doctypes, ...) is reachable through the tools
here: discover doctypes, inspect their fields, query lists with filters and
aggregates, open a single document with its child tables, find and run reports.

Only reads are possible: the client has no write methods, and security-related
doctypes plus password fields are filtered out.
"""
from __future__ import annotations

import re
from typing import Any

from app.agent.scope import current_scope
from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, int_param, like, round_rows, str_param

# Security / infrastructure doctypes that must never be read by the assistant.
BLOCKED_DOCTYPES = {
    "User", "API Key", "OAuth Client", "OAuth Bearer Token", "OAuth Authorization Code", "Password Reset",
    "Email Account", "Email Domain", "Integration Request", "Access Log", "Activity Log", "Error Log", "Error Snapshot",
    "System Settings", "Webhook", "Webhook Request Log", "Connected App", "Token Cache", "LDAP Settings",
    "Social Login Key", "Session Default Settings", "Push Notification Settings", "User Permission", "Role Permission for Page and Report",
    "Custom DocPerm", "DocPerm", "Server Script", "Client Script", "Scheduled Job Log", "Data Import", "Data Export",
    "Personal Data Deletion Request", "Personal Data Download Request", "Google Settings", "Dropbox Settings", "S3 Backup Settings",
    "Payment Gateway Account", "Razorpay Settings", "Stripe Settings", "PayPal Settings", "Braintree Settings",
    "Telephony Settings", "Twilio Settings", "Exotel Settings", "Plaid Settings", "QuickBooks Migrator", "Tally Migration",
}
# Any doctype whose name matches this is treated as sensitive too (covers custom apps).
BLOCKED_NAME_RE = re.compile(r"(password|token|oauth|api key|secret|credential|session|ldap|login|webhook|gateway|backup)", re.IGNORECASE)
# Field types / names that are stripped from documents.
SENSITIVE_FIELDTYPES = {"Password"}
SENSITIVE_FIELD_RE = re.compile(r"(password|secret|token|api_key|private_key|credential)", re.IGNORECASE)

SAFE_FIELD = re.compile(r"^[A-Za-z0-9_`. ()*,'+\-/<>=]+$")
LAYOUT_TYPES = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Image", "Fold", "Heading", "Barcode", "Geolocation"}


def _blocked(doctype: str) -> bool:
    return doctype in BLOCKED_DOCTYPES or bool(BLOCKED_NAME_RE.search(doctype))


def _check_doctype(doctype: str) -> None:
    if _blocked(doctype):
        raise ValidationError(f"Access to doctype '{doctype}' is not allowed (security-related data).")
    scope = current_scope()
    if not scope.allows_doctype(doctype):
        raise ValidationError(
            f"Doctype '{doctype}' is outside the {scope.module} module. Tell the user this data belongs to another module they do not have access to in this tab."
        )


def _scope_filter(rows: list[dict[str, Any]], key: str = "name") -> list[dict[str, Any]]:
    scope = current_scope()
    return [r for r in rows if r.get(key) and not _blocked(r[key]) and scope.allows_doctype(r[key])]


async def _check_report(client: ERPNextClient, report_name: str) -> None:
    """A report may run only if its reference doctype is inside the scope."""
    scope = current_scope()
    if scope.doctypes is None:
        return
    rows = await client.get_list("Report", ["name", "ref_doctype"], [["name", "=", report_name]], limit=1)
    ref = rows[0].get("ref_doctype") if rows else None
    if not ref or not scope.allows_doctype(ref):
        raise ValidationError(f"Report '{report_name}' is outside the {scope.module} module.")


def _strip_sensitive(doc: dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
    pw_fields = {f.get("fieldname") for f in (meta or {}).get("fields", []) if f.get("fieldtype") in SENSITIVE_FIELDTYPES}
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k in pw_fields or SENSITIVE_FIELD_RE.search(k):
            continue
        if isinstance(v, list):
            v = [_strip_sensitive(row, None) if isinstance(row, dict) else row for row in v]
        out[k] = v
    return out


# ---------------------------------------------------------------- discovery
async def list_doctypes(client: ERPNextClient, search: str | None = None, module: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["istable", "=", 0], ["issingle", "=", 0]]
    if search:
        filters.append(["name", "like", like(search)])
    if module:
        filters.append(["module", "like", like(module)])
    rows = await client.get_list("DocType", ["name", "module", "is_submittable", "custom", "description"], filters,
                                 order_by="module asc, name asc", limit=clamp_limit(limit, 50, 300))
    rows = _scope_filter(rows)
    for r in rows:
        r["description"] = (r.get("description") or "")[:120]
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="DocTypes",
                      note="Use query_doctype / get_document on these names. Call get_doctype_fields to see their fields.")


async def list_modules(client: ERPNextClient) -> ToolResult:
    rows = await client.get_list("Module Def", ["name", "app_name"], order_by="app_name asc, name asc", limit=300)
    counts = await client.get_list("DocType", ["module", "count(name) as doctypes"], [["istable", "=", 0]], group_by="module", limit=300)
    index = {c["module"]: c["doctypes"] for c in counts}
    for r in rows:
        r["doctypes"] = index.get(r["name"], 0)
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="ERPNext modules")


async def list_reports(client: ERPNextClient, search: str | None = None, module: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["disabled", "=", 0], ["report_type", "in", ["Query Report", "Script Report", "Report Builder"]]]
    if search:
        filters.append(["name", "like", like(search)])
    if module:
        filters.append(["module", "like", like(module)])
    rows = await client.get_list("Report", ["name", "ref_doctype", "report_type", "module", "is_standard"], filters,
                                 order_by="module asc, name asc", limit=clamp_limit(limit, 50, 300))
    rows = _scope_filter(rows, key="ref_doctype")
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="Reports", note="Run one with run_erpnext_report(report_name, filters).")


async def get_doctype_fields(client: ERPNextClient, doctype: str) -> ToolResult:
    _check_doctype(doctype)
    meta = await client.get_doctype_meta(doctype)
    rows = []
    for f in meta.get("fields", []):
        if f.get("fieldtype") in LAYOUT_TYPES or f.get("fieldtype") in SENSITIVE_FIELDTYPES:
            continue
        rows.append({
            "fieldname": f.get("fieldname"),
            "label": f.get("label"),
            "fieldtype": f.get("fieldtype"),
            "options": (f.get("options") or "")[:60] if f.get("fieldtype") in ("Link", "Select", "Table", "Table MultiSelect") else None,
        })
    rows.insert(0, {"fieldname": "name", "label": "ID", "fieldtype": "Data", "options": None})
    for std in ("owner", "creation", "modified", "docstatus"):
        rows.append({"fieldname": std, "label": std, "fieldtype": "Data", "options": None})
    summary = {
        "doctype": doctype,
        "is_submittable": bool(meta.get("is_submittable")),
        "field_count": len(rows),
        "child_tables": [f.get("options") for f in meta.get("fields", []) if f.get("fieldtype") in ("Table", "Table MultiSelect")],
    }
    return ToolResult(rows=rows, summary=summary, title=f"{doctype} fields")


# ------------------------------------------------------------------ queries
async def query_doctype(
    client: ERPNextClient,
    doctype: str,
    fields: list[str] | None = None,
    filters: list[list[Any]] | None = None,
    or_filters: list[list[Any]] | None = None,
    group_by: str | None = None,
    order_by: str | None = None,
    limit: int = 50,
) -> ToolResult:
    _check_doctype(doctype)
    fields = fields or ["name"]
    for f in fields:
        if not SAFE_FIELD.match(f) or SENSITIVE_FIELD_RE.search(f):
            raise ValidationError(f"Invalid field expression: {f}")
    for flt in list(filters or []) + list(or_filters or []):
        if not isinstance(flt, list) or len(flt) not in (3, 4):
            raise ValidationError("Each filter must be [field, operator, value] or [doctype, field, operator, value].")
    rows = await client.get_list(doctype, fields, filters, or_filters=or_filters, group_by=group_by, order_by=order_by,
                                 limit=clamp_limit(limit, 50, 500))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "doctype": doctype}, title=f"{doctype} query")


async def count_records(client: ERPNextClient, doctype: str, filters: list[list[Any]] | None = None) -> ToolResult:
    _check_doctype(doctype)
    n = await client.get_count(doctype, filters)
    return ToolResult(rows=[], summary={"doctype": doctype, "count": n}, title=f"{doctype} count")


async def get_document(client: ERPNextClient, doctype: str, name: str) -> ToolResult:
    _check_doctype(doctype)
    doc = await client.get_doc(doctype, name)
    if not doc:
        raise ValidationError(f"{doctype} '{name}' not found.")
    try:
        meta = await client.get_doctype_meta(doctype)
    except Exception:  # meta is only used to hide password fields
        meta = None
    doc = _strip_sensitive(doc, meta)
    # Split scalar fields from child tables so both are easy to read / export.
    scalars = {k: v for k, v in doc.items() if not isinstance(v, (list, dict)) and v not in (None, "", 0) or k in ("name", "docstatus", "status")}
    children = {k: v for k, v in doc.items() if isinstance(v, list) and v and isinstance(v[0], dict)}
    rows: list[dict[str, Any]] = []
    for table, items in children.items():
        for item in items:
            compact = {k: v for k, v in item.items() if v not in (None, "") and k not in ("parent", "parenttype", "parentfield", "doctype", "owner", "modified_by", "creation", "modified")}
            rows.append({"table": table, **compact})
    summary = {k: v for k, v in scalars.items() if k not in ("doctype", "owner", "modified_by", "_user_tags", "_comments", "_assign", "_liked_by")}
    return ToolResult(rows=round_rows(rows), summary=summary, title=f"{doctype} {name}",
                      note=f"Document header fields are in summary; child table rows ({', '.join(children) or 'none'}) are in rows.")


# ------------------------------------------------------------------ reports
async def run_erpnext_report(client: ERPNextClient, report_name: str, filters: dict[str, Any] | None = None, limit: int = 100) -> ToolResult:
    await _check_report(client, report_name)
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


FILTERS_PARAM = {
    "type": "array",
    "items": {"type": "array", "items": {}},
    "description": "List of [field, operator, value] filters. Operators: =, !=, >, <, >=, <=, like, not like, in, not in, between, is (set/not set).",
}

TOOLS: list[Tool] = [
    Tool(
        name="list_modules",
        description="List the ERPNext/Frappe modules installed on the site (Accounts, Stock, HR, Payroll, Projects, CRM, Assets, Support, Quality, custom apps...) with the number of doctypes in each. Use to discover what the site contains.",
        parameters={"type": "object", "properties": {}},
        handler=list_modules,
    ),
    Tool(
        name="list_doctypes",
        description=(
            "Search ERPNext doctypes by name or module to find the right doctype for a question that no dedicated tool covers "
            "(e.g. 'Leave Application', 'Salary Slip', 'Project', 'Task', 'Lead', 'Opportunity', 'Asset', 'Issue', 'Attendance', 'Material Request')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "search": str_param("Partial doctype name, e.g. 'salary' or 'leave'."),
                "module": str_param("Module name filter, e.g. 'HR', 'Projects', 'CRM', 'Assets', 'Support'."),
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=list_doctypes,
    ),
    Tool(
        name="get_doctype_fields",
        description="Discover the fields (name, label, type, link target) and child tables of an ERPNext doctype before querying it.",
        parameters={"type": "object", "properties": {"doctype": str_param("DocType name.")}, "required": ["doctype"]},
        handler=get_doctype_fields,
    ),
    Tool(
        name="query_doctype",
        description=(
            "Read-only list query on ANY ERPNext doctype (Employee, Attendance, Leave Application, Salary Slip, Project, Task, Timesheet, "
            "Lead, Opportunity, Asset, Issue, Material Request, Item Price, Pricing Rule, Address, Contact, custom doctypes...). "
            "Supports aggregates like 'sum(grand_total) as total', 'count(name) as n', 'avg(x) as a' with group_by, child-table fields via "
            "'`tabChild Doctype`.field', filters, or_filters and order_by. Call get_doctype_fields first if unsure of field names."
        ),
        parameters={
            "type": "object",
            "properties": {
                "doctype": str_param("ERPNext DocType name, e.g. 'Leave Application'."),
                "fields": {"type": "array", "items": {"type": "string"}, "description": "Field names or aggregates. Default ['name']."},
                "filters": FILTERS_PARAM,
                "or_filters": {**FILTERS_PARAM, "description": "Filters combined with OR."},
                "group_by": str_param("Group by field."),
                "order_by": str_param("e.g. 'modified desc'."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["doctype"],
        },
        handler=query_doctype,
    ),
    Tool(
        name="count_records",
        description="Count records of any doctype matching filters (e.g. how many employees, open tasks, active customers, pending leave applications).",
        parameters={"type": "object", "properties": {"doctype": str_param("DocType name."), "filters": FILTERS_PARAM}, "required": ["doctype"]},
        handler=count_records,
    ),
    Tool(
        name="get_document",
        description=(
            "Fetch ONE complete ERPNext document by its ID, including all child table rows (e.g. a Sales Invoice with its items and taxes, "
            "a Purchase Order, a Salary Slip with earnings/deductions, a BOM, a Project, an Employee record). Use when the user names a specific document or asks for its details."
        ),
        parameters={"type": "object", "properties": {"doctype": str_param("DocType name, e.g. 'Sales Invoice'."), "name": str_param("Document ID, e.g. 'ACC-SINV-2026-00012'.")}, "required": ["doctype", "name"]},
        handler=get_document,
    ),
    Tool(
        name="list_reports",
        description="Search the ERPNext reports available on the site by name or module (e.g. 'gross profit', 'attendance', 'salary register', 'project profitability'). Then run one with run_erpnext_report.",
        parameters={
            "type": "object",
            "properties": {"search": str_param("Partial report name."), "module": str_param("Module filter, e.g. 'HR', 'Accounts'."), "limit": int_param("Max rows.", 50)},
        },
        handler=list_reports,
    ),
    Tool(
        name="run_erpnext_report",
        description=(
            "Run a standard ERPNext query/script report by exact name with filters (e.g. 'Gross Profit', 'Sales Analytics', 'Stock Ledger', "
            "'Accounts Receivable Summary', 'Item-wise Sales Register', 'Monthly Attendance Sheet', 'Salary Register', 'Trial Balance'). "
            "Filters usually need company and from_date/to_date."
        ),
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
