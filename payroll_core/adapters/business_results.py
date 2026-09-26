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
    "student": ("学生", "学生姓名", "学员", "student", "姓名"),
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


def _is_zip_container(path: Path) -> bool:
    """Whether a file is really OOXML, regardless of what its name claims.

    The office renames legacy workbooks to ``.xlsx`` when they save them from
    WPS, so the extension cannot be trusted.  The container magic can.
    """
    try:
        with path.open("rb") as handle:
            return handle.read(2) == b"PK"
    except OSError:
        return False


def _legacy_sheets(source: Path) -> list[tuple[str, list[list[Any]]]]:
    """Read a legacy BIFF workbook so a renamed .xls still works."""
    import xlrd

    book = xlrd.open_workbook(str(source))
    output: list[tuple[str, list[list[Any]]]] = []
    for name in book.sheet_names():
        sheet = book.sheet_by_name(name)
        output.append((name, [list(sheet.row_values(index)) for index in range(sheet.nrows)]))
    return output


def _header_row_index(rows: list[list[Any]]) -> int:
    """Find the header row instead of assuming it is the first one.

    The 客服部 refund workbook carries a title/blank row above its headers.
    """
    aliases = {alias for names in ALIASES.values() for alias in names}
    for index, row in enumerate(rows[:8]):
        labels = {str(value).strip() for value in row if value not in (None, "")}
        if len(labels & aliases) >= 2 or (labels & {"教师"}) or (labels & {"姓名"} and labels & {"人头", "业绩", "退费"}):
            return index
    return 0


def read_business_result(path: str | Path, *, period: str | None = None) -> list[ImportedBusinessResult]:
    """Read a CSV or Excel final-result table with row-level provenance.

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
    # A real .xls whose name ends in .xlsx is common; decide by content.
    use_legacy = not _is_zip_container(source)
    if use_legacy:
        pairs = _legacy_sheets(source)
    else:
        workbook, cached_workbook = load_workbook_pair(source)
        cached_by_title = {sheet.title: sheet for sheet in cached_workbook.worksheets}
        pairs = [
            (sheet.title, _sheet_rows(sheet, cached_by_title.get(sheet.title)))
            for sheet in workbook.worksheets
        ]
        for opened in (workbook, cached_workbook):
            if hasattr(opened, "close"):
                opened.close()

    def month_sheet(title: str, month: int) -> bool:
        # "8月", "08月", "8月份 " and "2026-08" all mean the same month.
        cleaned = title.strip()
        return cleaned in {f"{month}月", f"{int(month):02d}月", f"{month}月份", f"{int(month):02d}月份"}

    records: list[ImportedBusinessResult] = []
    if period and len(period) == 7 and period[4] == "-":
        month = int(period[5:])
        selected = [(title, rows) for title, rows in pairs if month_sheet(title, month) or title.strip() == period]
        if selected:
            pairs = selected
    for title, values in pairs:
        if not values:
            continue
        header_index = _header_row_index(values)
        headers = [str(value).strip() if value is not None else "" for value in values[header_index]]
        # The production renewal workbook uses grouped two-row headers.  Give
        # the three subtotal columns stable semantic names without changing
        # the generic one-row importer contract.
        if headers[:3] == ["序号", "学科组", "教师"] and header_index + 1 < len(values):
            group_headers = list(headers)
            second = values[header_index + 1]
            for index, name in ((8, "1V1合计"), (24, "班课合计"), (28, "小班领航合计"), (29, "总计")):
                if index < len(group_headers) and not group_headers[index] and index < len(second) and second[index] == "合计":
                    group_headers[index] = name
            headers = group_headers
        mapping = _header_map(headers)
        if not mapping["teacher"]:
            continue
        for offset in range(header_index + 1, len(values)):
            values_row = tuple(values[offset])
            row = {headers[index]: value for index, value in enumerate(values_row) if index < len(headers) and headers[index]}
            if not any(value not in (None, "") for value in row.values()):
                continue
            # Grouped worksheets often end with a totals row.  It is not a
            # teacher result and must not become a synthetic "None" row.
            if mapping["teacher"] and row.get(mapping["teacher"]) in (None, ""):
                continue
            row_number = offset + 1
            teacher, payload = _row_payload(row, mapping)
            records.append(ImportedBusinessResult(
                str(payload.get("teacher_id") or teacher), str(row_number), payload,
                {"source_file": source.name, "sheet": title, "row": str(row_number), "headers": headers, "display_name": teacher},
            ))
    if not records:
        raise ValueError("结果表没有可识别的教师列或有效记录。")
    return records


def _sheet_rows(sheet, cached_sheet=None) -> list[list[Any]]:
    """Raw + cached values, with formula caches substituted where present.

    Final-result workbooks commonly store the monthly totals as formulas.
    Keeping the formula as provenance but reading Excel's cached result is what
    lets a production numeric field be used without recomputing it.
    """
    rows = [[cell.value for cell in row] for row in sheet.iter_rows()]
    if cached_sheet is None:
        return rows
    cached_rows = [[cell.value for cell in row] for row in cached_sheet.iter_rows()]
    output = []
    for index, row in enumerate(rows):
        cached_row = cached_rows[index] if index < len(cached_rows) else ()
        output.append([
            cached_row[position] if position < len(cached_row) and isinstance(value, str) and value.startswith("=") and cached_row[position] is not None else value
            for position, value in enumerate(row)
        ])
    return output
