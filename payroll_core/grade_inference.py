"""Evidence-based grade inference for schedule records.

This module deliberately knows nothing about Excel layouts or local storage.
It receives dated, structured evidence from earlier *normal* lessons and
returns either a reproducible conclusion or an explicit request for input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar
from typing import Iterable


NATURAL_GRADE_LADDER = (
    "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
    "七年级", "八年级", "九年级", "高一", "高二", "高三",
)


@dataclass(frozen=True)
class StudentGradeEvidence:
    """One dated, auditable statement of a student's grade.

    ``source_hash`` and the source coordinate let the application explain an
    automatic conclusion without retaining a copy of the original workbook.
    """

    student: str
    lesson_date: str
    grade: str
    source_file: str = ""
    source_hash: str = ""
    sheet: str = ""
    coordinate: str = ""
    origin: str = "HISTORICAL_SCHEDULE"
    confirmed_by: str = ""
    note: str = ""


@dataclass(frozen=True)
class GradeInference:
    grade: str = ""
    status: str = "NEEDS_INPUT"
    reason: str = ""
    evidence: tuple[StudentGradeEvidence, ...] = ()


def infer_historical_grade(
    student: str,
    target_period: str,
    evidence: Iterable[StudentGradeEvidence],
) -> GradeInference:
    """Infer a grade only when every usable historical statement agrees.

    The payroll month, rather than today's date or a later export title,
    provides the target date.  A promotion occurs only when crossing 1 Sept.
    """
    target = _period_end(target_period)
    if target is None or not student.strip():
        return GradeInference(reason="缺少学生或核算月份，无法从历史课表推断年级。")

    usable: list[tuple[StudentGradeEvidence, str]] = []
    for item in evidence:
        if item.student.strip() != student.strip():
            continue
        source_day = _parse_date(item.lesson_date)
        if source_day is None or source_day > target or item.grade not in NATURAL_GRADE_LADDER:
            continue
        advanced = _advance_for_boundaries(item.grade, source_day, target)
        if advanced:
            usable.append((item, advanced))
    if not usable:
        return GradeInference(reason="没有找到该学生在此前正常课程中的明确年级证据。")

    conclusions = {grade for _, grade in usable}
    if len(conclusions) != 1:
        return GradeInference(
            reason="历史课表中的年级证据推算后互相冲突，需要人工确认。",
            evidence=tuple(item for item, _ in usable),
        )
    grade = conclusions.pop()
    return GradeInference(
        grade=grade,
        status="DETERMINED",
        reason=f"依据 {len(usable)} 条历史正常课程的发生日期与年级证据自动推断。",
        evidence=tuple(item for item, _ in usable),
    )


def _period_end(period: str) -> date | None:
    try:
        year, month = (int(part) for part in period.split("-", 1))
        if not 1 <= month <= 12:
            return None
    except (TypeError, ValueError):
        return None
    return date(year, month, calendar.monthrange(year, month)[1])


def _parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _advance_for_boundaries(grade: str, source_day: date, target_day: date) -> str:
    index = NATURAL_GRADE_LADDER.index(grade)
    boundaries = 0
    for year in range(source_day.year, target_day.year + 1):
        boundary = date(year, 9, 1)
        if source_day < boundary <= target_day:
            boundaries += 1
    return NATURAL_GRADE_LADDER[min(index + boundaries, len(NATURAL_GRADE_LADDER) - 1)]
