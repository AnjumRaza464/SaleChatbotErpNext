"""Customers and suppliers module."""
from __future__ import annotations

from typing import Any

from app.core.errors import NotFoundError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, int_param, like, round_rows, str_param


async def list_customers(client: ERPNextClient, search: str | None = None, customer_group: str | None = None, territory: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["disabled", "=", 0]]
    or_filters = [["customer_name", "like", like(search)], ["name", "like", like(search)]] if search else None
    if customer_group:
        filters.append(["customer_group", "like", like(customer_group)])
    if territory:
        filters.append(["territory", "like", like(territory)])
    fields = ["name", "customer_name", "customer_group", "territory", "customer_type", "mobile_no", "email_id", "default_currency"]
    rows = await client.get_list("Customer", fields, filters, or_filters=or_filters, order_by="customer_name asc", limit=clamp_limit(limit, 50, 500))
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="Customers")


async def get_customer_details(client: ERPNextClient, customer: str) -> ToolResult:
    rows = await client.get_list("Customer", ["name", "customer_name", "customer_group", "territory", "customer_type", "mobile_no", "email_id", "disabled"], [],
                                 or_filters=[["name", "=", customer], ["customer_name", "like", like(customer)]], limit=1)
    if not rows:
        raise NotFoundError(f"Customer '{customer}' not found")
    cust = rows[0]
    base = [["docstatus", "=", 1], ["customer", "=", cust["name"]]]
    sales = await client.get_list("Sales Invoice", ["count(name) as invoices", "sum(grand_total) as total", "sum(outstanding_amount) as outstanding", "max(posting_date) as last_invoice_date"], base, limit=1)
    pos = await client.get_list("POS Invoice", ["count(name) as invoices", "sum(grand_total) as total"], base + [["status", "!=", "Consolidated"]], limit=1)
    recent = await client.get_list("Sales Invoice", ["name", "posting_date", "grand_total", "outstanding_amount", "status"], base, order_by="posting_date desc", limit=10)
    s = sales[0] if sales else {}
    p = pos[0] if pos else {}
    summary = {**cust, "lifetime_sales": round(float(s.get("total") or 0) + float(p.get("total") or 0), 2), "invoices": int(s.get("invoices") or 0) + int(p.get("invoices") or 0),
               "outstanding": round(float(s.get("outstanding") or 0), 2), "last_invoice_date": s.get("last_invoice_date")}
    return ToolResult(rows=round_rows(recent), summary=summary, title=f"Customer {cust['name']}", note="Rows are the 10 most recent Sales Invoices.")


async def list_suppliers(client: ERPNextClient, search: str | None = None, supplier_group: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["disabled", "=", 0]]
    or_filters = [["supplier_name", "like", like(search)], ["name", "like", like(search)]] if search else None
    if supplier_group:
        filters.append(["supplier_group", "like", like(supplier_group)])
    fields = ["name", "supplier_name", "supplier_group", "supplier_type", "country", "mobile_no", "email_id"]
    rows = await client.get_list("Supplier", fields, filters, or_filters=or_filters, order_by="supplier_name asc", limit=clamp_limit(limit, 50, 500))
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="Suppliers")


async def get_supplier_details(client: ERPNextClient, supplier: str) -> ToolResult:
    rows = await client.get_list("Supplier", ["name", "supplier_name", "supplier_group", "supplier_type", "country", "mobile_no", "email_id", "disabled"], [],
                                 or_filters=[["name", "=", supplier], ["supplier_name", "like", like(supplier)]], limit=1)
    if not rows:
        raise NotFoundError(f"Supplier '{supplier}' not found")
    sup = rows[0]
    base = [["docstatus", "=", 1], ["supplier", "=", sup["name"]]]
    agg = await client.get_list("Purchase Invoice", ["count(name) as invoices", "sum(grand_total) as total", "sum(outstanding_amount) as outstanding", "max(posting_date) as last_invoice_date"], base, limit=1)
    recent = await client.get_list("Purchase Invoice", ["name", "posting_date", "grand_total", "outstanding_amount", "status"], base, order_by="posting_date desc", limit=10)
    a = agg[0] if agg else {}
    summary = {**sup, "lifetime_purchases": round(float(a.get("total") or 0), 2), "invoices": int(a.get("invoices") or 0), "outstanding_payable": round(float(a.get("outstanding") or 0), 2), "last_invoice_date": a.get("last_invoice_date")}
    return ToolResult(rows=round_rows(recent), summary=summary, title=f"Supplier {sup['name']}", note="Rows are the 10 most recent Purchase Invoices.")


async def get_top_parties(client: ERPNextClient, party_type: str = "Customer", from_date: str | None = None, to_date: str | None = None, limit: int = 10) -> ToolResult:
    from app.services.erpnext.modules.purchase import get_purchase_summary
    from app.services.erpnext.modules.sales import get_sales_summary

    if party_type == "Supplier":
        return await get_purchase_summary(client, from_date, to_date, "supplier", limit)
    return await get_sales_summary(client, from_date, to_date, "customer", limit)


TOOLS: list[Tool] = [
    Tool(name="list_customers", description="Search customers (name, group, territory, contact).",
         parameters={"type": "object", "properties": {"search": str_param("Name contains."), "customer_group": str_param("Customer group contains."), "territory": str_param("Territory contains."), "limit": int_param("Max rows.", 50)}},
         handler=list_customers),
    Tool(name="get_customer_details", description="One customer's profile with lifetime sales, outstanding balance and recent invoices.",
         parameters={"type": "object", "properties": {"customer": str_param("Customer name or ID.")}, "required": ["customer"]}, handler=get_customer_details),
    Tool(name="list_suppliers", description="Search suppliers (name, group, contact).",
         parameters={"type": "object", "properties": {"search": str_param("Name contains."), "supplier_group": str_param("Supplier group contains."), "limit": int_param("Max rows.", 50)}},
         handler=list_suppliers),
    Tool(name="get_supplier_details", description="One supplier's profile with lifetime purchases, payable balance and recent invoices.",
         parameters={"type": "object", "properties": {"supplier": str_param("Supplier name or ID.")}, "required": ["supplier"]}, handler=get_supplier_details),
    Tool(name="get_top_parties", description="Top customers by sales or top suppliers by purchases in a period.",
         parameters={"type": "object", "properties": {"party_type": str_param("Customer or Supplier.", ["Customer", "Supplier"]), "from_date": {"type": "string", "description": "Start date YYYY-MM-DD"}, "to_date": {"type": "string", "description": "End date YYYY-MM-DD"}, "limit": int_param("Max rows.", 10)}, "required": ["party_type", "from_date", "to_date"]},
         handler=get_top_parties),
]
