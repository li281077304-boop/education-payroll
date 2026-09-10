"""Read teacher payroll sheets and map them onto the canonical submission shape.

Real payroll sheets differ slightly between subject groups. This adapter
therefore recognizes a known layout first, then falls back to semantic field
mapping, and only asks a human when a field is genuinely ambiguous.
"""
from __future__ import annotations

import csv
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from openpyxl import load_workbook

from ..models.payroll_submission import (
    CANONICAL_FIELDS,
    REQUIRED_FIELDS,
    LayoutDetection,
    LayoutProfile,
    StandardPayrollSubmission,
    SubmissionSourceKind,
)


CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "teacher": ("教师", "老师", "姓名", "教师姓名", "任课老师", "责任教师", "teacher", "name"),
    "one_to_one": ("一对一", "一对一折算", "一对一课时", "1对1", "1对1折算", "aa", "one_to_one"),
    "class_value": ("班课", "班课折算", "班课课时", "班课折算小时数", "ac", "class_value"),
    "production": ("课时生产", "生产课时", "生产", "production"),
    "ae": ("ae",),
    "af": ("af",),
    "av": ("av",),
}


def _normalize(value: object) -> str:
    return str(value).strip().lower().replace(" ", "").replace("（", "(").replace("）", ")") if value is not None else ""


def fingerprint_for(headers: Iterable[str]) -> str:
    normalized = sorted({_normalize(item) for item in headers if _normalize(item)})
    return sha256("|".join(normalized).encode("utf-8")).hexdigest()[:24]


def read_sheet_rows(path: str | Path, *, data_only: bool = True) -> list[tuple[str, str, dict[str, Any]]]:
    """Return (sheet, row_number, {header: value}) for CSV or Excel input.

    ``data_only=False`` keeps formulas visible as text, which is how an
    uncalculated formula is detected instead of silently becoming a blank.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            raw = list(reader)
        if not raw:
            return []
        headers = [str(item).strip() for item in raw[0]]
        return [
            ("CSV", str(index), {headers[i]: row[i] for i in range(min(len(headers), len(row))) if headers[i]})
            for index, row in enumerate(raw[1:], start=2)
            if any(str(item).strip() for item in row)
        ]
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError("目前只支持 CSV、.xlsx 或 .xlsm 的工资表。")
    workbook = load_workbook(source, data_only=data_only, read_only=True, keep_links=True)
    output: list[tuple[str, str, dict[str, Any]]] = []
    for sheet in workbook.worksheets:
        values = list(sheet.iter_rows(values_only=True))
        if not values:
            continue
        headers = [str(item).strip() if item is not None else "" for item in values[0]]
        if not any(headers):
            continue
        for number, row in enumerate(values[1:], start=2):
            record = {headers[i]: row[i] for i in range(min(len(headers), len(row))) if headers[i]}
            if any(item not in (None, "") for item in record.values()):
                output.append((sheet.title, str(number), record))
    return output


def detect_layout(headers: Iterable[str], profile: LayoutProfile | None = None) -> LayoutDetection:
    """Recognize a layout, reusing a saved profile when one matches."""
    header_list = [str(item).strip() for item in headers if str(item).strip()]
    fingerprint = fingerprint_for(header_list)
    if profile is not None and profile.fingerprint == fingerprint:
        return LayoutDetection(fingerprint, dict(profile.mapping), profile_id=profile.id)

    by_normalized: dict[str, str] = {}
    for header in header_list:
        by_normalized.setdefault(_normalize(header), header)

    mapping: dict[str, str] = {}
    ambiguous: dict[str, tuple[str, ...]] = {}
    for field in CANONICAL_FIELDS:
        candidates = [by_normalized[alias] for alias in CANONICAL_ALIASES[field] if alias in by_normalized]
        if len(candidates) == 1:
            mapping[field] = candidates[0]
        elif len(candidates) > 1:
            ambiguous[field] = tuple(candidates)
    missing_required = tuple(field for field in REQUIRED_FIELDS if field not in mapping and field not in ambiguous)
    return LayoutDetection(fingerprint, mapping, ambiguous=ambiguous, missing_required=missing_required)


def _coerce(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        return text


def build_submissions(
    path: str | Path,
    period: str,
    source_kind: SubmissionSourceKind,
    *,
    profile: LayoutProfile | None = None,
    confirmed_mapping: dict[str, str] | None = None,
    default_teacher: str = "",
    file_hash: str = "",
    identifier: str = "",
) -> tuple[list[StandardPayrollSubmission], LayoutDetection]:
    """Map one uploaded sheet onto canonical submissions.

    Ambiguous layouts produce no submissions: the caller must confirm the
    mapping and call again, so nothing silently enters payroll by guesswork.
    """
    source = Path(path)
    rows = read_sheet_rows(source)
    if not rows:
        raise ValueError("工资表没有可识别的内容。")
    detection = detect_layout(rows[0][2], profile=profile)
    mapping = dict(confirmed_mapping or detection.mapping)
    if not mapping.get("teacher") and not default_teacher:
        return [], detection
    if not mapping.get("teacher") and default_teacher:
        mapping["teacher"] = ""

    submissions: list[StandardPayrollSubmission] = []
    for sheet, row_number, row in rows:
        teacher = str(row.get(mapping["teacher"], "")).strip() if mapping.get("teacher") else default_teacher.strip()
        if not teacher:
            continue
        fields = {field: _coerce(row.get(header)) for field, header in mapping.items() if header}
        fields["teacher"] = teacher
        extra = {
            key: value
            for key, value in row.items()
            if key not in mapping.values() and value not in (None, "")
        }
        submissions.append(
            StandardPayrollSubmission(
                id=f"{identifier or source.stem}-{row_number}",
                period=period,
                teacher_id=teacher,
                fields=fields,
                source_file=source.name,
                source_sheet=sheet,
                source_row=row_number,
                source_file_hash=file_hash,
                source_kind=source_kind,
                layout_profile_id=detection.profile_id,
                extra=extra,
            )
        )
    if not submissions:
        raise ValueError("工资表没有可识别的教师或有效记录。")
    return submissions, detection
