"""Regression contract for the isolated versioned Core calculation chain."""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json

import pytest

from payroll_core.calculation import (
    CompensationProfile,
    RatingAuthority,
    TeacherContext,
    ValueState,
    calculate_course,
    calculate_payroll,
)
from payroll_core.config.core_rules import CoreRules, load_core_rules
from payroll_core.models.evidence import CellValueState, SourceEvidence
from payroll_core.models.records import ScheduleRecord


def record(**overrides):
    base = {
        "period": "2026-08", "teacher": "教师甲", "grade": "八年级",
        "subject": "数学", "class_type": "1对1", "attended": 2,
        "lesson_status": "已上课", "source": "synthetic.xlsx",
    }
    base.update(overrides)
    return base


def row(result, teacher="教师甲"):
    return next(item for item in result.rows if item.teacher == teacher)


def approved_profile(**overrides):
    base = {
        "teacher": "教师甲", "obligation_hours": 30, "deduction_enabled": True,
        "effective_from": "2026-08", "effective_to": "2026-09", "source": "个人确认政策",
    }
    base.update(overrides)
    return base


def test_rule_bundle_round_trips_as_json_and_is_not_future_policy():
    rules = load_core_rules()
    assert CoreRules.from_dict(json.loads(json.dumps(rules.to_dict()))) == rules
    assert rules.rule_version_id == "core_rules_2026_08_09_v1"
    assert rules.covers("2026-08") and rules.covers("2026-09")
    with pytest.raises(ValueError, match="does not cover"):
        rules.require_period("2026-10")


def test_aa_ac_ad_keep_chains_independent_and_special_precedes_headcount():
    rules = load_core_rules()
    result = calculate_payroll("2026-08", [
        record(class_type="1对1", attended=2),
        record(class_type="1对2", attended=2),  # 配置值 1.2，不乘小班人数系数 1.0
        record(class_type="1对3", attended=3),  # 配置值 1.5，不乘小班人数系数 1.2
        record(class_type="小班", attended=4),
    ], rules)
    calculated = row(result)
    assert calculated.aa.value == Decimal("3.6")
    assert calculated.ac.value == Decimal("7.38")  # 2.16 + 2.7 + 2.52
    assert calculated.ad.value == Decimal("10.98")
    assert calculated.ae.value == calculated.af.value == Decimal("0")
    assert "不乘普通小班人数系数" in next(item.reason for item in result.course_contributions if item.field == "ac" and "特殊班" in item.reason)
    # 特殊班型没有配置的人数组合：不许退回普通小班人数系数，直接 NEEDS_INPUT。
    unconfigured = calculate_course(record(class_type="1对2", attended=9), rules)
    assert unconfigured.value is None and unconfigured.state == ValueState.NEEDS_INPUT
    assert "UNKNOWN_CLASS_RULE" in unconfigured.reason


def test_user_acceptance_special_classes_do_not_use_small_group_headcount():
    rules = load_core_rules()
    one_to_two = calculate_course(record(class_type="1对2", attended=2), rules)
    small_two = calculate_course(record(class_type="小班", attended=2), rules)
    one_to_three = calculate_course(record(class_type="1对3", attended=3), rules)
    small_three = calculate_course(record(class_type="小班", attended=3), rules)
    assert (one_to_two.value, small_two.value) == (Decimal("2.16"), Decimal("1.80"))
    assert (one_to_three.value, small_three.value) == (Decimal("2.70"), Decimal("2.16"))


def test_effective_ac_injection_is_explicit_and_unknown_never_becomes_zero():
    rules = load_core_rules()
    unknown = record(class_type="新班型")
    initial = calculate_course(unknown, rules)
    assert initial.value is None and initial.state == ValueState.NEEDS_INPUT
    blocked = calculate_payroll("2026-08", [unknown], rules, effective_ac={initial.record_key: Decimal("4.2")})
    assert row(blocked).ac.state == ValueState.NEEDS_INPUT
    known = record(class_type="1对2")
    known_initial = calculate_course(known, rules)
    result = calculate_payroll("2026-08", [known], rules, effective_ac={known_initial.record_key: Decimal("4.2")})
    assert row(result).ac.value == Decimal("4.2")
    assert row(result).aa.value == Decimal("0")
    assert row(result).ad.value == Decimal("4.2"), "the confirmed resolution explicitly classifies this record as AC"


def test_schedule_provenance_keeps_identical_rows_and_overrides_independent():
    rules = load_core_rules()
    def scheduled(coordinate: str) -> ScheduleRecord:
        evidence = SourceEvidence("source.xlsx", "排课", coordinate, "班型", "1对2", "1对2", CellValueState.RAW_VALUE)
        return ScheduleRecord("2026-08", "教师甲", "八年级", "数学", "1对2", 2, lesson_status="已上课", source="source.xlsx", provenance={"class_type": evidence})
    first, second = scheduled("E5"), scheduled("E6")
    first_key, second_key = calculate_course(first, rules).record_key, calculate_course(second, rules).record_key
    assert first_key != second_key
    result = calculate_payroll("2026-08", [first, second], rules, effective_ac={first_key: Decimal("4.2")})
    assert row(result).ac.value == Decimal("6.36")
    assert any(item.record_key == first_key and item.value == Decimal("4.2") for item in result.course_contributions)
    assert any(item.record_key == second_key and item.value == Decimal("2.16") for item in result.course_contributions)


def test_unknown_lesson_status_requires_input_and_known_non_teaching_status_is_excluded():
    rules = load_core_rules()
    blank = calculate_course(record(class_type="小班", lesson_status=""), rules)
    assert blank.state == ValueState.NEEDS_INPUT and blank.field == "ac"
    assert calculate_course(record(lesson_status="待确认"), rules).state == ValueState.NEEDS_INPUT
    assert calculate_course(record(lesson_status="已取消"), rules).state == ValueState.NOT_APPLICABLE


def test_zero_attendance_is_not_an_unknown_contribution_or_a_hidden_zero_grade():
    result = calculate_payroll("2026-08", [record(class_type="1对1", grade="", attended=0)], load_core_rules())
    contribution = result.course_contributions[0]
    assert contribution.state == ValueState.NOT_APPLICABLE
    assert contribution.value == Decimal("0")
    assert row(result).aa.value == row(result).ac.value == row(result).ad.value == Decimal("0")


def test_unknown_ac_grade_blocks_only_ac_and_evidence_contains_hand_calculation_inputs():
    rules = load_core_rules()
    result = calculate_payroll("2026-08", [record(class_type="1对1"), record(class_type="小班", grade="未配置年级")], rules)
    calculated = row(result)
    assert calculated.aa.value == Decimal("3.6") and calculated.aa.state == ValueState.DETERMINED
    assert calculated.ac.state == calculated.ad.state == ValueState.NEEDS_INPUT
    special = calculate_course(record(class_type="1对2", attended=2), rules)
    evidence = special.evidence[0]
    assert evidence.formula == "grade_coefficient × special_multiplier(class_type, attended) × lesson_hour_factor"
    assert evidence.inputs["grade_coefficient"] == "0.9"
    assert evidence.inputs["special_multiplier"] == "1.2"
    assert evidence.inputs["attended"] == "2"
    assert evidence.inputs["lesson_hour_factor"] == "2"
    assert "= 2.16" in evidence.detail


def test_excluded_accompaniment_grade_is_not_applicable_and_does_not_enter_ad():
    result = calculate_payroll("2026-08", [record(grade="领航伴学")], load_core_rules())
    contribution = result.course_contributions[0]
    assert contribution.state == ValueState.NOT_APPLICABLE
    assert row(result).aa.value == row(result).ac.value == row(result).ad.value == Decimal("0")


def test_ae_authority_reference_and_missing_rating_states():
    rules = load_core_rules()
    classes = [record() for _ in range(10)]  # AA = 36
    authoritative = calculate_payroll("2026-08", classes, rules, ratings=[RatingAuthority("教师甲", 3, "2026-08", "2026-09", "星级权威")], profiles=[approved_profile()])
    assert row(authoritative).ae.value == Decimal("35")
    assert row(authoritative).ae.state == ValueState.DETERMINED
    assert row(authoritative).af.value == Decimal("210")
    assert row(authoritative).ae.evidence[0].inputs == {"AD": "36.0", "tier_base": "30", "rating": "3", "star_bonus": "5", "AE": "35"}
    referenced = calculate_payroll("2026-08", classes, rules, reference_ratings={"教师甲": 4}, profiles=[approved_profile()])
    assert row(referenced).ae.value == Decimal("40") and row(referenced).ae.state == ValueState.ESTIMATED
    assert row(referenced).af.state == ValueState.ESTIMATED
    missing = calculate_payroll("2026-08", classes, rules, profiles=[approved_profile()])
    assert row(missing).ae.state == row(missing).af.state == ValueState.NEEDS_INPUT


def test_ae_threshold_comes_from_first_tier_and_has_no_decimal_epsilon_gap():
    rules = load_core_rules()
    assert rules.ae_zero_threshold == Decimal("30")
    assert rules.ae_tier(Decimal("30")).id == "zero_to_30"
    assert rules.ae_tier(Decimal("30.0000000000000000001")).id == "30_to_60"
    assert rules.ae_tier(Decimal("60")).id == "30_to_60"
    assert rules.ae_tier(Decimal("60.0000000000000000001")).id == "60_to_80"


def test_user_acceptance_ae_boundaries_run_through_new_calculation_chain():
    """AE/AF stay zero at or below the first-tier threshold (AD = 30).

    AD is AA + AC. One 1对1 lesson with a single attending student contributes
    ``attended(1) x lesson_hour_factor(2) x grade_coefficient``, so the desired
    AD is reached by halving it into the grade coefficient.
    """
    raw = load_core_rules().to_dict()

    def boundary(ad: str):
        coefficient = Decimal(ad) / 2
        local = CoreRules.from_dict({**raw, "grade_coefficients": {"边界年级": str(coefficient)}})
        return calculate_payroll(
            "2026-08", [record(grade="边界年级", attended=1)], local,
            ratings=[RatingAuthority("教师甲", 1, "2026-08", "2026-09", "权威")],
            profiles=[approved_profile()],
        )

    assert row(boundary("29.9")).ae.value == row(boundary("29.9")).af.value == Decimal("0")
    assert row(boundary("30")).ae.value == row(boundary("30")).af.value == Decimal("0")
    above = row(boundary("30.1"))
    assert above.ad.value == Decimal("30.1") and above.ae.value == Decimal("30") and above.af.value == Decimal("3.0")


def test_af_honors_new_and_old_deduction_enabled_names():
    rules = load_core_rules()
    classes = [record() for _ in range(10)]
    rating = [RatingAuthority("教师甲", 3, "2026-08", "2026-09", "星级权威")]
    old_profile = {"teacher": "教师甲", "obligation_hours": 30, "obligation_hours_deduction_enabled": False, "effective_from": "2026-08", "effective_to": "2026-09", "source": "旧个人政策"}
    result = calculate_payroll("2026-08", classes, rules, ratings=rating, profiles=[old_profile])
    assert row(result).af.value == Decimal("1260"), "deduction disabled means AD × AE"
    result = calculate_payroll("2026-08", classes, rules, ratings=rating, profiles=[approved_profile(deduction_enabled=True)])
    assert row(result).af.value == Decimal("210")


def test_user_acceptance_two_explicit_trmt_policies_and_approved_override():
    rules = load_core_rules()
    lessons = [record(teacher="TRMT甲") for _ in range(10)] + [record(teacher="TRMT乙") for _ in range(10)]
    authorities = [RatingAuthority("TRMT甲", 3, "2026-08", "2026-09", "权威"), RatingAuthority("TRMT乙", 3, "2026-08", "2026-09", "权威")]
    profiles = [
        {"teacher": "TRMT甲", "obligation_hours": 0, "deduction_enabled": False, "effective_from": "2026-08", "effective_to": "2026-09", "source": "TRMT甲个人政策", "rating_override": 6, "approved_by": "主管", "approved_at": "2026-08-31"},
        {"teacher": "TRMT乙", "obligation_hours": 30, "deduction_enabled": True, "effective_from": "2026-08", "effective_to": "2026-09", "source": "TRMT乙个人政策"},
    ]
    result = calculate_payroll("2026-08", lessons, rules, ratings=authorities, profiles=profiles)
    first, second = row(result, "TRMT甲"), row(result, "TRMT乙")
    assert (first.ae.value, first.af.value) == (Decimal("50"), Decimal("1800.0"))
    assert (second.ae.value, second.af.value) == (Decimal("35"), Decimal("210.0"))
    assert first.af.state == second.af.state == ValueState.DETERMINED


def test_incomplete_policy_and_unapproved_override_cannot_be_silently_applied():
    rules = load_core_rules()
    classes = [record() for _ in range(10)]
    rating = [RatingAuthority("教师甲", 3, "2026-08", "2026-09", "星级权威")]
    incomplete = calculate_payroll("2026-08", classes, rules, ratings=rating, profiles=[{"teacher": "教师甲", "obligation_hours": 30, "deduction_enabled": True}])
    assert row(incomplete).af.state == ValueState.NEEDS_INPUT
    unapproved = calculate_payroll("2026-08", classes, rules, ratings=rating, profiles=[approved_profile(rating_override=6)])
    assert row(unapproved).ae.state == row(unapproved).af.state == ValueState.NEEDS_INPUT
    assert "不能静默忽略" in row(unapproved).ae.reason


def test_part_time_uses_one_active_record_per_lesson_and_wildcard_rate():
    rules = load_core_rules()
    result = calculate_payroll("2026-08", [record(teacher="兼职甲", grade="七年级", attended=None), record(teacher="兼职甲", grade="八年级", class_type="小班", attended=8)], rules, teacher_contexts=[TeacherContext("兼职甲", "PART_TIME", effective_from="2026-08", effective_to="2026-09")], part_time_rates=[{"teacher": "兼职甲", "grade": "*", "rate_per_lesson": 170, "effective_from": "2026-08", "effective_to": "2026-09", "approved_by": "主管", "approved_at": "2026-08-31", "source": "本月确认"}])
    calculated = row(result, "兼职甲")
    assert calculated.part_time_fee.value == Decimal("340")
    assert all(getattr(calculated, field).state == ValueState.NOT_APPLICABLE for field in ("aa", "ac", "ad", "ae", "af"))


def test_user_acceptance_part_time_grade_rates_missing_and_double_match_need_input():
    rules = load_core_rules()
    context = [TeacherContext("兼职乙", "PART_TIME", effective_from="2026-08", effective_to="2026-09")]
    lessons = [record(teacher="兼职乙", grade="七年级"), record(teacher="兼职乙", grade="八年级")]
    rates = [
        {"teacher": "兼职乙", "grade": "七年级", "rate_per_lesson": 100, "effective_from": "2026-08", "effective_to": "2026-09", "approved_by": "主管", "approved_at": "2026-08-31", "source": "确认"},
        {"teacher": "兼职乙", "grade": "八年级", "rate_per_lesson": 200, "effective_from": "2026-08", "effective_to": "2026-09", "approved_by": "主管", "approved_at": "2026-08-31", "source": "确认"},
    ]
    assert row(calculate_payroll("2026-08", lessons, rules, teacher_contexts=context, part_time_rates=rates), "兼职乙").part_time_fee.value == Decimal("300")
    missing = calculate_payroll("2026-08", [record(teacher="兼职乙", grade="九年级")], rules, teacher_contexts=context, part_time_rates=rates)
    assert row(missing, "兼职乙").part_time_fee.state == ValueState.NEEDS_INPUT
    double = calculate_payroll("2026-08", [record(teacher="兼职乙", grade="七年级")], rules, teacher_contexts=context, part_time_rates=[rates[0], rates[0]])
    assert row(double, "兼职乙").part_time_fee.state == ValueState.NEEDS_INPUT


def test_missing_teacher_and_cross_period_are_errors_not_silent_filters():
    rules = load_core_rules()
    with pytest.raises(ValueError, match="missing teacher"):
        calculate_payroll("2026-08", [record(teacher="")], rules)
    with pytest.raises(ValueError, match="does not match"):
        calculate_payroll("2026-08", [record(period="2026-09")], rules)


def test_management_no_teaching_cannot_mask_unknown_course_and_ordinary_no_schedule_is_pending():
    rules = load_core_rules()
    context = TeacherContext("管理甲", "MANAGEMENT", True, "2026-08", "2026-09", "显式管理档案")
    unknown = calculate_payroll("2026-08", [record(teacher="管理甲", class_type="未知班型")], rules, teacher_contexts=[context])
    assert row(unknown, "管理甲").ad.state == ValueState.NEEDS_INPUT
    empty = calculate_payroll("2026-08", [], rules, teacher_contexts=[context])
    assert row(empty, "管理甲").ad.value == Decimal("0") and row(empty, "管理甲").ae.state == ValueState.NOT_APPLICABLE
    ordinary = calculate_payroll("2026-08", [], rules, teacher_contexts=[TeacherContext("教师乙", "FULL_TIME", effective_from="2026-08", effective_to="2026-09")])
    assert row(ordinary, "教师乙").aa.state == row(ordinary, "教师乙").ad.state == ValueState.NEEDS_INPUT


def test_duplicate_class_type_and_invalid_tier_boundaries_fail_configuration():
    raw = load_core_rules().to_dict()
    raw["course_rules"].append({"id": "duplicate", "treatment": "SPECIAL", "class_types": ["1对2"], "coefficients": {"2": "1.9"}})
    with pytest.raises(ValueError, match="duplicate class type"):
        CoreRules.from_dict(raw)
    raw = load_core_rules().to_dict()
    raw["ae"]["tiers"][1]["minimum"] = "30.1"
    with pytest.raises(ValueError, match="boundaries"):
        CoreRules.from_dict(raw)


def test_asdict_and_json_safe_export_keep_every_core_field_state():
    result = calculate_payroll("2026-08", [record()], load_core_rules())
    raw = asdict(result)
    assert set(raw["rows"][0]) >= {"aa", "ac", "ad", "ae", "af"}
    exported = result.as_dict()
    assert exported["rows"][0]["ad"]["value"] == "3.6"
    assert exported["rows"][0]["ad"]["state"] == "DETERMINED"
