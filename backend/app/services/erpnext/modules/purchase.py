"""Purchase module: purchase summaries and purchase documents."""
from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.modules.common import grouped_invoice_totals, pct_change, resolve_period
from app.services.erpnext.tools import (
    Tool,
    ToolResult,
    clamp_limit,
    date_param,
    int_param,
    like,
    round_rows,
    str_param,
)

PURCHASE_SOURCES: list[tuple[str, str, list[list[Any]]]] = [
    ("Purchase Invoice", "Purchase Invoice Item", [["docstatus", "=", 1]]),
]
GROUP_CHOICES = ["none", "day", "month", "item", "item_group", "supplier", "cost_center", "warehouse"]


async def get_purchase_summary(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    group_by: str = "none",
    top_n: int = 20,
    supplier: str | None = None,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    gb = "party" if group_by == "supplier" else (group_by or "none")
    if gb == "pos_profile":
        raise ValidationError("pos_profile grouping is not available for purchases")
    extra = [["supplier", "like", like(supplier)]] if supplier else None
    rows, totals = await grouped_invoice_totals(
        client, PURCHASE_SOURCES, gb, start, end, extra, clamp_limit(top_n, 20, 500), party_field="supplier"
    )
    summary = {"from_date": start.isoformat(), "to_date": end.isoformat(), **totals}
    return ToolResult(rows=rows, summary=summary, title=f"Purchases {start} to {end}", note="Submitted Purchase Invoices (grand totals, returns netted).")


async def get_purchase_comparison(client: ERPNextClient, period_a_from: str, period_a_to: str, period_b_from: str, period_b_to: str) -> ToolResult:
    a = await get_purchase_summary(client, period_a_from, period_a_to)
    b = await get_purchase_summary(client, period_b_from, period_b_to)
    summary = {
        "period_a": f"{a.summary['from_date']} to {a.summary['to_date']}",
        "period_b": f"{b.summary['from_date']} to {b.summary['to_date']}",
        "period_a_total": a.summary["total"],
        "period_b_total": b.summary["total"],
        "difference": round(a.summary["total"] - b.summary["total"], 2),
        "change_pct_a_vs_b": pct_change(a.summary["total"], b.summary["total"]),
    }
    return ToolResult(summary=summary, title="Purchase comparison")


async def list_purchase_documents(
    client: ERPNextClient,
    doctype: str = "Purchase Invoice",
    from_date: str | None = None,
    to_date: str | None = None,
    supplier: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> ToolResult:
    allowed = {"Purchase Invoice": "posting_date", "Purchase Order": "transaction_date", "Purchase Receipt": "posting_date"}
    if doctype not in allowed:
        raise ValidationError(f"doctype must be one of {list(allowed)}")
    date_field = allowed[doctype]
    filters: list[list[Any]] = [["docstatus", "!=", 2]]
    if from_date or to_date:
        start, end = resolve_period(from_date, to_date)
        filters += [[date_field, ">=", start.isoformat()], [date_field, "<=", end.isoformat()]]
    if supplier:
        filters.append(["supplier", "like", like(supplier)])
    if status:
        filters.append(["status", "=", status])
    fields = ["name", date_field, "supplier", "supplier_name", "grand_total", "status", "docstatus"]
    if doctype == "Purchase Invoice":
        fields += ["outstanding_amount", "due_date", "is_return"]
    if doctype == "Purchase Order":
        fields += ["per_received", "per_billed", "schedule_date"]
    rows = await client.get_list(doctype, fields, filters, order_by=f"{date_field} desc", limit=clamp_limit(limit))
    total = sum(float(r.get("grand_total") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "grand_total_sum": round(total, 2)}, title=f"{doctype} list")


TOOLS: list[Tool] = [
    Tool(
        name="get_purchase_summary",
        description="Total purchases for a period from Purchase Invoices, optionally grouped by supplier, item, item_group, day, month, cost_center or warehouse.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "group_by": str_param("Grouping.", GROUP_CHOICES),
                "top_n": int_param("Max rows when grouped.", 20),
                "supplier": str_param("Supplier filter (partial)."),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_purchase_summary,
    ),
    Tool(
        name="get_purchase_comparison",
        description="Compare purchase totals between two periods.",
        parameters={
            "type": "object",
            "properties": {
                "period_a_from": date_param("Period A start"),
                "period_a_to": date_param("Period A end"),
                "period_b_from": date_param("Period B start"),
                "period_b_to": date_param("Period B end"),
            },
            "required": ["period_a_from", "period_a_to", "period_b_from", "period_b_to"],
        },
        handler=get_purchase_comparison,
    ),
    Tool(
        name="list_purchase_documents",
        description="List Purchase Invoices, Purchase Orders or Purchase Receipts with supplier, amount and status.",
        parameters={
            "type": "object",
            "properties": {
                "doctype": str_param("Document type.", ["Purchase Invoice", "Purchase Order", "Purchase Receipt"]),
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "supplier": str_param("Supplier filter (partial)."),
                "status": str_param("Status filter."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["doctype"],
        },
        handler=list_purchase_documents,
    ),
]
