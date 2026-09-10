"""Read final upstream renewal/refund results without inventing business rules."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


@dataclass(frozen=True)
class ImportedBusinessResult:
    teacher_id: str
    row: str
    payload: dict[str, Any]
    evidence: dict[str, Any]


ALIASES = {
    "teacher": ("教师", "老师", "任课老师", "责任教师", "责任老师", "charge_teacher", "teacher"),
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
    teacher = str(row.get(mapping["teacher"], "")).strip() if mapping["teacher"] else ""
    if not teacher:
        raise ValueError("结果表缺少可识别的教师列或教师值。")
    payload = {str(key): value for key, value in row.items() if key is not None and value not in (None, "")}
    payload["teacher"] = teacher
    for key in ("student", "amount", "note"):
        if mapping[key] and mapping[key] in row:
            payload[key] = row[mapping[key]]
    return teacher, payload


def read_business_result(path: str | Path) -> list[ImportedBusinessResult]:
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
        return [
            ImportedBusinessResult(
                teacher_id=(teacher := _row_payload(row, mapping)[0]),
                row=str(index),
                payload=_row_payload(row, mapping)[1],
                evidence={"source_file": source.name, "sheet": "CSV", "row": str(index), "headers": list(row)},
            )
            for index, row in enumerate(rows, start=2)
        ]
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError("目前只支持 CSV、.xlsx 或 .xlsm 的最终结果表。")
    workbook = load_workbook(source, data_only=False, read_only=True, keep_links=True)
    records: list[ImportedBusinessResult] = []
    for sheet in workbook.worksheets:
        values = list(sheet.iter_rows(values_only=True))
        if not values:
            continue
        headers = [str(value).strip() if value is not None else "" for value in values[0]]
        mapping = _header_map(headers)
        if not mapping["teacher"]:
            continue
        for row_number, values_row in enumerate(values[1:], start=2):
            row = {headers[index]: value for index, value in enumerate(values_row) if index < len(headers) and headers[index]}
            if not any(value not in (None, "") for value in row.values()):
                continue
            teacher, payload = _row_payload(row, mapping)
            records.append(ImportedBusinessResult(teacher, str(row_number), payload, {"source_file": source.name, "sheet": sheet.title, "row": str(row_number), "headers": headers}))
    if not records:
        raise ValueError("结果表没有可识别的教师列或有效记录。")
    return records
