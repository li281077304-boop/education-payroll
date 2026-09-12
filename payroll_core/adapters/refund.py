from __future__ import annotations

from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any

from ..models.records import RefundRecord
from ._csv import optional_float, rows
from .weekly_report import _column, _load_rows, _number, _text, _sheet_row_number


def read_refund_csv(path: str | Path, period: str) -> list[RefundRecord]:
    return [
        RefundRecord(
            period=period,
            charge_teacher=row["charge_teacher"].strip(),
            headcount_amount=optional_float(row.get("headcount_amount")),
            performance_amount=optional_float(row.get("performance_amount")),
            source=str(path),
        )
        for row in rows(path)
    ]


@dataclass(frozen=True)
class RefundReportRecord:
    period: str
    teacher: str
    student: str
    date: str
    amount: float | None
    status: str
    reason: str
    group: str
    source_file: str
    sheet: str
    cell: str
    range: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_refund_report(path: str | Path, period: str) -> list[RefundReportRecord]:
    """Identify explicit refund columns without deciding payroll treatment."""
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() == ".csv":
        import csv
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or [])
            rows_data = [("CSV", list(row.values()), row) for row in reader]
        header_index, sheet = 0, "CSV"
    else:
        rows = _load_rows(source)
        found = next((
            (index, sheet, [_text(value) for value in row])
            for index, (sheet, row) in enumerate(rows)
            if _has_refund_header(row)
        ), None)
        if found is None:
            return []
        header_index, sheet, headers = found
        rows_data = [(row_sheet, row, None, absolute_index) for absolute_index, (row_sheet, row) in enumerate(rows[header_index + 1:], start=header_index + 1)]
    # Do not use substring matching for the identity column: headers such as
    # “学科教师离职率” belong to an assessment sheet, not a refund table.
    teacher_col = _exact_column(headers, "扣款教师", "教师", "任课老师", "姓名")
    student_col = _column(headers, "学生", "学员")
    date_col = _column(headers, "日期", "退费日期", "发生日期")
    amount_col = _column(headers, "金额", "退费金额", "扣款金额")
    status_col = _column(headers, "状态", "处理状态")
    reason_col = _column(headers, "原因", "退费原因", "说明")
    group_col = _column(headers, "归属组", "学科组", "组别")
    if teacher_col is None or not any(index is not None for index in (amount_col, status_col, reason_col, date_col)):
        return []
    result: list[RefundReportRecord] = []
    for row_offset, item in enumerate(rows_data, start=header_index + 2):
        if len(item) == 3:
            row_sheet, row, mapping = item
            absolute_index = None
        else:
            row_sheet, row, mapping, absolute_index = item
        if row_sheet != sheet:
            continue
        row_number = row_offset if absolute_index is None else _sheet_row_number(rows, absolute_index, sheet)
        value = mapping if mapping is not None else None
        get = (lambda index: row[index] if index is not None and index < len(row) else None)
        teacher = _text(value.get(headers[teacher_col]) if value is not None else get(teacher_col))
        if not teacher or teacher in {"教师", "合计"}:
            continue
        student = _text(value.get(headers[student_col]) if value is not None and student_col is not None else get(student_col))
        raw_amount = value.get(headers[amount_col]) if value is not None and amount_col is not None else get(amount_col)
        result.append(RefundReportRecord(period, teacher, student, _text(value.get(headers[date_col]) if value is not None and date_col is not None else get(date_col)), _number(raw_amount), _text(value.get(headers[status_col]) if value is not None and status_col is not None else get(status_col)), _text(value.get(headers[reason_col]) if value is not None and reason_col is not None else get(reason_col)), _text(value.get(headers[group_col]) if value is not None and group_col is not None else get(group_col)), source.name, sheet, f"{sheet}!{_column_letter(teacher_col + 1)}{row_number}", f"{sheet}!A{row_number}:{_column_letter(len(headers))}{row_number}", {"headers": headers, "row": row_number}))
    return result


def _normalized(value: Any) -> str:
    return _text(value).replace(" ", "")


def _exact_column(headers: list[str], *names: str) -> int | None:
    targets = {_normalized(name) for name in names}
    return next((index for index, header in enumerate(headers) if _normalized(header) in targets), None)


def _has_refund_header(row: list[Any]) -> bool:
    values = {_normalized(value) for value in row if _text(value)}
    identity = {"扣款教师", "教师", "任课老师", "姓名"}
    refund = {"退费", "退款", "退费日期", "金额", "退费金额", "扣款金额", "状态", "退费原因", "原因"}
    return bool(values & identity) and bool(values & refund)


def _column_letter(number: int) -> str:
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output or "A"
