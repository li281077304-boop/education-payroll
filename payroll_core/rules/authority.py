"""Independent teacher-rating and hourly-rate authorities.

These objects deliberately live outside a payroll workbook.  A historical run
selects an effective-dated version and stores its id, so a future October import
cannot rewrite the basis of an earlier month.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isclose

from ..models.records import PayrollRecord
from ..reconcile.payroll_scope import FieldCheck, _star


@dataclass(frozen=True)
class TeacherRating:
    teacher: str
    rating: int
    role: str = "教师"
    effective_from: str = ""
    effective_to: str = ""
    source: str = ""
    source_version: str = ""
    confirmed_at: str = ""
    notes: str = ""

    def applies_to(self, period: str) -> bool:
        return (not self.effective_from or self.effective_from <= period) and (not self.effective_to or period <= self.effective_to)


@dataclass(frozen=True)
class CompensationBand:
    band: str
    min_hours: float
    max_hours: float | None
    base_amount: float
    rating_bonus: float
    rating: int | None = None
    role: str = "教师"
    effective_from: str = ""
    effective_to: str = ""
    source: str = ""
    source_version: str = ""

    def applies_to(self, period: str, role: str, hours: float) -> bool:
        return (
            # A general teaching rate applies to a specialised identity unless
            # a dedicated identity-specific rate table is later supplied.
            self.role in {role, "教师"}
            and self.min_hours <= hours
            and (self.max_hours is None or hours <= self.max_hours)
            and (not self.effective_from or self.effective_from <= period)
            and (not self.effective_to or period <= self.effective_to)
        )


@dataclass(frozen=True)
class TeacherCompensationProfile:
    """Effective-dated treatment authority, separate from the payroll sheet."""
    teacher: str
    role: str
    rating: int | None
    rating_override: int | None = None
    special_approval: str = ""
    obligation_hours: float = 0.0
    obligation_hours_deduction_enabled: bool = False
    effective_from: str = ""
    effective_to: str = ""
    source: str = ""
    note: str = ""

    @property
    def effective_rating(self) -> int | None:
        return self.rating_override if self.rating_override is not None else self.rating

    def applies_to(self, period: str) -> bool:
        return (not self.effective_from or self.effective_from <= period) and (not self.effective_to or period <= self.effective_to)


def default_compensation_bands(effective_from: str = "2025-10", effective_to: str = "2026-09", source_version: str = "2025-10") -> list[CompensationBand]:
    # Evidence: skill/payroll/references/ae_tier_rules.md.  The rating bonus is
    # represented by one rule per rating so ambiguity can never be hidden.
    ranges = (("0-30", 0, 30, 0), ("31-60", 30.000001, 60, 30), ("61-80", 60.000001, 80, 32), ("81-100", 80.000001, 100, 34), ("101-130", 100.000001, 130, 36), ("131-160", 130.000001, 160, 37), ("160+", 160.000001, None, 38))
    bonus = {1: 0, 2: 0, 3: 5, 4: 10, 5: 15, 6: 20}
    return [CompensationBand(f"{band}-{'一二三四五六'[rating - 1]}星", low, high, amount, extra, rating=rating, effective_from=effective_from, effective_to=effective_to, source="AE档位+星级加成规则", source_version=source_version) for band, low, high, amount in ranges for rating, extra in bonus.items()]


def rating_and_rate_checks(payroll: list[PayrollRecord], ratings: list[TeacherRating], bands: list[CompensationBand], period: str) -> list[FieldCheck]:
    by_teacher = {item.teacher: item for item in ratings if item.applies_to(period)}
    checks: list[FieldCheck] = []
    for row in payroll:
        authority = by_teacher.get(row.teacher)
        payroll_rating = _star(row.teacher_level)
        if authority is None:
            checks.append(FieldCheck(row.teacher, "rating", None, payroll_rating, "MISSING_AUTHORITY", "当前月份没有该教师的有效星级权威资料。"))
            checks.append(FieldCheck(row.teacher, "rate", None, row.ae, "RULE_NOT_FOUND", "缺少有效星级资料，不能独立确认档位金额。"))
            continue
        if payroll_rating is None:
            checks.append(FieldCheck(row.teacher, "rating", authority.rating, None, "MISSING_PAYROLL_VALUE", "工资表未读取到教师星级。"))
        elif payroll_rating != authority.rating:
            checks.append(FieldCheck(row.teacher, "rating", authority.rating, payroll_rating, "RATING_MISMATCH", f"权威星级来自：{authority.source or authority.source_version}。"))
        else:
            checks.append(FieldCheck(row.teacher, "rating", authority.rating, payroll_rating, "MATCH", "权威星级与工资表一致。"))
        if row.teaching_hours is None:
            checks.append(FieldCheck(row.teacher, "rate", None, row.ae, "NEEDS_MANUAL_REVIEW", "最终授课小时不可读，不能选择档位金额规则。"))
            continue
        matching = [band for band in bands if band.applies_to(period, authority.role, row.teaching_hours) and band.rating == authority.rating]
        if not matching:
            checks.append(FieldCheck(row.teacher, "rate", None, row.ae, "RULE_NOT_FOUND", "没有匹配当前月份、身份、星级和小时数的档位金额规则。"))
        elif len(matching) > 1:
            checks.append(FieldCheck(row.teacher, "rate", None, row.ae, "MULTIPLE_RULES_MATCHED", "命中多条档位金额规则，不能任意选择其中一条。"))
        else:
            expected = matching[0].base_amount + matching[0].rating_bonus
            status = "RATE_MATCH" if row.ae == expected else "RATE_MISMATCH"
            checks.append(FieldCheck(row.teacher, "rate", expected, row.ae, status, f"适用规则：{matching[0].band} / {matching[0].source_version or matching[0].source}。"))
    return checks


def policy_fee_checks(payroll: list[PayrollRecord], profiles: list[TeacherCompensationProfile], bands: list[CompensationBand], period: str) -> list[FieldCheck]:
    """Independently calculate AF from a compensation profile, never TRMT text."""
    profile_by_teacher = {item.teacher: item for item in profiles if item.applies_to(period)}
    bonus = {1: 0, 2: 0, 3: 5, 4: 10, 5: 15, 6: 20}
    checks: list[FieldCheck] = []
    for row in payroll:
        profile = profile_by_teacher.get(row.teacher)
        if profile is None:
            checks.append(FieldCheck(row.teacher, "af_policy", None, row.af, "MISSING_AUTHORITY", "当前月份没有教师工资政策档案，不能独立确认 AF。"))
            continue
        if row.teaching_hours is None or profile.effective_rating not in bonus:
            checks.append(FieldCheck(row.teacher, "af_policy", None, row.af, "NEEDS_MANUAL_REVIEW", "缺少有效星级或最终授课小时，不能独立计算 AF。"))
            continue
        matched = [item for item in bands if item.applies_to(period, profile.role, row.teaching_hours) and item.rating == profile.effective_rating]
        if len(matched) != 1:
            status = "RULE_NOT_FOUND" if not matched else "MULTIPLE_RULES_MATCHED"
            checks.append(FieldCheck(row.teacher, "af_policy", None, row.af, status, "无法唯一确定 AF 的档位金额规则。"))
            continue
        rate = matched[0].base_amount + matched[0].rating_bonus
        deductible = profile.obligation_hours if profile.obligation_hours_deduction_enabled else 0.0
        expected = (row.teaching_hours - deductible) * rate
        # Workbook cached values commonly round binary floating-point results
        # to two decimals. A representation-only difference is not a payroll
        # discrepancy.
        status = "AF_POLICY_MATCH" if row.af is not None and isclose(row.af, expected, abs_tol=1e-6) else "AF_POLICY_MISMATCH"
        checks.append(FieldCheck(row.teacher, "af_policy", expected, row.af, status, f"身份：{profile.role}；义务课时：{deductible:g}；特殊审批：{profile.special_approval or '无'}。"))
    return checks
