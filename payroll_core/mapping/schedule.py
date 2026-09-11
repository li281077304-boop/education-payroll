"""Schedule / AC import: known adapter first, semantic mapping as fallback.

The known SCHEDULE_EXPORT_V1 fast path is untouched. Anything that does not
match it goes through the mapping engine instead of failing, so a different
campus or subject group can still reach reconciliation.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ..excel.common import (
    as_float,
    cell_evidence,
    date_from_time,
    resolve_schedule_grade,
    normalize_schedule_class_type,
    subject_from_source,
)
from ..excel.inspect import load_workbook_pair
from ..excel.schedule import read_schedule_excel
from ..models.evidence import AdapterIssue, AdapterResult
from ..models.records import ScheduleRecord
from ..grade_inference import StudentGradeEvidence
from .requirements import SCHEDULE_AC_REQUIREMENT, ImportRequirement
from .semantic import MappingAnalysis, analyze_mapping


def read_schedule_with_mapping(
    path: str | Path,
    period: str,
    *,
    mapping: Mapping[str, int],
    requirement: ImportRequirement = SCHEDULE_AC_REQUIREMENT,
    sheet_name: str = "",
    header_row: int = 0,
    student_grades: Mapping[str, str] | None = None,
    manual_grade_evidence: Sequence[StudentGradeEvidence] = (),
    historical_grade_evidence: Sequence[StudentGradeEvidence] = (),
) -> AdapterResult[ScheduleRecord]:
    """Parse a schedule sheet using an explicit field-to-column mapping."""
    result: AdapterResult[ScheduleRecord] = AdapterResult()
    try:
        raw, cached = load_workbook_pair(path)
    except ValueError as exc:
        result.errors.append(AdapterIssue("UNSUPPORTED_FILE_FORMAT", str(exc)))
        return result

    missing = [item.field for item in requirement.required_fields if not mapping.get(item.field)]
    if missing:
        result.errors.append(AdapterIssue(
            "MISSING_REQUIRED_COLUMN",
            "缺少必要字段：" + "、".join(requirement.field(name).label for name in missing),
            "", ",".join(missing),
        ))
        return result

    sheet = raw[sheet_name] if sheet_name in raw.sheetnames else _pick_sheet(raw, mapping)
    if sheet is None:
        result.errors.append(AdapterIssue("MISSING_REQUIRED_COLUMN", "找不到包含所选列的工作表。", ""))
        return result
    cached_sheet = cached[sheet.title]
    header_row = header_row or _detect_header_row(sheet, mapping)

    def label(field: str) -> str:
        column = mapping.get(field) or 0
        return str(sheet.cell(header_row, column).value or "").strip() if column else ""

    def text(name: str) -> str:
        evidence = evidence_for.get(name)
        return str(evidence.normalized_value or "").strip() if evidence is not None else ""

    unknown_grades = missing_attendance = out_of_period = 0
    for row in range(header_row + 1, sheet.max_row + 1):
        if not str(sheet.cell(row, mapping["teacher"]).value or "").strip():
            continue
        evidence_for = {
            field: cell_evidence(sheet, cached_sheet, row, column, str(path), label(field))
            for field, column in mapping.items() if column
        }
        attendance = as_float(evidence_for["actual_student_count"].normalized_value)
        if attendance is None:
            missing_attendance += 1
            attended = None
        else:
            attended = int(attendance)

        class_name = text("class_name")
        lesson_time = text("lesson_time")
        lesson_date = date_from_time(lesson_time)
        if _is_period(period) and lesson_date and not lesson_date.startswith(period):
            out_of_period += 1
            continue
        # 年级 may have its own column; otherwise it is derived from the class
        # name and, for explicit authority data only, the student-grade table.
        grade, grade_origin, grade_reason = resolve_schedule_grade(
            class_name, text("student"), period=period, student_grades=student_grades,
            manual_evidence=manual_grade_evidence, historical_evidence=historical_grade_evidence,
            direct_grade=text("grade"),
        )
        if not grade:
            unknown_grades += 1
        result.records.append(ScheduleRecord(
            period=period,
            teacher=text("teacher"),
            grade=grade,
            subject=subject_from_source(text("subject")),
            class_type=normalize_schedule_class_type(text("class_type"), class_name, text("course_name")),
            attended=attended,
            lesson_status=text("lesson_status"),
            student=text("student"),
            lesson_time=lesson_time,
            lesson_date=lesson_date,
            class_name=class_name or text("course_name"),
            course_name=class_name or text("course_name"),
            duration_text="",  # every course defaults to two hours; duration is not required
            grade_origin=grade_origin,
            grade_reason=grade_reason,
            source=str(path),
            provenance=evidence_for,
        ))
    if unknown_grades:
        result.warnings.append(AdapterIssue("GRADE_UNRESOLVED", f"{unknown_grades} schedule rows have no grade", sheet.title, "grade"))
    if missing_attendance:
        result.warnings.append(AdapterIssue("MISSING_ATTENDANCE", f"{missing_attendance} schedule rows have no numeric attendance", sheet.title, "actual_student_count"))
    if out_of_period:
        result.warnings.append(AdapterIssue("OUT_OF_PERIOD_ROWS_EXCLUDED", f"{out_of_period} schedule rows are outside salary period {period} and were excluded", sheet.title, "lesson_time"))
    result.coverage = {"records": len(result.records), "required_columns": len(requirement.required_fields), "mapped_columns": len(mapping)}
    return result


def resolve_schedule_import(
    path: str | Path,
    period: str,
    *,
    profiles: Sequence[Mapping[str, Any]] = (),
    confirmed: Mapping[str, Any] | None = None,
    requirement: ImportRequirement = SCHEDULE_AC_REQUIREMENT,
    student_grades: Mapping[str, str] | None = None,
    manual_grade_evidence: Sequence[StudentGradeEvidence] = (),
    historical_grade_evidence: Sequence[StudentGradeEvidence] = (),
) -> tuple[AdapterResult[ScheduleRecord], MappingAnalysis | None]:
    """Try the known adapter; only fall back to semantic mapping when it fails.

    ``confirmed`` carries a mapping the user has already approved, in which
    case parsing happens directly and no question is asked again.
    """
    known = read_schedule_excel(path, period, student_grades=student_grades, manual_grade_evidence=manual_grade_evidence, historical_grade_evidence=historical_grade_evidence)
    if known.ok and known.records:
        return known, None
    if confirmed:
        result = read_schedule_with_mapping(
            path, period, mapping=confirmed.get("mapping", {}), requirement=requirement,
            sheet_name=str(confirmed.get("sheet", "")), header_row=int(confirmed.get("header_row", 0) or 0), student_grades=student_grades, manual_grade_evidence=manual_grade_evidence, historical_grade_evidence=historical_grade_evidence,
        )
        return result, None
    analysis = analyze_mapping(path, requirement, profiles=profiles)
    if analysis.ready:
        result = read_schedule_with_mapping(
            path, period, mapping=analysis.mapping, requirement=requirement,
            sheet_name=analysis.sheet, header_row=analysis.header_row, student_grades=student_grades, manual_grade_evidence=manual_grade_evidence, historical_grade_evidence=historical_grade_evidence,
        )
        return result, analysis
    return known, analysis


def _pick_sheet(workbook, mapping: Mapping[str, int]):
    best, best_score = None, 0
    for sheet in workbook.worksheets:
        score = sum(
            1 for column in mapping.values()
            if any(str(sheet.cell(row, column).value or "").strip() for row in range(1, min(10, sheet.max_row) + 1))
        )
        if score > best_score:
            best, best_score = sheet, score
    return best


def _detect_header_row(sheet, mapping: Mapping[str, int]) -> int:
    best_row, best_hits = 1, 0
    for row in range(1, min(15, sheet.max_row) + 1):
        hits = sum(1 for column in mapping.values() if column and str(sheet.cell(row, column).value or "").strip())
        if hits > best_hits:
            best_row, best_hits = row, hits
    return best_row


def _is_period(value: str) -> bool:
    return len(value) == 7 and value[4] == "-" and value[:4].isdigit() and value[5:].isdigit() and 1 <= int(value[5:]) <= 12
