from __future__ import annotations

from pathlib import Path

from ..models.evidence import AdapterIssue, AdapterResult, CommentRecord, CellValueState
from ..models.records import PayrollRecord
from .common import as_float, cell_evidence, find_header_row, header_map
from .inspect import detect_fingerprint, load_workbook_pair


PAYROLL_LABELS = {
    "teacher": "姓名",
    "one_to_one": "折算小时数",
    "class_value": "班课折算小时数",
    "ae": "该档每小时金额",
    "af": "总课时费",
    "av": "总工资数",
}


def read_payroll_excel(path: str | Path, period: str) -> AdapterResult[PayrollRecord]:
    result: AdapterResult[PayrollRecord] = AdapterResult()
    try:
        raw, cached = load_workbook_pair(path)
    except ValueError as exc:
        result.errors.append(AdapterIssue("UNSUPPORTED_FILE_FORMAT", str(exc)))
        return result
    fingerprint = detect_fingerprint(raw)
    if fingerprint.layout != "PAYROLL_SHEET_V1":
        result.errors.append(AdapterIssue("UNKNOWN_LAYOUT", "Expected PAYROLL_SHEET_V1"))
        return result
    sheet_name = fingerprint.matched_signals[0].removeprefix("sheet:")
    sheet, cached_sheet = raw[sheet_name], cached[sheet_name]
    name_header_row = find_header_row(sheet, {"姓名"})
    if name_header_row is None:
        result.errors.append(AdapterIssue("MISSING_REQUIRED_COLUMN", "Missing 姓名 header", sheet_name, "teacher"))
        return result
    columns = header_map(sheet, range(name_header_row, min(name_header_row + 3, sheet.max_row) + 1))
    missing = [label for label in PAYROLL_LABELS.values() if label not in columns]
    if missing:
        result.errors.append(AdapterIssue("MISSING_REQUIRED_COLUMN", f"Missing payroll headers: {', '.join(missing)}", sheet_name))
        return result
    source_file = str(path)
    seen: set[str] = set()
    cache_missing = 0
    for row in range(name_header_row + 2, sheet.max_row + 1):
        name = sheet.cell(row, columns["姓名"]).value
        if name is None or not str(name).strip():
            continue
        teacher = str(name).strip()
        if teacher in seen:
            result.errors.append(AdapterIssue("DUPLICATE_TEACHER", "Duplicate teacher row in payroll sheet", sheet_name, "teacher"))
            continue
        seen.add(teacher)
        evidence = {
            field: cell_evidence(sheet, cached_sheet, row, columns[label], source_file, label)
            for field, label in PAYROLL_LABELS.items()
        }
        for field, item in evidence.items():
            if item.state in {CellValueState.MISSING_CACHE, CellValueState.EXTERNAL_REFERENCE}:
                cache_missing += 1
                code = "EXTERNAL_REFERENCE_UNRESOLVED" if item.state is CellValueState.EXTERNAL_REFERENCE else "MISSING_CACHE"
                result.warnings.append(AdapterIssue(code, "Formula value is not reliable without a cached value", sheet_name, field))
            comment = sheet.cell(row, columns[PAYROLL_LABELS[field]]).comment
            if comment is not None:
                result.comments.append(CommentRecord(source_file, sheet_name, sheet.cell(row, columns[PAYROLL_LABELS[field]]).coordinate, teacher, field, comment.text, comment.author))
        result.records.append(
            PayrollRecord(
                period=period,
                teacher=teacher,
                one_to_one=as_float(evidence["one_to_one"].normalized_value),
                class_value=as_float(evidence["class_value"].normalized_value),
                ae=as_float(evidence["ae"].normalized_value),
                af=as_float(evidence["af"].normalized_value),
                av=as_float(evidence["av"].normalized_value),
                source=source_file,
                provenance=evidence,
            )
        )
    result.coverage = {"records": len(result.records), "required_fields": len(PAYROLL_LABELS) - 1, "formula_values_unresolved": cache_missing}
    return result
