"""Read final upstream renewal/refund results without inventing business rules."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..excel.inspect import load_workbook_pair


@dataclass(frozen=True)
class ImportedBusinessResult:
    teacher_id: str
    row: str
    payload: dict[str, Any]
    evidence: dict[str, Any]


ALIASES = {
    "teacher": ("教师", "老师", "任课老师", "责任教师", "责任老师", "charge_teacher", "teacher"),
    "teacher_id": ("teacher_id", "教师ID", "教师编号", "工号", "员工编号", "teacher id"),
    "student": ("学生", "学生姓名", "学员", "student"),
    "amount": ("退费金额", "金额", "退款金额", "amount", "headcount_amount", "performance_amount"),
    "note": ("说明", "备注", "退费原因", "备注说明", "note"),
}


def _header_map(headers: list[str]) -> dict[str, str]:
    normalized = {str(item).strip(): str(item).strip() for item in headers if item is not None and str(item).strip()}
    output: dict[str, str] = {}
    for name, aliases in ALIASES.items():
        output[name] = next((normalized[alias] for alias in aliases if alias in normalized), "")
    return output


def _row_payload(row: dict[str, Any], mapping: dict[str, str]) -> tuple[str, dict[str, Any]]:
    raw_teacher = row.get(mapping["teacher"]) if mapping["teacher"] else None
    teacher = str(raw_teacher).strip() if raw_teacher is not None else ""
    if not teacher or teacher.lower() in {"none", "nan"}:
        raise ValueError("结果表缺少可识别的教师列或教师值。")
    payload = {str(key): value for key, value in row.items() if key is not None and value not in (None, "")}
    payload["teacher"] = teacher
    if mapping.get("teacher_id") and row.get(mapping["teacher_id"]) not in (None, ""):
        payload["teacher_id"] = str(row[mapping["teacher_id"]]).strip()
    for key in ("student", "amount", "note"):
        if mapping[key] and mapping[key] in row:
            payload[key] = row[mapping[key]]
    return teacher, payload


def read_business_result(path: str | Path, *, period: str | None = None) -> list[ImportedBusinessResult]:
    """Read a CSV or simple Excel final-result table with row-level provenance.

    The importer preserves all supplied columns in payload. It only identifies
    the teacher needed to bind a result; it does not decide eligibility.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return []
        mapping = _header_map(list(rows[0]))
        output: list[ImportedBusinessResult] = []
        for index, row in enumerate(rows, start=2):
            teacher, payload = _row_payload(row, mapping)
            output.append(ImportedBusinessResult(
                teacher_id=str(payload.get("teacher_id") or teacher), row=str(index), payload=payload,
                evidence={"source_file": source.name, "sheet": "CSV", "row": str(index), "headers": list(row), "display_name": teacher},
            ))
        return output
    if suffix not in {".xlsx", ".xlsm", ".xls"}:
        raise ValueError("目前只支持 CSV、.xlsx、.xlsm 或 .xls 的最终结果表。")
    workbook, cached_workbook = load_workbook_pair(source)

    def rows_for(sheet):
        return [[cell.value for cell in row] for row in sheet.iter_rows()]

    records: list[ImportedBusinessResult] = []
    sheets = list(workbook.worksheets)
    cached_sheets = {sheet.title: sheet for sheet in cached_workbook.worksheets}
    if period and len(period) == 7 and period[4] == "-":
        month = str(int(period[5:]))
        candidates = {f"{month}月", f"{int(month):02d}月", period}
        selected = [sheet for sheet in sheets if sheet.title.strip() in candidates]
        if selected:
            sheets = selected
    for sheet in sheets:
        values = rows_for(sheet)
        if not values:
            continue
        cached_values = rows_for(cached_sheets.get(sheet.title, sheet))
        headers = [str(value).strip() if value is not None else "" for value in values[0]]
        # The production renewal workbook uses grouped two-row headers.  Give
        # the three subtotal columns stable semantic names without changing
        # the generic one-row importer contract.
        if len(values) > 1 and headers[:3] == ["序号", "学科组", "教师"]:
            group_headers = list(headers)
            second = values[1]
            for index, name in ((8, "1V1合计"), (24, "班课合计"), (28, "小班领航合计"), (29, "总计")):
                if index < len(group_headers) and not group_headers[index] and index < len(second) and second[index] == "合计":
                    group_headers[index] = name
            headers = group_headers
        mapping = _header_map(headers)
        if not mapping["teacher"]:
            continue
        for row_number, values_row in enumerate(values[1:], start=2):
            cached_row = cached_values[row_number - 1] if row_number - 1 < len(cached_values) else ()
            # Final-result workbooks commonly store the monthly totals as
            # formulas.  Keep formula provenance in the workbook itself, but
            # use Excel's cached result for production numeric fields.
            values_row = tuple(
                cached_row[index] if index < len(cached_row) and isinstance(value, str) and value.startswith("=") and cached_row[index] is not None else value
                for index, value in enumerate(values_row)
            )
            row = {headers[index]: value for index, value in enumerate(values_row) if index < len(headers) and headers[index]}
            if not any(value not in (None, "") for value in row.values()):
                continue
            # Grouped worksheets often end with a totals row.  It is not a
            # teacher result and must not become a synthetic "None" row.
            if mapping["teacher"] and row.get(mapping["teacher"]) in (None, ""):
                continue
            teacher, payload = _row_payload(row, mapping)
            records.append(ImportedBusinessResult(str(payload.get("teacher_id") or teacher), str(row_number), payload, {"source_file": source.name, "sheet": sheet.title, "row": str(row_number), "headers": headers, "display_name": teacher}))
    if not records:
        raise ValueError("结果表没有可识别的教师列或有效记录。")
    for opened in (workbook, cached_workbook):
        if hasattr(opened, "close"):
            opened.close()
    return records
