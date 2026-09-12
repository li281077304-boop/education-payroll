"""Read-only renewal adapter.

The uploaded rate is retained as a reconciliation value only.  The canonical
rate is always computed from the canonical count and student total.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..models.evidence import AdapterIssue, AdapterResult
from .weekly_report import _excel_col, _find_header as _find_weekly_header, _is_summary_teacher, _load_rows, _number, _text, _column, _sheet_row_number


@dataclass(frozen=True)
class RenewalReportRecord:
    period: str
    campus: str
    group: str
    teacher: str
    renewal_count: float | None
    total_students: float | None
    renewal_rate: float | None
    source_file: str
    sheet: str
    cell: str
    range: str
    evidence: dict[str, Any] = field(default_factory=dict)
    uploaded_renewal_rate: float | None = None
    rate_difference: float | None = None
    status: str = "READ"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _find_header(rows: list[tuple[str, list[Any]]]) -> tuple[int, str, list[str]] | None:
    for index, (sheet, row) in enumerate(rows):
        headers = [_text(value) for value in row]
        joined = " ".join(headers).replace(" ", "")
        exact_teacher = any(value.replace(" ", "") in {"教师", "教师姓名", "姓名", "任课老师"} for value in headers)
        if "续费" in joined and exact_teacher:
            return index, sheet, headers
    return None


def read_renewal_report(path: str | Path, period: str) -> AdapterResult[RenewalReportRecord]:
    source = Path(path).expanduser().resolve()
    result: AdapterResult[RenewalReportRecord] = AdapterResult()
    try:
        if source.suffix.lower() == ".csv":
            import csv
            with source.open(encoding="utf-8-sig", newline="") as handle:
                rows = [("CSV", list(row.values())) for row in csv.DictReader(handle)]
            headers = list(next(iter(csv.DictReader(source.open(encoding="utf-8-sig", newline=""))), {}).keys()) if source.exists() else []
            found = (0, "CSV", headers) if headers else None
        else:
            rows = _load_rows(source)
            found = _find_weekly_header(rows) or _find_header(rows)
    except (OSError, ValueError) as exc:
        result.errors.append(AdapterIssue("UNREADABLE_RENEWAL_REPORT", str(exc)))
        return result
    if found is None:
        result.errors.append(AdapterIssue("UNRECOGNIZED_RENEWAL_REPORT", "没有找到含教师与续费字段的续费表。"))
        return result
    header_index, sheet, headers = found
    teacher_col = next((index for index, value in enumerate(headers) if value.replace(" ", "") in {"教师", "教师姓名", "姓名", "任课老师"}), None)
    count_col = _column(headers, "续费人头", "续费人数", "续费人次", "续费数", "续费")
    total_col = _column(headers, "总学生数", "总学员数", "单科总数", "总人数", "学生数")
    one_to_one_col = _column(headers, "一对一生数", "一对一学生", "1对1学生", "1V1生数")
    class_students_col = _column(headers, "班课生数", "班课学生", "小班生数")
    rate_col = _column(headers, "续费率", "续费人次率", "续推人数率", "续费率（上传）")
    if teacher_col is None or count_col is None:
        result.errors.append(AdapterIssue("RENEWAL_REQUIRED_FIELD_MISSING", "续费表缺少教师或续费人数/人次字段。", sheet=sheet))
        return result
    title = " ".join(_text(value) for row_sheet, row in rows[max(0, header_index - 3):header_index] if row_sheet == sheet for value in row if value not in (None, ""))
    title = f"{title} {source.stem}"
    group = next((token for token in ("数学组", "理化组", "英语组", "综合组") if token in title), "")
    campus = next((token for token in ("宣城一校", "宣城二校", "宣城三校") if token in title), "")
    iterable = rows[header_index + 1:] if source.suffix.lower() != ".csv" else rows
    for offset, (row_sheet, row) in enumerate(iterable, start=header_index + 1):
        if source.suffix.lower() != ".csv" and row_sheet != sheet:
            continue
        row_number = offset + 1 if source.suffix.lower() == ".csv" else _sheet_row_number(rows, offset, sheet)
        if teacher_col >= len(row):
            continue
        teacher = _text(row[teacher_col])
        if not teacher or _is_summary_teacher(teacher):
            continue
        count = _number(row[count_col]) if count_col < len(row) else None
        reported_total = _number(row[total_col]) if total_col is not None and total_col < len(row) else None
        one_to_one = _number(row[one_to_one_col]) if one_to_one_col is not None and one_to_one_col < len(row) else None
        class_students = _number(row[class_students_col]) if class_students_col is not None and class_students_col < len(row) else None
        # The canonical population is the same one used by the weekly
        # adapter.  Some legacy reports' “单科总数” column is not the sum of
        # the two student populations, so it is retained only as evidence.
        total = (one_to_one + class_students) if one_to_one is not None and class_students is not None else reported_total
        uploaded = _number(row[rate_col]) if rate_col is not None and rate_col < len(row) else None
        canonical = count / total if count is not None and total not in (None, 0) else None
        difference = canonical - uploaded if canonical is not None and uploaded is not None else None
        status = "RATE_MISMATCH" if difference is not None and abs(difference) > 1e-9 else "READ"
        first = next((index for index, value in enumerate(row) if _text(value)), 0)
        last = max(first, len(row) - 1)
        result.records.append(RenewalReportRecord(
            period=period, campus=campus, group=group, teacher=teacher,
            renewal_count=count, total_students=total, renewal_rate=canonical,
            source_file=source.name, sheet=sheet, cell=f"{sheet}!{_excel_col(teacher_col + 1)}{row_number}",
            range=f"{sheet}!{_excel_col(first + 1)}{row_number}:{_excel_col(last + 1)}{row_number}",
            evidence={"headers": headers, "row": row_number, "canonical_formula": "RENEWAL_COUNT / TOTAL_STUDENTS", "reported_total_students": reported_total, "total_students_formula": "ONE_TO_ONE_STUDENTS + CLASS_STUDENTS" if one_to_one is not None and class_students is not None else "reported_total_students"},
            uploaded_renewal_rate=uploaded, rate_difference=difference, status=status,
        ))
    result.coverage = {"records": len(result.records), "teachers": len(result.records), "canonical_rates": sum(item.renewal_rate is not None for item in result.records)}
    if any(item.status == "RATE_MISMATCH" for item in result.records):
        result.warnings.append(AdapterIssue("RENEWAL_RATE_MISMATCH", "上传续费率与按人数重算的续费率存在差异；已保留两者供核对。", sheet=sheet))
    return result


read_renewal_excel = read_renewal_report
