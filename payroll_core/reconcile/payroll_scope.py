"""Independent, deliberately narrow payroll field checks.

These functions consume the original schedule export, never the processed
``工资核对`` workbook.  Rows that cannot be assigned a deterministic rule are
reported as blockers instead of being silently excluded.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from math import isclose
from typing import Iterable

from ..excel.reconciliation_bridge import GRADE_COEFFICIENTS
from ..models.records import PayrollRecord, ScheduleRecord

HEADCOUNT_COEFFICIENTS = {1: 0.8, 2: 1.0, 3: 1.2, 4: 1.4, 5: 1.7, 6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5, 10: 2.7}
CLASS_MULTIPLIERS = {"小班": 1.0, "1对2": 1.2}
STAR_BONUS = {1: 0.0, 2: 0.0, 3: 5.0, 4: 10.0, 5: 15.0, 6: 20.0}
TIER = ((30, 0.0), (60, 30.0), (80, 32.0), (100, 34.0), (130, 36.0), (160, 37.0), (10**9, 38.0))


@dataclass(frozen=True)
class FieldCheck:
    teacher: str
    field: str
    expected: float | None
    actual: float | None
    status: str
    reason: str


def _valid(record: ScheduleRecord) -> bool:
    return record.lesson_status.strip() == "已上课" and record.attended is not None and record.attended > 0


def class_value_contribution(record: ScheduleRecord) -> tuple[float | None, str]:
    """Return the exact AC contribution and its human-readable calculation.

    This is deliberately the same small calculation used by ``_schedule_totals``.
    The UI evidence view calls it too, so a user can add the displayed rows back
    to the Core's AC result without maintaining a second implementation.
    """
    if not _valid(record):
        return None, "未计入：只计已上课且实到人数大于零的记录。"
    if record.class_type not in CLASS_MULTIPLIERS:
        return None, "未计入：该班型没有当前可确定的班课折算规则。"
    grade = GRADE_COEFFICIENTS.get(record.grade)
    people = HEADCOUNT_COEFFICIENTS.get(record.attended)
    if grade is None:
        return None, "未计入：原始排课无法确定年级。"
    if people is None:
        return None, "未计入：实到人数超出当前已确认班课系数范围。"
    multiplier = CLASS_MULTIPLIERS[record.class_type]
    value = grade * people * multiplier * 2
    return value, f"年级系数 {grade:g} × 实到系数 {people:g} × 班型系数 {multiplier:g} × 2 = {value:g}"


def _schedule_totals(records: Iterable[ScheduleRecord]) -> tuple[dict[str, dict[str, float]], list[FieldCheck]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"one_to_one": 0.0, "class_value": 0.0})
    blockers: list[FieldCheck] = []
    for record in records:
        if not _valid(record):
            continue
        if record.class_type == "1对1":
            coeff = GRADE_COEFFICIENTS.get(record.grade)
            if coeff is None:
                blockers.append(FieldCheck(record.teacher, "one_to_one", None, None, "NEEDS_MANUAL_REVIEW", "原始排课无法确定年级，不能计算一对一折算。"))
            else:
                totals[record.teacher]["one_to_one"] += record.attended * 2 * coeff
        elif record.class_type in CLASS_MULTIPLIERS:
            value, reason = class_value_contribution(record)
            if value is None:
                blockers.append(FieldCheck(record.teacher, "class_value", None, None, "NEEDS_MANUAL_REVIEW", reason.removeprefix("未计入：")))
            else:
                totals[record.teacher]["class_value"] += value
        elif record.class_type:
            blockers.append(FieldCheck(record.teacher, "class_value", None, None, "NEEDS_MANUAL_REVIEW", "原始排课班型没有当前可确定的班课折算规则。"))
    return totals, blockers


def schedule_field_checks(records: Iterable[ScheduleRecord], payroll: Iterable[PayrollRecord], tolerance: float = 1e-6) -> list[FieldCheck]:
    totals, blockers = _schedule_totals(records)
    actual = {row.teacher: row for row in payroll}
    checks = list(blockers)
    for teacher in sorted(set(totals) | set(actual)):
        for field in ("one_to_one", "class_value"):
            expected = totals.get(teacher, {}).get(field)
            row = actual.get(teacher)
            value = getattr(row, field) if row else None
            if teacher not in totals:
                checks.append(FieldCheck(teacher, field, None, value, "MISSING_SOURCE", "工资表有该教师，但原始排课没有可计算记录。"))
            elif row is None:
                checks.append(FieldCheck(teacher, field, expected, None, "MISSING_TARGET", "原始排课有该教师，但工资表没有该教师。"))
            elif value is None:
                checks.append(FieldCheck(teacher, field, expected, None, "NEEDS_MANUAL_REVIEW", "工资表字段没有可靠可读值。"))
            elif isclose(expected or 0.0, value, abs_tol=tolerance):
                checks.append(FieldCheck(teacher, field, expected, value, "MATCH", "原始排课独立计算值与工资表一致。"))
            else:
                checks.append(FieldCheck(teacher, field, expected, value, "UNEXPLAINED_DIFFERENCE", "原始排课独立计算值与工资表不一致。"))
    return checks


def _star(level: str) -> int | None:
    match = re.search(r"([一二三四五六1-6])星", level)
    if not match:
        return None
    token = match.group(1)
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}
    return chinese[token] if token in chinese else int(token)


def _tier(hours: float) -> float:
    return next(value for upper, value in TIER if hours <= upper)


def rate_and_fee_checks(payroll: Iterable[PayrollRecord], tolerance: float = 1e-6) -> list[FieldCheck]:
    """Formula recomputation. F-column star remains same-workbook evidence.

    Therefore these results are intentionally labelled ``FORMULA_RECHECK`` by
    the UI, never an independent authority verification.
    """
    checks: list[FieldCheck] = []
    for row in payroll:
        if any(word in row.teacher_level for word in ("管理", "底薪")):
            checks.extend((FieldCheck(row.teacher, "ae", None, row.ae, "NEEDS_MANUAL_REVIEW", "管理/底薪行不适用当前 AE 公式。"), FieldCheck(row.teacher, "af", None, row.af, "NEEDS_MANUAL_REVIEW", "管理/底薪行不适用当前 AF 公式。")))
            continue
        if row.teaching_hours is None:
            checks.extend((FieldCheck(row.teacher, "ae", None, row.ae, "NEEDS_MANUAL_REVIEW", "AD 最终授课小时不可读。"), FieldCheck(row.teacher, "af", None, row.af, "NEEDS_MANUAL_REVIEW", "AD 最终授课小时不可读。")))
            continue
        star = _star(row.teacher_level)
        if star is None:
            checks.extend((FieldCheck(row.teacher, "ae", None, row.ae, "NEEDS_MANUAL_REVIEW", "教师星级未有独立权威来源，不能确认 AE。"), FieldCheck(row.teacher, "af", None, row.af, "NEEDS_MANUAL_REVIEW", "教师星级未有独立权威来源，不能确认 AF。")))
            continue
        expected_ae = 0.0 if row.teaching_hours <= 30 else _tier(row.teaching_hours) + STAR_BONUS[star]
        ae_status = "FORMULA_MATCH" if row.ae is not None and isclose(expected_ae, row.ae, abs_tol=tolerance) else "FORMULA_DIFFERENCE"
        checks.append(FieldCheck(row.teacher, "ae", expected_ae, row.ae, ae_status, "按 AD 与本表 F 列星级复算；星级尚未由独立权威表确认。"))
        expected_af = max(0.0, row.teaching_hours - 30) * expected_ae
        af_status = "FORMULA_MATCH" if row.af is not None and isclose(expected_af, row.af, abs_tol=tolerance) else "FORMULA_DIFFERENCE"
        checks.append(FieldCheck(row.teacher, "af", expected_af, row.af, af_status, "按 AD、AE 与身份规则复算；输入来源尚未独立确认。"))
    return checks


def total_salary_read_checks(payroll: Iterable[PayrollRecord]) -> list[FieldCheck]:
    return [FieldCheck(row.teacher, "av", None, row.av, "READ_ONLY", "AV 汇总多个收入与扣款字段；当前没有全部独立权威来源，仅读取，待人工确认。") for row in payroll]
