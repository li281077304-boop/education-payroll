"""Read-only adapter for independent teacher star/rating lists.

The source workbooks used by the campuses are wide tables: a tier label such
as ``三星`` sits above a ``姓名``/``学科`` pair.  This adapter preserves the
cell evidence and emits only explicit ratings; it never infers a tier from a
teacher's role text or from a payroll output.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..models.evidence import AdapterIssue, AdapterResult
from .weekly_report import _load_rows, _text, _sheet_row_number


_STAR_WORDS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6,
}


@dataclass(frozen=True)
class StarRecord:
    period: str
    teacher: str
    rating: int
    source_file: str
    sheet: str
    cell: str
    range: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rating(value: Any) -> int | None:
    text = _text(value).replace(" ", "")
    match = re.fullmatch(r"([一二三四五六1-6])星(?:级)?", text)
    return _STAR_WORDS.get(match.group(1)) if match else None


def _column_letter(number: int) -> str:
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output or "A"


def read_star_report(path: str | Path, period: str) -> AdapterResult[StarRecord]:
    source = Path(path).expanduser().resolve()
    result: AdapterResult[StarRecord] = AdapterResult()
    try:
        rows = _load_rows(source)
    except (OSError, ValueError) as exc:
        result.errors.append(AdapterIssue("UNREADABLE_STAR", str(exc)))
        return result

    found = False
    processed_sheets: set[str] = set()
    for header_index, (sheet, row) in enumerate(rows):
        if sheet in processed_sheets:
            continue
        tiers = {index: _rating(value) for index, value in enumerate(row)}
        tiers = {index: rating for index, rating in tiers.items() if rating is not None}
        if not tiers:
            continue
        # The row immediately below a tier header identifies the name column;
        # accepting a missing 学科 column keeps the adapter compatible with
        # narrower campus lists while still requiring explicit 姓名 labels.
        if header_index + 1 >= len(rows) or rows[header_index + 1][0] != sheet:
            continue
        labels = [_text(value).replace(" ", "") for value in rows[header_index + 1][1]]
        name_columns = {index for index, value in enumerate(labels) if value in {"姓名", "教师", "教师姓名"}}
        if not name_columns:
            continue
        found = True
        processed_sheets.add(sheet)
        for absolute_index, (row_sheet, values) in enumerate(rows[header_index + 2:], start=header_index + 2):
            if row_sheet != sheet:
                continue
            row_number = _sheet_row_number(rows, absolute_index, sheet)
            for column, rating in tiers.items():
                if column not in name_columns or column >= len(values):
                    continue
                teacher = _text(values[column])
                if not teacher or teacher in {"姓名", "教师", "合计", "总计"}:
                    continue
                subject = _text(values[column + 1]) if column + 1 < len(values) else ""
                result.records.append(StarRecord(
                    period=period, teacher=teacher, rating=rating,
                    source_file=source.name, sheet=sheet,
                    cell=f"{sheet}!{_column_letter(column + 1)}{row_number}",
                    range=f"{sheet}!{_column_letter(column + 1)}{row_number}:{_column_letter(min(len(values), column + 2))}{row_number}",
                    evidence={"row": row_number, "rating_header": f"{rating}星", "subject": subject, "header_row": header_index + 1},
                ))
        # Continue to the next sheet.  A workbook can contain one independent
        # star table per campus; each sheet is its own source view.
    if not found:
        result.errors.append(AdapterIssue("UNRECOGNIZED_STAR", "没有找到明确的星级标题与姓名列。"))
        return result
    result.coverage = {"records": len(result.records), "teachers": len({item.teacher for item in result.records}), "ratings": len({item.rating for item in result.records})}
    if not result.records:
        result.warnings.append(AdapterIssue("STAR_NO_DATA_ROWS", "找到星级表头，但没有可识别教师数据行。"))
    return result


read_star_excel = read_star_report
