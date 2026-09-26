"""Helpers shared by ERPNext modules (date handling, grouped aggregation)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from app.core.errors import ValidationError
from app.services.erpnext.client import ERPNextClient
from app.services.erpnext.context import get_site_context

MONEY_FIELDS = {"total", "net", "amount", "grand_total", "net_total", "outstanding", "value", "rate"}


def parse_date(value: str | None, field: str) -> date | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValidationError(f"{field} must be in YYYY-MM-DD format, got '{value}'") from exc


def resolve_period(from_date: str | None, to_date: str | None) -> tuple[date, date]:
    """Default to today when no dates were provided, and make the range sane."""
    today = get_site_context().now().date()
    start = parse_date(from_date, "from_date") or (parse_date(to_date, "to_date") or today)
    end = parse_date(to_date, "to_date") or start
    if end < start:
        start, end = end, start
    if (end - start) > timedelta(days=366 * 3):
        raise ValidationError("Date range too large. Please limit the period to three years.")
    return start, end


def date_filters(doctype: str, start: date, end: date, field: str = "posting_date") -> list[list[Any]]:
    return [
        [doctype, field, ">=", start.isoformat()],
        [doctype, field, "<=", end.isoformat()],
    ]


def month_key(value: Any) -> str:
    return str(value)[:7]


def add_share(rows: list[dict[str, Any]], amount_key: str = "total") -> None:
    total = sum(float(r.get(amount_key) or 0) for r in rows)
    for r in rows:
        r["share_pct"] = round(float(r.get(amount_key) or 0) / total * 100, 1) if total else 0.0


def finalize(df: pd.DataFrame, keys: list[str], sort_key: str, top_n: int | None, ascending: bool = False) -> list[dict[str, Any]]:
    if df.empty:
        return []
    numeric = [c for c in df.columns if c not in keys]
    grouped = df.groupby(keys, dropna=False, as_index=False)[numeric].sum()
    grouped = grouped.sort_values(sort_key, ascending=ascending, kind="stable")
    if top_n:
        grouped = grouped.head(top_n)
    out: list[dict[str, Any]] = []
    for rec in grouped.to_dict(orient="records"):
        clean: dict[str, Any] = {}
        for k, v in rec.items():
            if isinstance(v, float):
                v = round(v, 2)
            if pd.isna(v) if not isinstance(v, (list, dict)) else False:
                v = None
            clean[k] = v
        out.append(clean)
    return out


async def grouped_invoice_totals(
    client: ERPNextClient,
    sources: list[tuple[str, str, list[list[Any]]]],
    group_by: str,
    start: date,
    end: date,
    extra_filters: list[list[Any]] | None = None,
    top_n: int | None = 20,
    amount_field: str = "grand_total",
    party_field: str = "customer",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate invoice totals across one or more invoice doctypes.

    ``sources`` is a list of ``(parent_doctype, child_doctype, base_filters)``.
    ``group_by`` is one of: none, day, month, item, item_group, party,
    cost_center, pos_profile, warehouse, brand.
    """
    frames: list[pd.DataFrame] = []
    for doctype, child, base_filters in sources:
        filters = [[doctype, *f] if len(f) == 3 else f for f in base_filters]
        filters += date_filters(doctype, start, end)
        for f in extra_filters or []:
            filters.append([doctype, *f] if len(f) == 3 else f)

        if group_by in ("item", "item_group", "brand"):
            ct = f"`tab{child}`"
            if group_by == "item":
                keys = ["item_code", "item_name"]
                fields = [f"{ct}.item_code as item_code", f"{ct}.item_name as item_name"]
                gb = f"{ct}.item_code"
            else:
                keys = [group_by]
                fields = [f"{ct}.{group_by} as {group_by}"]
                gb = f"{ct}.{group_by}"
            fields += [f"sum({ct}.qty) as qty", f"sum({ct}.amount) as total", f"count(distinct `tab{doctype}`.name) as invoices"]
            rows = await client.get_list(doctype, fields, filters, group_by=gb, limit=5000)
        else:
            key_map = {
                "none": None,
                "day": "posting_date",
                "month": "posting_date",
                "party": party_field,
                "cost_center": "cost_center",
                "pos_profile": "pos_profile",
                "warehouse": "set_warehouse",
            }
            if group_by not in key_map:
                raise ValidationError(f"Unsupported group_by '{group_by}'")
            key = key_map[group_by]
            keys = [key] if key else []
            fields = ([f"`tab{doctype}`.{key} as {key}"] if key else []) + [
                f"sum(`tab{doctype}`.{amount_field}) as total",
                f"sum(`tab{doctype}`.net_total) as net",
                f"sum(`tab{doctype}`.total_qty) as qty",
                f"count(`tab{doctype}`.name) as invoices",
            ]
            rows = await client.get_list(doctype, fields, filters, group_by=(f"`tab{doctype}`.{key}" if key else None), limit=5000)
            if group_by == "month":
                for r in rows:
                    r["month"] = month_key(r.pop("posting_date"))
                keys = ["month"]
        if rows:
            frames.append(pd.DataFrame(rows))

    if not frames:
        return [], {"total": 0.0, "invoices": 0, "qty": 0.0}

    df = pd.concat(frames, ignore_index=True)
    for col in ("total", "net", "qty", "invoices"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    totals = {
        "total": round(float(df["total"].sum()), 2),
        "invoices": int(df["invoices"].sum()) if "invoices" in df else 0,
        "qty": round(float(df["qty"].sum()), 2) if "qty" in df else 0.0,
    }
    if "net" in df.columns:
        totals["net"] = round(float(df["net"].sum()), 2)

    if group_by == "none":
        return [], totals

    ascending = group_by in ("day", "month")
    sort_key = keys[0] if ascending else "total"
    rows_out = finalize(df, keys, sort_key, None if ascending else top_n, ascending=ascending)
    if not ascending:
        add_share(rows_out)
    return rows_out, totals


def pct_change(new: float, old: float) -> float | None:
    if not old:
        return None
    return round((new - old) / abs(old) * 100, 1)
