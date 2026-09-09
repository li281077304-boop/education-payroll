from __future__ import annotations

import re
from typing import Any, Iterable

from ..models.evidence import CellValueState, SourceEvidence


CLASS_TYPE_MAP = {"一对一": "1对1", "1对1": "1对1", "集体班": "小班", "一对多": "1对2", "10人班": "小班", "6人班": "小班", "8人班": "小班"}
GRADE_MAP = {"初一": "七年级", "初二": "八年级", "初三": "九年级"}
BRIDGE_GRADE_MAP = {"小升初": "六年级", "小初衔接": "六年级", "初升高": "九年级", "七升八": "七年级", "八升九": "八年级", "幼小衔接": "一年级"}
GRADE_TOKENS = ("高三", "高二", "高一", "初三", "初二", "初一", "九年级", "八年级", "七年级", "六年级", "五年级", "四年级", "三年级", "二年级", "一年级", "雅思", "托福")


def find_header_row(sheet, required: set[str], max_rows: int = 12) -> int | None:
    for row in range(1, min(max_rows, sheet.max_row) + 1):
        values = {clean_header(sheet.cell(row, column).value) for column in range(1, sheet.max_column + 1)}
        if required.issubset(values):
            return row
    return None


def header_map(sheet, rows: Iterable[int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        for column in range(1, sheet.max_column + 1):
            value = clean_header(sheet.cell(row, column).value)
            if value and value not in result:
                result[value] = column
    return result


def clean_header(value: Any) -> str:
    return "" if value is None else str(value).strip().replace("\n", " ")


def cell_evidence(raw_sheet, cached_sheet, row: int, column: int, source_file: str, source_field: str) -> SourceEvidence:
    raw_cell = raw_sheet.cell(row, column)
    cached_value = cached_sheet.cell(row, column).value
    raw_value = raw_cell.value
    if isinstance(raw_value, str) and raw_value.startswith("="):
        if "[" in raw_value:
            state = CellValueState.EXTERNAL_REFERENCE
            normalized = None
        elif cached_value is None:
            state = CellValueState.MISSING_CACHE
            normalized = None
        else:
            state = CellValueState.CACHED_VALUE
            normalized = cached_value
    else:
        state = CellValueState.RAW_VALUE
        normalized = raw_value
    return SourceEvidence(
        source_file=source_file,
        sheet=raw_sheet.title,
        coordinate=raw_cell.coordinate,
        source_field=source_field,
        raw_value=raw_value,
        normalized_value=normalized,
        state=state,
    )


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def normalize_class_type(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return CLASS_TYPE_MAP.get(text, text)


def grade_from_class_name(value: Any) -> str:
    text = "" if value is None else str(value)
    if "领航" in text:
        return "领航伴学"
    for keyword, grade in BRIDGE_GRADE_MAP.items():
        if keyword in text:
            return grade
    for token in GRADE_TOKENS:
        if token in text:
            return GRADE_MAP.get(token, token)
    return ""


def subject_from_source(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return re.sub(r"^\d+-", "", text)


def date_from_time(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", "" if value is None else str(value))
    return match.group(0) if match else ""
