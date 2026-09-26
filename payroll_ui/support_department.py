"""The 支持部 workbook as one formal payroll source.

The support department does not send four unrelated little tables.  It sends
one 教学部薪资表 whose columns carry several different kinds of fact:

* who the teacher is (科组 / 邮箱 / 入职日期 / 教师级别);
* the long-term compensation inputs (G 基本工资 … L 实际出勤);
* identity and pay items only they can supply (房租 / 社保 / 工装费 /
  内部推荐奖金 / 补发工资 / 考勤罚款).

Reading it once and freezing one snapshot means the final payroll consumes one
source instead of asking the operator to upload the same file five times, and
it means every value keeps a single, traceable provenance.

Values that the material does not contain this month are reported as absent,
never silently imported as zero.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from payroll_core.excel.inspect import load_workbook_pair

from .base_salary_import import (
    REQUIRED_FIELDS,
    _candidate_mappings,
    _header_for_column,
    _header_text,
    _numeric,
    _redacted_issue,
    normalize_teacher,
    source_fingerprint,
)


SUPPORT_SOURCE_TYPE = "SUPPORT_DEPARTMENT_PAYROLL_SOURCE"

# Business name -> final payroll code.  The names are the real headers of the
# company's own 教学部薪资表, so this mapping is read from the material rather
# than guessed from an Excel column letter.
SUPPORT_EXTRA_FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "group": ("科组", ("科组", "学科组", "组别")),
    "email": ("邮箱", ("邮箱", "电子邮箱", "邮件")),
    "hire_date": ("入职日期", ("入职日期", "入职时间", "入职")),
    "teacher_level": ("教师级别", ("教师级别", "教师等级", "级别")),
    "AO": ("房租", ("房租",)),
    "AP": ("社保", ("社保", "社会保险", "社保扣款")),
    "AQ": ("工装费", ("工装费", "工装")),
    "AR": ("内部推荐奖金", ("内部推荐奖金", "内部推荐")),
    "AS": ("月度激励", ("月度激励", "激励", "月度奖")),
    "AT": ("补发工资", ("补发工资", "补发")),
    "AU": ("考勤罚款", ("考勤罚款", "考勤扣款", "罚款")),
    "AV_reference": ("总工资数", ("总工资数", "总工资")),
}

# 支持部 pays these; the field is still this Run's own calculation, so the
# source column is never copied into it.
SUPPORT_NEVER_INHERITED = ("AA", "AC", "AD", "AE", "AF", "AG", "AK", "AN", "AV")
SUPPORT_INHERITED = ("AO", "AP", "AQ", "AR", "AT", "AU")
# 月度激励 has its own authority (the subject group submits it).  The support
# workbook may physically contain the column, but it is not the authority for
# it, so it is reported and left to the subject-group source.
SUPPORT_SEPARATE_AUTHORITY = ("AS",)

_CN_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_STAR_TOKEN = re.compile(r"([一二三四五六七八九\d]{1,2})\s*星")


def parse_star_rating(value: object) -> int | None:
    """Read a star rating out of a 教师级别 cell such as ``TR/四星级``.

    Used only as evidence about *which* rating the material states.  The AE
    rate算法 and the rating amounts are untouched by this helper.
    """
    text = str(value or "")
    if not text:
        return None
    match = _STAR_TOKEN.search(text)
    if not match:
        return None
    token = match.group(1)
    if token.isdigit():
        rating = int(token)
    else:
        rating = _CN_DIGITS.get(token, 0)
    return rating if 1 <= rating <= 9 else None


def _extra_columns(sheet, header_rows: list[int]) -> dict[str, int]:
    """Locate the extra support-department columns by their real header text."""
    found: dict[str, int] = {}
    for column in range(1, sheet.max_column + 1):
        header = _header_for_column(sheet, header_rows, column)
        if not header:
            continue
        fragments = [_header_text(piece) for piece in re.split(r"[\n\r]+", header) if _header_text(piece)]
        for name, (_, aliases) in SUPPORT_EXTRA_FIELDS.items():
            if name in found:
                continue
            if any(fragment in {_header_text(alias) for alias in aliases} for fragment in fragments):
                found[name] = column
    return found


def support_field_map(available: dict[str, str]) -> list[dict[str, Any]]:
    """The explicit business-name -> final field -> source column table.

    ``available`` maps a field name to the header text actually found in the
    file, so a field the material does not contain stays visibly absent instead
    of being invented.
    """
    rows: list[dict[str, Any]] = []
    for code in SUPPORT_INHERITED:
        name, _ = SUPPORT_EXTRA_FIELDS[code]
        rows.append({
            "business_name": name,
            "final_field": code,
            "source_column": available.get(code, ""),
            "source": SUPPORT_SOURCE_TYPE if code in available else "NOT_PRESENT_IN_MATERIAL",
            "inherited": True,
            "feeds_av": code in {"AO", "AP", "AQ", "AR", "AT", "AU"},
        })
    for code in SUPPORT_SEPARATE_AUTHORITY:
        name, _ = SUPPORT_EXTRA_FIELDS[code]
        rows.append({
            "business_name": name,
            "final_field": code,
            "source_column": available.get(code, ""),
            "source": "SUBJECT_GROUP_MONTHLY_INCENTIVE" if code in available else "NOT_PRESENT_IN_MATERIAL",
            "inherited": False,
            "feeds_av": True,
        })
    for code in SUPPORT_NEVER_INHERITED:
        rows.append({
            "business_name": "",
            "final_field": code,
            "source_column": available.get(code, ""),
            "source": "CURRENT_RUN_CALCULATION",
            "inherited": False,
            "feeds_av": code == "AV",
        })
    return rows


def preview_support_department(path: str | Path, period: str, roster: list[dict[str, Any]] | list[str]) -> dict[str, Any]:
    """Read the support workbook once, read-only, into a preview object."""
    source = Path(path)
    preview: dict[str, Any] = {
        "version": "SUPPORT_DEPARTMENT_PREVIEW/v1",
        "source_type": SUPPORT_SOURCE_TYPE,
        "period": str(period),
        "source": {},
        "sheet": "",
        "header_rows": [],
        "data_start_row": 0,
        "identity_fields": {},
        "rows": [],
        "month_without_history": [],
        "history_only": [],
        "identity_required": [],
        "counts": {},
        "field_map": [],
        "gaps": [],
        "can_import": False,
        "errors": [],
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
    except (OSError, ValueError):
        preview["errors"].append(_redacted_issue("UNREADABLE_WORKBOOK"))
        return preview

    complete: dict[tuple, dict] = {}
    for sheet in raw_book.worksheets:
        for item in _candidate_mappings(sheet):
            if item["duplicate_fields"] or not set(REQUIRED_FIELDS).issubset(item["mapping"]):
                continue
            key = (item["sheet"], item["data_start_row"], tuple(sorted(item["mapping"].items())))
            previous = complete.get(key)
            if previous is None or len(item["header_rows"]) > len(previous["header_rows"]):
                complete[key] = item
    layouts = list(complete.values())
    if not layouts:
        preview["errors"].append(_redacted_issue("MISSING_REQUIRED_COLUMNS"))
        return preview
    if len(layouts) > 1:
        preview["errors"].append(_redacted_issue("AMBIGUOUS_SHEET_LAYOUT"))
        return preview
    selected = layouts[0]
    raw_sheet = raw_book[selected["sheet"]]
    cached_sheet = cached_book[selected["sheet"]]
    preview["sheet"] = selected["sheet"]
    preview["header_rows"] = selected["header_rows"]
    preview["data_start_row"] = selected["data_start_row"]

    extra = _extra_columns(raw_sheet, selected["header_rows"])
    available = {name: _header_for_column(raw_sheet, selected["header_rows"], column) for name, column in extra.items()}
    preview["identity_fields"] = {name: available.get(name, "") for name in ("group", "email", "hire_date", "teacher_level")}
    preview["field_map"] = support_field_map(available)
    preview["gaps"] = [
        {"field": name, "business_name": SUPPORT_EXTRA_FIELDS[name][0], "reason": "本期资料没有该列或该列无数据。"}
        for name in SUPPORT_EXTRA_FIELDS if name not in extra
    ]

    by_name: dict[str, list[dict[str, Any]]] = {}
    for person in ({"display_name": item} if isinstance(item, str) else dict(item) for item in roster):
        key = normalize_teacher(person.get("display_name") or person.get("teacher") or "")
        if key:
            by_name.setdefault(key, []).append(person)
    roster_names = {normalize_teacher(person.get("display_name") or "") for person in roster if isinstance(person, dict)}

    seen: set[str] = set()
    matched_names: set[str] = set()
    for row_number in range(selected["data_start_row"], raw_sheet.max_row + 1):
        cells = {field: raw_sheet.cell(row_number, column).value for field, column in selected["mapping"].items()}
        if not any(value not in (None, "") for value in cells.values()):
            continue
        teacher = str(cells.get("teacher_name") or "").strip()
        key = normalize_teacher(teacher)
        if not key:
            continue
        if key == "total" or teacher in {"合计", "Total"}:
            continue
        candidates = by_name.get(key, [])
        if not candidates:
            preview["history_only"].append({"teacher": teacher, "source_row": row_number, "reason": "NOT_IN_CURRENT_CALCULATION"})
            continue
        if len(candidates) > 1:
            preview["identity_required"].append({"teacher": teacher, "source_row": row_number, "reason": "AMBIGUOUS_TEACHER_NAME"})
            continue
        if key in seen:
            preview["identity_required"].append({"teacher": teacher, "source_row": row_number, "reason": "DUPLICATE_SOURCE_TEACHER"})
            continue
        seen.add(key)
        matched_names.add(key)
        base_fields: dict[str, float] = {}
        invalid = False
        for code in REQUIRED_FIELDS:
            value = cells.get(code)
            if value in (None, ""):
                base_fields[code] = None  # type: ignore[assignment]
                continue
            if isinstance(value, str) and value.startswith("="):
                value = cached_sheet.cell(row_number, selected["mapping"][code]).value
            number = _numeric(value)
            if number is None:
                invalid = True
                break
            base_fields[code] = number
        if invalid:
            preview["errors"].append(_redacted_issue("INVALID_REQUIRED_VALUE", sheet=selected["sheet"], row=row_number))
            continue
        items: dict[str, Any] = {}
        for name, column in extra.items():
            if name in {"group", "email", "hire_date", "teacher_level", "AV_reference"}:
                continue
            raw = raw_sheet.cell(row_number, column).value
            number = _numeric(raw)
            items[name] = number
        identity = {name: raw_sheet.cell(row_number, column).value for name, column in extra.items() if name in {"group", "email", "hire_date", "teacher_level"}}
        preview["rows"].append({
            "teacher": candidates[0].get("display_name") or teacher,
            "teacher_id": str(candidates[0].get("teacher_id") or teacher),
            "source_row": row_number,
            "base_salary": base_fields,
            "items": items,
            "identity": identity,
            "star_rating": parse_star_rating(identity.get("teacher_level")),
            "provenance": {
                "source_sha256": preview["source"].get("sha256", ""),
                "sheet": selected["sheet"],
                "source_row": row_number,
                "header_rows": selected["header_rows"],
                "kind": SUPPORT_SOURCE_TYPE,
            },
        })
    preview["month_without_history"] = [
        {"teacher": person.get("display_name", ""), "teacher_id": person.get("teacher_id", "")}
        for person in roster
        if isinstance(person, dict) and normalize_teacher(person.get("display_name") or "") not in matched_names
    ]
    preview["counts"] = {
        "source_teachers": len(matched_names) + len(preview["history_only"]) + len(preview["identity_required"]),
        "current_run_teachers": len(roster_names),
        "matched": len(preview["rows"]),
        "month_without_history": len(preview["month_without_history"]),
        "history_only": len(preview["history_only"]),
        "identity_required": len(preview["identity_required"]),
    }
    preview["can_import"] = bool(preview["rows"])
    for book in (raw_book, cached_book):
        close = getattr(book, "close", None)
        if callable(close):
            close()
    return preview
