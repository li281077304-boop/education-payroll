"""Personnel and effective-dated part-time rate adapter."""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..models.evidence import AdapterIssue, AdapterResult
from .weekly_report import _column, _load_rows, _number, _text, _sheet_row_number


DEFAULT_PART_TIME_RATES: dict[str, float] = {"刘宇": 140.0, "张祥": 160.0, "胡涛": 170.0}


@dataclass(frozen=True)
class PersonnelRecord:
    teacher: str
    employment_type: str
    fixed_rate: float | None
    effective_from: str
    effective_to: str
    source_file: str
    sheet: str = ""
    cell: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IdentityConflict:
    kind: str
    names: tuple[str, ...]
    reason: str
    evidence: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_part_time_records(period: str, *, source: str = "兼职固定单价规则") -> tuple[PersonnelRecord, ...]:
    return tuple(PersonnelRecord(name, "PART_TIME", rate, period, period, source, evidence={"rule": "fixed_rate_per_lesson"}) for name, rate in DEFAULT_PART_TIME_RATES.items())


def identity_conflicts(names: Iterable[str]) -> tuple[IdentityConflict, ...]:
    cleaned = {str(name).strip() for name in names if str(name).strip()}
    if "刘宇" in cleaned and "刘雨" in cleaned:
        return (IdentityConflict("SAME_PERSON_POSSIBLE_VARIANT", ("刘宇", "刘雨"), "刘宇与刘雨同时出现；系统不擅自合并身份，请确认是否同一人。"),)
    return ()


def read_personnel(path: str | Path, period: str, *, effective_to: str | None = None) -> AdapterResult[PersonnelRecord]:
    source = Path(path).expanduser().resolve()
    result: AdapterResult[PersonnelRecord] = AdapterResult()
    try:
        if source.suffix.lower() == ".csv":
            with source.open(encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                headers = list(reader.fieldnames or [])
                rows = [("CSV", headers)] + [("CSV", [item.get(header, "") for header in headers]) for item in reader]
        else:
            rows = _load_rows(source)
    except (OSError, ValueError) as exc:
        result.errors.append(AdapterIssue("UNREADABLE_PERSONNEL", str(exc)))
        return result
    found: tuple[int, str, list[str]] | None = None
    for index, (sheet, row) in enumerate(rows):
        headers = [_text(value) for value in row]
        joined = " ".join(headers).replace(" ", "")
        if ("姓名" in joined or "教师" in joined) and ("兼职" in joined or "雇佣类型" in joined or "单价" in joined or "每节" in joined):
            found = (index, sheet, headers)
            break
    if found is None:
        result.errors.append(AdapterIssue("UNRECOGNIZED_PERSONNEL", "没有找到人员姓名、雇佣类型或单价字段。"))
        return result
    header_index, sheet, headers = found
    teacher_col = _column(headers, "姓名", "教师", "任课老师")
    type_col = _column(headers, "雇佣类型", "人员类型", "用工类型", "兼职")
    rate_col = _column(headers, "每节单价", "单价", "课时单价", "固定单价")
    from_col = _column(headers, "生效开始", "生效日期", "开始月份")
    to_col = _column(headers, "生效结束", "结束月份")
    if teacher_col is None:
        result.errors.append(AdapterIssue("PERSONNEL_NAME_MISSING", "人员资料缺少姓名字段。", sheet=sheet))
        return result
    end = effective_to or period
    for absolute_index, (row_sheet, row) in enumerate(rows[header_index + 1:], start=header_index + 1):
        if row_sheet != sheet or teacher_col >= len(row):
            continue
        row_number = _sheet_row_number(rows, absolute_index, sheet)
        name = _text(row[teacher_col])
        if not name or name in {"姓名", "教师", "合计"}:
            continue
        raw_type = _text(row[type_col]) if type_col is not None and type_col < len(row) else ""
        employment = "PART_TIME" if any(token in raw_type for token in ("兼职", "PART_TIME", "非全")) else "FULL_TIME"
        rate = _number(row[rate_col]) if rate_col is not None and rate_col < len(row) else None
        start = _text(row[from_col]) if from_col is not None and from_col < len(row) else period
        finish = _text(row[to_col]) if to_col is not None and to_col < len(row) else end
        result.records.append(PersonnelRecord(name, employment, rate, start, finish, source.name, sheet, f"{sheet}!{_col(teacher_col + 1)}{row_number}", {"headers": headers, "row": row_number}))
    result.coverage = {"records": len(result.records), "part_time": sum(item.employment_type == "PART_TIME" for item in result.records), "fixed_rates": sum(item.fixed_rate is not None for item in result.records)}
    result.warnings.extend(AdapterIssue("IDENTITY_CONFLICT", item.reason) for item in identity_conflicts(item.teacher for item in result.records))
    return result


def _col(number: int) -> str:
    value, output = number, ""
    while value:
        value, remainder = divmod(value - 1, 26)
        output = chr(65 + remainder) + output
    return output or "A"


read_personnel_excel = read_personnel
