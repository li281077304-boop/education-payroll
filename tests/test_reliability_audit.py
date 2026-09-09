from pathlib import Path

from openpyxl import Workbook

from payroll_core.formula_audit import audit_payroll_formulas
from payroll_core.models.records import PayrollRecord
from payroll_core.rules.authority import TeacherCompensationProfile, TeacherRating, default_compensation_bands, policy_fee_checks, rating_and_rate_checks


def row(name: str, level: str, hours: float, ae: float, af: float | None = None) -> PayrollRecord:
    return PayrollRecord(period="2026-08", teacher=name, teacher_level=level, teaching_hours=hours, ae=ae, af=af)


def test_wrong_teacher_rating_is_detected():
    checks = rating_and_rate_checks([row("张三", "三星", 70, 42)], [TeacherRating("张三", 4, effective_from="2025-10", effective_to="2026-09", source="年度星级评定")], default_compensation_bands(), "2026-08")
    assert next(item for item in checks if item.field == "rating").status == "RATING_MISMATCH"


def test_correct_band_wrong_amount_is_detected():
    checks = rating_and_rate_checks([row("张三", "四星", 70, 41)], [TeacherRating("张三", 4, effective_from="2025-10", effective_to="2026-09")], default_compensation_bands(), "2026-08")
    rate = next(item for item in checks if item.field == "rate")
    assert rate.status == "RATE_MISMATCH"
    assert rate.expected == 42


def _formula_book(path: Path, formulas: list[object]) -> None:
    book = Workbook(); sheet = book.active
    sheet["C3"] = "姓名"
    for row_no, formula in enumerate(formulas, start=5):
        sheet[f"C{row_no}"] = f"教师{row_no}"
        sheet[f"AA{row_no}"] = 10
        sheet[f"AD{row_no}"] = 40
        sheet[f"AE{row_no}"] = formula
    book.save(path)


def test_formula_replaced_by_manual_value_is_detected(tmp_path):
    path = tmp_path / "formula.xlsx"; _formula_book(path, ["=AD5+AA5", "=AD6+AA6", 850, "=AD8+AA8"])
    assert "FORMULA_REPLACED_BY_VALUE" in {item.status for item in audit_payroll_formulas(path, {"AE": "AE"})}


def test_formula_row_reference_shift_is_detected(tmp_path):
    path = tmp_path / "formula.xlsx"; _formula_book(path, ["=AD5+AA5", "=AD6+AA6", "=AD6+AA7", "=AD8+AA8"])
    assert "ROW_REFERENCE_SHIFT" in {item.status for item in audit_payroll_formulas(path, {"AE": "AE"})}


def test_formula_column_reference_shift_is_detected(tmp_path):
    path = tmp_path / "formula.xlsx"; _formula_book(path, ["=AD5+AA5", "=AD6+AA6", "=AD7+AB7", "=AD8+AA8"])
    assert "COLUMN_REFERENCE_SHIFT" in {item.status for item in audit_payroll_formulas(path, {"AE": "AE"})}


def test_missing_formula_is_detected(tmp_path):
    path = tmp_path / "formula.xlsx"; _formula_book(path, ["=AD5+AA5", "=AD6+AA6", None, "=AD8+AA8"])
    assert "FORMULA_MISSING" in {item.status for item in audit_payroll_formulas(path, {"AE": "AE"})}


def test_historical_run_keeps_original_rating_version():
    old = TeacherRating("张三", 4, effective_from="2025-10", effective_to="2026-09", source_version="2025")
    new = TeacherRating("张三", 3, effective_from="2026-10", effective_to="2027-09", source_version="2026")
    checks = rating_and_rate_checks([row("张三", "四星", 70, 42)], [old, new], default_compensation_bands(), "2026-08")
    assert next(item for item in checks if item.field == "rating").status == "MATCH"


def test_october_requires_new_rating_confirmation():
    old = TeacherRating("张三", 4, effective_from="2025-10", effective_to="2026-09")
    checks = rating_and_rate_checks([row("张三", "四星", 70, 42)], [old], default_compensation_bands(), "2026-10")
    assert next(item for item in checks if item.field == "rating").status == "MISSING_AUTHORITY"


def test_blank_payroll_rating_can_be_an_explicit_one_star_policy():
    authority = TeacherRating("教师甲", 1, effective_from="2025-10", effective_to="2026-09", allow_blank_payroll_rating=True)
    checks = rating_and_rate_checks([row("教师甲", "兼职MT", 70, 32)], [authority], default_compensation_bands(), "2026-08")
    assert next(item for item in checks if item.field == "rating").status == "MATCH"


def test_under_thirty_hours_has_zero_rate_even_when_policy_rating_is_higher():
    bands = default_compensation_bands()
    matched = [item for item in bands if item.applies_to("2026-08", "教师", 20) and item.rating == 4]
    assert len(matched) == 1
    assert matched[0].base_amount + matched[0].rating_bonus == 0


def test_same_trmt_identity_can_have_different_obligation_hour_policy():
    bands = default_compensation_bands()
    profiles = [
        TeacherCompensationProfile("教师甲", "TRMT", 4, special_approval="保留四星待遇", obligation_hours=30, obligation_hours_deduction_enabled=True, effective_from="2025-10", effective_to="2026-09"),
        TeacherCompensationProfile("教师乙", "TRMT", 2, obligation_hours=30, obligation_hours_deduction_enabled=False, effective_from="2025-10", effective_to="2026-09"),
    ]
    # 70 小时、四星对应 42；扣 30 小时后为 40*42。二星对应 32 且不扣。
    payroll = [row("教师甲", "TRMT 四星", 70, 42, 1680), row("教师乙", "TRMT 二星", 70, 32, 2240)]
    checks = policy_fee_checks(payroll, profiles, bands, "2026-08")
    assert {item.teacher: item.status for item in checks} == {"教师甲": "AF_POLICY_MATCH", "教师乙": "AF_POLICY_MATCH"}


def test_profile_special_approval_is_not_inferred_from_trmt_text():
    profile = TeacherCompensationProfile("教师甲", "TRMT", 4, rating_override=4, special_approval="书面特批", obligation_hours=30, obligation_hours_deduction_enabled=True, effective_from="2025-10", effective_to="2026-09")
    payroll = [row("教师甲", "TRMT 四星", 70, 42, 2940)]
    check = policy_fee_checks(payroll, [profile], default_compensation_bands(), "2026-08")[0]
    assert check.status == "AF_POLICY_MISMATCH"
    assert "义务课时：30" in check.reason


def test_policy_fee_ignores_binary_float_representation_noise():
    profile = TeacherCompensationProfile("教师甲", "教师", 6, obligation_hours=30, obligation_hours_deduction_enabled=True, effective_from="2025-10", effective_to="2026-09")
    payroll = [row("教师甲", "六星", 178.55, 58, 8615.9)]

    assert policy_fee_checks(payroll, [profile], default_compensation_bands(), "2026-08")[0].status == "AF_POLICY_MATCH"
