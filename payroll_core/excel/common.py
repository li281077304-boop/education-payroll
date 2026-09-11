from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..models.evidence import CellValueState, SourceEvidence
from ..grade_inference import StudentGradeEvidence, infer_historical_grade


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
) -> tuple[str, str, str]:
    """Resolve one grade with an auditable authority order.

    A current source cell is strongest.  A prior human confirmation comes
    next: it is an explicit fact, so it is safer than a statistical inference.
    Historical normal-course evidence is used only when it agrees.  The old
    local CSV remains a compatibility fallback for existing installations.
    """
    direct = normalize_grade(direct_grade) or grade_from_class_name(class_name)
    if direct:
        return direct, "DIRECT_SOURCE", "当前课程或源表已明确标注年级。"

    name = "" if student is None else str(student).strip()
    confirmed = infer_historical_grade(name, period, manual_evidence)
    if confirmed.grade:
        return confirmed.grade, "MANUAL_CONFIRMATION", confirmed.reason
    if confirmed.evidence:
        return "", "NEEDS_INPUT", confirmed.reason

    inferred = infer_historical_grade(name, period, historical_evidence)
    if inferred.grade:
        return inferred.grade, "HISTORICAL_SCHEDULE", inferred.reason
    if inferred.evidence:
        return "", "NEEDS_INPUT", inferred.reason

    legacy = grade_from_schedule(class_name, student, student_grades)
    if legacy:
        return legacy, "MANUAL_LOOKUP", "来自本地学生年级确认表（兼容来源）。"
    return "", "NEEDS_INPUT", inferred.reason or "当前课程未标年级，且没有可用历史证据或人工确认。"


def subject_from_source(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    return re.sub(r"^\d+-", "", text)


def date_from_time(value: Any) -> str:
    match = re.search(r"\d{4}-\d{2}-\d{2}", "" if value is None else str(value))
    return match.group(0) if match else ""
