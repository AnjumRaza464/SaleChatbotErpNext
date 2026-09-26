"""Tool that lets the assistant compute exact figures from an uploaded spreadsheet."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from app.core.errors import ValidationError
from app.files.parser import dataframe_to_records, load_spreadsheets
from app.services.erpnext.tools import Tool, ToolResult, int_param, str_param
from app.storage.db import get_db

_cache: dict[str, dict[str, pd.DataFrame]] = {}


def _frames(file_id: str) -> dict[str, pd.DataFrame]:
    if file_id not in _cache:
        upload = get_db().get_upload(file_id)
        if upload["kind"] not in ("excel", "csv"):
            raise ValidationError("analyze_uploaded_file only works with Excel/CSV uploads.")
        _cache[file_id] = load_spreadsheets(Path(upload["path"]), upload["kind"])
    return _cache[file_id]


def _pick_sheet(frames: dict[str, pd.DataFrame], sheet: str | None) -> tuple[str, pd.DataFrame]:
    if sheet and sheet in frames:
        return sheet, frames[sheet]
    if sheet:
        for name in frames:
            if name.lower() == sheet.lower():
                return name, frames[name]
        raise ValidationError(f"Sheet '{sheet}' not found. Available: {list(frames)}")
    name = next(iter(frames))
    return name, frames[name]


def _col(df: pd.DataFrame, name: str | None, required: bool = True) -> str | None:
    if not name:
        if required:
            raise ValidationError("A column name is required for this operation.")
        return None
    if name in df.columns:
        return name
    lowered = {str(c).lower(): c for c in df.columns}
    if name.lower() in lowered:
        return lowered[name.lower()]
    for c in df.columns:
        if name.lower() in str(c).lower():
            return c
    raise ValidationError(f"Column '{name}' not found. Available: {list(df.columns)}")


def _apply_filter(df: pd.DataFrame, column: str | None, op: str | None, value: Any) -> pd.DataFrame:
    if not column:
        return df
    col = _col(df, column)
    series = df[col]
    op = op or "=="
    if op in ("contains", "like"):
        return df[series.astype(str).str.contains(str(value), case=False, na=False)]
    if pd.api.types.is_numeric_dtype(series):
        try:
            value = float(value)
        except (TypeError, ValueError):
            pass
    ops = {"==": series == value, "=": series == value, "!=": series != value, ">": series > value, "<": series < value, ">=": series >= value, "<=": series <= value}
    if op not in ops:
        raise ValidationError(f"Unsupported operator '{op}'")
    return df[ops[op]]


async def analyze_uploaded_file(
    client: Any,
    file_id: str,
    operation: str = "describe",
    sheet: str | None = None,
    column: str | None = None,
    group_by: str | None = None,
    aggregate: str = "sum",
    filter_column: str | None = None,
    filter_operator: str | None = None,
    filter_value: Any = None,
    limit: int = 20,
    ascending: bool = False,
) -> ToolResult:
    frames = _frames(file_id)
    sheet_name, df = _pick_sheet(frames, sheet)
    df = _apply_filter(df, filter_column, filter_operator, filter_value)
    limit = max(1, min(int(limit or 20), 500))
    title = f"{sheet_name}: {operation}"

    if operation == "describe":
        numeric = df.select_dtypes(include="number")
        rows = []
        for c in df.columns:
            info: dict[str, Any] = {"column": c, "dtype": str(df[c].dtype), "non_null": int(df[c].notna().sum()), "unique": int(df[c].nunique())}
            if c in numeric.columns:
                info.update({"sum": round(float(numeric[c].sum()), 2), "mean": round(float(numeric[c].mean()), 2), "min": round(float(numeric[c].min()), 2), "max": round(float(numeric[c].max()), 2)})
            rows.append(info)
        return ToolResult(rows=rows, summary={"sheet": sheet_name, "rows": len(df), "columns": len(df.columns), "sheets": list(frames)}, title=title)

    if operation == "groupby":
        if not group_by:
            raise ValidationError("group_by is required for groupby")
        keys = [_col(df, k.strip()) for k in group_by.split(",")]
        if column:
            target = _col(df, column)
            func = aggregate if aggregate in ("sum", "mean", "count", "min", "max", "median") else "sum"
            grouped = df.groupby(keys, dropna=False)[target].agg(func).reset_index().rename(columns={target: f"{func}_{target}"})
            sort_col = f"{func}_{target}"
        else:
            grouped = df.groupby(keys, dropna=False).size().reset_index(name="count")
            sort_col = "count"
        grouped = grouped.sort_values(sort_col, ascending=ascending).head(limit)
        total = float(grouped[sort_col].sum()) if pd.api.types.is_numeric_dtype(grouped[sort_col]) else None
        return ToolResult(rows=dataframe_to_records(grouped, limit), summary={"sheet": sheet_name, "groups": int(len(grouped)), "total_of_shown": round(total, 2) if total is not None else None, "rows_considered": len(df)}, title=title)

    if operation == "sort":
        target = _col(df, column)
        out = df.sort_values(target, ascending=ascending).head(limit)
        return ToolResult(rows=dataframe_to_records(out, limit), summary={"sheet": sheet_name, "rows_considered": len(df)}, title=title)

    if operation == "value_counts":
        target = _col(df, column)
        counts = df[target].value_counts(dropna=False).head(limit).reset_index()
        counts.columns = [target, "count"]
        return ToolResult(rows=dataframe_to_records(counts, limit), summary={"sheet": sheet_name, "unique_values": int(df[target].nunique())}, title=title)

    if operation == "rows":
        return ToolResult(rows=dataframe_to_records(df, limit), summary={"sheet": sheet_name, "rows_matching": len(df)}, title=title, truncated=len(df) > limit)

    if operation == "sum":
        numeric = df.select_dtypes(include="number")
        target_cols = [_col(df, column)] if column else list(numeric.columns)
        summary = {c: round(float(pd.to_numeric(df[c], errors="coerce").sum()), 2) for c in target_cols}
        summary.update({"sheet": sheet_name, "rows_considered": len(df)})
        return ToolResult(summary=summary, title=title)

    raise ValidationError("operation must be one of describe, groupby, sort, value_counts, rows, sum")


TOOLS: list[Tool] = [
    Tool(
        name="analyze_uploaded_file",
        description=(
            "Compute exact numbers from an uploaded Excel/CSV file (by file_id from the conversation). Operations: "
            "describe (columns & stats), groupby (totals per category, e.g. sales by branch), sort (top/bottom rows by a column), "
            "value_counts, rows (list rows, optionally filtered), sum (column totals). Supports an optional row filter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "file_id": str_param("The uploaded file id."),
                "operation": str_param("Analysis operation.", ["describe", "groupby", "sort", "value_counts", "rows", "sum"]),
                "sheet": str_param("Sheet name (defaults to first sheet)."),
                "column": str_param("Target column (numeric for groupby/sum, any for sort/value_counts)."),
                "group_by": str_param("Column(s) to group by, comma separated."),
                "aggregate": str_param("Aggregation for groupby.", ["sum", "mean", "count", "min", "max", "median"]),
                "filter_column": str_param("Optional column to filter rows on."),
                "filter_operator": str_param("Filter operator.", ["==", "!=", ">", "<", ">=", "<=", "contains"]),
                "filter_value": {"type": ["string", "number"], "description": "Filter value."},
                "limit": int_param("Max rows returned.", 20),
                "ascending": {"type": "boolean", "description": "Sort ascending (default false = largest first)."},
            },
            "required": ["file_id", "operation"],
        },
        handler=analyze_uploaded_file,
    )
]
