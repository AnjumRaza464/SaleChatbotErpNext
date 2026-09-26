"""Organization module: companies, branches, departments, cost centers, warehouses, employees."""
from __future__ import annotations

from typing import Any

from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, int_param, like, str_param

MASTERS: dict[str, tuple[str, list[str]]] = {
    "company": ("Company", ["name", "abbr", "default_currency", "country"]),
    "branch": ("Branch", ["name", "branch"]),
    "department": ("Department", ["name", "department_name", "parent_department", "company", "is_group"]),
    "cost_center": ("Cost Center", ["name", "cost_center_name", "parent_cost_center", "is_group", "company"]),
    "warehouse": ("Warehouse", ["name", "warehouse_name", "parent_warehouse", "is_group", "warehouse_type", "company"]),
    "pos_profile": ("POS Profile", ["name", "warehouse", "cost_center", "company"]),
    "territory": ("Territory", ["name", "parent_territory", "is_group"]),
    "customer_group": ("Customer Group", ["name", "parent_customer_group", "is_group"]),
    "supplier_group": ("Supplier Group", ["name", "parent_supplier_group", "is_group"]),
    "item_group": ("Item Group", ["name", "parent_item_group", "is_group"]),
    "brand": ("Brand", ["name"]),
    "mode_of_payment": ("Mode of Payment", ["name", "type", "enabled"]),
    "account": ("Account", ["name", "account_type", "root_type", "is_group", "parent_account"]),
}


async def get_organization_masters(client: ERPNextClient, kind: str, search: str | None = None, include_groups: bool = True, limit: int = 100) -> ToolResult:
    if kind not in MASTERS:
        raise ValidationError(f"kind must be one of {sorted(MASTERS)}")
    doctype, fields = MASTERS[kind]
    filters: list[list[Any]] = []
    if search:
        filters.append(["name", "like", like(search)])
    if not include_groups and "is_group" in fields:
        filters.append(["is_group", "=", 0])
    rows = await client.get_list(doctype, fields, filters, order_by="name asc", limit=clamp_limit(limit, 100, 1000))
    note = None
    if kind == "branch" and not rows:
        note = "No Branch records exist in this ERPNext. Branch-wise reporting can be done by cost center, POS profile or warehouse instead."
    return ToolResult(rows=rows, summary={"kind": kind, "count": len(rows)}, note=note, title=f"{doctype} list")


async def get_employee_summary(client: ERPNextClient, department: str | None = None, branch: str | None = None, status: str = "Active", limit: int = 50) -> ToolResult:
    filters: list[list[Any]] = []
    if status:
        filters.append(["status", "=", status])
    if department:
        filters.append(["department", "like", like(department)])
    if branch:
        filters.append(["branch", "like", like(branch)])
    by_dept = await client.get_list("Employee", ["department", "count(name) as employees"], filters, group_by="department", order_by="employees desc", limit=200)
    rows = await client.get_list("Employee", ["name", "employee_name", "department", "designation", "branch", "status", "date_of_joining"], filters, order_by="employee_name asc", limit=clamp_limit(limit))
    total = sum(int(r.get("employees") or 0) for r in by_dept)
    return ToolResult(rows=rows, summary={"total_employees": total, "by_department": {(r["department"] or "Unassigned"): int(r["employees"]) for r in by_dept}}, title="Employees")


TOOLS: list[Tool] = [
    Tool(
        name="get_organization_masters",
        description="List master records: companies, branches, departments, cost centers, warehouses, POS profiles, territories, customer/supplier/item groups, brands, modes of payment, accounts.",
        parameters={
            "type": "object",
            "properties": {
                "kind": str_param("Which master to list.", sorted(MASTERS)),
                "search": str_param("Name contains."),
                "include_groups": {"type": "boolean", "description": "Include group (parent) nodes. Default true."},
                "limit": int_param("Max rows.", 100),
            },
            "required": ["kind"],
        },
        handler=get_organization_masters,
    ),
    Tool(
        name="get_employee_summary",
        description="Employees with headcount per department, optionally filtered by department/branch/status.",
        parameters={"type": "object", "properties": {"department": str_param("Department contains."), "branch": str_param("Branch contains."), "status": str_param("Employee status.", ["Active", "Inactive", "Suspended", "Left"]), "limit": int_param("Max employee rows.", 50)}},
        handler=get_employee_summary,
    ),
]
