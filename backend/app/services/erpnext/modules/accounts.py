"""Accounts module: receivables/payables, payments, ledgers and statements."""
from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.context import get_site_context
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

PARTY_DOCTYPE = {"Customer": ("Sales Invoice", "customer", "customer_name"), "Supplier": ("Purchase Invoice", "supplier", "supplier_name")}


async def get_outstanding_invoices(
    client: ERPNextClient,
    party_type: str = "Customer",
    party: str | None = None,
    only_overdue: bool = False,
    limit: int = 50,
) -> ToolResult:
    if party_type not in PARTY_DOCTYPE:
        raise ValidationError("party_type must be Customer or Supplier")
    doctype, party_field, party_name_field = PARTY_DOCTYPE[party_type]
    today = get_site_context().today()
    filters: list[list[Any]] = [["docstatus", "=", 1], ["outstanding_amount", ">", 0]]
    if party:
        filters.append([party_field, "like", like(party)])
    if only_overdue:
        filters.append(["due_date", "<", today])
    fields = ["name", "posting_date", "due_date", party_field, party_name_field, "grand_total", "outstanding_amount", "status", "currency"]
    rows = await client.get_list(doctype, fields, filters, order_by="outstanding_amount desc", limit=clamp_limit(limit, 50, 500))
    agg = await client.get_list(
        doctype,
        ["count(name) as invoices", "sum(outstanding_amount) as outstanding"],
        filters,
        limit=1,
    )
    overdue = await client.get_list(
        doctype,
        ["count(name) as invoices", "sum(outstanding_amount) as outstanding"],
        filters + ([["due_date", "<", today]] if not only_overdue else []),
        limit=1,
    )
    summary = {
        "party_type": party_type,
        "total_outstanding": round(float((agg[0].get("outstanding") if agg else 0) or 0), 2),
        "invoice_count": int((agg[0].get("invoices") if agg else 0) or 0),
        "overdue_outstanding": round(float((overdue[0].get("outstanding") if overdue else 0) or 0), 2),
        "overdue_invoice_count": int((overdue[0].get("invoices") if overdue else 0) or 0),
        "as_of": today,
    }
    label = "Receivables" if party_type == "Customer" else "Payables"
    return ToolResult(rows=round_rows(rows), summary=summary, title=f"Outstanding {label}", note=f"Submitted {doctype}s with outstanding amount > 0.")


async def get_party_outstanding_summary(client: ERPNextClient, party_type: str = "Customer", limit: int = 30) -> ToolResult:
    if party_type not in PARTY_DOCTYPE:
        raise ValidationError("party_type must be Customer or Supplier")
    doctype, party_field, party_name_field = PARTY_DOCTYPE[party_type]
    rows = await client.get_list(
        doctype,
        [party_field, party_name_field, "count(name) as invoices", "sum(outstanding_amount) as outstanding", "min(due_date) as oldest_due_date"],
        [["docstatus", "=", 1], ["outstanding_amount", ">", 0]],
        group_by=party_field,
        order_by="outstanding desc",
        limit=clamp_limit(limit, 30, 500),
    )
    total = sum(float(r.get("outstanding") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"party_type": party_type, "total_outstanding": round(total, 2), "parties": len(rows)},
                      title=f"Outstanding by {party_type}")


async def list_payment_entries(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    party_type: str | None = None,
    party: str | None = None,
    payment_type: str | None = None,
    limit: int = 50,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["docstatus", "=", 1], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if party_type:
        filters.append(["party_type", "=", party_type])
    if party:
        filters.append(["party", "like", like(party)])
    if payment_type:
        filters.append(["payment_type", "=", payment_type])
    fields = ["name", "posting_date", "payment_type", "party_type", "party", "party_name", "paid_amount", "mode_of_payment", "reference_no", "status"]
    rows = await client.get_list("Payment Entry", fields, filters, order_by="posting_date desc", limit=clamp_limit(limit))
    received = sum(float(r["paid_amount"] or 0) for r in rows if r.get("payment_type") == "Receive")
    paid = sum(float(r["paid_amount"] or 0) for r in rows if r.get("payment_type") == "Pay")
    return ToolResult(rows=round_rows(rows), summary={"from_date": start.isoformat(), "to_date": end.isoformat(), "received": round(received, 2), "paid": round(paid, 2), "count": len(rows)},
                      title="Payment Entries")


async def get_financial_statement(
    client: ERPNextClient,
    statement: str = "Profit and Loss Statement",
    from_date: str | None = None,
    to_date: str | None = None,
    company: str | None = None,
) -> ToolResult:
    if statement not in ("Profit and Loss Statement", "Balance Sheet", "Cash Flow"):
        raise ValidationError("statement must be 'Profit and Loss Statement', 'Balance Sheet' or 'Cash Flow'")
    ctx = get_site_context()
    start, end = resolve_period(from_date, to_date)
    company = company or ctx.default_company
    report = await client.run_report(
        statement,
        {
            "company": company,
            "filter_based_on": "Date Range",
            "period_start_date": start.isoformat(),
            "period_end_date": end.isoformat(),
            "periodicity": "Yearly",
            "include_default_book_entries": 1,
            "accumulated_values": 1,
        },
    )
    rows: list[dict[str, Any]] = []
    for r in report["result"]:
        if not isinstance(r, dict) or not (r.get("account") or r.get("account_name")):
            continue
        if r.get("has_value") is False:
            continue
        rows.append({
            "account": r.get("account_name") or r.get("account"),
            "level": int(r.get("indent") or 0),
            "is_group": bool(r.get("is_group")),
            "amount": round(float(r.get("total") or 0), 2),
        })
    summary: dict[str, Any] = {"statement": statement, "company": company, "from_date": start.isoformat(), "to_date": end.isoformat()}
    if statement == "Profit and Loss Statement":
        for r in report["result"]:
            if isinstance(r, dict) and r.get("account_name") and "Profit for the period" in str(r.get("account_name")):
                summary["net_profit"] = round(float(r.get("total") or 0), 2)
        for r in rows:
            if r["level"] == 0 and r["account"] in ("Income", "Expenses", "Expense"):
                summary[f"total_{r['account'].lower()}"] = r["amount"]
    return ToolResult(rows=rows, summary=summary, title=statement, note="From ERPNext standard report; amounts in company currency.")


async def get_general_ledger(
    client: ERPNextClient,
    account: str | None = None,
    party: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    voucher_type: str | None = None,
    limit: int = 50,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["is_cancelled", "=", 0], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if account:
        filters.append(["account", "like", like(account)])
    if party:
        filters.append(["party", "like", like(party)])
    if voucher_type:
        filters.append(["voucher_type", "=", voucher_type])
    fields = ["posting_date", "account", "debit", "credit", "party_type", "party", "voucher_type", "voucher_no", "against", "remarks"]
    rows = await client.get_list("GL Entry", fields, filters, order_by="posting_date desc, creation desc", limit=clamp_limit(limit))
    agg = await client.get_list("GL Entry", ["sum(debit) as debit", "sum(credit) as credit", "count(name) as entries"], filters, limit=1)
    a = agg[0] if agg else {}
    summary = {"from_date": start.isoformat(), "to_date": end.isoformat(), "total_debit": round(float(a.get("debit") or 0), 2),
               "total_credit": round(float(a.get("credit") or 0), 2), "entries": int(a.get("entries") or 0)}
    return ToolResult(rows=round_rows(rows), summary=summary, title="General Ledger")


async def get_account_balances(client: ERPNextClient, search: str | None = None, root_type: str | None = None, limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = [["is_cancelled", "=", 0]]
    if search:
        filters.append(["account", "like", like(search)])
    rows = await client.get_list(
        "GL Entry",
        ["account", "sum(debit) as debit", "sum(credit) as credit", "sum(debit) - sum(credit) as balance"],
        filters,
        group_by="account",
        order_by="balance desc",
        limit=clamp_limit(limit, 50, 500),
    )
    if root_type:
        accounts = await client.get_list("Account", ["name"], [["root_type", "=", root_type]], limit=2000)
        allowed = {a["name"] for a in accounts}
        rows = [r for r in rows if r.get("account") in allowed]
    return ToolResult(rows=round_rows(rows), summary={"accounts": len(rows)}, title="Account balances",
                      note="Balance = debit - credit from posted GL entries (positive = debit balance).")


async def list_journal_entries(client: ERPNextClient, from_date: str | None = None, to_date: str | None = None, voucher_type: str | None = None, limit: int = 50) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["docstatus", "=", 1], ["posting_date", ">=", start.isoformat()], ["posting_date", "<=", end.isoformat()]]
    if voucher_type:
        filters.append(["voucher_type", "=", voucher_type])
    fields = ["name", "posting_date", "voucher_type", "total_debit", "total_credit", "user_remark", "cheque_no"]
    rows = await client.get_list("Journal Entry", fields, filters, order_by="posting_date desc", limit=clamp_limit(limit))
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "from_date": start.isoformat(), "to_date": end.isoformat()}, title="Journal Entries")


TOOLS: list[Tool] = [
    Tool(
        name="get_outstanding_invoices",
        description="Outstanding (unpaid) invoices: receivables from customers or payables to suppliers, with overdue totals. Use for 'outstanding invoices', 'who owes us', 'unpaid bills', 'overdue'.",
        parameters={
            "type": "object",
            "properties": {
                "party_type": str_param("Customer for receivables, Supplier for payables.", ["Customer", "Supplier"]),
                "party": str_param("Filter to one customer/supplier (partial match)."),
                "only_overdue": {"type": "boolean", "description": "Only invoices past due date."},
                "limit": int_param("Max rows.", 50),
            },
            "required": ["party_type"],
        },
        handler=get_outstanding_invoices,
    ),
    Tool(
        name="get_party_outstanding_summary",
        description="Outstanding balance grouped per customer or per supplier (top debtors / creditors).",
        parameters={
            "type": "object",
            "properties": {
                "party_type": str_param("Customer or Supplier.", ["Customer", "Supplier"]),
                "limit": int_param("Max parties.", 30),
            },
            "required": ["party_type"],
        },
        handler=get_party_outstanding_summary,
    ),
    Tool(
        name="list_payment_entries",
        description="Payments received from customers or paid to suppliers in a period (Payment Entry).",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "party_type": str_param("Customer or Supplier.", ["Customer", "Supplier", "Employee"]),
                "party": str_param("Party filter (partial)."),
                "payment_type": str_param("Receive, Pay or Internal Transfer.", ["Receive", "Pay", "Internal Transfer"]),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=list_payment_entries,
    ),
    Tool(
        name="get_financial_statement",
        description="Profit and Loss, Balance Sheet or Cash Flow for a period from ERPNext standard reports. Use for profit, expenses, income, net profit, assets/liabilities questions.",
        parameters={
            "type": "object",
            "properties": {
                "statement": str_param("Statement type.", ["Profit and Loss Statement", "Balance Sheet", "Cash Flow"]),
                "from_date": date_param("Period start"),
                "to_date": date_param("Period end"),
                "company": str_param("Company name (defaults to the default company)."),
            },
            "required": ["statement", "from_date", "to_date"],
        },
        handler=get_financial_statement,
    ),
    Tool(
        name="get_general_ledger",
        description="GL entries (debit/credit lines) for an account or party in a period.",
        parameters={
            "type": "object",
            "properties": {
                "account": str_param("Account name filter (partial)."),
                "party": str_param("Party filter (partial)."),
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "voucher_type": str_param("e.g. Sales Invoice, Payment Entry, Journal Entry."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_general_ledger,
    ),
    Tool(
        name="get_account_balances",
        description="Current balance of ledger accounts (cash, bank, debtors, expense accounts...). Optional search text or root type.",
        parameters={
            "type": "object",
            "properties": {
                "search": str_param("Account name contains."),
                "root_type": str_param("Asset, Liability, Equity, Income or Expense.", ["Asset", "Liability", "Equity", "Income", "Expense"]),
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=get_account_balances,
    ),
    Tool(
        name="list_journal_entries",
        description="List submitted Journal Entries in a period.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "voucher_type": str_param("Journal Entry voucher type filter."),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=list_journal_entries,
    ),
]
