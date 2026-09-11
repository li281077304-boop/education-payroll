from pathlib import Path

from openpyxl import Workbook

from payroll_core.grade_inference import StudentGradeEvidence, infer_historical_grade
from payroll_core.excel.schedule import read_schedule_excel
from payroll_ui.service import PayrollService


def evidence(student: str, day: str, grade: str, *, source_hash: str = "h1") -> StudentGradeEvidence:
    return StudentGradeEvidence(student, day, grade, "历史课表.xlsx", source_hash, "课表", "A2")


def test_july_eighth_grade_stays_eighth_in_august():
    result = infer_historical_grade("学生甲", "2026-08", [evidence("学生甲", "2026-07-18", "八年级")])
    assert (result.grade, result.status) == ("八年级", "DETERMINED")


def test_july_eighth_grade_advances_to_ninth_in_september():
    result = infer_historical_grade("学生甲", "2026-09", [evidence("学生甲", "2026-07-18", "八年级")])
    assert result.grade == "九年级"


def test_august_sixth_grade_advances_to_seventh_in_september():
    result = infer_historical_grade("学生甲", "2026-09", [evidence("学生甲", "2026-08-28", "六年级")])
    assert result.grade == "七年级"


def test_consistent_history_is_automatic_even_across_academic_boundary():
    result = infer_historical_grade("学生甲", "2026-09", [
        evidence("学生甲", "2026-06-12", "八年级", source_hash="v1"),
        evidence("学生甲", "2026-07-19", "八年级", source_hash="v2"),
    ])
    assert result.grade == "九年级" and len(result.evidence) == 2


def test_conflicting_history_needs_input_instead_of_picking_latest_export():
    result = infer_historical_grade("学生甲", "2026-08", [
        evidence("学生甲", "2026-07-18", "八年级", source_hash="old-export"),
        evidence("学生甲", "2026-07-18", "九年级", source_hash="new-export"),
    ])
    assert result.grade == "" and result.status == "NEEDS_INPUT"
    assert "冲突" in result.reason


def test_only_ungradable_special_lessons_need_input():
    result = infer_historical_grade("学生甲", "2026-08", [
        evidence("学生甲", "2026-07-18", "领航伴学"),
        evidence("学生甲", "2026-07-25", "雅思"),
    ])
    assert result.grade == "" and result.status == "NEEDS_INPUT"


def _gift_workbook(path: Path, class_name: str = "赠送课程", student: str = "学生甲", lesson_time: str = "2026-08-03 09:00") -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "排课记录-08月03日到08月30日"
    headers = ["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"]
    sheet.append(headers)
    sheet.append([class_name, "一对一", lesson_time, "已上课", 1, student, "数学", "教师甲"])
    book.save(path)
    return path


def test_current_course_direct_grade_is_never_overridden_by_history(tmp_path):
    path = _gift_workbook(tmp_path / "direct.xlsx", "八年级数学")
    result = read_schedule_excel(path, "2026-08", historical_grade_evidence=[evidence("学生甲", "2026-07-18", "九年级")])
    assert result.records[0].grade == "八年级"
    assert result.records[0].grade_origin == "DIRECT_SOURCE"


def test_adapter_uses_history_before_legacy_csv_for_missing_current_grade(tmp_path):
    path = _gift_workbook(tmp_path / "gift.xlsx", lesson_time="2026-09-03 09:00")
    result = read_schedule_excel(
        path, "2026-09", student_grades={"学生甲": "八年级"},
        historical_grade_evidence=[evidence("学生甲", "2026-07-18", "八年级")],
    )
    # A dated history fact is more current than an undated compatibility CSV.
    assert result.records[0].grade == "九年级"
    assert result.records[0].grade_origin == "HISTORICAL_SCHEDULE"


def test_manual_confirmation_persists_and_is_reused(tmp_path):
    service = PayrollService(tmp_path / "local")
    saved = service.save_student_grade_confirmation("学生甲", "八年级", "2026-08", "审核人", "赠送课确认")
    assert saved["origin"] == "MANUAL_CONFIRMATION"
    manual, history = PayrollService(tmp_path / "local")._stored_grade_evidence()
    assert len(manual) == 1 and not history
    path = _gift_workbook(tmp_path / "gift.xlsx")
    result = read_schedule_excel(path, "2026-08", manual_grade_evidence=manual)
    assert result.records[0].grade == "八年级"
    assert result.records[0].grade_origin == "MANUAL_CONFIRMATION"


def test_historical_schedule_import_keeps_minimum_dated_evidence_only(tmp_path):
    service = PayrollService(tmp_path / "local")
    source = _gift_workbook(tmp_path / "history.xlsx", "八年级数学")
    imported = service.import_grade_history(str(source), "2026-08")
    assert imported["direct_grade_evidence"] == 1
    manual, history = service._stored_grade_evidence()
    assert not manual and len(history) == 1
    assert history[0].student == "学生甲" and history[0].lesson_date == "2026-08-03"
    # The durable evidence points back to its source; it does not store a copy
    # of the workbook or any schedule rows unrelated to grade inference.
    stored = service.store.list_student_grade_evidence()[0]
    assert stored["source_hash"] and stored["source_file"].endswith("history.xlsx")


def test_saved_history_is_used_by_a_later_monthly_schedule_import(tmp_path):
    service = PayrollService(tmp_path / "local")
    history = _gift_workbook(tmp_path / "july.xlsx", "八年级数学", lesson_time="2026-07-18 09:00")
    service.import_grade_history(str(history), "2026-07")
    run = service.create("2026-09", "GENERATE")
    current = _gift_workbook(tmp_path / "september-gift.xlsx", lesson_time="2026-09-03 09:00")
    service.import_file(run["id"], "schedule", str(current))
    imported = service._read("schedule", current, "2026-09")
    assert imported.records[0].grade == "九年级"
    assert imported.records[0].grade_origin == "HISTORICAL_SCHEDULE"


def test_legacy_student_grade_lookup_remains_compatible(tmp_path):
    path = _gift_workbook(tmp_path / "gift.xlsx")
    result = read_schedule_excel(path, "2026-08", student_grades={"学生甲": "初二"})
    assert result.records[0].grade == "八年级"
    assert result.records[0].grade_origin == "MANUAL_LOOKUP"
