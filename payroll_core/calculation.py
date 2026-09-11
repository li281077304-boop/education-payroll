"""Auditable Core calculation chain; it deliberately does not replace legacy code.

All numeric arithmetic is Decimal.  Unknown source facts stay ``None`` and
``NEEDS_INPUT``: they are never converted into a zero contribution.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from .config.core_rules import CoreRules
from .models.class_type_rules import (
    ONE_TO_ONE_CLASS_TYPES,
    ORDINARY_SMALL_GROUP_HEADCOUNT_COEFFICIENTS,
    SMALL_GROUP_CLASS_TYPES,
)
from .models.records import ScheduleRecord


class ValueState(StrEnum):
    DETERMINED = "DETERMINED"
    ESTIMATED = "ESTIMATED"
    NEEDS_INPUT = "NEEDS_INPUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a finite decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be a finite decimal")
    return result


def _get(item: object, name: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(name, default)
    return getattr(item, name, default)


def _as_mapping(item: object) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        return item
    if is_dataclass(item):
        return asdict(item)
    return vars(item)


def _applies(item: object, period: str) -> bool:
    start, end = _get(item, "effective_from", ""), _get(item, "effective_to", "")
    return (not start or start <= period) and (not end or period <= end)


@dataclass(frozen=True)
class Evidence:
    kind: str
    source: str = ""
    rule_id: str = ""
    detail: str = ""
    record_key: str = ""
    formula: str = ""
    inputs: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CalculatedValue:
    value: Decimal | None
    state: ValueState
    reason: str
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class CourseContribution(CalculatedValue):
    record_key: str = ""
    teacher: str = ""
    field: str = ""  # aa, ac, or part_time_fee


@dataclass(frozen=True)
class TeacherContext:
    """Explicit employment context.  No role text is interpreted by Core."""
    teacher: str
    employment_type: str = "FULL_TIME"  # FULL_TIME, PART_TIME, MANAGEMENT
    allow_no_teaching: bool = False
    effective_from: str = ""
    effective_to: str = ""
    source: str = ""


@dataclass(frozen=True)
class PartTimeRateProfile:
    """One approved, teacher-and-grade, per-scheduled-lesson rate."""
    teacher: str
    grade: str
    rate_per_lesson: Decimal | str | int | float
    effective_from: str
    effective_to: str
    approved_by: str
    approved_at: str
    source: str = ""


@dataclass(frozen=True)
class RatingAuthority:
    teacher: str
    rating: int
    effective_from: str = ""
    effective_to: str = ""
    source: str = ""
    source_version: str = ""


@dataclass(frozen=True)
class CompensationProfile:
    """Personal AF policy. ``rating_override`` requires approval and dates."""
    teacher: str
    obligation_hours: Decimal | str | int | float
    effective_from: str = ""
    effective_to: str = ""
    source: str = ""
    deduction_enabled: bool = True
    rating_override: int | None = None
    approved_by: str = ""
    approved_at: str = ""


@dataclass(frozen=True)
class PayrollRow:
    teacher: str
    aa: CalculatedValue
    ac: CalculatedValue
    ad: CalculatedValue
    ae: CalculatedValue
    af: CalculatedValue
    part_time_fee: CalculatedValue


@dataclass(frozen=True)
class PayrollResult:
    period: str
    rule_version_id: str
    rows: tuple[PayrollRow, ...]
    course_contributions: tuple[CourseContribution, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-safe structure while preserving Decimal exactness."""
        def convert(value: object) -> object:
            if isinstance(value, Decimal):
                return str(value)
            if isinstance(value, StrEnum):
                return str(value)
            if is_dataclass(value):
                return {key: convert(item) for key, item in asdict(value).items()}
            if isinstance(value, dict):
                return {str(key): convert(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [convert(item) for item in value]
            return value
        return convert(self)  # type: ignore[return-value]


def course_record_key(record: object) -> str:
    """Stable key for an explicit effective-AC resolution injection.

    An adapter may pass ``record_key``/``id`` to retain its own source identity.
    Otherwise this is a hash of non-mutating normalized source attributes.
    """
    explicit = _get(record, "record_key") or _get(record, "id")
    if explicit:
        return str(explicit)
    if isinstance(record, ScheduleRecord):
        # This is intentionally the same identity payload as
        # reconcile.ac_resolution.schedule_record_id, kept local so the pure
        # calculator does not import the Excel-dependent reconciliation stack.
        locations = sorted({(item.source_file, item.sheet, item.coordinate) for item in record.provenance.values()})
        identity = {
            "period": record.period, "teacher": record.teacher, "source": record.source,
            "locations": locations,
            "fallback": [record.lesson_date, record.lesson_time, record.class_name, record.course_name, record.student],
        }
        return sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]
    provenance = _get(record, "provenance", {})
    locations: list[tuple[str, str, str]] = []
    if isinstance(provenance, Mapping):
        for item in provenance.values():
            locations.append((str(_get(item, "source_file", "")), str(_get(item, "sheet", "")), str(_get(item, "coordinate", ""))))
    identity = {key: _get(record, key, "") for key in (
        "period", "teacher", "grade", "subject", "class_type", "attended",
        "lesson_status", "student", "lesson_date", "lesson_time", "class_name",
        "course_name", "source",
    )}
    identity["provenance_locations"] = sorted(locations)
    return sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]


def _course_identity(record: object) -> tuple[str, str, str, object, str]:
    return (
        str(_get(record, "teacher", "")), str(_get(record, "grade", "")),
        str(_get(record, "class_type", "")), _get(record, "attended"),
        str(_get(record, "lesson_status", "")),
    )


def _not_applicable(key: str, teacher: str, reason: str) -> CourseContribution:
    return CourseContribution(Decimal("0"), ValueState.NOT_APPLICABLE, reason, (), key, teacher, "")


def _number(value: Decimal | int) -> str:
    return str(value)


def _course_evidence(*, key: str, rule_id: str, formula: str, value: Decimal, **inputs: Decimal | int | str) -> Evidence:
    return Evidence(
        "COURSE_CALCULATION", rule_id=rule_id, record_key=key,
        detail=f"{formula} = {value}", formula=formula,
        inputs={name: _number(item) if isinstance(item, (Decimal, int)) else str(item) for name, item in inputs.items()},
    )


def calculate_course(record: object, rules: CoreRules | Mapping[str, Any], *, effective_ac: Mapping[str, object] | None = None) -> CourseContribution:
    """Calculate one full-time course's AA or AC contribution with evidence.

    ``effective_ac`` is an explicit, already-approved resolution layer.  It
    never makes an unknown record zero; it only supplies a concrete AC value.
    """
    core = rules if isinstance(rules, CoreRules) else CoreRules.from_dict(rules)
    key = course_record_key(record)
    teacher, grade, class_type, attended_raw, lesson_status = _course_identity(record)
    if not teacher:
        return CourseContribution(None, ValueState.NEEDS_INPUT, "课程缺少教师，不能归集 AA/AC。", (), key, "", "")
    if grade in core.excluded_grades:
        return _not_applicable(key, teacher, f"年级“{grade}”在规则版本中明确排除，不进入核心 AA/AC/AD。")
    if lesson_status in core.non_teaching_lesson_statuses:
        return _not_applicable(key, teacher, f"状态“{lesson_status}”在规则版本中明确为未上课，不计入核心 AA/AC/AD。")
    # 一对一 与 普通小班 是主核稳定规则（Core 常量，不可外部配置）；
    # 只有特殊班型从规则包里按 (班型, 实到人数) 查系数。
    if class_type in ONE_TO_ONE_CLASS_TYPES:
        treatment, rule_id, rule = "ONE_TO_ONE", "core_one_to_one", None
    elif class_type in SMALL_GROUP_CLASS_TYPES:
        treatment, rule_id, rule = "SMALL_GROUP", "core_small_group", None
    else:
        rule = core.course_rule(class_type)
        if rule is None:
            return CourseContribution(None, ValueState.NEEDS_INPUT, f"班型“{class_type}”既不是一对一、也不是普通小班，且没有配置特殊班型规则，不能按最接近班型或人数猜测。", (), key, teacher, "")
        treatment, rule_id = "SPECIAL", rule.id
    target_field = "aa" if treatment == "ONE_TO_ONE" else "ac"
    if lesson_status != "已上课":
        return CourseContribution(None, ValueState.NEEDS_INPUT, f"上课状态“{lesson_status or '空'}”不在已上课或明确排除状态中，不能静默跳过。", (), key, teacher, target_field)
    if attended_raw is None:
        return CourseContribution(None, ValueState.NEEDS_INPUT, "已上课记录缺少实到人数，不能把未知贡献计为 0。", (), key, teacher, target_field)
    try:
        attended = int(attended_raw)
    except (TypeError, ValueError):
        return CourseContribution(None, ValueState.NEEDS_INPUT, "实到人数不是整数，不能计算课程贡献。", (), key, teacher, target_field)
    if str(attended) != str(attended_raw) and not isinstance(attended_raw, int):
        return CourseContribution(None, ValueState.NEEDS_INPUT, "实到人数不是整数，不能计算课程贡献。", (), key, teacher, target_field)
    if attended <= 0:
        return _not_applicable(key, teacher, "实到人数不大于 0，不计入核心 AA/AC/AD。")
    grade_coefficient = core.grade_coefficients.get(grade)
    if grade_coefficient is None:
        return CourseContribution(None, ValueState.NEEDS_INPUT, f"年级“{grade}”没有配置系数，不能计算课程贡献；effective_ac 不可旁路未知年级。", (Evidence("COURSE_RULE", rule_id=rule_id, record_key=key),), key, teacher, target_field)
    if treatment == "ONE_TO_ONE":
        value = Decimal(attended) * core.lesson_hour_factor * grade_coefficient
        return CourseContribution(value, ValueState.DETERMINED, "AA：实到人数 × 每节小时系数 × 年级系数。", (_course_evidence(key=key, rule_id=rule_id, formula="attended × lesson_hour_factor × grade_coefficient", value=value, attended=attended, lesson_hour_factor=core.lesson_hour_factor, grade_coefficient=grade_coefficient),), key, teacher, "aa")
    if treatment == "SPECIAL":
        assert rule is not None
        multiplier = rule.multiplier_for(attended)
        if multiplier is None:
            return CourseContribution(None, ValueState.NEEDS_INPUT, f"特殊班型“{class_type}”没有配置实到 {attended} 人的系数（UNKNOWN_CLASS_RULE），不能按邻近人数或单一固定系数猜测。", (Evidence("COURSE_RULE", rule_id=rule.id, record_key=key),), key, teacher, "ac")
        value = grade_coefficient * multiplier * core.lesson_hour_factor
        evidence = _course_evidence(key=key, rule_id=rule.id, formula="grade_coefficient × special_multiplier(class_type, attended) × lesson_hour_factor", value=value, grade_coefficient=grade_coefficient, special_multiplier=multiplier, attended=attended, lesson_hour_factor=core.lesson_hour_factor)
        reason = "AC 特殊班：年级系数 × 该班型在本次实到人数下的系数 × 每节小时系数；不乘普通小班人数系数。"
    else:
        people = ORDINARY_SMALL_GROUP_HEADCOUNT_COEFFICIENTS.get(attended)
        if people is None:
            return CourseContribution(None, ValueState.NEEDS_INPUT, f"普通小班实到人数 {attended} 没有系数，不能按邻近人数猜测。", (Evidence("COURSE_RULE", rule_id=rule_id, record_key=key),), key, teacher, "ac")
        people_coefficient = Decimal(str(people))
        value = grade_coefficient * people_coefficient * core.lesson_hour_factor
        evidence = _course_evidence(key=key, rule_id=rule_id, formula="grade_coefficient × small_group_headcount_coefficient × lesson_hour_factor", value=value, grade_coefficient=grade_coefficient, small_group_headcount_coefficient=people_coefficient, lesson_hour_factor=core.lesson_hour_factor, attended=attended)
        reason = "AC 普通小班：年级系数 × 实到人数系数 × 每节小时系数。"
    injected = None if effective_ac is None else effective_ac.get(key)
    if injected is not None:
        effective_value = _decimal(injected, f"effective_ac[{key}]")
        if effective_value < 0:
            raise ValueError("effective_ac contribution must be non-negative")
        override = Evidence("EFFECTIVE_AC", "approved resolution", record_key=key, detail=f"confirmed effective AC overrides calculated {value} with {effective_value}", formula="effective_ac", inputs={"calculated_value": str(value), "effective_value": str(effective_value)})
        return CourseContribution(effective_value, ValueState.DETERMINED, "使用已确认的 AC resolution 有效贡献。", (evidence, override), key, teacher, "ac")
    return CourseContribution(value, ValueState.DETERMINED, reason, (evidence,), key, teacher, "ac")


def _context_for(teacher: str, contexts: Iterable[object], period: str) -> object | None:
    matched = [item for item in contexts if _get(item, "teacher") == teacher and _applies(item, period)]
    if len(matched) > 1:
        raise ValueError(f"multiple active teacher contexts for {teacher}")
    if matched:
        kind = _get(matched[0], "employment_type", "FULL_TIME")
        if kind not in {"FULL_TIME", "PART_TIME", "MANAGEMENT"}:
            raise ValueError(f"unsupported employment_type for {teacher}: {kind}")
    return matched[0] if matched else None


def _value(value: Decimal | None, state: ValueState, reason: str, *evidence: Evidence) -> CalculatedValue:
    return CalculatedValue(value, state, reason, tuple(evidence))


def _aggregate(field: str, contributions: list[CourseContribution]) -> CalculatedValue:
    relevant = [item for item in contributions if item.field == field or (item.state == ValueState.NEEDS_INPUT and not item.field)]
    blocking = [item for item in relevant if item.state == ValueState.NEEDS_INPUT]
    if blocking:
        return _value(None, ValueState.NEEDS_INPUT, f"{field.upper()} 有 {len(blocking)} 条课程贡献未知，不能作为 0 汇总。", *(evidence for item in blocking for evidence in item.evidence))
    values = [item.value for item in relevant if item.value is not None and item.state == ValueState.DETERMINED]
    return _value(sum(values, Decimal("0")), ValueState.DETERMINED, f"{field.upper()} 由 {len(values)} 条确定课程贡献汇总。", *(evidence for item in relevant for evidence in item.evidence))


def _one_active(items: Iterable[object], teacher: str, period: str, label: str) -> object | None:
    matched = [item for item in items if _get(item, "teacher") == teacher and _applies(item, period)]
    if len(matched) > 1:
        raise ValueError(f"multiple active {label} records for {teacher}")
    return matched[0] if matched else None


def _rating_for(teacher: str, period: str, ratings: Iterable[object], profiles: Iterable[object], reference_ratings: Mapping[str, object]) -> tuple[int | None, ValueState, str, tuple[Evidence, ...]]:
    profile = _one_active(profiles, teacher, period, "compensation profile")
    override = None if profile is None else _get(profile, "rating_override")
    if override is not None:
        # An override without both approval fact and effective range is not policy.
        if _get(profile, "approved_by") and _get(profile, "approved_at") and _get(profile, "effective_from") and _get(profile, "effective_to"):
            rating = int(override)
            return rating, ValueState.DETERMINED, "使用已审批且有效期覆盖本期的个人星级覆盖。", (Evidence("PROFILE_RATING_OVERRIDE", str(_get(profile, "source", ""))),)
        return None, ValueState.NEEDS_INPUT, "个人星级覆盖缺少审批事实或完整生效期，不能静默忽略或生效。", (Evidence("UNAPPROVED_PROFILE_RATING_OVERRIDE", str(_get(profile, "source", ""))),)
    authority = _one_active(ratings, teacher, period, "rating authority")
    if authority is not None:
        return int(_get(authority, "rating")), ValueState.DETERMINED, "使用独立星级权威资料。", (Evidence("RATING_AUTHORITY", str(_get(authority, "source", _get(authority, "source_version", "")))),)
    reference = reference_ratings.get(teacher)
    if reference is not None:
        rating = _get(reference, "rating", reference)
        return int(rating), ValueState.ESTIMATED, "仅使用提交/参考星级；未由独立权威资料确认。", (Evidence("REFERENCE_RATING"),)
    return None, ValueState.NEEDS_INPUT, "缺少独立星级权威资料；参考值也未提交。", ()


def _ae_af_for_period(teacher: str, period: str, ad: CalculatedValue, rules: CoreRules, ratings: Iterable[object], profiles: Iterable[object], reference_ratings: Mapping[str, object]) -> tuple[CalculatedValue, CalculatedValue]:
    if ad.state != ValueState.DETERMINED or ad.value is None:
        pending = _value(None, ValueState.NEEDS_INPUT, "AD 未确定，不能选择 AE 档位或计算 AF。")
        return pending, pending
    if ad.value <= rules.ae_zero_threshold:
        threshold = rules.ae_zero_threshold
        return _value(Decimal("0"), ValueState.DETERMINED, f"AD 不超过第一 AE 档阈值 {threshold}，AE 固定为 0。"), _value(Decimal("0"), ValueState.DETERMINED, f"AD 不超过第一 AE 档阈值 {threshold}，AF 固定为 0。")
    rating, rating_state, rating_reason, rating_evidence = _rating_for(teacher, period, ratings, profiles, reference_ratings)
    if rating is None or rating not in rules.star_bonuses:
        pending = _value(None, ValueState.NEEDS_INPUT, rating_reason if rating is None else "星级不在当前版本的星级加成配置内。", *rating_evidence)
        return pending, pending
    tier = rules.ae_tier(ad.value)
    star_bonus = rules.star_bonuses[rating]
    ae_value = tier.base + star_bonus
    ae = _value(ae_value, rating_state, f"AE：{tier.id} 基础档 + 星级加成；{rating_reason}", Evidence("AE_CALCULATION", rule_id=tier.id, detail=f"tier base {tier.base} + star bonus {star_bonus} = {ae_value}", formula="tier_base + star_bonus", inputs={"AD": str(ad.value), "tier_base": str(tier.base), "rating": str(rating), "star_bonus": str(star_bonus), "AE": str(ae_value)}), *rating_evidence)
    profile = _one_active(profiles, teacher, period, "compensation profile")
    if profile is not None:
        has_authority = bool(_get(profile, "source")) and bool(_get(profile, "effective_from")) and bool(_get(profile, "effective_to"))
        # The new name is explicit; the old profile name remains a supported
        # input contract for historical callers.
        deduction_enabled = _get(profile, "deduction_enabled", _get(profile, "obligation_hours_deduction_enabled", None))
        if not has_authority or not isinstance(deduction_enabled, bool):
            return ae, _value(None, ValueState.NEEDS_INPUT, "个人 AF 政策缺少来源、完整生效期或义务课时开关，不能确定 AF。")
        obligation = _decimal(_get(profile, "obligation_hours"), "profile obligation_hours")
        if obligation < 0:
            raise ValueError("profile obligation_hours must be non-negative")
        if not deduction_enabled:
            obligation = Decimal("0")
        policy_state, policy_reason, policy_evidence = ValueState.DETERMINED, "使用个人有效期 AF 政策。", (Evidence("PERSONAL_AF_POLICY", str(_get(profile, "source", ""))),)
    elif rules.default_af_policy_candidate is not None:
        obligation = rules.default_af_policy_candidate.obligation_hours
        policy_state, policy_reason, policy_evidence = ValueState.ESTIMATED, "缺个人 AF 政策；使用配置中显式默认候选，仍需确认。", (Evidence("DEFAULT_AF_POLICY_CANDIDATE", rules.default_af_policy_candidate.source, rules.default_af_policy_candidate.label),)
    else:
        return ae, _value(None, ValueState.NEEDS_INPUT, "缺少个人有效期 AF 政策，且配置没有默认候选；不能从角色猜测。")
    state = ValueState.ESTIMATED if ValueState.ESTIMATED in {ae.state, policy_state} else ValueState.DETERMINED
    fee = max(Decimal("0"), ad.value - obligation) * ae.value  # ae.value known above
    return ae, _value(fee, state, f"AF：(AD − {obligation}) × AE；{policy_reason}", Evidence("AF_CALCULATION", detail=f"max(0, AD {ad.value} − obligation {obligation}) × AE {ae.value} = {fee}", formula="max(0, AD - obligation_hours) × AE", inputs={"AD": str(ad.value), "obligation_hours": str(obligation), "AE": str(ae.value), "AF": str(fee)}), *policy_evidence, *rating_evidence)


def _part_time_contributions(records: Iterable[object], teacher: str, period: str, rates: Iterable[object], rules: CoreRules) -> list[CourseContribution]:
    result: list[CourseContribution] = []
    for record in records:
        key = course_record_key(record)
        grade = str(_get(record, "grade", ""))
        status = str(_get(record, "lesson_status", ""))
        if grade in rules.excluded_grades or status in rules.non_teaching_lesson_statuses:
            result.append(_not_applicable(key, teacher, "兼职记录未满足核心计费范围（明确排除或规则明确的未上课状态）。"))
            continue
        if status != "已上课":
            result.append(CourseContribution(None, ValueState.NEEDS_INPUT, f"兼职排课上课状态“{status or '空'}”未知，不能静默跳过或计费。", (), key, teacher, "part_time_fee"))
            continue
        exact = [rate for rate in rates if _get(rate, "teacher") == teacher and _get(rate, "grade") == grade and _applies(rate, period)]
        matches = exact or [rate for rate in rates if _get(rate, "teacher") == teacher and _get(rate, "grade") == "*" and _applies(rate, period)]
        if len(matches) != 1:
            reason = "缺少该兼职教师/年级的每节费率。" if not matches else "命中多条兼职教师/年级每节费率。"
            result.append(CourseContribution(None, ValueState.NEEDS_INPUT, reason, (), key, teacher, "part_time_fee"))
            continue
        rate = _decimal(_get(matches[0], "rate_per_lesson"), "part-time rate_per_lesson")
        if rate < 0:
            raise ValueError("part-time rate_per_lesson must be non-negative")
        result.append(CourseContribution(rate, ValueState.DETERMINED, "兼职：本条已上课排课记录计一节 × 该教师/年级确认单价。", (Evidence("PART_TIME_RATE", str(_get(matches[0], "source", "")), record_key=key),), key, teacher, "part_time_fee"))
    return result


def calculate_payroll(period: str, schedule: Iterable[object], rules: CoreRules | Mapping[str, Any], ratings: Iterable[object] = (), profiles: Iterable[object] = (), reference_ratings: Mapping[str, object] | None = None, teacher_contexts: Iterable[object] = (), part_time_rates: Iterable[object] = (), effective_ac: Mapping[str, object] | None = None) -> PayrollResult:
    """Calculate AA/AC/AD/AE/AF and explicit part-time fees for one period.

    Submitted payroll values are intentionally not an input: they remain audit
    targets, not an authority for a new calculation.
    """
    core = rules if isinstance(rules, CoreRules) else CoreRules.from_dict(rules)
    core.require_period(period)
    records = list(schedule)
    for record in records:
        source_period = _get(record, "period", period)
        if source_period != period:
            raise ValueError(f"schedule record period {source_period!r} does not match calculation period {period!r}")
        if not str(_get(record, "teacher", "")):
            raise ValueError("schedule record is missing teacher; cannot silently skip it")
    if effective_ac:
        keys = [course_record_key(record) for record in records]
        ambiguous = {key for key in keys if keys.count(key) > 1}.intersection(effective_ac)
        if ambiguous:
            raise ValueError(f"effective_ac target is ambiguous without distinct source provenance: {sorted(ambiguous)[0]}")
    ratings, profiles, contexts, rates = tuple(ratings), tuple(profiles), tuple(teacher_contexts), tuple(part_time_rates)
    references = dict(reference_ratings or {})
    by_teacher: dict[str, list[object]] = defaultdict(list)
    for record in records:
        teacher = str(_get(record, "teacher", ""))
        if teacher:
            by_teacher[teacher].append(record)
    for context in contexts:
        if _applies(context, period) and _get(context, "teacher"):
            by_teacher.setdefault(str(_get(context, "teacher")), [])
    rows: list[PayrollRow] = []
    all_contributions: list[CourseContribution] = []
    for teacher in sorted(by_teacher):
        teacher_records = by_teacher[teacher]
        context = _context_for(teacher, contexts, period)
        employment = "FULL_TIME" if context is None else _get(context, "employment_type", "FULL_TIME")
        if employment == "PART_TIME":
            contributions = _part_time_contributions(teacher_records, teacher, period, rates, core)
            all_contributions.extend(contributions)
            zero_na = _value(None, ValueState.NOT_APPLICABLE, "兼职不适用 AA/AC/AD/AE/AF 核心折算链。")
            rows.append(PayrollRow(teacher, zero_na, zero_na, zero_na, zero_na, zero_na, _aggregate("part_time_fee", contributions)))
            continue
        contributions = [calculate_course(record, core, effective_ac=effective_ac) for record in teacher_records]
        all_contributions.extend(contributions)
        if not teacher_records and not (employment == "MANAGEMENT" and bool(_get(context, "allow_no_teaching", False))):
            aa = _value(None, ValueState.NEEDS_INPUT, "普通教师没有本期排课来源，不能把未提供的排课汇总为 0。")
            ac = _value(None, ValueState.NEEDS_INPUT, "普通教师没有本期排课来源，不能把未提供的排课汇总为 0。")
        else:
            aa, ac = _aggregate("aa", contributions), _aggregate("ac", contributions)
        if aa.state == ValueState.DETERMINED and ac.state == ValueState.DETERMINED:
            ad_value = aa.value + ac.value
            ad = _value(ad_value, ValueState.DETERMINED, "AD = AA + AC。", Evidence("AD_CALCULATION", detail=f"AA {aa.value} + AC {ac.value} = {ad_value}", formula="AA + AC", inputs={"AA": str(aa.value), "AC": str(ac.value), "AD": str(ad_value)}))
        else:
            ad = _value(None, ValueState.NEEDS_INPUT, "AA 或 AC 未确定，AD 不能把未知贡献当作 0。")
        no_activity_management = (
            employment == "MANAGEMENT"
            and bool(_get(context, "allow_no_teaching", False))
            and not any(item.state == ValueState.NEEDS_INPUT for item in contributions)
            and not any(item.state == ValueState.DETERMINED and item.value for item in contributions)
        )
        if no_activity_management:
            aa, ac, ad = (_value(Decimal("0"), ValueState.DETERMINED, "管理岗位已明确允许无教学活动。") for _ in range(3))
            ae = af = _value(None, ValueState.NOT_APPLICABLE, "管理岗位无教学活动，不适用 AE/AF。")
        else:
            ae, af = _ae_af_for_period(teacher, period, ad, core, ratings, profiles, references)
        rows.append(PayrollRow(teacher, aa, ac, ad, ae, af, _value(None, ValueState.NOT_APPLICABLE, "非兼职不适用按节兼职费。")))
    return PayrollResult(period, core.rule_version_id, tuple(rows), tuple(all_contributions))
