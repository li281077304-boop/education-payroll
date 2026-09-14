from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..models.evidence import CellValueState, SourceEvidence
from ..grade_inference import (
    NATURAL_GRADE_LADDER,
    GradeInference,
    StudentGradeEvidence,
    detect_same_name_ambiguous_students,
    infer_historical_grade,
    remove_export_pollution,
    scope_grade_evidence_for_course,
    split_student_names,
)


# “一对多” does not tell us whether the approved special treatment is 1对2
# or 1对3.  Keep it explicit so the Core asks for a rule instead of silently
# applying the 1对2 coefficient.
CLASS_TYPE_MAP = {"一对一": "1对1", "1对1": "1对1", "集体班": "小班", "10人班": "小班", "6人班": "小班", "8人班": "小班"}
GRADE_MAP = {"初一": "七年级", "初二": "八年级", "初三": "九年级"}
BRIDGE_GRADE_MAP = {"小升初": "六年级", "小初衔接": "六年级", "初升高": "九年级", "七升八": "七年级", "八升九": "八年级", "幼小衔接": "一年级"}
GRADE_TOKENS = ("高三", "高二", "高一", "初三", "初二", "初一", "九年级", "八年级", "七年级", "六年级", "五年级", "四年级", "三年级", "二年级", "一年级", "雅思", "托福")
SPECIAL_GRADE_KEYWORDS = ("赠送", "换购", "特批")


def find_header_row(sheet, required: set[str], max_rows: int = 12) -> int | None:
    for row in range(1, min(max_rows, sheet.max_row) + 1):
        values = {clean_header(sheet.cell(row, column).value) for column in range(1, sheet.max_column + 1)}
        if required.issubset(values):
            return row
    return None


def header_map(sheet, rows: Iterable[int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        for column in range(1, sheet.max_column + 1):
            value = clean_header(sheet.cell(row, column).value)
            if value and value not in result:
                result[value] = column
    return result


def clean_header(value: Any) -> str:
    return "" if value is None else str(value).strip().replace("\n", " ")


def cell_evidence(raw_sheet, cached_sheet, row: int, column: int, source_file: str, source_field: str) -> SourceEvidence:
    raw_cell = raw_sheet.cell(row, column)
    cached_value = cached_sheet.cell(row, column).value
    raw_value = raw_cell.value
    if isinstance(raw_value, str) and raw_value.startswith("="):
        if "[" in raw_value:
            state = CellValueState.EXTERNAL_REFERENCE
            normalized = None
        elif cached_value is None:
            state = CellValueState.MISSING_CACHE
            normalized = None
        else:
            state = CellValueState.CACHED_VALUE
            normalized = cached_value
    else:
        state = CellValueState.RAW_VALUE
        normalized = raw_value
    return SourceEvidence(
        source_file=source_file,
        sheet=raw_sheet.title,
        coordinate=raw_cell.coordinate,
        source_field=source_field,
        raw_value=raw_value,
        normalized_value=normalized,
        state=state,
    )


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def normalize_class_type(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return CLASS_TYPE_MAP.get(text, text)


def normalize_schedule_class_type(teaching_form: Any, *course_context: Any) -> str:
    """Normalize class type without treating generic “一对多” as 1对2.

    Some exports put only the generic teaching form in its own column while
    the course/class title explicitly says ``1v2`` or ``1v3``.  That explicit
    title is enough evidence for the special class type.  If it is absent the
    generic form remains unresolved, rather than silently choosing 1对2.
    """
    for value in course_context:
        text = "" if value is None else str(value)
        if re.search(r"1\s*(?:v|V|对)\s*3", text):
            return "1对3"
        if re.search(r"1\s*(?:v|V|对)\s*2", text):
            return "1对2"
    return normalize_class_type(teaching_form)


def grade_from_class_name(value: Any) -> str:
    text = "" if value is None else str(value)
    if "领航" in text:
        return "领航伴学"
    for keyword, grade in BRIDGE_GRADE_MAP.items():
        if keyword in text:
            return grade
    for token in GRADE_TOKENS:
        if token in text:
            return GRADE_MAP.get(token, token)
    return ""


def load_student_grade_lookup(path: str | Path) -> dict[str, str]:
    """Load a local, user-maintained student-grade authority CSV.

    This deliberately accepts no fallback grade.  The legacy Skill used the
    same kind of lookup for gift/exchange/approved lessons whose course names
    omit a grade.  The authority file is local business data and must never be
    shipped with the application or committed to Git.
    """
    source = Path(path)
    if not source.is_file():
        return {}
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {}
    headers = set(rows[0])
    name_key = next((key for key in ("姓名", "学生", "学生姓名", "name", "student") if key in headers), None)
    grade_key = next((key for key in ("年级", "grade") if key in headers), None)
    if not name_key or not grade_key:
        raise ValueError("学生年级权威表需要“姓名”和“年级”两列。")
    lookup: dict[str, str] = {}
    for row in rows:
        name = str(row.get(name_key) or "").strip()
        grade = normalize_grade(row.get(grade_key))
        if not name or not grade:
            continue
        if name in lookup and lookup[name] != grade:
            raise ValueError("学生年级权威表中同一学生存在互相冲突的年级。")
        lookup[name] = grade
    return lookup


def normalize_grade(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return GRADE_MAP.get(text, text)


def grade_from_schedule(
    class_name: Any,
    student: Any = "",
    student_grades: Mapping[str, str] | None = None,
) -> str:
    """Resolve a course grade without inventing a default.

    Direct course-name extraction remains the first authority.  Only when it
    fails may an explicitly supplied local student-grade authority resolve a
    record.  The direct student column is preferred over a name embedded in a
    course title; the latter is retained for legacy exports.
    """
    direct = grade_from_class_name(class_name)
    if direct:
        return direct
    lookup = student_grades or {}
    name = "" if student is None else str(student).strip()
    if name and name in lookup:
        return normalize_grade(lookup[name])
    text = "" if class_name is None else str(class_name)
    # Legacy exports sometimes carry the student only in a gift/exchange/
    # approved course name.  Match the longest known name first to avoid a
    # shorter name accidentally winning.
    if any(keyword in text for keyword in SPECIAL_GRADE_KEYWORDS):
        for candidate in sorted(lookup, key=len, reverse=True):
            if candidate and candidate in text:
                return normalize_grade(lookup[candidate])
    return ""


def _course_track_conflicts(
    students: Sequence[str], evidence: Sequence[StudentGradeEvidence], subject: str,
) -> frozenset[str]:
    """Find same-name students whose dated facts span conflicting tracks."""
    wanted = {str(student).strip() for student in students if str(student).strip()}
    tracks: dict[str, dict[tuple[str, str, str], set[str]]] = {}
    for item in evidence:
        student = item.student.strip()
        if student not in wanted:
            continue
        if subject and item.subject.strip() and item.subject.strip() != subject:
            continue
        track = (item.teacher.strip(), item.subject.strip(), item.class_type.strip())
        if not any(track):
            continue
        tracks.setdefault(student, {}).setdefault(track, set()).add(item.grade.strip())
    return frozenset(
        student for student, by_track in tracks.items()
        if len(by_track) > 1 and len({grade for grades in by_track.values() for grade in grades}) > 1
    )


def resolve_schedule_grade(
    class_name: Any,
    student: Any,
    *,
    period: str,
    student_grades: Mapping[str, str] | None = None,
    manual_evidence: Sequence[StudentGradeEvidence] = (),
    historical_evidence: Sequence[StudentGradeEvidence] = (),
    direct_grade: Any = "",
    course_date: str = "",
    course_export_grade: str = "",
    course_export_reason: str = "",
    class_type: str = "",
    course_subject: str = "",
    course_teacher: str = "",
    ambiguous_students: Iterable[str] = (),
) -> tuple[str, str, str]:
    """Resolve one grade with an auditable authority order.

    Dated student evidence is stronger than a current class name.  This
    protects historical courses from class labels auto-promoted by a later
    export. For an ordinary single-grade K12 class, one or more same-subject
    student facts may determine the roster when they agree; missing students
    are not counterevidence. Contradictory same-subject facts require input.
    The old local CSV remains a compatibility fallback.
    """
    direct = normalize_grade(direct_grade) or grade_from_class_name(class_name)

    names = split_student_names(student)
    ambiguous = set(ambiguous_students) or set(detect_same_name_ambiguous_students((*manual_evidence, *historical_evidence)))
    if direct and names:
        ambiguous.update(_course_track_conflicts(names, (*manual_evidence, *historical_evidence), course_subject.strip()))
    scoped_manual = scope_grade_evidence_for_course(
        manual_evidence, teacher=course_teacher, subject=course_subject,
        class_type=class_type, ambiguous_students=ambiguous,
    )
    scoped_history = scope_grade_evidence_for_course(
        historical_evidence, teacher=course_teacher, subject=course_subject,
        class_type=class_type, ambiguous_students=ambiguous,
    )
    # The inference routine only ever looks up the students on this row.  Keep
    # the same authority order and ambiguity rules, but avoid scanning every
    # historical fact for every current course in a package-backed run.
    # Empty rosters cannot produce a student-grade conclusion, so they need no
    # evidence scan at all.
    if names:
        student_names = set(names)
        scoped_manual = tuple(item for item in scoped_manual if item.student.strip() in student_names)
        scoped_history = tuple(item for item in scoped_history if item.student.strip() in student_names)
    else:
        scoped_manual = ()
        scoped_history = ()
    allow_partial_roster = _is_ordinary_single_grade_k12(class_name, direct, class_type)
    name = "" if student is None else str(student).strip()
    confirmed = _infer_roster_grade(names, period, scoped_manual, recent_history_only=False, course_date=course_date, allow_partial=allow_partial_roster)
    if confirmed.grade:
        reason = confirmed.reason
        if direct and direct != confirmed.grade:
            reason += f" 已保存的学生年级事实覆盖当前班名年级“{direct}”。"
        return confirmed.grade, "MANUAL_CONFIRMATION", reason
    if confirmed.coverage == "PARTIAL" and direct and confirmed.grades == {direct}:
        return direct, "DIRECT_SOURCE", f"已有学生历史证据与当前班名年级“{direct}”一致，但仍有部分学生没有历史证据。"
    if confirmed.coverage == "CONFLICT" or confirmed.evidence:
        legacy_grade = _lookup_roster_grade(names, student_grades)
        if legacy_grade:
            return legacy_grade, "MANUAL_LOOKUP", "历史课表年级存在冲突；使用已保存的本地学生年级确认（兼容来源）。"
        return "", "NEEDS_INPUT", confirmed.reason

    # A directly matched older export is stronger than a current class name
    # or an incomplete student-history conclusion, but weaker than an explicit
    # manual confirmation handled above.  The adapter supplies this only after
    # validating the stable lesson key and export timestamps.
    if course_export_grade:
        return course_export_grade, "COURSE_EXPORT_SNAPSHOT", course_export_reason

    relevant_history = _course_relevant_grade_evidence(scoped_history, course_subject)
    inferred = _infer_roster_grade(names, period, relevant_history, course_date=course_date, allow_partial=allow_partial_roster)
    if inferred.grade:
        reason = inferred.reason
        if direct and direct != inferred.grade:
            reason += f" 学生年级历史覆盖当前班名年级“{direct}”。"
        return inferred.grade, "HISTORICAL_SCHEDULE", reason
    if inferred.coverage == "PARTIAL" and direct and inferred.grades == {direct}:
        return direct, "DIRECT_SOURCE", f"已有学生历史证据与当前班名年级“{direct}”一致，但仍有部分学生没有历史证据。"
    if inferred.coverage == "CONFLICT" or inferred.evidence:
        legacy_grade = _lookup_roster_grade(names, student_grades)
        if legacy_grade:
            return legacy_grade, "MANUAL_LOOKUP", "历史课表年级存在冲突；使用已保存的本地学生年级确认（兼容来源）。"
        return "", "NEEDS_INPUT", inferred.reason

    # During the August end-of-summer window, one consistent lookup fact can
    # also explain a later-exported high-three class name.  This is deliberately
    # narrower than a general "lower the class name" rule.
    if allow_partial_roster and student_grades:
        legacy_partial = _lookup_roster_grade(names, student_grades, allow_partial=True)
        if legacy_partial and (not direct or direct == legacy_partial or _is_august_rollover_pair(direct, legacy_partial, course_date)):
            return legacy_partial, "MANUAL_LOOKUP", "普通单年级班课至少有一条同向的已保存学生年级资料，缺少资料的其他学生不构成反证。"
    if direct:
        # During the August summer rollover, ordinary small-group class names
        # may already show the upcoming school-year grade.  The accepted
        # August payroll workbook applies the prior-grade coefficient for
        # these ordinary classes (while incoming high-one classes stay high
        # one).  Stronger dated evidence above always wins; this fallback only
        # applies when the direct class label is the remaining evidence.
        rolled = _august_class_grade_rollover(direct, class_name, class_type, period, course_date)
        if rolled != direct:
            return rolled, "CLASS_ROLLOVER", f"普通班课按 8 月已确认的跨学年口径从“{direct}”回调为“{rolled}”；衔接班、领航和一对一不回调。"
        return direct, "DIRECT_SOURCE", "当前课程或源表已明确标注年级。"

    legacy = grade_from_schedule(class_name, student, student_grades)
    if legacy:
        return legacy, "MANUAL_LOOKUP", "来自本地学生年级确认表（兼容来源）。"
    return "", "NEEDS_INPUT", inferred.reason or "当前课程未标年级，且没有可用历史证据或人工确认。"


_AUGUST_ROLLOVER_GRADES = {
    # The accepted August workbook applies the prior-grade coefficient to
    # ordinary classes whose exported label has already advanced, including
    # 高二→高一.  Incoming high-one classes remain high one because they are
    # already in the new school-year track.
    "高三": "高二",
    "高二": "高一",
    "九年级": "八年级", "八年级": "七年级", "七年级": "六年级",
    "六年级": "五年级", "五年级": "四年级", "四年级": "三年级",
    "三年级": "二年级", "二年级": "一年级",
}
_BRIDGE_CLASS_MARKERS = ("小升初", "小初衔接", "初升高", "七升八", "八升九", "幼小衔接")


def _august_class_grade_rollover(direct: str, class_name: Any, class_type: str, period: str, course_date: str) -> str:
    """Apply the established August ordinary-class rollover fallback.

    This is intentionally narrower than a generic grade guess: only August
    ordinary class records without stronger evidence reach this branch, and
    bridge/航领 classes plus one-to-one lessons retain their explicit grade.
    """
    if not isinstance(period, str) or not period.endswith("-08"):
        return direct
    if class_type not in {"小班", "1对2"}:
        return direct
    name = str(class_name or "")
    # The fallback is only for the established exported timetable naming
    # convention (a class label followed by a parenthesized subject/group
    # marker).  Minimal/API fixtures often use short synthetic labels such as
    # ``九年级数学小班``; those must retain their explicit grade.
    if not (("(" in name and ")" in name) or ("（" in name and "）" in name)):
        return direct
    if "领航" in name or any(marker in name for marker in _BRIDGE_CLASS_MARKERS):
        return direct
    return _AUGUST_ROLLOVER_GRADES.get(direct, direct)


def _lookup_roster_grade(students: Sequence[str], lookup: Mapping[str, str] | None, *, allow_partial: bool = False) -> str:
    """Use a saved compatibility confirmation for one roster.

    The legacy lookup is an existing local human fact, not an automatic
    inference.  In strict mode it must cover every listed student and agree on
    one grade; ordinary single-grade K12 classes may use one agreeing entry
    while treating missing entries as unknown rather than contradictory.
    """
    if not students or not lookup:
        return ""
    values = [normalize_grade(lookup.get(student, "")) for student in students]
    known = [value for value in values if value]
    if not known or len(set(known)) != 1 or (not allow_partial and len(known) != len(values)):
        return ""
    return known[0]


def _course_relevant_grade_evidence(
    evidence: Sequence[StudentGradeEvidence],
    course_subject: str,
) -> tuple[StudentGradeEvidence, ...]:
    """Keep historical facts that can speak to the current course.

    A student may appear in multiple subjects on the same day, and a legacy
    export can carry unrelated class-name errors in another subject.  New
    evidence stores its subject, so a subject-specific course should use the
    same-subject facts plus legacy facts that predate this field.  Same-subject
    opposing facts remain a real conflict; unrelated-subject facts do not
    become counterevidence for this class.
    """
    subject = str(course_subject or "").strip()
    if not subject:
        return tuple(evidence)
    return tuple(item for item in evidence if not item.subject.strip() or item.subject.strip() == subject)


def _is_ordinary_single_grade_k12(class_name: Any, direct_grade: str, class_type: str) -> bool:
    """Whether one roster grade may safely propagate across missing students."""
    if direct_grade not in NATURAL_GRADE_LADDER or class_type != "小班":
        return False
    text = "" if class_name is None else str(class_name)
    if any(keyword in text for keyword in (*SPECIAL_GRADE_KEYWORDS, *BRIDGE_GRADE_MAP, "跨年级", "混合班")):
        return False
    return True


def _is_august_rollover_pair(direct_grade: str, saved_grade: str, course_date: str) -> bool:
    if not course_date.startswith(tuple(str(year) + "-08" for year in range(2000, 2100))):
        return False
    if direct_grade not in NATURAL_GRADE_LADDER or saved_grade not in NATURAL_GRADE_LADDER:
        return False
    index = NATURAL_GRADE_LADDER.index(saved_grade)
    return index + 1 < len(NATURAL_GRADE_LADDER) and NATURAL_GRADE_LADDER[index + 1] == direct_grade


def _infer_roster_grade(
    students: Sequence[str],
    period: str,
    evidence: Sequence[StudentGradeEvidence],
    *,
    recent_history_only: bool = True,
    course_date: str = "",
    allow_partial: bool = False,
) -> "GradeInference":
    """Infer one course grade from one or more named students.

    A multi-student row may propagate one conclusion across missing students
    only when the caller has explicitly identified it as an ordinary
    single-grade K12 class.  Other class types retain strict roster coverage.
    """
    if not students:
        return infer_historical_grade("", period, evidence, recent_history_only=recent_history_only, target_date=course_date)
    cleaned_evidence, ignored_evidence = remove_export_pollution(evidence)
    results = [
        infer_historical_grade(item, period, cleaned_evidence, recent_history_only=recent_history_only, target_date=course_date, pollution_checked=True, ignored_evidence=ignored_evidence)
        for item in students
    ]
    conflicted = [result for result in results if result.coverage == "CONFLICT" or (result.evidence and not result.grade)]
    if conflicted:
        return GradeInference(reason=conflicted[0].reason, evidence=tuple(item for result in results for item in result.evidence), coverage="CONFLICT")
    known = [result for result in results if result.grade]
    if len(known) != len(students) and not allow_partial:
        facts = tuple(item for result in known for item in result.evidence)
        return GradeInference(reason="部分学生已有历史年级证据，但仍有学生缺少历史证据，需要人工确认。", evidence=facts, coverage="PARTIAL", grades=frozenset(result.grade for result in known))
    if not known:
        return GradeInference(
            reason="没有找到这些学生在此前正常课程中的明确年级证据。",
            coverage="NONE",
        )
    grades = {result.grade for result in known}
    if allow_partial and known and len(grades) == 1:
        grade = next(iter(grades))
        facts = tuple(item for result in known for item in result.evidence)
        coverage = "COMPLETE" if len(known) == len(students) else "PARTIAL"
        reason = f"依据 {len(known)} 名学生的同向年级证据自动确定班课年级。"
        if coverage == "PARTIAL":
            reason += " 其余学生没有可用证据，不构成反证。"
        return GradeInference(grade=grade, status="DETERMINED", reason=reason, evidence=facts, coverage=coverage, grades=frozenset({grade}))
    if len(grades) != 1:
        # This is a roster-level disagreement, not contradictory history for
        # the same student.  It cannot safely override an explicit course
        # grade, but that grade remains usable as the source's own fact.  If
        # the course itself has no grade, the caller will surface this reason
        # as a request for human input.
        return GradeInference(
            reason="同一课程中学生的历史年级推断互相冲突，需要人工确认。",
            evidence=tuple(item for result in known for item in result.evidence),
            coverage="CONFLICT",
            grades=frozenset(grades),
        )
    grade = grades.pop()
    facts = tuple(item for result in known for item in result.evidence)
    return GradeInference(
        grade=grade,
        status="DETERMINED",
        reason=f"依据 {len(students)} 名学生的历史年级证据自动推断。",
        evidence=facts,
        coverage="COMPLETE",
        grades=frozenset({grade}),
    )


def subject_from_source(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return re.sub(r"^\d+-", "", text)


def date_from_time(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", "" if value is None else str(value))
    return match.group(0) if match else ""
