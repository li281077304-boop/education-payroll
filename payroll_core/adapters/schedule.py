from __future__ import annotations

from pathlib import Path

from ..models.records import ScheduleRecord
from ._csv import required_int, rows


def read_schedule_csv(path: str | Path, period: str) -> list[ScheduleRecord]:
    return [
        ScheduleRecord(
            period=period,
            teacher=row["teacher"].strip(),
            grade=row["grade"].strip(),
            subject=row["subject"].strip(),
            class_type=row["class_type"].strip(),
            attended=required_int(row.get("attended"), "attended"),
            lesson_status=row.get("lesson_status", "").strip(),
            student=row.get("student", "").strip(),
            lesson_time=row.get("time", "").strip(),
            source=str(path),
        )
        for row in rows(path)
    ]
