"""Sales module: revenue summaries, comparisons and sales documents.

Sales figures combine submitted POS Invoices with submitted Sales Invoices
that are *not* POS consolidations (``is_consolidated = 0``), because ERPNext
copies consolidated POS invoices into Sales Invoices at day close and adding
both would double count.
"""
from __future__ import annotations

from typing import Any

from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.modules.common import (
    grouped_invoice_totals,
    pct_change,
    resolve_period,
)
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

SALES_SOURCES: list[tuple[str, str, list[list[Any]]]] = [
    ("POS Invoice", "POS Invoice Item", [["docstatus", "=", 1]]),
    ("Sales Invoice", "Sales Invoice Item", [["docstatus", "=", 1], ["is_consolidated", "=", 0]]),
]

SALES_NOTE = (
    "Sales = submitted POS Invoices + submitted non-consolidated Sales Invoices (returns are netted). "
    "Amounts are grand totals in company currency. ERPNext sales invoices carry no Department field; "
    "for branch-wise figures use cost_center, pos_profile or warehouse."
)

GROUP_CHOICES = ["none", "day", "month", "item", "item_group", "customer", "cost_center", "pos_profile", "warehouse", "brand"]


def _extra_filters(customer: str | None, cost_center: str | None, pos_profile: str | None, warehouse: str | None) -> list[list[Any]]:
    f: list[list[Any]] = []
    if customer:
        f.append(["customer", "like", like(customer)])
    if cost_center:
        f.append(["cost_center", "like", like(cost_center)])
    if pos_profile:
        f.append(["pos_profile", "like", like(pos_profile)])
    if warehouse:
        f.append(["set_warehouse", "like", like(warehouse)])
    return f


async def get_sales_summary(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    group_by: str = "none",
    top_n: int = 20,
    customer: str | None = None,
    cost_center: str | None = None,
    pos_profile: str | None = None,
    warehouse: str | None = None,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    gb = "party" if group_by == "customer" else (group_by or "none")
    rows, totals = await grouped_invoice_totals(
        client, SALES_SOURCES, gb, start, end, _extra_filters(customer, cost_center, pos_profile, warehouse), clamp_limit(top_n, 20, 500)
    )
    summary = {"from_date": start.isoformat(), "to_date": end.isoformat(), **totals}
    if totals.get("invoices"):
        summary["average_invoice_value"] = round(totals["total"] / totals["invoices"], 2)
    return ToolResult(rows=rows, summary=summary, note=SALES_NOTE, title=f"Sales {start} to {end} by {group_by}")


async def get_sales_comparison(
    client: ERPNextClient,
    period_a_from: str,
    period_a_to: str,
    period_b_from: str,
    period_b_to: str,
    group_by: str = "none",
    top_n: int = 10,
) -> ToolResult:
    a_start, a_end = resolve_period(period_a_from, period_a_to)
    b_start, b_end = resolve_period(period_b_from, period_b_to)
    gb = "party" if group_by == "customer" else (group_by or "none")
    rows_a, tot_a = await grouped_invoice_totals(client, SALES_SOURCES, gb, a_start, a_end, None, clamp_limit(top_n, 10, 200))
    rows_b, tot_b = await grouped_invoice_totals(client, SALES_SOURCES, gb, b_start, b_end, None, clamp_limit(top_n, 10, 200))
    summary = {
        "period_a": f"{a_start} to {a_end}",
        "period_b": f"{b_start} to {b_end}",
        "period_a_total": tot_a["total"],
        "period_b_total": tot_b["total"],
        "difference": round(tot_a["total"] - tot_b["total"], 2),
        "change_pct_a_vs_b": pct_change(tot_a["total"], tot_b["total"]),
        "period_a_invoices": tot_a["invoices"],
        "period_b_invoices": tot_b["invoices"],
    }
    rows: list[dict[str, Any]] = []
    if gb != "none":
        key = {"party": "customer", "item": "item_code", "day": "posting_date", "month": "month", "warehouse": "set_warehouse"}.get(gb, gb)
        index_b = {r.get(key): r for r in rows_b}
        for r in rows_a:
            b = index_b.pop(r.get(key), {})
            rows.append({key: r.get(key), **({"item_name": r.get("item_name")} if "item_name" in r else {}),
                         "period_a_total": r.get("total", 0), "period_b_total": b.get("total", 0),
                         "difference": round(float(r.get("total", 0)) - float(b.get("total", 0)), 2),
                         "change_pct": pct_change(float(r.get("total", 0)), float(b.get("total", 0)))})
        for k, b in index_b.items():
            rows.append({key: k, **({"item_name": b.get("item_name")} if "item_name" in b else {}),
                         "period_a_total": 0, "period_b_total": b.get("total", 0),
                         "difference": round(-float(b.get("total", 0)), 2), "change_pct": None})
    return ToolResult(rows=rows, summary=summary, note=SALES_NOTE, title="Sales comparison")


async def list_sales_invoices(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    customer: str | None = None,
    status: str | None = None,
    doctype: str = "Sales Invoice",
    include_cancelled: bool = False,
    limit: int = 50,
) -> ToolResult:
    doctype = doctype if doctype in ("Sales Invoice", "POS Invoice") else "Sales Invoice"
    filters: list[list[Any]] = []
    if not include_cancelled:
        filters.append(["docstatus", "!=", 2])
    if from_date or to_date:
        start, end = resolve_period(from_date, to_date)
        filters += [["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if customer:
        filters.append(["customer", "like", like(customer)])
    if status:
        filters.append(["status", "=", status])
    fields = ["name", "posting_date", "customer", "customer_name", "grand_total", "outstanding_amount", "status",
              "is_return", "cost_center", "pos_profile", "set_warehouse", "total_qty", "currency"]
    if doctype == "Sales Invoice":
        fields += ["is_pos", "is_consolidated", "due_date"]
    rows = await client.get_list(doctype, fields, filters, order_by="posting_date desc, name desc", limit=clamp_limit(limit))
    total = sum(float(r.get("grand_total") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "grand_total_sum": round(total, 2)},
                      note=f"Latest {doctype} documents (max {clamp_limit(limit)}). Consolidated Sales Invoices duplicate POS invoices.",
                      title=f"{doctype} list")


async def list_sales_documents(
    client: ERPNextClient,
    doctype: str,
    from_date: str | None = None,
    to_date: str | None = None,
    customer: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> ToolResult:
    allowed = {"Sales Order": "transaction_date", "Quotation": "transaction_date", "Delivery Note": "posting_date"}
    if doctype not in allowed:
        raise ValueError(f"doctype must be one of {list(allowed)}")
    date_field = allowed[doctype]
    filters: list[list[Any]] = [["docstatus", "!=", 2]]
    if from_date or to_date:
        start, end = resolve_period(from_date, to_date)
        filters += [[date_field, ">=", start.isoformat()], [date_field, "<=", end.isoformat()]]
    if customer:
        filters.append(["customer" if doctype != "Quotation" else "party_name", "like", like(customer)])
    if status:
        filters.append(["status", "=", status])
    fields = ["name", date_field, "grand_total", "status", "docstatus"]
    fields.append("party_name" if doctype == "Quotation" else "customer")
    if doctype == "Sales Order":
        fields += ["delivery_date", "per_delivered", "per_billed"]
    rows = await client.get_list(doctype, fields, filters, order_by=f"{date_field} desc", limit=clamp_limit(limit))
    total = sum(float(r.get("grand_total") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "grand_total_sum": round(total, 2)}, title=f"{doctype} list")


TOOLS: list[Tool] = [
    Tool(
        name="get_sales_summary",
        description=(
            "Total sales (revenue) for a date range from live ERPNext, optionally grouped. Use for today's/yesterday's/"
            "monthly sales, item-wise, customer-wise, branch-wise (cost_center / pos_profile / warehouse), item-group-wise "
            "or daily/monthly trends. Returns totals, invoice counts, quantities and share %. Dates default to today."
        ),
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "group_by": str_param("How to group results.", GROUP_CHOICES),
                "top_n": int_param("Max rows for grouped results (ignored for day/month).", 20),
                "customer": str_param("Filter by customer name (partial match)."),
                "cost_center": str_param("Filter by cost center / branch (partial match)."),
                "pos_profile": str_param("Filter by POS profile (partial match)."),
                "warehouse": str_param("Filter by source warehouse (partial match)."),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_sales_summary,
    ),
    Tool(
        name="get_sales_comparison",
        description="Compare sales between two periods (e.g. this month vs last month, this week vs last week), optionally grouped by item, customer, cost_center, etc. Returns both totals, difference and growth %.",
        parameters={
            "type": "object",
            "properties": {
                "period_a_from": date_param("Period A start"),
                "period_a_to": date_param("Period A end"),
                "period_b_from": date_param("Period B start"),
                "period_b_to": date_param("Period B end"),
                "group_by": str_param("Optional grouping.", GROUP_CHOICES),
                "top_n": int_param("Max rows when grouped.", 10),
            },
            "required": ["period_a_from", "period_a_to", "period_b_from", "period_b_to"],
        },
        handler=get_sales_comparison,
    ),
    Tool(
        name="list_sales_invoices",
        description="List individual Sales Invoices or POS Invoices with date, customer, amount, outstanding and status. Use when the user wants invoice-level detail or a specific invoice.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "customer": str_param("Customer filter (partial)."),
                "status": str_param("Status filter, e.g. Paid, Unpaid, Overdue, Return, Consolidated, Draft."),
                "doctype": str_param("Which doctype to list.", ["Sales Invoice", "POS Invoice"]),
                "include_cancelled": {"type": "boolean", "description": "Include cancelled documents."},
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=list_sales_invoices,
    ),
    Tool(
        name="list_sales_documents",
        description="List Sales Orders, Quotations or Delivery Notes with amounts and status.",
        parameters={
            "type": "object",
            "properties": {
                "doctype": str_param("Document type.", ["Sales Order", "Quotation", "Delivery Note"]),
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "customer": str_param("Customer filter (partial)."),
                "status": str_param("Status filter."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["doctype"],
        },
        handler=list_sales_documents,
    ),
]
