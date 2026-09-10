"""Generate the unified payroll workbook from merged internal data.

The output is written cell by cell from the standard model. It is never a copy
of an uploaded workbook, so every published value is traceable to a merged,
canonical submission rather than to a pasted range.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from openpyxl import Workbook
from openpyxl.styles import Font

from ..models.payroll_submission import NUMERIC_FIELDS

HEADERS: tuple[str, ...] = ("教师", "一对一折算", "班课折算", "课时生产", "AE", "AF", "AV")


def write_standard_workbook(
    merged: Mapping[str, Mapping[str, Any]],
    period: str,
    output: str | Path,
    *,
    title: str = "标准工资表",
) -> str:
    """Write one standardized payroll table. Existing files are never replaced."""
    target = Path(output)
    if target.exists():
        raise ValueError(f"输出文件已存在，不能覆盖：{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)

    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append([f"{period} 标准工资表（由标准内部数据模型生成）"])
    sheet["A1"].font = Font(bold=True)
    sheet.append(list(HEADERS))

    for teacher in sorted(merged):
        values = merged[teacher]
        row: list[Any] = [teacher]
        for field in NUMERIC_FIELDS:
            value = values.get(field)
            row.append(round(float(value), 4) if isinstance(value, (int, float)) else None)
        sheet.append(row)

    book.save(target)
    return str(target.resolve())
