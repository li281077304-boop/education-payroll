from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..models.evidence import CellValueState, SourceEvidence
from ..grade_inference import GradeInference, StudentGradeEvidence, infer_historical_grade, remove_export_pollution, split_student_names


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
) -> tuple[str, str, str]:
    """Resolve one grade with an auditable authority order.

    Dated student evidence is stronger than a current class name.  This
    protects historical courses from class labels auto-promoted by a later
    export. Contradictory facts for one student require input; a multi-student
    roster that cannot form one conclusion falls back to an explicit course
    grade when one exists. The old local CSV remains a compatibility fallback.
    """
    direct = normalize_grade(direct_grade) or grade_from_class_name(class_name)

    names = split_student_names(student)
    name = "" if student is None else str(student).strip()
    confirmed = _infer_roster_grade(names, period, manual_evidence, recent_history_only=False, course_date=course_date)
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

    inferred = _infer_roster_grade(names, period, historical_evidence, course_date=course_date)
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

    if direct:
        return direct, "DIRECT_SOURCE", "当前课程或源表已明确标注年级。"

    legacy = grade_from_schedule(class_name, student, student_grades)
    if legacy:
        return legacy, "MANUAL_LOOKUP", "来自本地学生年级确认表（兼容来源）。"
    return "", "NEEDS_INPUT", inferred.reason or "当前课程未标年级，且没有可用历史证据或人工确认。"


def _lookup_roster_grade(students: Sequence[str], lookup: Mapping[str, str] | None) -> str:
    """Use a saved compatibility confirmation only when it covers one roster.

    The legacy lookup is an existing local human fact, not an automatic
    inference.  It can break a conflict between historical exports, but it
    must cover every listed student and agree on one grade.
    """
    if not students or not lookup:
        return ""
    values = [normalize_grade(lookup.get(student, "")) for student in students]
    if not all(values) or len(set(values)) != 1:
        return ""
    return values[0]


def _infer_roster_grade(
    students: Sequence[str],
    period: str,
    evidence: Sequence[StudentGradeEvidence],
    *,
    recent_history_only: bool = True,
    course_date: str = "",
) -> "GradeInference":
    """Infer one course grade from one or more named students.

    A multi-student row may override a current class-name grade only when
    every listed student has a non-conflicting conclusion and all conclusions
    agree.  This prevents a single remembered student from silently assigning
    a grade to their classmates.
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
    if len(known) != len(students):
        facts = tuple(item for result in known for item in result.evidence)
        return GradeInference(reason="部分学生已有历史年级证据，但仍有学生缺少历史证据，需要人工确认。", evidence=facts, coverage="PARTIAL", grades=frozenset(result.grade for result in known))
    grades = {result.grade for result in known}
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
