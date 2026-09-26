"""Read-only preview adapter for historical base-salary workbooks.

This module deliberately does not import, persist, or mutate anything.  It
turns a compatible historical payroll table into a *preview* that a later UI
step may show for review before calling the existing Run-scoped save path.

Values remain in the returned in-memory preview because a caller needs them to
present G--L for confirmation.  The adapter never writes values, names, source
paths, or rows to logs or disk.
"""
from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any, Iterable

from payroll_core.excel.inspect import load_workbook_pair


REQUIRED_FIELDS = ("G", "H", "I", "J", "K", "L")

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "teacher_id": ("教师id", "教师编号", "工号", "员工编号", "teacherid", "employeeid"),
    "teacher_name": ("姓名", "教师", "老师", "任课老师", "教师姓名"),
    "G": ("基本工资", "基本工资元", "底薪"),
    "H": ("岗位津贴", "岗位工资", "岗位补贴"),
    "I": ("工龄工资/教师等级", "工龄工资", "教师等级", "教师等级工资"),
    "J": ("其他待遇", "其他工资", "补贴"),
    "K": ("应出勤", "应出勤天", "应出勤天数", "应出勤日"),
    "L": ("实际出勤", "实际出勤天", "实出勤", "实际出勤天数", "实出勤天数", "实际出勤日"),
}


def normalize_teacher(value: object) -> str:
    """Normalize only presentation whitespace; never infer aliases."""
    return "".join(str(value or "").replace("\u3000", "").split())


def source_fingerprint(path: str | Path) -> dict[str, Any]:
    """Return a path-free fingerprint for stale-source checks."""
    source = Path(path)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "sha256": digest.hexdigest(),
        "size": source.stat().st_size,
        "extension": source.suffix.lower(),
    }


def source_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    """Whether a source can no longer be treated as the reviewed source."""
    return any(before.get(key) != after.get(key) for key in ("sha256", "size", "extension"))


def _header_text(value: object) -> str:
    return re.sub(r"[\s\-_()（）/\\]+", "", str(value or "")).lower()


def _merged_value(sheet, row: int, column: int) -> object:
    """Read a merged heading as its top-left value without altering it."""
    value = sheet.cell(row, column).value
    if value not in (None, ""):
        return value
    merged = getattr(getattr(sheet, "merged_cells", None), "ranges", ())
    for item in merged:
        if item.min_row <= row <= item.max_row and item.min_col <= column <= item.max_col:
            return sheet.cell(item.min_row, item.min_col).value
    return value


def _header_for_column(sheet, rows: Iterable[int], column: int) -> str:
    return "\n".join(
        str(value).strip()
        for row in rows
        if (value := _merged_value(sheet, row, column)) not in (None, "")
    )


def _field_for_header(header: str) -> str | None:
    # In a two-level header, a merged parent such as “基本工资” is repeated
    # above “岗位津贴”.  The child label is the semantic field in that case.
    # Prefer exact individual header fragments, from child to parent.
    fragments = [piece for piece in re.split(r"[\n\r]+", header) if _header_text(piece)]
    for fragment in reversed(fragments):
        compact_fragment = _header_text(fragment)
        for field, aliases in FIELD_ALIASES.items():
            if any(compact_fragment == _header_text(alias) for alias in aliases):
                return field
    # Substring matching is unsafe for this workbook: “教师级别” is not a
    # teacher-name column, and “实际基本工资” is M, not source field G.
    return None


def _candidate_mappings(sheet) -> list[dict[str, Any]]:
    """Find one-to-three-row headers, including vertically merged headings."""
    candidates: list[dict[str, Any]] = []
    maximum = min(int(getattr(sheet, "max_row", 0) or 0), 12)
    for start in range(1, maximum + 1):
        for depth in range(1, 4):
            end = start + depth - 1
            if end > maximum:
                continue
            # A candidate cannot include a data row.  This simple guard keeps
            # a valid one-row header from being rediscovered together with the
            # first numeric payroll row as an artificial two-row header.
            if any(
                isinstance(_merged_value(sheet, row, column), (int, float))
                and not isinstance(_merged_value(sheet, row, column), bool)
                for row in range(start, end + 1)
                for column in range(1, sheet.max_column + 1)
            ):
                continue
            columns: dict[str, int] = {}
            headers: dict[str, str] = {}
            duplicates: dict[str, list[int]] = {}
            for column in range(1, sheet.max_column + 1):
                header = _header_for_column(sheet, range(start, end + 1), column)
                field = _field_for_header(header)
                if not field:
                    continue
                if field in columns:
                    duplicates.setdefault(field, [columns[field]]).append(column)
                    continue
                columns[field] = column
                headers[field] = header
            mapped = set(columns)
            if not ({"teacher_id", "teacher_name"} & mapped):
                continue
            score = len(mapped & set(REQUIRED_FIELDS))
            if score < 3:
                continue
            candidates.append({
                "sheet": sheet.title,
                "header_rows": list(range(start, end + 1)),
                "data_start_row": end + 1,
                "mapping": columns,
                "headers": headers,
                "duplicate_fields": duplicates,
                "required_count": score,
            })
    return candidates


def _roster_indexes(roster: list[dict[str, Any]] | list[str]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_name: dict[str, list[dict[str, Any]]] = {}
    for raw in roster:
        person = {"teacher_id": str(raw), "display_name": str(raw)} if isinstance(raw, str) else dict(raw)
        teacher_id = str(person.get("teacher_id") or "").strip()
        name_key = normalize_teacher(person.get("display_name") or person.get("teacher") or "")
        if teacher_id:
            # Two roster entries with one stable ID are itself an ambiguity.
            if teacher_id in by_id:
                by_id[teacher_id] = {"_ambiguous": True}
            else:
                by_id[teacher_id] = person
        if name_key:
            by_name.setdefault(name_key, []).append(person)
    return by_id, by_name


def _numeric(value: object) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _column_letter(number: int) -> str:
    letters = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _formula_verified_blanks(raw_sheet, cached_sheet, row_number: int, mapping: dict[str, int], m_column: int | None, values: dict[str, object]) -> set[str]:
    """Use a source M formula as evidence that blank H/I/J really means zero.

    This does not apply to G/K/L and cannot work with a missing formula cache.
    Only the exact known G–L formula (or its SUM equivalent) is accepted.
    """
    blanks = {code for code in ("H", "I", "J") if values.get(code) in (None, "")}
    if not blanks or m_column is None:
        return set()
    numbers = {code: _numeric(values.get(code)) for code in REQUIRED_FIELDS if code not in blanks}
    if any(numbers.get(code) is None for code in ("G", "K", "L")) or numbers["K"] <= 0:
        return set()
    formula = raw_sheet.cell(row_number, m_column).value
    if not isinstance(formula, str):
        return set()
    normalized = formula.replace("$", "").replace(" ", "").upper()
    ref = {code: f"{_column_letter(mapping[code])}{row_number}" for code in REQUIRED_FIELDS}
    allowed = {
        f"=({ref['G']}+{ref['H']}+{ref['I']}+{ref['J']})/{ref['K']}*{ref['L']}",
        f"=SUM({ref['G']}:{ref['J']})/{ref['K']}*{ref['L']}",
    }
    if normalized not in allowed:
        return set()
    cached_m = _numeric(cached_sheet.cell(row_number, m_column).value)
    if cached_m is None:
        return set()
    raw_total = sum(numbers.get(code) or 0.0 for code in ("G", "H", "I", "J"))
    calculated = raw_total / numbers["K"] * numbers["L"]
    return blanks if math.isclose(calculated, cached_m, rel_tol=0, abs_tol=0.011) else set()


def _is_formula(value: object) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _source_only_item(teacher: object, sheet: str, row: int, reason: str) -> dict[str, Any]:
    """One teacher the source file mentions that this month does not calculate.

    This is a *fact about scope*, not a failure: the person exists in the
    company's payroll material but is not part of this payroll month's
    calculation.  Naming it explicitly stops the screen from implying the
    system could not recognise the person.
    """
    return {
        "teacher": str(teacher or "").strip(),
        "sheet": sheet,
        "source_row": row,
        "reason": reason,
    }


def _redacted_issue(code: str, *, sheet: str = "", row: int | None = None, field: str = "") -> dict[str, Any]:
    """Issue metadata intentionally excludes source names, values and paths."""
    result: dict[str, Any] = {"code": code}
    if sheet:
        result["sheet"] = sheet
    if row is not None:
        result["source_row"] = row
    if field:
        result["field"] = field
    return result


def preview_base_salary(path: str | Path, period: str, roster: list[dict[str, Any]] | list[str]) -> dict[str, Any]:
    """Preview a historical G--L table without persisting any payroll data.

    ``period`` is validated here so this read-only output cannot be mistaken
    for an unscoped long-term profile.  The caller must still obtain a human
    confirmation before it enters the Run through ``save_base_salary_inputs``.

    Every teacher the file mentions ends up in exactly one bucket, so the
    screen can say what is really happening instead of calling a person the
    system has no roster entry for "unrecognisable":

    * ``matched`` -- present in both this month's calculation and the file;
    * ``month_without_history`` -- this month's teacher, absent from the file;
    * ``history_only`` -- in the file, not part of this month's calculation;
    * ``identity_required`` -- looks like the same person but the evidence is
      not conclusive, so a human decides.
    """
    source = Path(path)
    preview: dict[str, Any] = {
        "version": "BASE_SALARY_IMPORT_PREVIEW/v1",
        "period": str(period),
        "source": {},
        "candidates": [],
        "matched": [],
        "unmatched": [],
        "conflicts": [],
        "errors": [],
        "rows": [],
        "history_only": [],
        "month_without_history": [],
        "identity_required": [],
        "counts": {},
        "can_import": False,
    }
    try:
        preview["source"] = source_fingerprint(source)
    except OSError:
        preview["errors"].append(_redacted_issue("UNREADABLE_WORKBOOK"))
        return preview
    if not re.fullmatch(r"\d{4}-\d{2}", str(period)):
        preview["errors"].append(_redacted_issue("INVALID_PERIOD"))
        return preview
    if source.suffix.lower() not in {".xlsx", ".xlsm", ".xls"}:
        preview["errors"].append(_redacted_issue("UNSUPPORTED_FILE_FORMAT"))
        return preview
    try:
        raw_book, cached_book = load_workbook_pair(source)
    except (OSError, ValueError) as exc:
        preview["errors"].append(_redacted_issue("UNREADABLE_WORKBOOK"))
        return preview

    all_candidates: list[dict[str, Any]] = []
    for sheet in raw_book.worksheets:
        all_candidates.extend(_candidate_mappings(sheet))
    preview["candidates"] = [
        {key: item[key] for key in ("sheet", "header_rows", "data_start_row", "mapping", "headers", "duplicate_fields", "required_count")}
        for item in all_candidates
    ]
    complete_by_layout: dict[tuple[str, int, tuple[tuple[str, int], ...]], dict[str, Any]] = {}
    for item in all_candidates:
        if item["duplicate_fields"] or not set(REQUIRED_FIELDS).issubset(item["mapping"]):
            continue
        key = (item["sheet"], item["data_start_row"], tuple(sorted(item["mapping"].items())))
        previous = complete_by_layout.get(key)
        if previous is None or len(item["header_rows"]) > len(previous["header_rows"]):
            complete_by_layout[key] = item
    complete = list(complete_by_layout.values())
    if not complete:
        preview["errors"].append(_redacted_issue("MISSING_REQUIRED_COLUMNS"))
        return preview
    if len(complete) > 1:
        preview["errors"].append(_redacted_issue("AMBIGUOUS_SHEET_LAYOUT"))
        return preview
    selected = complete[0]
    raw_sheet = raw_book[selected["sheet"]]
    cached_sheet = cached_book[selected["sheet"]]
    m_columns = [
        column for column in range(1, raw_sheet.max_column + 1)
        if any(
            _header_text(fragment) == "实际基本工资"
            for fragment in _header_for_column(raw_sheet, selected["header_rows"], column).splitlines()
        )
    ]
    m_column = m_columns[0] if len(m_columns) == 1 else None
    by_id, by_name = _roster_indexes(roster)
    source_seen: dict[tuple[str, str], int] = {}

    for row_number in range(selected["data_start_row"], raw_sheet.max_row + 1):
        raw_values = {field: raw_sheet.cell(row_number, column).value for field, column in selected["mapping"].items()}
        if not any(value not in (None, "") for value in raw_values.values()):
            continue
        source_id = str(raw_values.get("teacher_id") or "").strip()
        source_name_value = str(raw_values.get("teacher_name") or "").strip()
        source_name_key = normalize_teacher(source_name_value)
        target: dict[str, Any] | None = None
        match_kind = ""
        if source_id:
            found = by_id.get(source_id)
            if found and not found.get("_ambiguous"):
                target, match_kind = found, "STABLE_ID"
            else:
                preview["unmatched"].append(_redacted_issue("UNMATCHED_TEACHER_ID", sheet=selected["sheet"], row=row_number))
                preview["history_only"].append(_source_only_item(source_name_value or source_id, selected["sheet"], row_number, "STABLE_ID_NOT_IN_RUN"))
                continue
        elif source_name_key:
            candidates = by_name.get(source_name_key, [])
            if len(candidates) == 1:
                target, match_kind = candidates[0], "NORMALIZED_EXACT_NAME"
            elif len(candidates) > 1:
                preview["conflicts"].append(_redacted_issue("AMBIGUOUS_TEACHER_NAME", sheet=selected["sheet"], row=row_number))
                preview["identity_required"].append(_source_only_item(source_name_value, selected["sheet"], row_number, "AMBIGUOUS_TEACHER_NAME"))
                continue
            else:
                preview["unmatched"].append(_redacted_issue("UNMATCHED_TEACHER_NAME", sheet=selected["sheet"], row=row_number))
                preview["history_only"].append(_source_only_item(source_name_value, selected["sheet"], row_number, "NOT_IN_CURRENT_CALCULATION"))
                continue
        else:
            preview["errors"].append(_redacted_issue("MISSING_TEACHER_IDENTIFIER", sheet=selected["sheet"], row=row_number))
            continue

        target_id = str(target.get("teacher_id") or "").strip()
        dedupe_key = (target_id or source_name_key, match_kind)
        if dedupe_key in source_seen:
            preview["conflicts"].append(_redacted_issue("DUPLICATE_SOURCE_TEACHER", sheet=selected["sheet"], row=row_number))
            preview["identity_required"].append(_source_only_item(source_name_value, selected["sheet"], row_number, "DUPLICATE_SOURCE_TEACHER"))
            continue
        source_seen[dedupe_key] = row_number
        fields: dict[str, float] = {}
        invalid = False
        verified_blanks = _formula_verified_blanks(raw_sheet, cached_sheet, row_number, selected["mapping"], m_column, raw_values)
        for field in REQUIRED_FIELDS:
            raw_value = raw_values[field]
            if field in verified_blanks:
                fields[field] = 0.0
                continue
            cached_value = cached_sheet.cell(row_number, selected["mapping"][field]).value
            if _is_formula(raw_value):
                if _numeric(cached_value) is None:
                    preview["errors"].append(_redacted_issue("FORMULA_CACHE_MISSING", sheet=selected["sheet"], row=row_number, field=field))
                    invalid = True
                    continue
                value = cached_value
            else:
                value = raw_value
            number = _numeric(value)
            if number is None:
                preview["errors"].append(_redacted_issue("INVALID_REQUIRED_VALUE", sheet=selected["sheet"], row=row_number, field=field))
                invalid = True
                continue
            fields[field] = number
        if invalid:
            continue
        record = {
            "teacher_id": target_id,
            "fields": fields,
            "match_kind": match_kind,
            "provenance": {
                "source_sha256": preview["source"]["sha256"],
                "sheet": selected["sheet"],
                "source_row": row_number,
                "header_rows": selected["header_rows"],
                "mapping": selected["mapping"],
                "formula_verified_zero_fields": sorted(verified_blanks),
            },
        }
        preview["rows"].append(record)
        preview["matched"].append({"teacher_id": target_id, "match_kind": match_kind, "source_row": row_number})

    # A broken row stays out of the import. Valid teachers may still be
    # confirmed as one batch, while the affected teachers remain visibly
    # unmatched for later correction. Structural ambiguity or duplicate
    # identity blocks the whole batch.
    preview["can_import"] = bool(preview["rows"]) and not preview["conflicts"]
    people = [{"display_name": item} if isinstance(item, str) else dict(item) for item in roster]
    matched_ids = {str(item["teacher_id"]) for item in preview["matched"]}
    preview["month_without_history"] = [
        {"teacher": str(person.get("display_name") or person.get("teacher") or ""), "teacher_id": str(person.get("teacher_id") or "")}
        for person in people
        if str(person.get("teacher_id") or "") not in matched_ids
    ]
    # Every teacher name the material mentions: matched + history-only +
    # identity-pending.  Reported separately from the current month's roster so
    # the screen can show both sides of the comparison honestly.
    source_names = {
        str(person.get("display_name") or person.get("teacher") or "").strip()
        for person in people if str(person.get("teacher_id") or "") in matched_ids
    }
    source_names |= {str(item.get("teacher") or "").strip() for item in preview["history_only"]}
    source_names |= {str(item.get("teacher") or "").strip() for item in preview["identity_required"]}
    preview["counts"] = {
        "source_teachers": len({name for name in source_names if name}),
        "current_run_teachers": len(people),
        "matched": len(preview["matched"]),
        "month_without_history": len(preview["month_without_history"]),
        "history_only": len(preview["history_only"]),
        "identity_required": len(preview["identity_required"]),
    }
    preview["formula_verified_zero_count"] = sum(len(row["provenance"]["formula_verified_zero_fields"]) for row in preview["rows"])
    for book in (raw_book, cached_book):
        close = getattr(book, "close", None)
        if callable(close):
            close()
    return preview
