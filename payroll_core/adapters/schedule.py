from __future__ import annotations

from pathlib import Path
from datetime import date
import re

from ..models.records import ScheduleRecord
from ..models.evidence import AdapterIssue, AdapterResult
from ._csv import required_int, rows


def _lesson_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.search(r"(?P<year>20\d{2})[-/.年](?P<month>\d{1,2})[-/.月](?P<day>\d{1,2})日?", text)
    if match:
        try:
            return date(int(match.group("year")), int(match.group("month")), int(match.group("day"))).isoformat()
        except ValueError:
            return ""
    return ""


def read_schedule_csv_result(
    path: str | Path,
    period: str,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> AdapterResult[ScheduleRecord]:
    result: AdapterResult[ScheduleRecord] = AdapterResult()
    records: list[ScheduleRecord] = []
    all_dates: list[str] = []
    outside_period = 0
    unparseable_attended = 0
    total_rows = 0
    for row in rows(path):
        total_rows += 1
        lesson_time = (row.get("lesson_time") or row.get("time") or "").strip()
        raw_date = row.get("lesson_date") or lesson_time
        lesson_date = _lesson_date(raw_date)
        status = row.get("lesson_status", "").strip()
        attended = required_int(row.get("attended"), "attended")
        if lesson_date:
            all_dates.append(lesson_date)
        elif status == "已上课" and attended > 0:
            # A date-less attended row must never be relabelled as belonging
            # to the current Run period.  Keep it out of Core entirely.
            unparseable_attended += 1
            continue
        if lesson_date and period_start and period_end and not (period_start <= lesson_date <= period_end):
            outside_period += 1
            continue
        if lesson_date and not period_start and not period_end and period and not lesson_date.startswith(period):
            outside_period += 1
            continue
        records.append(
        ScheduleRecord(
            period=period,
            teacher=row["teacher"].strip(),
            grade=row["grade"].strip(),
            subject=row["subject"].strip(),
            class_type=row["class_type"].strip(),
            attended=attended,
            lesson_status=status,
            student=row.get("student", "").strip(),
            lesson_time=lesson_time,
            lesson_date=lesson_date,
            source=str(path),
        )
        )
    if unparseable_attended:
        result.warnings.append(AdapterIssue(
            "UNPARSEABLE_LESSON_DATE",
            f"有 {unparseable_attended} 条已上课记录无法识别上课日期，已排除。",
            "CSV", "lesson_date",
        ))
    if outside_period:
        result.warnings.append(AdapterIssue(
            "OUT_OF_PERIOD_ROWS_EXCLUDED",
            f"有 {outside_period} 条排课记录不属于工资月份 {period}，已排除。",
            "CSV", "lesson_date",
        ))
    result.records = records
    result.coverage = {
        "records": len(records),
        "source_rows": total_rows,
        "all_lesson_dates": tuple(all_dates),
        "unparseable_attended": unparseable_attended,
        "outside_period": outside_period,
    }
    return result


def read_schedule_csv(
    path: str | Path,
    period: str,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[ScheduleRecord]:
    """Backward-compatible list API over the evidence-preserving adapter."""
    return read_schedule_csv_result(path, period, period_start=period_start, period_end=period_end).records
