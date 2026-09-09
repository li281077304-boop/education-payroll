from payroll_core.models.records import PayrollRecord, ScheduleRecord
from payroll_core.reconcile.payroll_scope import rate_and_fee_checks, schedule_field_checks, total_salary_read_checks


def schedule(teacher: str, kind: str, grade: str, attended: int) -> ScheduleRecord:
    return ScheduleRecord("2026-08", teacher, grade, "数学", kind, attended, lesson_status="已上课")


def test_raw_schedule_independently_checks_one_to_one_and_class_value():
    records = [schedule("张三", "1对1", "九年级", 18), schedule("李四", "小班", "八年级", 3)]
    payroll = [PayrollRecord("2026-08", "张三", one_to_one=36, class_value=0), PayrollRecord("2026-08", "李四", one_to_one=0, class_value=2.16)]

    checks = {(item.teacher, item.field): item for item in schedule_field_checks(records, payroll)}

    assert checks[("张三", "one_to_one")].status == "MATCH"
    assert checks[("李四", "class_value")].expected == 2.16
    assert checks[("李四", "class_value")].status == "MATCH"


def test_class_unknown_grade_never_becomes_a_match():
    checks = schedule_field_checks([schedule("张三", "小班", "", 3)], [PayrollRecord("2026-08", "张三", class_value=3)])
    assert any(item.field == "class_value" and item.status == "NEEDS_MANUAL_REVIEW" for item in checks)


def test_ae_af_are_formula_rechecks_and_av_is_read_only():
    payroll = PayrollRecord("2026-08", "张三", teaching_hours=80, teacher_level="TR 三星", ae=37, af=1850, av=2200)
    checks = {item.field: item for item in rate_and_fee_checks([payroll])}

    assert checks["ae"].status == "FORMULA_MATCH"
    assert checks["af"].status == "FORMULA_MATCH"
    assert total_salary_read_checks([payroll])[0].status == "READ_ONLY"


def test_missing_independent_star_source_is_manual_not_verified():
    payroll = PayrollRecord("2026-08", "张三", teaching_hours=80, teacher_level="TR", ae=32, af=1600)
    assert {item.status for item in rate_and_fee_checks([payroll])} == {"NEEDS_MANUAL_REVIEW"}


def test_ae_is_zero_when_ad_below_obligation_threshold():
    payroll = PayrollRecord("2026-08", "张三", teaching_hours=29.9, teacher_level="TR 三星", ae=0, af=0)
    checks = {item.field: item for item in rate_and_fee_checks([payroll])}
    assert checks["ae"].expected == 0
    assert checks["af"].expected == 0


def test_ae_obligation_threshold_boundaries():
    at = PayrollRecord("2026-08", "张三", teaching_hours=30, teacher_level="TR 三星", ae=0, af=0)
    above = PayrollRecord("2026-08", "张三", teaching_hours=30.1, teacher_level="TR 三星", ae=35, af=3.5)
    at_checks = {item.field: item for item in rate_and_fee_checks([at])}
    above_checks = {item.field: item for item in rate_and_fee_checks([above])}
    assert at_checks["ae"].expected == 0
    assert above_checks["ae"].expected == 35
