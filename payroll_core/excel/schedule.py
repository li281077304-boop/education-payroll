from __future__ import annotations

from pathlib import Path
from typing import Mapping

from ..models.evidence import AdapterIssue, AdapterResult, CellValueState
from ..models.records import ScheduleRecord
from .common import (
    as_float,
    cell_evidence,
    date_from_time,
    find_header_row,
    grade_from_schedule,
    header_map,
    normalize_schedule_class_type,
    subject_from_source,
)
from .inspect import detect_fingerprint, load_workbook_pair


REQUIRED_SCHEDULE_HEADERS = {"上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"}


def read_schedule_excel(
    path: str | Path,
    period: str,
    *,
    student_grades: Mapping[str, str] | None = None,
) -> AdapterResult[ScheduleRecord]:
    result: AdapterResult[ScheduleRecord] = AdapterResult()
    try:
        raw, cached = load_workbook_pair(path)
    except ValueError as exc:
        result.errors.append(AdapterIssue("UNSUPPORTED_FILE_FORMAT", str(exc)))
        return result
    fingerprint = detect_fingerprint(raw)
    if fingerprint.layout != "SCHEDULE_EXPORT_V1":
        result.errors.append(AdapterIssue("UNKNOWN_LAYOUT", "Expected SCHEDULE_EXPORT_V1"))
        return result
    sheet = raw[fingerprint.matched_signals[0].removeprefix("sheet:")]
    cached_sheet = cached[sheet.title]
    header_row = find_header_row(sheet, REQUIRED_SCHEDULE_HEADERS)
    if header_row is None:
        result.errors.append(AdapterIssue("MISSING_REQUIRED_COLUMN", "Schedule header row is missing required columns", sheet.title))
        return result
    columns = header_map(sheet, [header_row])
    source_file = str(path)
    unknown_grades = 0
    missing_attendance = out_of_period = 0
    for row in range(header_row + 1, sheet.max_row + 1):
        teacher = sheet.cell(row, columns["任课老师"]).value
        if teacher is None or not str(teacher).strip():
            continue
        evidence = {
            "teacher": cell_evidence(sheet, cached_sheet, row, columns["任课老师"], source_file, "任课老师"),
            "class_name": cell_evidence(sheet, cached_sheet, row, columns["上课班级"], source_file, "上课班级"),
            "course_name": cell_evidence(sheet, cached_sheet, row, columns.get("上课课程", columns["上课班级"]), source_file, "上课课程"),
            "class_type": cell_evidence(sheet, cached_sheet, row, columns["教学形式"], source_file, "教学形式"),
            "lesson_time": cell_evidence(sheet, cached_sheet, row, columns["上课时间"], source_file, "上课时间"),
            "duration_text": cell_evidence(sheet, cached_sheet, row, columns.get("上课时长", columns["上课时间"]), source_file, "上课时长"),
            "lesson_status": cell_evidence(sheet, cached_sheet, row, columns["上课状态"], source_file, "上课状态"),
            "attended": cell_evidence(sheet, cached_sheet, row, columns["实到"], source_file, "实到"),
            "student": cell_evidence(sheet, cached_sheet, row, columns["上课学员"], source_file, "上课学员"),
            "subject": cell_evidence(sheet, cached_sheet, row, columns["上课科目"], source_file, "上课科目"),
        }
        attendance = as_float(evidence["attended"].normalized_value)
        if attendance is None:
            missing_attendance += 1
            attended = None
        else:
            attended = int(attendance)
        lesson_date = date_from_time(evidence["lesson_time"].normalized_value)
        # The run period is the salary period, never the calendar day when the
        # program happens to run.  A source export may span two months.
        if _is_period(period) and lesson_date and not lesson_date.startswith(period):
            out_of_period += 1
            continue
        grade = grade_from_schedule(
            evidence["class_name"].normalized_value,
            evidence["student"].normalized_value,
            student_grades,
        )
        if not grade:
            unknown_grades += 1
        result.records.append(
            ScheduleRecord(
                period=period,
                teacher=str(evidence["teacher"].normalized_value).strip(),
                grade=grade,
                subject=subject_from_source(evidence["subject"].normalized_value),
                class_type=normalize_schedule_class_type(
                    evidence["class_type"].normalized_value,
                    evidence["class_name"].normalized_value,
                    evidence["course_name"].normalized_value,
                ),
                attended=attended,
                lesson_status=str(evidence["lesson_status"].normalized_value or "").strip(),
                student=str(evidence["student"].normalized_value or "").strip(),
                lesson_time=str(evidence["lesson_time"].normalized_value or "").strip(),
                lesson_date=lesson_date,
                class_name=str(evidence["class_name"].normalized_value or "").strip(),
                course_name=str(evidence["course_name"].normalized_value or "").strip(),
                duration_text=str(evidence["duration_text"].normalized_value or "").strip(),
                source=source_file,
                provenance=evidence,
            )
        )
    if unknown_grades:
        result.warnings.append(AdapterIssue("GRADE_UNRESOLVED", f"{unknown_grades} schedule rows have no direct grade token", sheet.title, "grade"))
    if missing_attendance:
        result.warnings.append(AdapterIssue("MISSING_ATTENDANCE", f"{missing_attendance} schedule rows have no numeric attendance", sheet.title, "attended"))
    if out_of_period:
        result.warnings.append(AdapterIssue("OUT_OF_PERIOD_ROWS_EXCLUDED", f"{out_of_period} schedule rows are outside salary period {period} and were excluded", sheet.title, "lesson_time"))
    result.coverage = {"records": len(result.records), "required_columns": len(REQUIRED_SCHEDULE_HEADERS), "mapped_columns": len(REQUIRED_SCHEDULE_HEADERS)}
    return result


def _is_period(value: str) -> bool:
    return len(value) == 7 and value[4] == "-" and value[:4].isdigit() and value[5:].isdigit() and 1 <= int(value[5:]) <= 12
