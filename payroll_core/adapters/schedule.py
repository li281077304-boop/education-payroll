from __future__ import annotations

from pathlib import Path
from datetime import datetime

from ..models.records import ScheduleRecord
from ._csv import required_int, rows


def _lesson_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text.replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    for candidate in (normalized, normalized.split()[0]):
        try:
            return datetime.fromisoformat(candidate).date().isoformat()
        except ValueError:
            continue
    return ""


def read_schedule_csv(
    path: str | Path,
    period: str,
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> list[ScheduleRecord]:
    records: list[ScheduleRecord] = []
    for row in rows(path):
        lesson_time = (row.get("lesson_time") or row.get("time") or "").strip()
        lesson_date = _lesson_date(row.get("lesson_date") or lesson_time)
        if lesson_date and period_start and period_end and not (period_start <= lesson_date <= period_end):
            continue
        if lesson_date and not period_start and not period_end and period and not lesson_date.startswith(period):
            continue
        records.append(
        ScheduleRecord(
            period=period,
            teacher=row["teacher"].strip(),
            grade=row["grade"].strip(),
            subject=row["subject"].strip(),
            class_type=row["class_type"].strip(),
            attended=required_int(row.get("attended"), "attended"),
            lesson_status=row.get("lesson_status", "").strip(),
            student=row.get("student", "").strip(),
            lesson_time=lesson_time,
            lesson_date=lesson_date,
            source=str(path),
        )
        )
    return records
