from __future__ import annotations

from pathlib import Path

from ..models.evidence import AdapterIssue, AdapterResult, CellValueState
from ..models.records import PayrollCheckRecord, ScheduleRecord
from .common import as_float, cell_evidence, find_header_row, header_map
from .inspect import detect_fingerprint, load_workbook_pair


def read_check_workbook_schedule(path: str | Path, period: str) -> AdapterResult[ScheduleRecord]:
    result: AdapterResult[ScheduleRecord] = AdapterResult()
    try:
        raw, cached = load_workbook_pair(path)
    except ValueError as exc:
        result.errors.append(AdapterIssue("UNSUPPORTED_FILE_FORMAT", str(exc)))
        return result
    if detect_fingerprint(raw).layout != "PAYROLL_CHECK_V1":
        result.errors.append(AdapterIssue("UNKNOWN_LAYOUT", "Expected PAYROLL_CHECK_V1"))
        return result
    sheet, cached_sheet = raw["排课记录"], cached["排课记录"]
    required = {"任课老师", "年级", "学科", "课程所属班型", "实到人数", "上课学员", "上课时间"}
    header_row = find_header_row(sheet, required)
    if header_row is None:
        result.errors.append(AdapterIssue("MISSING_REQUIRED_COLUMN", "Missing normalized schedule columns", sheet.title))
        return result
    columns = header_map(sheet, [header_row])
    source_file = str(path)
    for row in range(header_row + 1, sheet.max_row + 1):
        teacher = sheet.cell(row, columns["任课老师"]).value
        if teacher is None or not str(teacher).strip():
            continue
        fields = {key: cell_evidence(sheet, cached_sheet, row, columns[label], source_file, label) for key, label in {
            "teacher": "任课老师", "grade": "年级", "subject": "学科", "class_type": "课程所属班型", "attended": "实到人数", "student": "上课学员", "lesson_time": "上课时间"}.items()}
        attendance = as_float(fields["attended"].normalized_value)
        if attendance is None:
            result.warnings.append(AdapterIssue("MISSING_ATTENDANCE", "Normalized schedule row has no numeric attendance", sheet.title, "attended"))
            attended = None
        else:
            attended = int(attendance)
        result.records.append(ScheduleRecord(
            period=period, teacher=str(fields["teacher"].normalized_value).strip(), grade=str(fields["grade"].normalized_value or "").strip(), subject=str(fields["subject"].normalized_value or "").strip(), class_type=str(fields["class_type"].normalized_value or "").strip(), attended=attended, student=str(fields["student"].normalized_value or "").strip(), lesson_time=str(fields["lesson_time"].normalized_value or "").strip(), source=source_file, provenance=fields))
    result.coverage = {"records": len(result.records), "required_columns": len(required), "mapped_columns": len(required)}
    return result


def read_payroll_check_excel(path: str | Path, period: str) -> AdapterResult[PayrollCheckRecord]:
    result: AdapterResult[PayrollCheckRecord] = AdapterResult()
    try:
        raw, cached = load_workbook_pair(path)
    except ValueError as exc:
        result.errors.append(AdapterIssue("UNSUPPORTED_FILE_FORMAT", str(exc)))
        return result
    if detect_fingerprint(raw).layout != "PAYROLL_CHECK_V1":
        result.errors.append(AdapterIssue("UNKNOWN_LAYOUT", "Expected PAYROLL_CHECK_V1"))
        return result
    sheet, cached_sheet = raw["工资核对"], cached["工资核对"]
    header_row = find_header_row(sheet, {"学科", "填报", "差值", "班课"})
    if header_row is None:
        result.errors.append(AdapterIssue("MISSING_REQUIRED_COLUMN", "Missing payroll check headers", sheet.title))
        return result
    headers = [str(sheet.cell(header_row, column).value or "").strip() for column in range(1, sheet.max_column + 1)]
    expected_sequence = ["1对1", "填报", "差值", "班课", "填报", "差值"]
    start = next((index for index in range(0, len(headers) - 5) if headers[index:index + 6] == expected_sequence), None)
    if start is None:
        result.errors.append(AdapterIssue("AMBIGUOUS_HEADER", "Could not locate Q-V semantic header sequence", sheet.title))
        return result
    source_file = str(path)
    cache_missing = 0
    for row in range(header_row + 1, sheet.max_row + 1):
        name = sheet.cell(row, 3).value
        if name is None or not str(name).strip():
            continue
        teacher = str(name).strip()
        labels = ("one_to_one_expected", "one_to_one_actual", "one_to_one_difference", "class_expected", "class_actual", "class_difference")
        evidence = {label: cell_evidence(sheet, cached_sheet, row, start + offset + 1, source_file, headers[start + offset]) for offset, label in enumerate(labels)}
        for field, item in evidence.items():
            if item.state in {CellValueState.MISSING_CACHE, CellValueState.EXTERNAL_REFERENCE}:
                cache_missing += 1
                code = "EXTERNAL_REFERENCE_UNRESOLVED" if item.state is CellValueState.EXTERNAL_REFERENCE else "MISSING_CACHE"
                result.warnings.append(AdapterIssue(code, "Check formula has no reliable readable value", sheet.title, field))
        result.records.append(PayrollCheckRecord(period=period, teacher=teacher, one_to_one_expected=as_float(evidence["one_to_one_expected"].normalized_value), one_to_one_actual=as_float(evidence["one_to_one_actual"].normalized_value), one_to_one_difference=as_float(evidence["one_to_one_difference"].normalized_value), class_expected=as_float(evidence["class_expected"].normalized_value), class_actual=as_float(evidence["class_actual"].normalized_value), class_difference=as_float(evidence["class_difference"].normalized_value), source=source_file, provenance=evidence))
    result.coverage = {"records": len(result.records), "formula_values_unresolved": cache_missing}
    return result
