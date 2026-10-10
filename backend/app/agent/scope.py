"""Role-based module scope: which tools, doctypes and reports each chat tab may use.

The four user-facing modules are ``sales``, ``warehouse``, ``stock`` and ``hr``.
Administrators additionally get ``all`` (every tool, every non-blocked doctype).

Enforcement happens in three places, all server-side:
  * the tool registry only exposes and executes the tools listed here;
  * the generic doctype/report tools consult the active scope (a contextvar)
    before touching ERPNext;
  * the HTTP routes refuse requests for modules the user does not hold.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field

MODULES: dict[str, dict[str, str]] = {
    "sales": {"label": "Sales", "description": "Sales reports, revenue, POS, customers, receivables and branch comparisons"},
    "warehouse": {"label": "Warehouse", "description": "Warehouse operations: receipts, dispatches, transfers, stock movement"},
    "stock": {"label": "Stock", "description": "Stock balances, low-stock items, item master and availability"},
    "hr": {"label": "HR", "description": "Employees, attendance, leave, departments and HR reports"},
    "accounts": {"label": "Accounts", "description": "Receivables, payables, payments, ledgers, P&L, balance sheet and journal entries"},
}
ADMIN_MODULE = "all"
ALL_MODULES = [*MODULES, ADMIN_MODULE]

# Tools shared by every module (own uploads + generic read tools, which are
# further restricted by the doctype allowlist below).
COMMON_TOOLS = {
    "analyze_uploaded_file",
    "list_doctypes", "get_doctype_fields", "query_doctype", "count_records", "get_document", "list_reports", "run_erpnext_report",
}

MODULE_TOOLS: dict[str, set[str]] = {
    "sales": {
        "get_sales_summary", "get_sales_comparison", "list_sales_invoices", "list_sales_documents",
        "get_pos_summary", "list_pos_closing_entries", "list_pos_profiles",
        "list_customers", "get_customer_details", "get_top_parties",
        "get_outstanding_invoices", "get_party_outstanding_summary", "list_payment_entries",
        "get_organization_masters",
    },
    "warehouse": {
        "list_stock_entries", "get_stock_ledger", "get_stock_movement_summary", "get_stock_by_warehouse",
        "list_purchase_documents", "list_sales_documents", "list_work_orders", "get_production_summary",
        "get_organization_masters",
    },
    "stock": {
        "get_stock_balance", "get_stock_by_warehouse", "get_low_stock_items", "list_items", "get_item_details",
        "get_stock_ledger", "list_boms", "get_bom_details", "get_organization_masters",
    },
    "hr": {
        "get_employee_summary", "list_employees", "get_attendance_summary", "list_leave_applications",
        "get_leave_balance", "list_holidays", "get_salary_register", "get_organization_masters",
    },
    "accounts": {
        "get_outstanding_invoices", "get_party_outstanding_summary", "list_payment_entries",
        "get_financial_statement", "get_general_ledger", "get_account_balances", "list_journal_entries",
        "list_sales_invoices", "list_purchase_documents", "get_sales_summary", "get_purchase_summary",
        "get_customer_details", "get_supplier_details", "get_top_parties", "list_pos_closing_entries",
        "get_organization_masters",
    },
}

# Doctypes the generic tools may read per module. ``None`` means every
# non-blocked doctype (administrators only).
MODULE_DOCTYPES: dict[str, set[str] | None] = {
    "sales": {
        "Sales Invoice", "POS Invoice", "Sales Order", "Quotation", "Delivery Note", "Customer", "Customer Group",
        "Territory", "Payment Entry", "Pricing Rule", "Item Price", "Price List", "POS Profile", "POS Closing Entry",
        "POS Opening Entry", "Cost Center", "Sales Person", "Sales Partner", "Mode of Payment", "Item", "Item Group",
        "Brand", "Company", "Address", "Contact", "Lead", "Opportunity", "Campaign",
    },
    "warehouse": {
        "Stock Entry", "Material Request", "Purchase Receipt", "Purchase Order", "Delivery Note", "Warehouse",
        "Stock Ledger Entry", "Pick List", "Packing Slip", "Stock Reconciliation", "Work Order", "Item", "Item Group",
        "UOM", "Batch", "Serial No", "Supplier", "Company", "Landed Cost Voucher", "Quality Inspection", "Putaway Rule",
    },
    "stock": {
        "Item", "Item Group", "Bin", "Warehouse", "Stock Ledger Entry", "Stock Reconciliation", "Batch", "Serial No",
        "Item Price", "Price List", "Brand", "UOM", "Item Reorder", "Item Attribute", "BOM", "Stock Entry",
        "Material Request", "Company", "Item Alternative", "Item Manufacturer",
    },
    "hr": {
        "Employee", "Department", "Designation", "Branch", "Employee Grade", "Employment Type", "Attendance",
        "Attendance Request", "Leave Application", "Leave Allocation", "Leave Type", "Holiday List", "Shift Type",
        "Shift Assignment", "Employee Checkin", "Salary Slip", "Salary Structure", "Salary Structure Assignment",
        "Salary Component", "Payroll Entry", "Employee Advance", "Expense Claim", "Job Opening", "Job Applicant",
        "Appraisal", "Training Event", "Company",
    },
    "accounts": {
        "Sales Invoice", "Purchase Invoice", "POS Invoice", "Payment Entry", "Journal Entry", "GL Entry", "Account",
        "Cost Center", "Fiscal Year", "Payment Terms Template", "Mode of Payment", "Bank Account", "Bank Transaction",
        "Bank Reconciliation Tool", "Customer", "Supplier", "Expense Claim", "Budget", "Tax Category", "Sales Taxes and Charges Template",
        "Purchase Taxes and Charges Template", "Payment Request", "Loyalty Point Entry", "POS Closing Entry", "Dunning",
        "Finance Book", "Accounting Dimension", "Accounting Period", "Company", "Currency", "Currency Exchange", "Asset",
        "Asset Depreciation Schedule", "Subscription", "Invoice Discounting", "Process Statement Of Accounts",
    },
    ADMIN_MODULE: None,
}


def tools_for(module: str) -> set[str] | None:
    """Allowed tool names for a module; ``None`` = all tools (admin)."""
    if module == ADMIN_MODULE:
        return None
    return MODULE_TOOLS[module] | COMMON_TOOLS


def doctypes_for(module: str) -> set[str] | None:
    return MODULE_DOCTYPES.get(module)


def is_valid_module(module: str) -> bool:
    return module in ALL_MODULES


# ---------------------------------------------------------------- active scope
@dataclass
class Scope:
    module: str = ADMIN_MODULE
    user_id: str | None = None
    doctypes: set[str] | None = None  # None = unrestricted
    tools: set[str] | None = None     # None = unrestricted
    extra: dict = field(default_factory=dict)

    def allows_doctype(self, doctype: str) -> bool:
        return self.doctypes is None or doctype in self.doctypes

    def allows_tool(self, name: str) -> bool:
        return self.tools is None or name in self.tools


_current: ContextVar[Scope] = ContextVar("erpnext_scope", default=Scope())


def set_scope(module: str, user_id: str | None = None) -> Scope:
    if not is_valid_module(module):
        raise ValueError(f"Unknown module '{module}'")
    scope = Scope(module=module, user_id=user_id, doctypes=doctypes_for(module), tools=tools_for(module))
    _current.set(scope)
    return scope


def current_scope() -> Scope:
    return _current.get()
