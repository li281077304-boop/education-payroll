from __future__ import annotations

from decimal import Decimal

from payroll_core.calculation import ValueState, calculate_payroll
from payroll_core.config.core_rules import load_core_rules
from payroll_core.models.records import ScheduleRecord
from payroll_ui.service import PayrollService


def lesson(**extra):
    value = {
        "period": "2026-08", "teacher": "兼职甲", "grade": "高一",
        "subject": "数学", "class_type": "1对1", "attended": 1,
        "lesson_status": "已上课", "student_id": "student-1", "class_id": "class-1",
    }
    value.update(extra)
    return value


def result(records, rates):
    return calculate_payroll("2026-08", records, load_core_rules(), teacher_contexts=[{"teacher": "兼职甲", "employment_type": "PART_TIME", "effective_from": "2026-08", "effective_to": "2026-08"}], part_time_rates=rates)


def test_coefficient_based_teacher_grade_rate_reuses_core_coefficients():
    records = [lesson(class_type="1对1"), lesson(student_id="student-2", class_id="class-2", class_type="1对2", attended=2)]
    rates = [{"teacher": "兼职甲", "grade": "高一", "pricing_mode": "COEFFICIENT_BASED", "base_rate": 170, "effective_from": "2026-08", "effective_to": "2026-08", "source": "政策"}]
    row = result(records, rates).rows[0]
    assert row.part_time_fee.value == Decimal("374")
    assert [c.value for c in result(records, rates).course_contributions if c.field == "part_time_fee"] == [Decimal("170"), Decimal("204")]


def test_fixed_grade_rate_ignores_class_headcount():
    records = [lesson(class_type="1对1"), lesson(student_id="student-2", class_id="class-2", class_type="1对2", attended=2)]
    rates = [{"teacher": "兼职甲", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 180, "effective_from": "2026-08", "effective_to": "2026-08", "source": "政策"}]
    assert result(records, rates).rows[0].part_time_fee.value == Decimal("360")


def test_target_override_wins_and_clearing_restores_grade_rule():
    records = [lesson(), lesson(student_id="student-2", class_id="class-2")]
    base = {"teacher": "兼职甲", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 170, "effective_from": "2026-08", "effective_to": "2026-08", "source": "政策"}
    overridden = [base, {**base, "student_id": "student-2", "override_rate": 190}]
    assert result(records, overridden).rows[0].part_time_fee.value == Decimal("360")
    cleared = [base]
    assert result(records, cleared).rows[0].part_time_fee.value == Decimal("340")


def test_target_override_row_keeps_grade_base_for_other_targets():
    records = [lesson(), lesson(student_id="student-2", class_id="class-2")]
    rates = [{"teacher": "兼职甲", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 170,
              "student_id": "student-2", "override_rate": 190}]
    contributions = [c.value for c in result(records, rates).course_contributions if c.field == "part_time_fee"]
    assert contributions == [Decimal("170"), Decimal("190")]


def test_personal_policy_rate_outranks_shared_part_time_rate():
    records = [lesson()]
    rates = [
        {"teacher": "兼职甲", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 170, "policy_type": "PART_TIME_RATE", "effective_from": "2026-08", "effective_to": "2026-08", "source": "共享政策"},
        {"teacher": "兼职甲", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 190, "policy_type": "PERSONAL_POLICY", "effective_from": "2026-08", "effective_to": "2026-08", "source": "个人政策"},
    ]
    assert result(records, rates).rows[0].part_time_fee.value == Decimal("190")


def test_same_display_name_with_distinct_teacher_ids_fails_closed():
    rates = [
        {"teacher": "刘雨", "teacher_id": "teacher-a", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 140,
         "effective_from": "2026-08", "effective_to": "2026-08", "source": "政策"},
        {"teacher": "刘雨", "teacher_id": "teacher-b", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 160,
         "effective_from": "2026-08", "effective_to": "2026-08", "source": "政策"},
    ]
    checked = calculate_payroll(
        "2026-08", [lesson(teacher="刘雨")], load_core_rules(),
        teacher_contexts=[{"teacher": "刘雨", "employment_type": "PART_TIME"}],
        part_time_rates=rates,
    )
    assert checked.rows[0].part_time_fee.state == ValueState.NEEDS_INPUT


def test_missing_teacher_grade_rule_is_needs_price():
    row = result([lesson()], []).rows[0]
    assert row.part_time_fee.state == ValueState.NEEDS_INPUT


def test_historical_or_expired_part_time_rate_does_not_enter_new_period():
    historical = [{"teacher": "兼职甲", "grade": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 140,
                   "effective_from": "2026-07", "effective_to": "2026-07", "source": "历史工资表",
                   "policy_type": "HISTORICAL_EVIDENCE"}]
    assert result([lesson()], historical).rows[0].part_time_fee.state == ValueState.NEEDS_INPUT


def test_july_rate_does_not_carry_into_august_run(tmp_path):
    service = PayrollService(tmp_path / "data")
    service.save_part_time_rate_version([
        {"teacher": "兼职甲", "grade_scope": "*", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 140},
    ], "July 历史证据", "2026-07", "2026-07", "审核员")
    august = service.create("2026-08", "GENERATE")
    assert august["part_time_rate_version_id"] is None
    assert august["run_policy_snapshot"]["part_time_rates"] == []


def test_run_pricing_snapshot_is_immune_to_later_policy_edit(tmp_path):
    service = PayrollService(tmp_path / "data")
    version = service.save_part_time_rate_version([{"teacher": "兼职甲", "grade_scope": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 170}], "本月政策", "2026-08", "2026-08", "审核员")[0]
    run = service.create("2026-08", "GENERATE")
    assert run["part_time_rate_version_id"] == version["id"]
    snapshot = run["run_policy_snapshot"]
    service.save_part_time_rate_version([{"teacher": "兼职甲", "grade_scope": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 210}], "修订政策", "2026-08", "2026-08", "审核员")
    restored = service.store.get(run["id"])
    assert restored["run_policy_snapshot"] == snapshot
    assert service._calculation_version(restored, "part_time")["profiles"][0]["fixed_rate"] == 170


def test_run_part_time_pricing_snapshot_records_effective_lesson_inputs(tmp_path):
    service = PayrollService(tmp_path / "data")
    service.save_part_time_rate_version([{
        "teacher": "兼职甲", "grade_scope": "高一", "pricing_mode": "COEFFICIENT_BASED", "base_rate": 170,
        "student_id": "s-1", "override_rate": 190,
    }], "本月生产兼职政策", "2026-08", "2026-08", "审核员")
    run = service.create("2026-08", "GENERATE")
    record = ScheduleRecord("2026-08", "兼职甲", "高一", "数学", "1对1", 1, "已上课", student_id="s-1", class_id="c-1")
    calculated = service._configured_calculation(run, [record], [])
    snapshot = service._build_part_time_pricing_snapshot(run, [record], calculated)
    assert snapshot["version"] == "RUN_PART_TIME_PRICING_SNAPSHOT/v1"
    assert snapshot["entries"][0]["pricing_mode"] == "COEFFICIENT_BASED"
    assert snapshot["entries"][0]["target_override"] == 190.0
    assert snapshot["entries"][0]["final_rate"] == 190.0


def test_registry_exposes_default_active_and_expired_policy_rows(tmp_path):
    service = PayrollService(tmp_path / "data")
    service.save_part_time_rate_version([{"teacher": "刘雨", "teacher_id": "t-liuyu", "grade_scope": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 140}], "生产政策", "2026-08", "2026-08", "审核员")
    service.save_part_time_rate_version([{"teacher": "张祥", "grade_scope": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 160}], "过期政策", "2026-07", "2026-07", "审核员")
    rows = service.payroll_policy_registry(period="2026-08")["rows"]
    assert any(row["policy_type"] == "DEFAULT_FULL_TIME" and row["status"] == "ACTIVE" for row in rows)
    active = next(row for row in rows if row["display_name"] == "刘雨")
    assert active["status"] == "ACTIVE" and active["teacher_id"] == "t-liuyu"
    expired = next(row for row in rows if row["display_name"] == "张祥")
    assert expired["status"] == "EXPIRED"


def test_service_uses_active_part_time_version_as_employment_context(tmp_path):
    """A production PART_TIME_RATE alone must enter the existing Core path."""
    service = PayrollService(tmp_path / "data")
    version = service.save_part_time_rate_version([
        {"teacher": "兼职甲", "grade_scope": "高一", "pricing_mode": "FIXED_GRADE_RATE", "fixed_rate": 180},
    ], "本月生产兼职政策", "2026-08", "2026-08", "审核员")[0]
    run = service.create("2026-08", "GENERATE")
    record = ScheduleRecord("2026-08", "兼职甲", "高一", "数学", "1对1", 1, "已上课", student_id="s-1", class_id="c-1")
    calculated = service._configured_calculation(run, [record], [])
    row = calculated["rows"][0]
    assert run["part_time_rate_version_id"] == version["id"]
    assert row["employment_type"] == "PART_TIME"
    assert row["fields"]["PART_TIME"]["value"] == 180.0


def test_missing_part_time_rate_stays_needs_price_not_full_time(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    run["personnel_contexts"] = [{"teacher": "兼职甲", "employment_type": "PART_TIME", "effective_from": "2026-08", "effective_to": "2026-08", "source": "人员资料"}]
    record = ScheduleRecord("2026-08", "兼职甲", "高一", "数学", "1对1", 1, "已上课", student_id="s-1", class_id="c-1")
    row = service._configured_calculation(run, [record], [])["rows"][0]
    assert row["employment_type"] == "PART_TIME"
    assert row["fields"]["PART_TIME"]["state"] == "NEEDS_INPUT"
