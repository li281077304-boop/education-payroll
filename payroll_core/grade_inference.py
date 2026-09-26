"""Evidence-based grade inference for schedule records.

This module deliberately knows nothing about Excel layouts or local storage.
It receives dated, structured evidence from earlier *normal* lessons and
returns either a reproducible conclusion or an explicit request for input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import calendar
from functools import lru_cache
import re
from typing import Iterable, Mapping, Sequence


NATURAL_GRADE_LADDER = (
    "一年级", "二年级", "三年级", "四年级", "五年级", "六年级",
    "七年级", "八年级", "九年级", "高一", "高二", "高三",
)
ACADEMIC_ADVANCEMENT_MONTH = 9
ACADEMIC_ADVANCEMENT_DAY = 20
SUMMER_ROLLOVER_MONTH = 8
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
    teacher: str = ""
    subject: str = ""
    lesson_start_time: str = ""
    class_type: str = ""


@dataclass(frozen=True)
class StudentCourseContext:
    """Ephemeral course context used to detect same-name collisions.

    This is intentionally not a student master record.  It only describes a
    student occurrence in an attended course so a clearly overlapping,
    different lesson can be kept out of another occurrence's grade evidence.
    """

    student: str
    lesson_date: str
    lesson_start_time: str
    teacher: str
    subject: str
    class_type: str = ""
    attended: int | None = None
    lesson_status: str = ""
    source_file: str = ""


@dataclass(frozen=True)
class CourseExportSnapshot:
    """One export's view of one scheduled lesson.

    This is deliberately separate from :class:`StudentGradeEvidence`.
    A snapshot describes how a source export named a lesson; it does not claim
    that a student actually attended that lesson or establish a student's
    dated grade fact.
    """

    lesson_date: str
    lesson_start_time: str
    teacher: str
    subject: str
    class_name: str
    parsed_grade: str
    lesson_status: str = ""
    attended: int | None = None
    teaching_form: str = ""
    source_file: str = ""
    source_hash: str = ""
    exported_at: str = ""
    sheet: str = ""
    coordinate: str = ""
    student: str = ""


@dataclass(frozen=True)
class GradeInference:
    grade: str = ""
    status: str = "NEEDS_INPUT"
    reason: str = ""
    evidence: tuple[StudentGradeEvidence, ...] = ()
    ignored_evidence: tuple[StudentGradeEvidence, ...] = ()
    coverage: str = "NONE"
    grades: frozenset[str] = frozenset()


def normalize_lesson_start_time(value: object) -> str:
    """Normalize the actual lesson start clock for stable export matching."""
    match = re.search(r"(?:^|\s)([0-2]?\d):([0-5]\d)", "" if value is None else str(value))
    if not match:
        return ""
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def stable_lesson_key(teacher: object, subject: object, lesson_date: object, lesson_time: object = "") -> tuple[str, str, str, str]:
    """Return the minimum identity shared by two exports of one lesson."""
    def clean(value: object) -> str:
        return re.sub(r"\s+", " ", "" if value is None else str(value).strip()).casefold()

    day = str(lesson_date or "").strip()[:10]
    start = normalize_lesson_start_time(lesson_time)
    return clean(teacher), clean(subject), day, start


def detect_same_name_ambiguous_students(items: Iterable[object]) -> frozenset[str]:
    """Find names that demonstrably refer to overlapping course entities.

    A name is ambiguous only when it occurs in attended courses on the same
    date and start time, and those occurrences have different stable lesson
    keys.  Different exports of the same lesson therefore do not trigger the
    flag, and a grade disagreement by itself is never enough.
    """
    grouped: dict[tuple[str, str, str], set[tuple[str, str, str, str]]] = {}
    for item in items:
        contexts = _student_course_contexts(item)
        for context in contexts:
            student = context.student.strip()
            day = str(context.lesson_date or "").strip()[:10]
            start = normalize_lesson_start_time(context.lesson_start_time)
            lesson_key = stable_lesson_key(context.teacher, context.subject, day, start)
            if not student or not day or not start or not all(lesson_key):
                continue
            grouped.setdefault((student, day, start), set()).add(lesson_key)
    return frozenset(student for (student, _day, _start), keys in grouped.items() if len(keys) > 1)


def scope_grade_evidence_for_course(
    evidence: Sequence[StudentGradeEvidence],
    *,
    teacher: str,
    subject: str,
    class_type: str = "",
    ambiguous_students: Iterable[str] = (),
) -> tuple[StudentGradeEvidence, ...]:
    """Keep ambiguous-name evidence only when it matches this course track.

    Non-ambiguous names retain the existing behavior.  For an ambiguous name,
    evidence without enough course context is not attributed silently; legacy
    evidence with a teacher/subject but no class type remains usable when the
    available context still identifies the track.
    """
    ambiguous = {str(name).strip() for name in ambiguous_students if str(name).strip()}
    if not ambiguous:
        return tuple(evidence)
    current_teacher = str(teacher or "").strip()
    current_subject = str(subject or "").strip()
    current_class_type = str(class_type or "").strip()
    scoped: list[StudentGradeEvidence] = []
    for item in evidence:
        if item.student.strip() not in ambiguous:
            scoped.append(item)
            continue
        if not current_teacher or not current_subject:
            continue
        if not item.teacher.strip() or item.teacher.strip() != current_teacher:
            continue
        if item.subject.strip() and item.subject.strip() != current_subject:
            continue
        if item.class_type.strip() and current_class_type and item.class_type.strip() != current_class_type:
            continue
        scoped.append(item)
    return tuple(scoped)


def _student_course_contexts(item: object) -> tuple[StudentCourseContext, ...]:
    if isinstance(item, StudentCourseContext):
        return (item,)
    if isinstance(item, StudentGradeEvidence):
        return (
            StudentCourseContext(
                student=item.student, lesson_date=item.lesson_date,
                lesson_start_time=item.lesson_start_time, teacher=item.teacher,
                subject=item.subject, class_type=item.class_type,
            ),
        )
    if isinstance(item, CourseExportSnapshot):
        status = str(item.lesson_status or "").strip()
        if status and status != "已上课":
            return ()
        if item.attended is not None and item.attended <= 0:
            return ()
        return tuple(
            StudentCourseContext(
                student=student, lesson_date=item.lesson_date,
                lesson_start_time=item.lesson_start_time, teacher=item.teacher,
                subject=item.subject, class_type=item.teaching_form,
                attended=item.attended, lesson_status=status,
                source_file=item.source_file,
            )
            for student in split_student_names(item.student)
        )
    return ()


def _timestamp_from_text(value: str) -> str:
    match = EXPORT_TIMESTAMP_PATTERN.search(value)
    if not match or not match.group("hour") or not match.group("minute"):
        return ""
    try:
        return datetime(
            int(match.group("year")), int(match.group("month")), int(match.group("day")),
            int(match.group("hour")), int(match.group("minute")),
        ).isoformat(timespec="minutes")
    except ValueError:
        return ""


def export_timestamp_from_source(value: object) -> str:
    """Extract an export timestamp from a dated source name/path.

    Source timestamps are evidence, not a configured rollover date.  A file
    without a traceable timestamp is intentionally unusable for automatic
    export-pollution resolution.

    The file name is searched first and the containing directories only as a
    fallback.  Searching the whole path in one pass made the result depend on
    where the file happened to live: a directory whose name carries a date-like
    fragment (for example the checkout `.../education-payroll-longrun-20260913/`)
    matched before the real export stamp in the file name, the match then had no
    hour/minute, and this function reported "no timestamp".  A folder name must
    never override the evidence carried by the export itself.
    """
    if value is None:
        return ""
    text = str(value)
    if not text:
        return ""
    # Split the file name from its directories with plain string handling: this
    # module deliberately never touches the filesystem.
    head, _, name = text.replace("\\", "/").rpartition("/")
    stamp = _timestamp_from_text(name)
    if stamp:
        return stamp
    # Only when the file itself carries no usable stamp may its location be used
    # as evidence (for example `/exports/202609011200/课表.xlsx`).
    return _timestamp_from_text(head) if head else ""


def course_export_snapshot_index(snapshots: Iterable[CourseExportSnapshot]) -> dict[tuple[str, str, str, str], tuple[CourseExportSnapshot, ...]]:
    indexed: dict[tuple[str, str, str, str], list[CourseExportSnapshot]] = {}
    for snapshot in snapshots:
        key = stable_lesson_key(snapshot.teacher, snapshot.subject, snapshot.lesson_date, snapshot.lesson_start_time)
        if not all(key):
            continue
        indexed.setdefault(key, []).append(snapshot)
    return {key: tuple(values) for key, values in indexed.items()}


def course_export_grade_override(
    *,
    teacher: str,
    subject: str,
    lesson_date: str,
    lesson_time: str,
    current_grade: str,
    current_source_file: str,
    snapshots: Mapping[tuple[str, str, str, str], Sequence[CourseExportSnapshot]] | Sequence[CourseExportSnapshot],
) -> tuple[str, str, tuple[CourseExportSnapshot, ...]] | None:
    """Find a safe old-export grade for the current course.

    The function compares the current export with the immediately preceding
    export version for the same stable lesson key.  It only accepts an exact
    one-step natural grade upgrade before 20 September; it never relies on a
    hard-coded source-system switch date and never uses student attendance to
    manufacture a student fact.
    """
    current_grade = str(current_grade or "").strip()
    current_time = export_timestamp_from_source(current_source_file)
    current_dt = _parse_export_datetime(current_time)
    lesson_day = _parse_date(lesson_date)
    key = stable_lesson_key(teacher, subject, lesson_date, lesson_time)
    if not current_grade or not current_dt or lesson_day is None or not all(key):
        return None
    if isinstance(snapshots, Mapping):
        candidates = tuple(snapshots.get(key, ()))
    else:
        candidates = tuple(snapshot for snapshot in snapshots if stable_lesson_key(snapshot.teacher, snapshot.subject, snapshot.lesson_date, snapshot.lesson_start_time) == key)
    candidates = tuple(
        snapshot for snapshot in candidates
        if snapshot.source_file != current_source_file
        and (snapshot.exported_at or export_timestamp_from_source(snapshot.source_file))
        and _parse_export_datetime(snapshot.exported_at or export_timestamp_from_source(snapshot.source_file)) is not None
        and _parse_export_datetime(snapshot.exported_at or export_timestamp_from_source(snapshot.source_file)) < current_dt
        and snapshot.parsed_grade in NATURAL_GRADE_LADDER
    )
    # The source-system early class-name promotion is a known end-of-summer
    # phenomenon, not a year-round permission to downgrade class names.
    if lesson_day.month != SUMMER_ROLLOVER_MONTH or not candidates:
        return None
    def snapshot_datetime(snapshot: CourseExportSnapshot) -> datetime | None:
        return _parse_export_datetime(snapshot.exported_at or export_timestamp_from_source(snapshot.source_file))

    latest_dt = max(snapshot_datetime(snapshot) for snapshot in candidates if snapshot_datetime(snapshot) is not None)
    latest = tuple(snapshot for snapshot in candidates if snapshot_datetime(snapshot) == latest_dt)
    old_grades = {snapshot.parsed_grade for snapshot in latest}
    if len(old_grades) != 1:
        return None
    old_grade = next(iter(old_grades))
    old_index = NATURAL_GRADE_LADDER.index(old_grade)
    if old_index + 1 >= len(NATURAL_GRADE_LADDER) or NATURAL_GRADE_LADDER[old_index + 1] != current_grade:
        return None
    export_day = latest_dt.date().isoformat()
    reason = (
        f"同一课次在 {export_day} 的较早导出中为{old_grade}，"
        f"后续导出班名更新为{current_grade}；课程实际发生于 {lesson_day.isoformat()}，"
        f"早于 {lesson_day.year}-09-20 工资年级生效日，因此按{old_grade}计算。"
    )
    return old_grade, reason, latest


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


def evidence_identity(item: StudentGradeEvidence) -> tuple[str, str, str, str, str, str, str, str]:
    return (
        item.student.strip(), item.lesson_date[:10], item.grade, item.source_hash,
        item.coordinate, item.teacher.strip(), item.subject.strip(), item.lesson_start_time.strip(),
    )


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

    This is intentionally narrow.  The known source-system early promotion is
    only handled for August lessons in the summer changeover window.  A later
    export may be dated before 20 September (the real system can already show
    the promoted class name on 1 September), so the export ordering—not a
    hard-coded source-system switch date—is decisive.  Without export
    timestamps the disagreement remains a genuine conflict requiring input.
    """
    items = list(items)
    ignored: set[int] = set()
    grouped: dict[tuple[str, str, str, str, str], list[tuple[int, StudentGradeEvidence]]] = {}
    for index, item in enumerate(items):
        # New evidence carries the stable course identity.  Legacy rows that
        # predate those fields retain the old student+date fallback so they can
        # still be read, but new imports no longer merge different courses on
        # the same day.
        course_key = (
            item.teacher.strip(), item.subject.strip(), item.lesson_start_time.strip(),
        ) if item.teacher.strip() and item.subject.strip() and item.lesson_start_time.strip() else ("", "", "")
        grouped.setdefault((item.student.strip(), item.lesson_date[:10], *course_key), []).append((index, item))
    for (_student, lesson_date, _teacher, _subject, _start_time), group in grouped.items():
        grades = {item.grade for _index, item in group}
        if len(grades) < 2:
            continue
        try:
            lesson_day = date.fromisoformat(lesson_date[:10])
        except ValueError:
            continue
        if lesson_day.month != SUMMER_ROLLOVER_MONTH:
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
            if export_day > base_export and item.grade == expected_next and item.grade != base_item.grade:
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


def _parse_export_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
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
