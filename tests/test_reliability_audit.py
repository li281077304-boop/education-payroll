from pathlib import Path

from openpyxl import Workbook

from payroll_core.formula_audit import audit_payroll_formulas
from payroll_core.models.records import PayrollRecord
from payroll_core.rules.authority import TeacherRating, default_compensation_bands, rating_and_rate_checks


def row(name: str, level: str, hours: float, ae: float) -> PayrollRecord:
    return PayrollRecord(period="2026-08", teacher=name, teacher_level=level, teaching_hours=hours, ae=ae)


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
