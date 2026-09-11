"""Evidence-based grade inference for schedule records.

This module deliberately knows nothing about Excel layouts or local storage.
It receives dated, structured evidence from earlier *normal* lessons and
returns either a reproducible conclusion or an explicit request for input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar
from functools import lru_cache
import re
from typing import Iterable


NATURAL_GRADE_LADDER = (
    "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
    "七年级", "八年级", "九年级", "高一", "高二", "高三",
)
ACADEMIC_ADVANCEMENT_MONTH = 9
ACADEMIC_ADVANCEMENT_DAY = 20
EXPORT_TIMESTAMP_PATTERN = re.compile(r"(?P<year>20\d{2})(?P<month>0[1-9]|1[0-2])(?P<day>[0-3]\d)(?P<hour>[0-2]\d)?(?P<minute>[0-5]\d)?")


def split_student_names(value: object) -> tuple[str, ...]:
    """Return the individual students represented by one schedule roster cell.

    Schedule exports commonly put a whole small-class roster in the student
    column.  Grade evidence is stored per student, never against an unstable
    comma-joined roster string.  A single name remains a single-item tuple.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return ()
    return tuple(dict.fromkeys(part.strip() for part in re.split(r"[,，、;；\n]+", text) if part.strip()))


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
    exported_at: str = ""


@dataclass(frozen=True)
class GradeInference:
    grade: str = ""
    status: str = "NEEDS_INPUT"
    reason: str = ""
    evidence: tuple[StudentGradeEvidence, ...] = ()
    ignored_evidence: tuple[StudentGradeEvidence, ...] = ()
    coverage: str = "NONE"
    grades: frozenset[str] = frozenset()


def infer_historical_grade(
    student: str,
    target_period: str,
    evidence: Iterable[StudentGradeEvidence],
    *,
    recent_history_only: bool = True,
    target_date: str = "",
    pollution_checked: bool = False,
    ignored_evidence: Sequence[StudentGradeEvidence] = (),
) -> GradeInference:
    """Infer a grade only when every usable historical statement agrees.

    The actual course date, when available, provides the target date.  The
    payroll month only defines the history window.  A promotion occurs when
    crossing 20 Sept, never when a later export happens to be opened.
    """
    target = _parse_date(target_date) if target_date else _period_end(target_period)
    if target is None or not student.strip():
        return GradeInference(reason="缺少学生或核算月份，无法从历史课表推断年级。")

    # A monthly payroll decision should not be destabilised by a record from a
    # long-completed school year.  The window is inclusive: for 2026-09 it is
    # 2025-09-01 through 2026-09-30.  Human confirmations are deliberately
    # exempt because they are explicit, dated authority facts rather than an
    # automatic historical inference.
    window_start = date(target.year - 1, target.month, 1)
    if pollution_checked:
        cleaned, ignored = tuple(evidence), tuple(ignored_evidence)
    else:
        cleaned, ignored = remove_export_pollution(evidence)
    usable: list[tuple[StudentGradeEvidence, str]] = []
    expired_grade_count = 0
    for item in cleaned:
        if item.student.strip() != student.strip():
            continue
        source_day = _parse_date(item.lesson_date)
        if source_day is None or source_day > target or item.grade not in NATURAL_GRADE_LADDER:
            continue
        if recent_history_only and source_day < window_start:
            continue
        advanced = _advance_for_boundaries(item.grade, source_day, target)
        if advanced is None:
            expired_grade_count += 1
            continue
        usable.append((item, advanced))
    if not usable:
        if expired_grade_count:
            return GradeInference(reason="历史年级跨越后已超出可推断的自然学段，需要人工确认。", ignored_evidence=ignored, coverage="CONFLICT")
        return GradeInference(reason="没有找到该学生在此前正常课程中的明确年级证据。", ignored_evidence=ignored, coverage="NONE")

    conclusions = {grade for _, grade in usable}
    if len(conclusions) != 1:
        return GradeInference(
            reason=("历史课表中的年级证据推算后互相冲突，需要人工确认。" if not ignored else f"已自动忽略 {len(ignored)} 条后续导出造成的班名升级记录；其余历史年级仍互相冲突，需要人工确认。"),
            evidence=tuple(item for item, _ in usable),
            ignored_evidence=ignored,
            coverage="CONFLICT",
        )
    grade = conclusions.pop()
    return GradeInference(
        grade=grade,
        status="DETERMINED",
        reason=(f"依据 {len(usable)} 条历史正常课程的发生日期与年级证据自动推断。" if not ignored else f"依据 {len(usable)} 条历史正常课程推断；已自动忽略 {len(ignored)} 条后续导出造成的班名升级记录。"),
        evidence=tuple(item for item, _ in usable),
        ignored_evidence=ignored,
        coverage="COMPLETE",
        grades=frozenset({grade}),
    )


def evidence_identity(item: StudentGradeEvidence) -> tuple[str, str, str, str, str]:
    return (item.student.strip(), item.lesson_date[:10], item.grade, item.source_hash, item.coordinate)


def _export_day(item: StudentGradeEvidence) -> date | None:
    value = item.exported_at or item.source_file
    match = EXPORT_TIMESTAMP_PATTERN.search(str(value))
    if not match:
        return None
    try:
        return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def remove_export_pollution(evidence: Iterable[StudentGradeEvidence]) -> tuple[tuple[StudentGradeEvidence, ...], tuple[StudentGradeEvidence, ...]]:
    return _remove_export_pollution_cached(tuple(evidence))


@lru_cache(maxsize=16)
def _remove_export_pollution_cached(items: tuple[StudentGradeEvidence, ...]) -> tuple[tuple[StudentGradeEvidence, ...], tuple[StudentGradeEvidence, ...]]:
    """Ignore later-export class-name upgrades for the same old lesson.

    This is intentionally narrow.  A later export can only be treated as
    pollution when the lesson happened before 20 September, the later export
    happened on/after that boundary, and its grade is exactly the next grade
    after the earliest dated export's grade.  Without export timestamps the
    disagreement remains a genuine conflict requiring input.
    """
    items = list(items)
    ignored: set[int] = set()
    grouped: dict[tuple[str, str], list[tuple[int, StudentGradeEvidence]]] = {}
    for index, item in enumerate(items):
        grouped.setdefault((item.student.strip(), item.lesson_date[:10]), []).append((index, item))
    for (_student, lesson_date), group in grouped.items():
        grades = {item.grade for _index, item in group}
        if len(grades) < 2:
            continue
        try:
            lesson_day = date.fromisoformat(lesson_date[:10])
        except ValueError:
            continue
        boundary = date(lesson_day.year, ACADEMIC_ADVANCEMENT_MONTH, ACADEMIC_ADVANCEMENT_DAY)
        if lesson_day >= boundary:
            continue
        dated = [(index, item, _export_day(item)) for index, item in group]
        if any(export_day is None for _index, _item, export_day in dated):
            continue
        dated.sort(key=lambda value: (value[2], value[0]))
        base_index, base_item, base_export = dated[0]
        base_grade_index = NATURAL_GRADE_LADDER.index(base_item.grade) if base_item.grade in NATURAL_GRADE_LADDER else -1
        if base_grade_index < 0:
            continue
        for index, item, export_day in dated[1:]:
            expected_next = NATURAL_GRADE_LADDER[base_grade_index + 1] if base_grade_index + 1 < len(NATURAL_GRADE_LADDER) else ""
            if export_day >= boundary and item.grade == expected_next and item.grade != base_item.grade:
                ignored.add(index)
    return tuple(item for index, item in enumerate(items) if index not in ignored), tuple(item for index, item in enumerate(items) if index in ignored)


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


def _advance_for_boundaries(grade: str, source_day: date, target_day: date) -> str | None:
    index = NATURAL_GRADE_LADDER.index(grade)
    boundaries = 0
    for year in range(source_day.year, target_day.year + 1):
        boundary = date(year, ACADEMIC_ADVANCEMENT_MONTH, ACADEMIC_ADVANCEMENT_DAY)
        if source_day < boundary <= target_day:
            boundaries += 1
    target_index = index + boundaries
    # High-three is not a permanent category.  Once a course has crossed a
    # later academic-year boundary, it provides no K12 conclusion at all.
    if target_index >= len(NATURAL_GRADE_LADDER):
        return None
    return NATURAL_GRADE_LADDER[target_index]
