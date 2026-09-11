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


def test_eighth_grade_stays_eighth_before_september_twentieth():
    result = infer_historical_grade(
        "学生甲", "2026-09", [evidence("学生甲", "2026-07-18", "八年级")], target_date="2026-09-19",
    )
    assert result.grade == "八年级"


def test_eighth_grade_advances_on_september_twentieth():
    result = infer_historical_grade(
        "学生甲", "2026-09", [evidence("学生甲", "2026-07-18", "八年级")], target_date="2026-09-20",
    )
    assert result.grade == "九年级"


def test_eighth_grade_advances_after_september_twentieth():
    result = infer_historical_grade(
        "学生甲", "2026-09", [evidence("学生甲", "2026-07-18", "八年级")], target_date="2026-09-21",
    )
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


def test_history_older_than_twelve_months_does_not_participate():
    result = infer_historical_grade("学生甲", "2026-09", [evidence("学生甲", "2025-08-31", "八年级")])
    assert result.grade == "" and result.status == "NEEDS_INPUT"


def test_old_history_cannot_create_a_conflict_with_recent_evidence():
    result = infer_historical_grade("学生甲", "2026-09", [
        evidence("学生甲", "2025-08-31", "高三", source_hash="old"),
        evidence("学生甲", "2026-07-18", "八年级", source_hash="recent"),
    ])
    assert result.grade == "九年级" and len(result.evidence) == 1


def test_manual_confirmation_is_not_limited_to_twelve_month_history_window():
    result = infer_historical_grade(
        "学生甲", "2026-08", [evidence("学生甲", "2025-07-18", "八年级")], recent_history_only=False,
    )
    assert result.grade == "九年级"


def test_high_three_does_not_remain_high_three_after_next_september():
    result = infer_historical_grade("学生甲", "2026-09", [evidence("学生甲", "2026-07-18", "高三")])
    assert result.grade == "" and result.status == "NEEDS_INPUT"
    assert "超出" in result.reason


def test_high_two_advances_once_to_high_three():
    result = infer_historical_grade("学生甲", "2026-09", [evidence("学生甲", "2026-07-18", "高二")])
    assert result.grade == "高三"


def test_high_two_advanced_across_two_septembers_becomes_invalid():
    result = infer_historical_grade("学生甲", "2027-09", [evidence("学生甲", "2026-07-18", "高二")])
    assert result.grade == "" and result.status == "NEEDS_INPUT"


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


def test_reliable_student_history_corrects_polluted_current_class_name(tmp_path):
    path = _gift_workbook(tmp_path / "direct.xlsx", "高三数学")
    result = read_schedule_excel(path, "2026-08", historical_grade_evidence=[evidence("学生甲", "2026-07-18", "高二")])
    assert result.records[0].grade == "高二"
    assert result.records[0].grade_origin == "HISTORICAL_SCHEDULE"
    assert "覆盖当前班名" in result.records[0].grade_reason


def test_roster_history_uses_each_student_and_corrects_current_class_name(tmp_path):
    history_service = PayrollService(tmp_path / "local")
    history = _gift_workbook(tmp_path / "history.xlsx", "八年级数学", "学生甲,学生乙", "2026-07-18 09:00")
    imported = history_service.import_grade_history(str(history))
    assert imported["direct_grade_evidence"] == 2
    _manual, stored = history_service._stored_grade_evidence()
    current = _gift_workbook(tmp_path / "current.xlsx", "高三数学", "学生甲,学生乙", "2026-08-03 09:00")
    result = read_schedule_excel(current, "2026-08", historical_grade_evidence=stored)
    assert result.records[0].grade == "八年级"
    assert result.records[0].grade_origin == "HISTORICAL_SCHEDULE"


def test_multi_student_conflicting_history_requires_input(tmp_path):
    current = _gift_workbook(tmp_path / "current.xlsx", "赠送课程", "学生甲,学生乙", "2026-08-03 09:00")
    result = read_schedule_excel(current, "2026-08", historical_grade_evidence=[
        evidence("学生甲", "2026-07-18", "八年级"),
        evidence("学生乙", "2026-07-18", "九年级"),
    ])
    assert result.records[0].grade == ""
    assert result.records[0].grade_origin == "NEEDS_INPUT"
    assert "同一课程" in result.records[0].grade_reason


def test_saved_legacy_confirmation_can_resolve_conflicting_history(tmp_path):
    current = _gift_workbook(tmp_path / "current.xlsx", "赠送课程", "学生甲", "2026-08-03 09:00")
    result = read_schedule_excel(
        current, "2026-08", student_grades={"学生甲": "八年级"}, historical_grade_evidence=[
            evidence("学生甲", "2026-07-18", "八年级", source_hash="v1"),
            evidence("学生甲", "2026-07-18", "九年级", source_hash="v2"),
        ],
    )
    assert result.records[0].grade == "八年级"
    assert result.records[0].grade_origin == "MANUAL_LOOKUP"


def test_adapter_uses_history_before_legacy_csv_for_missing_current_grade(tmp_path):
    path = _gift_workbook(tmp_path / "gift.xlsx", lesson_time="2026-09-03 09:00")
    result = read_schedule_excel(
        path, "2026-09", student_grades={"学生甲": "八年级"},
        historical_grade_evidence=[evidence("学生甲", "2026-07-18", "八年级")],
    )
    # The class happened before 20 September, so the dated history fact has
    # not crossed the academic-year boundary yet.
    assert result.records[0].grade == "八年级"
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
    current = _gift_workbook(tmp_path / "september-gift.xlsx", lesson_time="2026-09-21 09:00")
    service.import_file(run["id"], "schedule", str(current))
    imported = service._read("schedule", current, "2026-09")
    assert imported.records[0].grade == "九年级"
    assert imported.records[0].grade_origin == "HISTORICAL_SCHEDULE"


def _schedule_workbook(path: Path, rows: list[dict]) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "排课记录"
    headers = ["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"]
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    book.save(path)
    return path


def test_grade_help_groups_many_ungraded_courses_by_student(tmp_path):
    service = PayrollService(tmp_path / "local")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule_workbook(tmp_path / "current.xlsx", [
        {"上课班级": "赠送课程", "教学形式": "一对一", "上课时间": f"2026-08-{day:02d} 09:00", "上课状态": "已上课", "实到": 1, "上课学员": "学生甲", "上课科目": "数学", "任课老师": "教师甲"}
        for day in range(1, 11)
    ])
    service.import_file(run["id"], "schedule", str(schedule))
    help_data = service.grade_help(run["id"])
    assert help_data["count"] == 1
    assert help_data["students"][0]["student"] == "学生甲"
    assert help_data["students"][0]["course_count"] == 10


def test_grade_help_splits_one_class_roster_into_student_confirmations(tmp_path):
    service = PayrollService(tmp_path / "local")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule_workbook(tmp_path / "current.xlsx", [
        {"上课班级": "赠送课程", "教学形式": "一对一", "上课时间": "2026-08-03 09:00", "上课状态": "已上课", "实到": 2, "上课学员": "学生甲,学生乙", "上课科目": "数学", "任课老师": "教师甲"},
    ])
    service.import_file(run["id"], "schedule", str(schedule))
    help_data = service.grade_help(run["id"])
    assert [item["student"] for item in help_data["students"]] == ["学生乙", "学生甲"]
    assert [item["course_count"] for item in help_data["students"]] == [1, 1]


def test_manual_grade_confirmation_rechecks_all_courses_for_one_student(tmp_path):
    service = PayrollService(tmp_path / "local")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule_workbook(tmp_path / "current.xlsx", [
        {"上课班级": "换购课程", "教学形式": "一对一", "上课时间": f"2026-08-{day:02d} 09:00", "上课状态": "已上课", "实到": 1, "上课学员": "学生甲", "上课科目": "数学", "任课老师": "教师甲"}
        for day in (3, 8, 15)
    ])
    service.import_file(run["id"], "schedule", str(schedule))
    saved = service.save_grade_confirmations_for_run(run["id"], [{"student": "学生甲", "grade": "八年级"}], "审核人")
    assert saved["saved"] == 1 and saved["remaining"] == 0
    reread = service._read("schedule", schedule, "2026-08")
    assert [row.grade for row in reread.records] == ["八年级", "八年级", "八年级"]


def test_all_roster_confirmations_recheck_the_same_course(tmp_path):
    service = PayrollService(tmp_path / "local")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule_workbook(tmp_path / "current.xlsx", [
        {"上课班级": "赠送课程", "教学形式": "一对一", "上课时间": "2026-08-03 09:00", "上课状态": "已上课", "实到": 2, "上课学员": "学生甲,学生乙", "上课科目": "数学", "任课老师": "教师甲"},
    ])
    service.import_file(run["id"], "schedule", str(schedule))
    result = service.save_grade_confirmations_for_run(run["id"], [
        {"student": "学生甲", "grade": "八年级"},
        {"student": "学生乙", "grade": "八年级"},
    ], "审核人")
    assert result["saved"] == 2 and result["remaining"] == 0
    reread = service._read("schedule", schedule, "2026-08")
    assert reread.records[0].grade == "八年级"


def test_multiple_history_imports_continue_to_reduce_student_groups(tmp_path):
    service = PayrollService(tmp_path / "local")
    run = service.create("2026-08", "GENERATE")
    current = _schedule_workbook(tmp_path / "current.xlsx", [
        {"上课班级": "赠送课程", "教学形式": "一对一", "上课时间": "2026-08-03 09:00", "上课状态": "已上课", "实到": 1, "上课学员": "学生甲", "上课科目": "数学", "任课老师": "教师甲"},
        {"上课班级": "换购课程", "教学形式": "一对一", "上课时间": "2026-08-03 09:00", "上课状态": "已上课", "实到": 1, "上课学员": "学生乙", "上课科目": "数学", "任课老师": "教师乙"},
    ])
    service.import_file(run["id"], "schedule", str(current))
    history_a = _gift_workbook(tmp_path / "history-a.xlsx", "八年级数学", "学生甲", "2026-07-18 09:00")
    history_b = _gift_workbook(tmp_path / "history-b.xlsx", "高一数学", "学生乙", "2026-07-18 09:00")
    first = service.import_grade_history_for_run(run["id"], str(history_a))
    second = service.import_grade_history_for_run(run["id"], str(history_b))
    assert first["before_count"] == 2 and first["remaining"] == 1
    assert second["before_count"] == 1 and second["remaining"] == 0


def test_legacy_student_grade_lookup_remains_compatible(tmp_path):
    path = _gift_workbook(tmp_path / "gift.xlsx")
    result = read_schedule_excel(path, "2026-08", student_grades={"学生甲": "初二"})
    assert result.records[0].grade == "八年级"
    assert result.records[0].grade_origin == "MANUAL_LOOKUP"
