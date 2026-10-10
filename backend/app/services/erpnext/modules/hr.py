"""HR module: employees, attendance, leave, holidays and salary (read-only).

Salary figures are only reachable through ``get_salary_register``, which the
scope layer exposes to HR users alone. Bank account numbers and other personal
identifiers are never selected.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.modules.common import resolve_period
from app.services.erpnext.tools import Tool, ToolResult, clamp_limit, date_param, int_param, like, round_rows, str_param


async def list_employees(
    client: ERPNextClient,
    search: str | None = None,
    department: str | None = None,
    designation: str | None = None,
    branch: str | None = None,
    status: str = "Active",
    limit: int = 50,
) -> ToolResult:
    filters: list[list[Any]] = []
    if status:
        filters.append(["status", "=", status])
    if search:
        filters.append(["employee_name", "like", like(search)])
    if department:
        filters.append(["department", "like", like(department)])
    if designation:
        filters.append(["designation", "like", like(designation)])
    if branch:
        filters.append(["branch", "like", like(branch)])
    fields = ["name", "employee_name", "gender", "department", "designation", "branch", "status", "date_of_joining", "employment_type", "company"]
    rows = await client.get_list("Employee", fields, filters, order_by="employee_name asc", limit=clamp_limit(limit))
    return ToolResult(rows=rows, summary={"count": len(rows), "status": status}, title="Employees")


async def get_attendance_summary(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    employee: str | None = None,
    department: str | None = None,
    group_by: str = "employee",
    limit: int = 50,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["docstatus", "=", 1], ["attendance_date", ">=", start.isoformat()], ["attendance_date", "<=", end.isoformat()]]
    if employee:
        filters.append(["employee_name", "like", like(employee)])
    if department:
        filters.append(["department", "like", like(department)])
    rows = await client.get_list(
        "Attendance", ["employee", "employee_name", "department", "attendance_date", "status", "late_entry", "early_exit", "working_hours"],
        filters, order_by="attendance_date desc", limit=5000,
    )
    if not rows:
        return ToolResult(rows=[], summary={"from_date": start.isoformat(), "to_date": end.isoformat(), "records": 0},
                          note="No submitted attendance records for this period.", title="Attendance")
    df = pd.DataFrame(rows)
    status_counts = df["status"].value_counts().to_dict()
    if group_by == "day":
        out = df.groupby("attendance_date")["status"].value_counts().unstack(fill_value=0).reset_index()
    elif group_by == "department":
        out = df.groupby("department", dropna=False)["status"].value_counts().unstack(fill_value=0).reset_index()
    else:
        out = df.groupby(["employee", "employee_name", "department"], dropna=False)["status"].value_counts().unstack(fill_value=0).reset_index()
        if "late_entry" in df:
            late = df.groupby("employee")["late_entry"].sum().rename("late_entries").reset_index()
            out = out.merge(late, on="employee", how="left")
    out = out.head(clamp_limit(limit))
    summary = {"from_date": start.isoformat(), "to_date": end.isoformat(), "records": len(df), **{str(k): int(v) for k, v in status_counts.items()}}
    return ToolResult(rows=round_rows(out.to_dict(orient="records")), summary=summary, title=f"Attendance {start} to {end} by {group_by}")


async def list_leave_applications(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    employee: str | None = None,
    status: str | None = None,
    leave_type: str | None = None,
    limit: int = 50,
) -> ToolResult:
    filters: list[list[Any]] = [["docstatus", "!=", 2]]
    if from_date or to_date:
        start, end = resolve_period(from_date, to_date)
        filters += [["to_date", ">=", start.isoformat()], ["from_date", "<=", end.isoformat()]]
    if employee:
        filters.append(["employee_name", "like", like(employee)])
    if status:
        filters.append(["status", "=", status])
    if leave_type:
        filters.append(["leave_type", "like", like(leave_type)])
    fields = ["name", "employee", "employee_name", "department", "leave_type", "from_date", "to_date", "total_leave_days", "status", "posting_date"]
    rows = await client.get_list("Leave Application", fields, filters, order_by="from_date desc", limit=clamp_limit(limit))
    days = sum(float(r.get("total_leave_days") or 0) for r in rows)
    return ToolResult(rows=round_rows(rows), summary={"count": len(rows), "total_leave_days": round(days, 1)}, title="Leave applications")


async def get_leave_balance(client: ERPNextClient, employee: str | None = None, leave_type: str | None = None, limit: int = 100) -> ToolResult:
    filters: list[list[Any]] = [["docstatus", "=", 1]]
    if employee:
        filters.append(["employee_name", "like", like(employee)])
    if leave_type:
        filters.append(["leave_type", "like", like(leave_type)])
    alloc = await client.get_list(
        "Leave Allocation", ["employee", "employee_name", "leave_type", "from_date", "to_date", "total_leaves_allocated", "new_leaves_allocated"],
        filters, order_by="employee_name asc", limit=1000,
    )
    if not alloc:
        return ToolResult(rows=[], summary={"count": 0}, note="No submitted leave allocations found.", title="Leave balance")
    taken_rows = await client.get_list(
        "Leave Application", ["employee", "leave_type", "sum(total_leave_days) as taken"],
        [["docstatus", "=", 1], ["status", "=", "Approved"]], group_by="employee, leave_type", limit=5000,
    )
    taken = {(t["employee"], t["leave_type"]): float(t.get("taken") or 0) for t in taken_rows}
    rows = []
    for a in alloc:
        used = taken.get((a["employee"], a["leave_type"]), 0.0)
        total = float(a.get("total_leaves_allocated") or 0)
        rows.append({"employee": a["employee"], "employee_name": a["employee_name"], "leave_type": a["leave_type"], "period": f"{a['from_date']} to {a['to_date']}",
                     "allocated": total, "taken": used, "balance": round(total - used, 1)})
    rows = rows[: clamp_limit(limit, 100, 1000)]
    return ToolResult(rows=rows, summary={"count": len(rows)}, note="Balance = submitted allocation minus approved leave applications.", title="Leave balance")


async def list_holidays(client: ERPNextClient, holiday_list: str | None = None, from_date: str | None = None, to_date: str | None = None, limit: int = 100) -> ToolResult:
    filters: list[list[Any]] = []
    if holiday_list:
        filters.append(["Holiday List", "name", "like", like(holiday_list)])
    if from_date or to_date:
        start, end = resolve_period(from_date, to_date)
        filters += [["Holiday", "holiday_date", ">=", start.isoformat()], ["Holiday", "holiday_date", "<=", end.isoformat()]]
    rows = await client.get_list(
        "Holiday List",
        ["`tabHoliday List`.name as holiday_list", "`tabHoliday`.holiday_date as holiday_date", "`tabHoliday`.description as description", "`tabHoliday`.weekly_off as weekly_off"],
        filters, order_by="`tabHoliday`.holiday_date asc", limit=clamp_limit(limit, 100, 1000),
    )
    return ToolResult(rows=rows, summary={"count": len(rows)}, title="Holidays")


async def get_salary_register(
    client: ERPNextClient,
    from_date: str | None = None,
    to_date: str | None = None,
    employee: str | None = None,
    department: str | None = None,
    group_by: str = "employee",
    limit: int = 50,
) -> ToolResult:
    start, end = resolve_period(from_date, to_date)
    filters: list[list[Any]] = [["docstatus", "=", 1], ["start_date", "<=", end.isoformat()], ["end_date", ">=", start.isoformat()]]
    if employee:
        filters.append(["employee_name", "like", like(employee)])
    if department:
        filters.append(["department", "like", like(department)])
    fields = ["name", "employee", "employee_name", "department", "designation", "start_date", "end_date", "gross_pay", "total_deduction", "net_pay", "status"]
    rows = await client.get_list("Salary Slip", fields, filters, order_by="end_date desc, employee_name asc", limit=5000)
    if not rows:
        return ToolResult(rows=[], summary={"from_date": start.isoformat(), "to_date": end.isoformat(), "slips": 0}, note="No submitted salary slips for this period.", title="Salary register")
    df = pd.DataFrame(rows)
    for c in ("gross_pay", "total_deduction", "net_pay"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    totals = {"slips": len(df), "gross_pay": round(float(df["gross_pay"].sum()), 2), "total_deduction": round(float(df["total_deduction"].sum()), 2), "net_pay": round(float(df["net_pay"].sum()), 2)}
    if group_by == "department":
        out = df.groupby("department", dropna=False)[["gross_pay", "total_deduction", "net_pay"]].sum().reset_index()
        out["slips"] = df.groupby("department", dropna=False).size().values
    elif group_by == "month":
        df["month"] = df["start_date"].astype(str).str[:7]
        out = df.groupby("month")[["gross_pay", "total_deduction", "net_pay"]].sum().reset_index()
    else:
        out = df[["name", "employee", "employee_name", "department", "start_date", "end_date", "gross_pay", "total_deduction", "net_pay", "status"]]
    out = out.head(clamp_limit(limit))
    return ToolResult(rows=round_rows(out.to_dict(orient="records")), summary={"from_date": start.isoformat(), "to_date": end.isoformat(), **totals},
                      note="Confidential payroll data. Figures are from submitted Salary Slips.", title=f"Salary register {start} to {end}")


TOOLS: list[Tool] = [
    Tool(
        name="list_employees",
        description="List employees with department, designation, branch, status and joining date. Filter by name, department, designation or branch.",
        parameters={
            "type": "object",
            "properties": {
                "search": str_param("Employee name (partial)."),
                "department": str_param("Department filter (partial)."),
                "designation": str_param("Designation filter (partial)."),
                "branch": str_param("Branch filter (partial)."),
                "status": str_param("Employee status.", ["Active", "Inactive", "Suspended", "Left"]),
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=list_employees,
    ),
    Tool(
        name="get_attendance_summary",
        description="Attendance for a period: Present/Absent/On Leave/Half Day counts per employee, per day or per department, plus late entries. Dates default to today.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Start date"),
                "to_date": date_param("End date"),
                "employee": str_param("Employee name filter (partial)."),
                "department": str_param("Department filter (partial)."),
                "group_by": str_param("Grouping.", ["employee", "day", "department"]),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_attendance_summary,
    ),
    Tool(
        name="list_leave_applications",
        description="List leave applications (pending/approved/rejected) with employee, leave type, dates and days.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Period start (leave overlapping the period)"),
                "to_date": date_param("Period end"),
                "employee": str_param("Employee name filter (partial)."),
                "status": str_param("Status filter.", ["Open", "Approved", "Rejected", "Cancelled"]),
                "leave_type": str_param("Leave type filter (partial)."),
                "limit": int_param("Max rows.", 50),
            },
        },
        handler=list_leave_applications,
    ),
    Tool(
        name="get_leave_balance",
        description="Leave balance per employee and leave type: allocated, taken (approved) and remaining.",
        parameters={"type": "object", "properties": {"employee": str_param("Employee name filter (partial)."), "leave_type": str_param("Leave type filter."), "limit": int_param("Max rows.", 100)}},
        handler=get_leave_balance,
    ),
    Tool(
        name="list_holidays",
        description="Holidays from the company's holiday lists, optionally within a date range.",
        parameters={"type": "object", "properties": {"holiday_list": str_param("Holiday list name (partial)."), "from_date": date_param("Start date"), "to_date": date_param("End date"), "limit": int_param("Max rows.", 100)}},
        handler=list_holidays,
    ),
    Tool(
        name="get_salary_register",
        description="CONFIDENTIAL: salary slips for a period with gross pay, deductions and net pay, per employee, department or month. Only for HR users.",
        parameters={
            "type": "object",
            "properties": {
                "from_date": date_param("Period start"),
                "to_date": date_param("Period end"),
                "employee": str_param("Employee name filter (partial)."),
                "department": str_param("Department filter (partial)."),
                "group_by": str_param("Grouping.", ["employee", "department", "month"]),
                "limit": int_param("Max rows.", 50),
            },
            "required": ["from_date", "to_date"],
        },
        handler=get_salary_register,
    ),
]
