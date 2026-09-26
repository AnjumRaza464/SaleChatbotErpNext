"""POS module: POS invoice summaries by profile / payment mode / cashier and closings."""
from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.modules.common import add_share, month_key, resolve_period
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, date_param, int_param, like, round_rows, str_param

GROUP_CHOICES = ["none", "pos_profile", "mode_of_payment", "cashier", "day", "month", "status", "cost_center", "warehouse", "item"]


async def get_pos_summary(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    group_by: str = "none",
    pos_profile: str | None = None,
    limit: int = 30,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    dt = "POS Invoice"
    filters: list[list[Any]] = [[dt, "docstatus", "=", 1], [dt, "posting_date", ">=", start.isoformat()], [dt, "posting_date", "<=", end.isoformat()]]
    if pos_profile:
        filters.append([dt, "pos_profile", "like", like(pos_profile)])

    agg = await client.get_list(dt, ["sum(grand_total) as total", "sum(net_total) as net", "count(name) as invoices", "sum(total_qty) as qty"], filters, limit=1)
    returns = await client.get_count(dt, filters + [[dt, "is_return", "=", 1]])
    a = agg[0] if agg else {}
    summary = {"from_date": start.isoformat(), "to_date": end.isoformat(), "total": round(float(a.get("total") or 0), 2), "net": round(float(a.get("net") or 0), 2),
               "invoices": int(a.get("invoices") or 0), "qty": round(float(a.get("qty") or 0), 2), "returns": returns}
    if summary["invoices"]:
        summary["average_bill"] = round(summary["total"] / summary["invoices"], 2)

    rows: list[dict[str, Any]] = []
    if group_by == "mode_of_payment":
        ct = "`tabSales Invoice Payment`"
        rows = await client.get_list(dt, [f"{ct}.mode_of_payment as mode_of_payment", f"sum({ct}.amount) as total", f"count(distinct `tab{dt}`.name) as invoices"], filters, group_by=f"{ct}.mode_of_payment", order_by="total desc", limit=clamp_limit(limit, 30, 200))
        add_share(rows)
    elif group_by == "item":
        ct = "`tabPOS Invoice Item`"
        rows = await client.get_list(dt, [f"{ct}.item_code as item_code", f"{ct}.item_name as item_name", f"sum({ct}.qty) as qty", f"sum({ct}.amount) as total"], filters, group_by=f"{ct}.item_code", order_by="total desc", limit=clamp_limit(limit, 30, 500))
        add_share(rows)
    elif group_by != "none":
        key = {"pos_profile": "pos_profile", "cashier": "owner", "day": "posting_date", "month": "posting_date", "status": "status", "cost_center": "cost_center", "warehouse": "set_warehouse"}.get(group_by)
        if not key:
            raise ValidationError(f"Unsupported group_by '{group_by}'")
        rows = await client.get_list(dt, [key, "sum(grand_total) as total", "count(name) as invoices", "sum(total_qty) as qty"], filters, group_by=key,
                                     order_by=(f"{key} asc" if group_by in ("day", "month") else "total desc"), limit=5000 if group_by == "month" else clamp_limit(limit, 30, 500))
        if group_by == "month":
            merged: dict[str, dict[str, Any]] = {}
            for r in rows:
                m = month_key(r["posting_date"])
                cur = merged.setdefault(m, {"month": m, "total": 0.0, "invoices": 0, "qty": 0.0})
                cur["total"] += float(r["total"] or 0)
                cur["invoices"] += int(r["invoices"] or 0)
                cur["qty"] += float(r["qty"] or 0)
            rows = list(merged.values())
        elif group_by == "cashier":
            for r in rows:
                r["cashier"] = r.pop("owner")
        if group_by not in ("day", "month"):
            add_share(rows)
    return ToolResult(rows=round_rows(rows), summary=summary, title=f"POS sales {start} to {end}", note="Submitted POS Invoices (including those later consolidated). Returns are netted in totals.")


async def list_pos_closing_entries(client: ERPNextClient, from_date: str | None = None, to_date: str | None = None, pos_profile: str | None = None, limit: int = 30) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["docstatus", "!=", 2], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if pos_profile:
        filters.append(["pos_profile", "like", like(pos_profile)])
    fields = ["name", "posting_date", "period_start_date", "period_end_date", "pos_profile", "user", "grand_total", "net_total", "total_quantity", "status", "docstatus"]
    rows = await client.get_list("POS Closing Entry", fields, filters, order_by="posting_date desc", limit=clamp_limit(limit, 30, 200))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "from_date": start.isoformat(), "to_date": end.isoformat()}, title="POS Closing Entries")


async def list_pos_profiles(client: ERPNextClient) -> ToolResult:
    rows = await client.get_list("POS Profile", ["name", "company", "warehouse", "cost_center", "currency", "disabled"], limit=200)
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="POS Profiles")


TOOLS: list[Tool] = [
    Tool(
        name="get_pos_summary",
        description="POS (point of sale) sales for a period with grouping by POS profile/counter, payment mode (cash/card...), cashier, day, month, status, item, cost_center or warehouse. Includes average bill value and returns count.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "group_by": str_param("Grouping.", GROUP_CHOICES),
                "pos_profile": str_param("POS profile filter (partial)."),
                "limit": int_param("Max rows when grouped.", 30),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_pos_summary,
    ),
    Tool(
        name="list_pos_closing_entries",
        description="POS closing (shift/day-end) entries with totals per profile and user.",
        parameters={"type": "object", "properties": {"from_date": date_param("Start date"), "to_date": date_param("End date"), "pos_profile": str_param("POS profile filter."), "limit": int_param("Max rows.", 30)}, "required": ["from_date", "to_date"]},
        handler=list_pos_closing_entries,
    ),
    Tool(name="list_pos_profiles", description="List POS profiles (counters) with their warehouse and cost center.", parameters={"type": "object", "properties": {}}, handler=list_pos_profiles),
]
