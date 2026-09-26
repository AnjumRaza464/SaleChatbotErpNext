"""Manufacturing module: work orders, BOMs and production output."""
from __future__ import annotations

from typing import Any

from app.core.errors import NotFoundError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.modules.common import resolve_period
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, date_param, int_param, like, round_rows, str_param


async def list_work_orders(client: ERPNextClient, status: str | None = None, from_date: str | None = None, to_date: str | None = None, item: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["docstatus", "!=", 2]]
    if status:
        filters.append(["status", "=", status])
    if from_date or to_date:
        start, end = resolve_period(from_date, to_date)
        filters += [["planned_start_date", ">=", start.isoformat()], ["planned_start_date", "<=", end.isoformat() + " 23:59:59"]]
    if item:
        filters.append(["production_item", "like", like(item)])
    fields = ["name", "production_item", "item_name", "qty", "produced_qty", "status", "planned_start_date", "actual_start_date", "actual_end_date", "wip_warehouse", "fg_warehouse", "bom_no"]
    rows = await client.get_list("Work Order", fields, filters, order_by="planned_start_date desc", limit=clamp_limit(limit))
    planned = sum(float(r.get("qty") or 0) for r in rows)
    produced = sum(float(r.get("produced_qty") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "planned_qty": round(planned, 2), "produced_qty": round(produced, 2)}, title="Work Orders")


async def get_production_summary(client: ERPNextClient, from_date: str | None = None, to_date: str | None = None) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    by_status = await client.get_list("Work Order", ["status", "count(name) as work_orders", "sum(qty) as planned_qty", "sum(produced_qty) as produced_qty"], [["docstatus", "!=", 2]], group_by="status", limit=50)
    produced = await client.get_list(
        "Stock Entry",
        ["`tabStock Entry Detail`.item_code as item_code", "`tabStock Entry Detail`.item_name as item_name", "sum(`tabStock Entry Detail`.qty) as qty", "sum(`tabStock Entry Detail`.amount) as value"],
        [["Stock Entry", "docstatus", "=", 1], ["Stock Entry", "purpose", "=", "Manufacture"], ["Stock Entry", "posting_date", ">=", start.isoformat()], ["Stock Entry", "posting_date", "<=", end.isoformat()], ["Stock Entry Detail", "is_finished_item", "=", 1]],
        group_by="`tabStock Entry Detail`.item_code",
        order_by="qty desc",
        limit=100,
    )
    summary = {"from_date": start.isoformat(), "to_date": end.isoformat(), "finished_goods_qty": round(sum(float(r.get("qty") or 0) for r in produced), 2),
               "finished_goods_value": round(sum(float(r.get("value") or 0) for r in produced), 2),
               "work_orders_by_status": {r["status"]: int(r["work_orders"]) for r in by_status}}
    return ToolResult(rows=round_rows(produced), summary=summary, title="Production summary", note="Rows: finished items produced via Manufacture stock entries in the period. Work order status counts are all-time.")


async def list_boms(client: ERPNextClient, item: str | None = None, only_active: bool = True, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["docstatus", "=", 1]]
    if only_active:
        filters.append(["is_active", "=", 1])
    or_filters = [["item", "like", like(item)], ["item_name", "like", like(item)]] if item else None
    fields = ["name", "item", "item_name", "quantity", "is_default", "is_active", "total_cost", "raw_material_cost", "operating_cost"]
    rows = await client.get_list("BOM", fields, filters, or_filters=or_filters, order_by="modified desc", limit=clamp_limit(limit))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows)}, title="Bills of Material")


async def get_bom_details(client: ERPNextClient, bom: str) -> ToolResult:
    doc = await client.get_doc("BOM", bom)
    if not doc:
        raise NotFoundError(f"BOM '{bom}' not found")
    items = [{"item_code": i.get("item_code"), "item_name": i.get("item_name"), "qty": i.get("qty"), "uom": i.get("uom"), "rate": i.get("rate"), "amount": i.get("amount")} for i in doc.get("items", [])]
    summary = {k: doc.get(k) for k in ("name", "item", "item_name", "quantity", "is_active", "is_default", "raw_material_cost", "operating_cost", "total_cost")}
    return ToolResult(rows=round_rows(items), summary=summary, title=f"BOM {bom}")


TOOLS: list[Tool] = [
    Tool(name="list_work_orders", description="List work orders (production orders) with planned vs produced quantity and status.",
         parameters={"type": "object", "properties": {"status": str_param("Status.", ["Draft", "Not Started", "In Process", "Completed", "Stopped", "Closed"]), "from_date": date_param("Planned start from"), "to_date": date_param("Planned start to"), "item": str_param("Production item filter (partial)."), "limit": int_param("Max rows.", 50)}},
         handler=list_work_orders),
    Tool(name="get_production_summary", description="Production output (finished goods manufactured) in a period plus work order status counts.",
         parameters={"type": "object", "properties": {"from_date": date_param("Start date"), "to_date": date_param("End date")}, "required": ["from_date", "to_date"]},
         handler=get_production_summary),
    Tool(name="list_boms", description="List Bills of Material, optionally for an item.",
         parameters={"type": "object", "properties": {"item": str_param("Item code/name filter."), "only_active": {"type": "boolean", "description": "Only active BOMs (default true)."}, "limit": int_param("Max rows.", 50)}},
         handler=list_boms),
    Tool(name="get_bom_details", description="Raw materials and costs of one BOM.",
         parameters={"type": "object", "properties": {"bom": str_param("BOM ID, e.g. BOM-ITEM-001.")}, "required": ["bom"]}, handler=get_bom_details),
]
