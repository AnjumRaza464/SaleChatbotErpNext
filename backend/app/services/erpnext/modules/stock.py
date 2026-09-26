"""Stock / Inventory module: balances, ledger, items, low stock, stock entries."""
from __future__ import annotations

from typing import Any

from app.core.errors import NotFoundError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.modules.common import resolve_period
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


async def _item_names(client: ERPNextClient, codes: list[str]) -> dict[str, dict[str, Any]]:
    if not codes:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(codes), 200):
        chunk = codes[i : i + 200]
        rows = await client.get_list("Item", ["name", "item_name", "item_group", "stock_uom"], [["name", "in", chunk]], limit=len(chunk))
        out.update({r["name"]: r for r in rows})
    return out


async def _items_matching(client: ERPNextClient, item_name: str | None, item_group: str | None) -> list[str] | None:
    if not item_name and not item_group:
        return None
    filters: list[list[Any]] = []
    if item_name:
        filters.append(["item_name", "like", like(item_name)])
    if item_group:
        filters.append(["item_group", "like", like(item_group)])
    rows = await client.get_list("Item", ["name"], filters, limit=2000)
    return [r["name"] for r in rows]


async def get_stock_balance(
    client: ERPNextClient,
    item_code: str | None = None,
    item_name: str | None = None,
    item_group: str | None = None,
    warehouse: str | None = None,
    only_in_stock: bool = True,
    limit: int = 50,
) -> ToolResult:
    filters: list[list[Any]] = []
    if item_code:
        filters.append(["item_code", "=", item_code])
    codes = await _items_matching(client, item_name, item_group)
    if codes is not None:
        if not codes:
            return ToolResult(rows=[], summary={"matched_items": 0}, note="No items matched the given name/group.")
        filters.append(["item_code", "in", codes])
    matched_note = f" {len(codes)} item(s) matched the name/group filter." if codes else ""
    if warehouse:
        filters.append(["warehouse", "like", like(warehouse)])
    if only_in_stock:
        filters.append(["actual_qty", "!=", 0])
    fields = ["item_code", "warehouse", "actual_qty", "reserved_qty", "ordered_qty", "projected_qty", "valuation_rate", "stock_value", "stock_uom"]
    rows = await client.get_list("Bin", fields, filters, order_by="stock_value desc", limit=clamp_limit(limit, 50, 1000))
    names = await _item_names(client, sorted({r["item_code"] for r in rows}))
    for r in rows:
        meta = names.get(r["item_code"], {})
        r["item_name"] = meta.get("item_name")
        r["item_group"] = meta.get("item_group")
    agg = await client.get_list("Bin", ["sum(actual_qty) as qty", "sum(stock_value) as value", "count(name) as bins"], filters, limit=1)
    a = agg[0] if agg else {}
    ordered_cols = ["item_code", "item_name", "item_group", "warehouse", "actual_qty", "stock_uom", "reserved_qty", "projected_qty", "valuation_rate", "stock_value"]
    rows = [{c: r.get(c) for c in ordered_cols} for r in rows]
    summary = {"total_qty": round(float(a.get("qty") or 0), 2), "total_stock_value": round(float(a.get("value") or 0), 2), "item_warehouse_rows": int(a.get("bins") or 0)}
    note = "Live Bin quantities per item and warehouse; stock_value at valuation rate." + matched_note
    if not rows and only_in_stock:
        note += " No rows have non-zero stock for this filter (the items exist but current quantity is zero everywhere)."
    return ToolResult(rows=round_rows(rows), summary=summary, title="Stock balance", note=note)


async def get_stock_by_warehouse(client: ERPNextClient) -> ToolResult:
    rows = await client.get_list(
        "Bin",
        ["warehouse", "count(name) as items", "sum(actual_qty) as qty", "sum(stock_value) as stock_value"],
        [["actual_qty", "!=", 0]],
        group_by="warehouse",
        order_by="stock_value desc",
        limit=200,
    )
    total = sum(float(r.get("stock_value") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"total_stock_value": round(total, 2), "warehouses": len(rows)}, title="Stock value by warehouse")


async def get_stock_ledger(
    client: ERPNextClient,
    item_code: str | None = None,
    warehouse: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    voucher_type: str | None = None,
    limit: int = 50,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["is_cancelled", "=", 0], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if item_code:
        filters.append(["item_code", "=", item_code])
    if warehouse:
        filters.append(["warehouse", "like", like(warehouse)])
    if voucher_type:
        filters.append(["voucher_type", "=", voucher_type])
    fields = ["posting_date", "posting_time", "item_code", "warehouse", "actual_qty", "qty_after_transaction", "valuation_rate", "stock_value_difference", "voucher_type", "voucher_no"]
    rows = await client.get_list("Stock Ledger Entry", fields, filters, order_by="posting_date desc, posting_time desc, creation desc", limit=clamp_limit(limit))
    inbound = sum(float(r["actual_qty"]) for r in rows if float(r.get("actual_qty") or 0) > 0)
    outbound = sum(-float(r["actual_qty"]) for r in rows if float(r.get("actual_qty") or 0) < 0)
    return ToolResult(rows=round_rows(rows), summary={"from_date": start.isoformat(), "to_date": end.isoformat(), "rows": len(rows), "qty_in": round(inbound, 2), "qty_out": round(outbound, 2)}, title="Stock ledger")


async def get_stock_movement_summary(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    warehouse: str | None = None,
    group_by: str = "item",
    limit: int = 30,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["is_cancelled", "=", 0], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if warehouse:
        filters.append(["warehouse", "like", like(warehouse)])
    key = {"item": "item_code", "warehouse": "warehouse", "voucher_type": "voucher_type"}.get(group_by, "item_code")
    # The server forbids CASE expressions in field lists, so split in/out with two grouped queries.
    inbound = await client.get_list("Stock Ledger Entry", [key, "sum(actual_qty) as qty_in", "sum(stock_value_difference) as value_in"], filters + [["actual_qty", ">", 0]], group_by=key, limit=5000)
    outbound = await client.get_list("Stock Ledger Entry", [key, "sum(actual_qty) as qty_out", "sum(stock_value_difference) as value_out"], filters + [["actual_qty", "<", 0]], group_by=key, limit=5000)
    merged: dict[Any, dict[str, Any]] = {}
    for r in inbound:
        merged.setdefault(r[key], {key: r[key], "qty_in": 0.0, "qty_out": 0.0, "value_change": 0.0})
        merged[r[key]]["qty_in"] += float(r.get("qty_in") or 0)
        merged[r[key]]["value_change"] += float(r.get("value_in") or 0)
    for r in outbound:
        merged.setdefault(r[key], {key: r[key], "qty_in": 0.0, "qty_out": 0.0, "value_change": 0.0})
        merged[r[key]]["qty_out"] += -float(r.get("qty_out") or 0)
        merged[r[key]]["value_change"] += float(r.get("value_out") or 0)
    for r in merged.values():
        r["net_qty"] = r["qty_in"] - r["qty_out"]
    rows = sorted(merged.values(), key=lambda r: r["qty_out"], reverse=True)[: clamp_limit(limit, 30, 500)]
    if key == "item_code":
        names = await _item_names(client, [r["item_code"] for r in rows])
        for r in rows:
            r["item_name"] = names.get(r["item_code"], {}).get("item_name")
    return ToolResult(rows=round_rows(rows), summary={"from_date": start.isoformat(), "to_date": end.isoformat()}, title="Stock movement")


async def list_items(
    client: ERPNextClient,
    search: str | None = None,
    item_group: str | None = None,
    is_stock_item: bool | None = None,
    include_disabled: bool = False,
    limit: int = 50,
) -> ToolResult:
    filters: list[list[Any]] = []
    or_filters: list[list[Any]] | None = None
    if search:
        or_filters = [["item_name", "like", like(search)], ["name", "like", like(search)]]
    if item_group:
        filters.append(["item_group", "like", like(item_group)])
    if is_stock_item is not None:
        filters.append(["is_stock_item", "=", 1 if is_stock_item else 0])
    if not include_disabled:
        filters.append(["disabled", "=", 0])
    fields = ["name as item_code", "item_name", "item_group", "stock_uom", "is_stock_item", "standard_rate", "valuation_rate", "disabled", "brand"]
    rows = await client.get_list("Item", fields, filters, or_filters=or_filters, order_by="item_name asc", limit=clamp_limit(limit, 50, 500))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows)}, title="Items")


async def get_item_details(client: ERPNextClient, item_code: str) -> ToolResult:
    items = await client.get_list("Item", ["name", "item_name", "item_group", "stock_uom", "is_stock_item", "standard_rate", "valuation_rate", "disabled", "brand", "description"],
                                  [], or_filters=[["name", "=", item_code], ["item_name", "like", like(item_code)]], limit=5)
    if not items:
        raise NotFoundError(f"Item '{item_code}' not found")
    item = items[0]
    bins = await client.get_list("Bin", ["warehouse", "actual_qty", "reserved_qty", "projected_qty", "valuation_rate", "stock_value"], [["item_code", "=", item["name"]]], limit=100)
    prices = await client.get_list("Item Price", ["price_list", "price_list_rate", "selling", "buying", "valid_from"], [["item_code", "=", item["name"]]], order_by="modified desc", limit=10)
    summary = {**{k: v for k, v in item.items() if k != "description"}, "total_qty": round(sum(float(b.get("actual_qty") or 0) for b in bins), 2),
               "total_stock_value": round(sum(float(b.get("stock_value") or 0) for b in bins), 2),
               "prices": [{"price_list": p["price_list"], "rate": p["price_list_rate"]} for p in prices]}
    return ToolResult(rows=round_rows(bins), summary=summary, title=f"Item {item['name']}", note="Rows are stock per warehouse.")


async def get_low_stock_items(client: ERPNextClient, threshold: float = 10, warehouse: str | None = None, item_group: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["actual_qty", "<=", threshold]]
    if warehouse:
        filters.append(["warehouse", "like", like(warehouse)])
    codes = await _items_matching(client, None, item_group)
    if codes is not None:
        filters.append(["item_code", "in", codes or ["__none__"]])
    rows = await client.get_list("Bin", ["item_code", "warehouse", "actual_qty", "reserved_qty", "ordered_qty", "projected_qty", "stock_uom"], filters, order_by="actual_qty asc", limit=clamp_limit(limit, 50, 500))
    names = await _item_names(client, sorted({r["item_code"] for r in rows}))
    for r in rows:
        r["item_name"] = names.get(r["item_code"], {}).get("item_name")
        r["item_group"] = names.get(r["item_code"], {}).get("item_group")
    return ToolResult(rows=round_rows(rows), summary={"threshold": threshold, "count": len(rows)}, title="Low stock items", note="Bins with actual_qty at or below the threshold (includes zero/negative).")


async def list_stock_entries(client: ERPNextClient, from_date: str | None = None, to_date: str | None = None, purpose: str | None = None, limit: int = 50) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["docstatus", "=", 1], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if purpose:
        filters.append(["purpose", "=", purpose])
    fields = ["name", "posting_date", "purpose", "stock_entry_type", "from_warehouse", "to_warehouse", "total_outgoing_value", "total_incoming_value", "work_order"]
    rows = await client.get_list("Stock Entry", fields, filters, order_by="posting_date desc", limit=clamp_limit(limit))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "from_date": start.isoformat(), "to_date": end.isoformat()}, title="Stock Entries")


TOOLS: list[Tool] = [
    Tool(
        name="get_stock_balance",
        description="Current stock quantity and value per item and warehouse (live Bin data). Use for 'stock of X', 'how many units in stock', 'inventory value', 'stock in warehouse Y'.",
        parameters={
            "type": "object",
            "properties": {
                "item_code": str_param("Exact item code."),
                "item_name": str_param("Item name contains (partial match)."),
                "item_group": str_param("Item group contains."),
                "warehouse": str_param("Warehouse name contains."),
                "only_in_stock": {"type": "boolean", "description": "Exclude zero-quantity rows (default true)."},
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=get_stock_balance,
    ),
    Tool(name="get_stock_by_warehouse", description="Total stock quantity and value grouped by warehouse.", parameters={"type": "object", "properties": {}}, handler=get_stock_by_warehouse),
    Tool(
        name="get_stock_ledger",
        description="Stock ledger transactions (in/out movements) for an item or warehouse in a period.",
        parameters={
            "type": "object",
            "properties": {
                "item_code": str_param("Exact item code."),
                "warehouse": str_param("Warehouse contains."),
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "voucher_type": str_param("e.g. Sales Invoice, Purchase Receipt, Stock Entry."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_stock_ledger,
    ),
    Tool(
        name="get_stock_movement_summary",
        description="Quantity in/out per item, warehouse or voucher type for a period (fast movers, consumption).",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "warehouse": str_param("Warehouse contains."),
                "group_by": str_param("Grouping.", ["item", "warehouse", "voucher_type"]),
                "limit": int_param("Max rows.", 30),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_stock_movement_summary,
    ),
    Tool(
        name="list_items",
        description="Search the item master by name/code/group.",
        parameters={
            "type": "object",
            "properties": {
                "search": str_param("Item name or code contains."),
                "item_group": str_param("Item group contains."),
                "is_stock_item": {"type": "boolean", "description": "Only stock (or only non-stock) items."},
                "include_disabled": {"type": "boolean", "description": "Include disabled items."},
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=list_items,
    ),
    Tool(
        name="get_item_details",
        description="Full details for one item: master data, stock per warehouse and price lists.",
        parameters={"type": "object", "properties": {"item_code": str_param("Item code or item name.")}, "required": ["item_code"]},
        handler=get_item_details,
    ),
    Tool(
        name="get_low_stock_items",
        description="Items whose stock is at or below a threshold (reorder / out-of-stock check).",
        parameters={
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "description": "Quantity threshold. Default 10."},
                "warehouse": str_param("Warehouse contains."),
                "item_group": str_param("Item group contains."),
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=get_low_stock_items,
    ),
    Tool(
        name="list_stock_entries",
        description="List Stock Entries (material receipt/issue/transfer/manufacture) in a period.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "purpose": str_param("Purpose filter.", ["Material Issue", "Material Receipt", "Material Transfer", "Manufacture", "Repack", "Material Transfer for Manufacture", "Material Consumption for Manufacture"]),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=list_stock_entries,
    ),
]
