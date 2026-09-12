"""Generate the unified payroll workbook from merged internal data.

The output is written cell by cell from the standard model. It is never a copy
of an uploaded workbook, so every published value is traceable to a merged,
canonical submission rather than to a pasted range.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from ..final_fields import FINAL_FIELD_CODES, FIELD_NOTES, HUMAN_REQUIRED
from ..models.payroll_submission import NUMERIC_FIELDS

HEADERS: tuple[str, ...] = ("教师", "一对一折算", "班课折算", "课时生产", "AE", "AF", "AV")


def write_standard_workbook(
    merged: Mapping[str, Mapping[str, Any]],
    period: str,
    output: str | Path,
    *,
    title: str = "标准工资表",
) -> str:
    """Write a reviewed submission snapshot without claiming final payroll.

    This is the legacy teacher-sheet merge workflow, not the Core generation
    entry.  Its compatibility table keeps the historical row layout, but AV is
    deliberately blank and every downstream field is exposed as
    ``HUMAN_REQUIRED`` until an independent Core result is available.
    """
    target = Path(output)
    if target.exists():
        raise ValueError(f"输出文件已存在，不能覆盖：{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)

    if not merged:
        raise ValueError("没有可合并的教师记录，不能创建空的提交快照。")
    teachers = sorted(str(teacher) for teacher in merged)
    if len(teachers) != len(set(teachers)):
        raise ValueError("教师记录不能重复。")
    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append([f"{period} 工资表提交合并快照（未完成 Core 最终工资计算）"])
    sheet["A1"].font = Font(bold=True)
    headers = list(HEADERS) + ["状态", "待确认原因"] + list(FINAL_FIELD_CODES)
    sheet.append(headers)
    for column in range(1, len(headers) + 1):
        sheet.cell(2, column).font = Font(bold=True)

    reason = "提交表合并结果不是独立工资计算；缺少 Core 结果和最终字段权威来源，AV 不写入。"
    for teacher in teachers:
        values = merged[teacher]
        row: list[Any] = [teacher]
        for field in NUMERIC_FIELDS:
            value = values.get(field)
            row.append(round(float(value), 4) if isinstance(value, (int, float)) and not isinstance(value, bool) else None)
        row[6] = None  # Submitted AV is a target, never a Core authority.
        sheet.append(row + ["待确认", reason] + [HUMAN_REQUIRED for _ in FINAL_FIELD_CODES])

    boundary = book.create_sheet("外围字段状态")
    boundary.append(["提交快照的外围字段状态"])
    boundary.append(["本页不是最终工资结果；所有 AF 之后的最终字段需回到独立 Core/业务来源。"])
    boundary.append(["字段", "状态", "缺失依据"])
    for column in range(1, 4):
        boundary.cell(3, column).font = Font(bold=True)
    for code in FINAL_FIELD_CODES:
        boundary.append([code, HUMAN_REQUIRED, FIELD_NOTES.get(code, "缺少权威业务依据。")])

    book.save(target)
    validation = validate_standard_workbook(target, merged, period, title=title)
    if not validation["ok"]:
        raise ValueError("生成的提交合并快照校验失败：" + "；".join(validation["errors"]))
    return str(target.resolve())


def validate_standard_workbook(path: str | Path, merged: Mapping[str, Mapping[str, Any]], period: str, *, title: str = "标准工资表") -> dict[str, Any]:
    """Re-open the compatibility snapshot and reject target-value leakage."""
    errors: list[str] = []
    book = load_workbook(path, data_only=False, read_only=False, keep_links=True)
    if title not in book.sheetnames:
        errors.append(f"缺少工作表：{title}")
        return {"ok": False, "errors": errors, "rows_checked": 0, "path": str(Path(path).resolve())}
    sheet = book[title]
    expected_headers = list(HEADERS) + ["状态", "待确认原因"] + list(FINAL_FIELD_CODES)
    actual_headers = [sheet.cell(2, column).value for column in range(1, len(expected_headers) + 1)]
    if actual_headers != expected_headers or sheet.max_column != len(expected_headers):
        errors.append("提交合并快照表头或列数发生变化")
    expected_teachers = sorted(str(teacher) for teacher in merged)
    if sheet.max_row != len(expected_teachers) + 2:
        errors.append("提交合并快照教师行数发生变化")
    for index, teacher in enumerate(expected_teachers, start=3):
        if sheet.cell(index, 1).value != teacher:
            errors.append(f"第 {index} 行教师不一致")
        if sheet.cell(index, 7).value not in (None, ""):
            errors.append(f"{teacher} 的提交表 AV 不应写入标准结果")
        if sheet.cell(index, 8).value != "待确认":
            errors.append(f"{teacher} 的状态不一致")
        for row in sheet.iter_rows(min_row=index, max_row=index):
            if any(isinstance(cell.value, str) and cell.value.startswith("=") for cell in row):
                errors.append(f"{teacher} 行不应包含公式")
    if "外围字段状态" not in book.sheetnames:
        errors.append("缺少外围字段状态工作表")
    else:
        boundary = book["外围字段状态"]
        for index, code in enumerate(FINAL_FIELD_CODES, start=4):
            if (boundary.cell(index, 1).value, boundary.cell(index, 2).value) != (code, HUMAN_REQUIRED):
                errors.append(f"外围字段 {code} 状态不一致")
    return {"ok": not errors, "errors": errors, "rows_checked": len(expected_teachers), "path": str(Path(path).resolve())}
