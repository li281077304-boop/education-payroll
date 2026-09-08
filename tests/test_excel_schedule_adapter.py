from pathlib import Path

from openpyxl import Workbook

from payroll_core.excel.schedule import read_schedule_excel


FIXTURE = Path(__file__).parent / "fixtures" / "excel" / "fake_schedule.xlsx"
REQUIRED_HEADERS = ["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"]


def _schedule_workbook(path: Path, headers: list[str]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "排课记录-08月03日到08月30日"
    sheet.append(headers)
    sheet.append([{"上课班级": "初一数学一对一", "教学形式": "一对一", "上课时间": "2026-08-03 09:00", "上课状态": "已上课", "实到": 1, "上课学员": "学生甲", "上课科目": "数学", "任课老师": "张三"}.get(header, "") for header in headers])
    workbook.save(path)


def test_schedule_adapter_reads_fake_current_layout_with_normalized_fields():
    result = read_schedule_excel(FIXTURE, period="2026-08")

    assert result.ok
    assert len(result.records) == 2
    record = result.records[0]
    assert (record.grade, record.subject, record.class_type, record.attended) == ("七年级", "数学", "1对1", 1)
    assert record.lesson_date == "2026-08-10"
    assert record.provenance["teacher"].source_field == "任课老师"
    assert record.provenance["teacher"].coordinate == "O2"


def test_schedule_adapter_reports_missing_required_column(tmp_path):
    path = tmp_path / "missing-attendance.xlsx"
    headers = [header for header in REQUIRED_HEADERS if header != "实到"]
    _schedule_workbook(path, headers)

    result = read_schedule_excel(path, period="2026-08")

    assert not result.ok
    assert result.errors[0].code == "MISSING_REQUIRED_COLUMN"


def test_schedule_adapter_uses_headers_not_fixed_column_positions(tmp_path):
    path = tmp_path / "moved-columns.xlsx"
    headers = list(reversed(REQUIRED_HEADERS))
    _schedule_workbook(path, headers)

    result = read_schedule_excel(path, period="2026-08")

    assert result.ok
    assert result.records[0].teacher == "张三"
    assert result.records[0].attended == 1
