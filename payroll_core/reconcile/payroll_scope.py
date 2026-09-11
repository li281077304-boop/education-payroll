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
from ..models.class_type_rules import (
    DEFAULT_HEADCOUNT_COEFFICIENTS,
    LESSON_HOUR_FACTOR,
    ONE_TO_ONE_CLASS_TYPES,
    SMALL_GROUP_CLASS_TYPES,
    SPECIAL_RULES_KEY,
    UNKNOWN_CLASS_RULE,
    UNKNOWN_CLASS_TYPE_RULE,
    normalize_special,
)
from ..models.records import PayrollRecord, ScheduleRecord

#: 两张表共用同一份定义（见 models.class_type_rules），这里只是重新导出，
#: 避免第二套常量漂移：
#:   普通小班 → 只看实到人数系数；特殊班型 → 固定系数，不乘人数系数。
HEADCOUNT_COEFFICIENTS = dict(DEFAULT_HEADCOUNT_COEFFICIENTS)
#: 特殊班型没有 Core 内置系数：必须由配置提供。
SPECIAL_CLASS_COEFFICIENTS: dict[str, dict[int, float]] = {}


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


def normalize_class_rules(rules=None) -> tuple[dict[str, dict[int, float]], dict[int, float]]:
    """Return (特殊班型配置, 普通小班实到人数系数).

    特殊班型配置的形状是 ``{class_type: {实到人数: multiplier}}``，
    并且**必须由配置提供**；Core 不写死任何特殊班型系数。

    普通小班与一对一属于主核稳定规则，分别走 Core 固定的实到人数系数表与
    一对一固定逻辑，都不接受外部配置。
    """
    if not rules:
        return {}, dict(DEFAULT_HEADCOUNT_COEFFICIENTS)
    if SPECIAL_RULES_KEY in rules:
        special = normalize_special(rules.get(SPECIAL_RULES_KEY) or {})
        for name in special:
            if name in SMALL_GROUP_CLASS_TYPES:
                raise ValueError("普通小班按 Core 固定的实到人数系数折算，不能配置外部系数。")
            if name in ONE_TO_ONE_CLASS_TYPES:
                raise ValueError("一对一走主核固定逻辑，不能配置班型系数。")
        return special, dict(DEFAULT_HEADCOUNT_COEFFICIENTS)
    raise ValueError("特殊班型必须按「班型 → 实到人数 → 系数」配置，不能给单一固定系数。")


def class_value_contribution(record: ScheduleRecord, rules: dict[str, float] | None = None) -> tuple[float | None, str]:
    """Return the exact AC contribution and its human-readable calculation.

    This is deliberately the same small calculation used by ``_schedule_totals``.
    The UI evidence view calls it too, so a user can add the displayed rows back
    to the Core's AC result without maintaining a second implementation.
    """
    if not _valid(record):
        return None, "未计入：只计已上课且实到人数大于零的记录。"
    special, headcounts = normalize_class_rules(rules)
    grade = GRADE_COEFFICIENTS.get(record.grade)
    if grade is None:
        return None, "未计入：原始排课无法确定年级。"
    if record.class_type in special:
        # 特殊班型：按 (班型, 实到人数) 从配置里查 multiplier，未配置不猜。
        coefficient = special[record.class_type].get(record.attended)
        if coefficient is None:
            return None, f"{UNKNOWN_CLASS_RULE}：特殊班型“{record.class_type}”没有配置实到 {record.attended} 人的系数，请配置后重新计算。"
        value = grade * coefficient * LESSON_HOUR_FACTOR
        return value, f"特殊班型 {record.class_type}（实到 {record.attended} 人）：年级系数 {grade:g} × 班型系数 {coefficient:g} × {LESSON_HOUR_FACTOR} = {value:g}"
    if record.class_type in SMALL_GROUP_CLASS_TYPES:
        # 普通小班：只有实到人数系数，没有班型系数。
        people = headcounts.get(record.attended)
        if people is None:
            return None, "未计入：实到人数超出当前已确认人数系数范围。"
        value = grade * people * LESSON_HOUR_FACTOR
        return value, f"普通小班：年级系数 {grade:g} × 实到人数系数 {people:g}（实到 {record.attended} 人）× {LESSON_HOUR_FACTOR} = {value:g}"
    # Never default to 小班, 1.0 or "the closest class type".
    return None, f"{UNKNOWN_CLASS_TYPE_RULE}：发现新班型“{record.class_type}”，当前没有有效折算规则，请配置后重新计算。"


def _schedule_totals(records: Iterable[ScheduleRecord], rules: dict[str, float] | None = None) -> tuple[dict[str, dict[str, float]], list[FieldCheck]]:
    """Compute AA and AC per teacher. 一对一 stays in its own AA chain."""
    special, _headcounts = normalize_class_rules(rules)
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
        elif record.class_type in special or record.class_type in SMALL_GROUP_CLASS_TYPES:
            value, reason = class_value_contribution(record, rules)
            if value is None:
                blockers.append(FieldCheck(record.teacher, "class_value", None, None, "NEEDS_MANUAL_REVIEW", reason.removeprefix("未计入：")))
            else:
                totals[record.teacher]["class_value"] += value
        elif record.class_type:
            blockers.append(FieldCheck(
                record.teacher, "class_value", None, None, UNKNOWN_CLASS_TYPE_RULE,
                f"发现新班型：“{record.class_type}”。当前没有有效折算规则，请配置后重新计算。",
            ))
    return totals, blockers


def schedule_totals(records: Iterable[ScheduleRecord], rules: dict[str, float] | None = None) -> tuple[dict[str, dict[str, float]], list[FieldCheck]]:
    """Public wrapper: AA/AC totals per teacher plus blockers.

    Both modes call this, so an audit comparison and a generated payroll can
    never drift apart.
    """
    return _schedule_totals(records, rules)


def schedule_field_checks(records: Iterable[ScheduleRecord], payroll: Iterable[PayrollRecord], tolerance: float = 1e-6, rules: dict[str, float] | None = None) -> list[FieldCheck]:
    totals, blockers = _schedule_totals(records, rules)
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


# Public names so the generate mode reuses exactly the same AE/AF arithmetic as
# the audit mode instead of maintaining a second implementation.
def tier_for_hours(hours: float) -> float:
    return _tier(hours)


def star_from_level(level: str) -> int | None:
    return _star(level)


def expected_hourly_rate(teaching_hours: float, star: int) -> float:
    """AE: zero below 30 hours, otherwise tier amount plus star bonus."""
    return 0.0 if teaching_hours <= 30 else _tier(teaching_hours) + STAR_BONUS[star]


def expected_total_fee(teaching_hours: float, hourly_rate: float) -> float:
    """AF: ordinary (AD - 30) × AE, floored at zero."""
    return max(0.0, teaching_hours - 30) * hourly_rate


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
        expected_ae = expected_hourly_rate(row.teaching_hours, star)
        ae_status = "FORMULA_MATCH" if row.ae is not None and isclose(expected_ae, row.ae, abs_tol=tolerance) else "FORMULA_DIFFERENCE"
        checks.append(FieldCheck(row.teacher, "ae", expected_ae, row.ae, ae_status, "按 AD 与本表 F 列星级复算；星级尚未由独立权威表确认。"))
        expected_af = expected_total_fee(row.teaching_hours, expected_ae)
        af_status = "FORMULA_MATCH" if row.af is not None and isclose(expected_af, row.af, abs_tol=tolerance) else "FORMULA_DIFFERENCE"
        checks.append(FieldCheck(row.teacher, "af", expected_af, row.af, af_status, "按 AD、AE 与身份规则复算；输入来源尚未独立确认。"))
    return checks


def total_salary_read_checks(payroll: Iterable[PayrollRecord]) -> list[FieldCheck]:
    return [FieldCheck(row.teacher, "av", None, row.av, "READ_ONLY", "AV 汇总多个收入与扣款字段；当前没有全部独立权威来源，仅读取，待人工确认。") for row in payroll]
