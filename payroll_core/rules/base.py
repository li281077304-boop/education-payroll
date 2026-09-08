from __future__ import annotations

from collections.abc import Iterable

from ..models.records import ScheduleRecord


def schedule_teachers(records: Iterable[ScheduleRecord]) -> set[str]:
    return {record.teacher for record in records if record.teacher}


def sum_one_to_one(records: Iterable[ScheduleRecord], teacher: str) -> float:
    return float(sum(1 for record in records if record.teacher == teacher and record.class_type == "1对1"))


def sum_class_value(records: Iterable[ScheduleRecord], teacher: str) -> float:
    """Stable core primitive: a caller supplies the authoritative value per row later."""
    return float(sum(record.attended for record in records if record.teacher == teacher and record.class_type != "1对1"))
