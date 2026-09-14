from pathlib import Path

import openpyxl

from payroll_core.adapters.personnel import DEFAULT_PART_TIME_RATES, default_part_time_records, identity_conflicts, read_personnel
from payroll_core.adapters.star import read_star_report
from payroll_core.calculation import calculate_payroll
from payroll_core.config.core_rules import load_core_rules
from payroll_core.models.records import ScheduleRecord
from payroll_core.adapters.renewal_report import read_renewal_report
from payroll_core.adapters.business_results import read_business_result
from payroll_core.adapters.weekly_report import read_weekly_report
from payroll_core.excel.package import discover_payroll_package
from payroll_core.data_center import discover_payroll_package as discover_from_public_facade
from payroll_core.source_registry import SourceRegistry, SourceStatus


def _weekly_book(path: Path) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "教师"
    sheet.append(["理化组学科教师数据汇总"])
    sheet.append(["序号", "教师", "一对一", "", "", "班课", "", "", "单科总数", "总课次", "续费", "续费率"])
    sheet.append(["", "", "生数", "课时数", "周均", "班课生数", "班级数", "平均班级生数", "", "", "人头", "率"])
    sheet.append([1, "刘宇", 2, 6, 3, 4, 1, 4, 6, 10, 2, 0.25])
    book.save(path)
    return path


def _star_book(path: Path, *, rating: str = "三星", teacher: str = "教师甲") -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sheet1"
    sheet.append(["星级教师具体名单"])
    sheet.append(["", rating, "", "四星", ""])
    sheet.append(["", "姓名", "学科", "姓名", "学科"])
    sheet.append(["", teacher, "数学", "", ""])
    book.save(path)
    return path


def test_weekly_and_renewal_are_normalized_from_one_readable_layout(tmp_path):
    source = _weekly_book(tmp_path / "weekly.xlsx")
    weekly = read_weekly_report(source, "2026-08")
    assert not weekly.errors
    assert weekly.records[0].one_to_one_students == 2
    assert weekly.records[0].class_students == 4
    assert weekly.records[0].total_students == 6
    assert weekly.records[0].suggested_total_students == 6
    assert weekly.records[0].one_to_one_weekly_average == 3

    renewal = read_renewal_report(source, "2026-08")
    assert not renewal.errors
    assert renewal.records[0].renewal_count == 2
    assert renewal.records[0].total_students == 6
    assert renewal.records[0].suggested_total_students == 6
    assert renewal.records[0].renewal_rate == 2 / 6
    assert renewal.records[0].uploaded_renewal_rate == 0.25
    assert renewal.records[0].status == "RATE_MISMATCH"


def test_ooxml_content_with_xls_suffix_is_read_without_manual_rename(tmp_path):
    # Some WPS exports retain an .xls suffix while the payload is OOXML.  The
    # adapter must sniff the payload and not route it straight to xlrd.
    source = _weekly_book(tmp_path / "weekly.xls")
    weekly = read_weekly_report(source, "2026-08")
    assert not weekly.errors
    assert weekly.records[0].total_students == 6
    renewal = read_renewal_report(source, "2026-08")
    assert not renewal.errors
    assert renewal.records[0].renewal_rate == 2 / 6


def test_star_adapter_reads_wide_tier_table_with_cell_evidence(tmp_path):
    source = _star_book(tmp_path / "星级名单.xls")
    result = read_star_report(source, "2026-08")
    assert not result.errors
    assert result.records[0].teacher == "教师甲"
    assert result.records[0].rating == 3
    assert result.records[0].cell == "Sheet1!B4"


def test_star_adapter_reads_each_sheet_once(tmp_path):
    source = _star_book(tmp_path / "multi-sheet-stars.xlsx")
    book = openpyxl.load_workbook(source)
    sheet = book.create_sheet("Sheet2")
    sheet.append(["星级教师具体名单"])
    sheet.append(["", "四星", ""])
    sheet.append(["", "姓名", "学科"])
    sheet.append(["", "教师乙", "物理"])
    book.save(source)
    result = read_star_report(source, "2026-08")
    assert {(item.teacher, item.rating, item.sheet) for item in result.records} == {
        ("教师甲", 3, "Sheet1"), ("教师乙", 4, "Sheet2")
    }


def test_package_loads_system_star_authority_and_preserves_conflicts(tmp_path):
    source = _weekly_book(tmp_path / "weekly.xlsx")
    book = openpyxl.load_workbook(source)
    book.active.title = "排课列表"
    book.active.delete_rows(1, book.active.max_row)
    book.active.append(["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"])
    book.active.append(["高二物理一对一", "一对一", "2026-08-01 10:00", "已上课", 1, "学生甲", "物理", "教师甲"])
    book.save(tmp_path / "排课列表.xlsx")
    _star_book(tmp_path / "星级名单.xlsx")
    package = discover_payroll_package(tmp_path, "2026-08")
    assert package.authority_ratings == {"教师甲": 3}
    star_source = next(item for item in package.source_registry if item["source_type"] == "STAR")
    assert star_source["status"] == "IMPORTED"

    _star_book(tmp_path / "星级名单-冲突.xlsx", rating="四星")
    conflicted = discover_payroll_package(tmp_path, "2026-08")
    assert conflicted.authority_ratings == {}
    assert conflicted.star_conflicts[0]["teacher"] == "教师甲"
    assert conflicted.star_conflicts[0]["ratings"] == [3, 4]


def test_renewal_population_prefers_one_to_one_plus_class_students(tmp_path):
    source = _weekly_book(tmp_path / "weekly-renewal.xlsx")
    # The fixture has a deliberately inconsistent “单科总数” value in the
    # source shape used by legacy reports.  The operating population must use
    # the explicit one-to-one and class populations instead.
    book = openpyxl.load_workbook(source)
    book["教师"]["I4"] = 99
    book.save(source)
    renewal = read_renewal_report(source, "2026-08")
    assert not renewal.errors
    assert renewal.records[0].total_students == 99
    assert renewal.records[0].suggested_total_students == 6
    assert renewal.records[0].evidence["reported_total_students"] == 99
    assert renewal.records[0].evidence["total_students_authority"] == "FINAL_REPORTED_VALUE"


def test_personnel_keeps_effective_rates_and_identity_conflict(tmp_path):
    path = tmp_path / "personnel.xlsx"
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["姓名", "雇佣类型", "每节单价", "生效开始", "生效结束"])
    sheet.append(["刘宇", "兼职", 140, "2026-08", "2026-08"])
    sheet.append(["刘雨", "兼职", 140, "2026-08", "2026-08"])
    sheet.append(["张祥", "兼职", 160, "2026-08", "2026-08"])
    book.save(path)
    result = read_personnel(path, "2026-08")
    assert not result.errors
    assert {item.teacher: item.fixed_rate for item in result.records} == {"刘宇": 140, "刘雨": 140, "张祥": 160}
    assert identity_conflicts(item.teacher for item in result.records)[0].names == ("刘宇", "刘雨")
    assert DEFAULT_PART_TIME_RATES["胡涛"] == 170


def test_business_result_period_selects_grouped_month_sheet_and_subtotals(tmp_path):
    path = tmp_path / "renewals.xlsx"
    book = openpyxl.Workbook()
    july = book.active
    july.title = "7月"
    header = [None] * 30
    header[:3] = ["序号", "学科组", "教师"]
    header[3] = "1V1课时"; header[9] = "班课"; header[25] = "小班领航伴学课次"; header[29] = "总计"
    july.append(header)
    sub = [None] * 30
    for i, value in enumerate([1, 2, 3, 4, 5], start=3): sub[i] = value
    sub[8] = "合计"
    for i, value in enumerate(range(1, 16), start=9): sub[i] = value
    sub[24] = "合计"
    for i, value in enumerate([1, 2, 3], start=25): sub[i] = value
    sub[28] = "合计"
    july.append(sub)
    row = [None] * 30
    row[:3] = [1, "组", "七月教师"]; row[3] = 1; row[8] = 1; row[9] = 2; row[24] = 2; row[28] = 0; row[29] = 4
    july.append(row)
    august = book.create_sheet("8月")
    august.append([cell.value for cell in july[1]])
    august.append([cell.value for cell in july[2]])
    row = [None] * 30
    row[:3] = [1, "组", "八月教师"]; row[3] = 3; row[8] = 3; row[9] = 4; row[24] = 4; row[28] = 0; row[29] = 9
    august.append(row)
    book.save(path)
    records = read_business_result(path, period="2026-08")
    assert [item.teacher_id for item in records] == ["八月教师"]
    assert records[0].payload["1V1合计"] == 3
    assert records[0].payload["班课合计"] == 4
    assert records[0].payload["小班领航合计"] == 0


def test_personnel_csv_is_read_only_and_keeps_effective_dates(tmp_path):
    path = tmp_path / "personnel.csv"
    path.write_text("姓名,雇佣类型,每节单价,生效开始,生效结束\n刘宇,兼职,140,2026-08,2026-09\n", encoding="utf-8")
    result = read_personnel(path, "2026-08")
    assert not result.errors
    assert result.records[0].fixed_rate == 140
    assert result.records[0].effective_from == "2026-08"
    assert result.records[0].effective_to == "2026-09"


def test_optional_personnel_read_failure_is_reported_not_raised(tmp_path):
    result = read_personnel(tmp_path / "missing.xlsx", "2026-08")
    assert result.errors and result.errors[0].code == "UNREADABLE_PERSONNEL"


def test_default_part_time_records_keep_effective_source_and_pay_by_lesson():
    records = default_part_time_records("2026-08", source="2026-08 人员资料确认")
    by_teacher = {item.teacher: item for item in records}
    assert {teacher: item.fixed_rate for teacher, item in by_teacher.items()} == {"刘宇": 140, "张祥": 160, "胡涛": 170}
    assert all(item.effective_from == item.effective_to == "2026-08" for item in records)
    assert all(item.source_file == "2026-08 人员资料确认" for item in records)

    schedule = [ScheduleRecord("2026-08", "胡涛", "高二", "物理", "小班", 2, "已上课")]
    result = calculate_payroll(
        "2026-08", schedule, load_core_rules(),
        teacher_contexts=[{"teacher": "胡涛", "employment_type": "PART_TIME", "effective_from": "2026-08", "effective_to": "2026-08", "source": "2026-08 人员资料确认"}],
        part_time_rates=[{"teacher": item.teacher, "grade": "*", "rate_per_lesson": item.fixed_rate, "effective_from": item.effective_from, "effective_to": item.effective_to, "source": item.source_file, "approved_by": "审核员", "approved_at": "2026-08-01"} for item in records],
    )
    row = next(item for item in result.rows if item.teacher == "胡涛")
    assert row.part_time_fee.value == 170
    assert row.part_time_fee.evidence[0].source == "2026-08 人员资料确认"


def test_source_registry_deduplicates_same_hash_and_marks_unknown(tmp_path):
    path = tmp_path / "unknown.txt"
    path.write_text("not a payroll source", encoding="utf-8")
    registry = SourceRegistry()
    first = registry.register("OTHER", "2026-08", path, status=SourceStatus.NEEDS_CONFIRMATION)
    second = registry.register("OTHER", "2026-08", path, status=SourceStatus.NEEDS_CONFIRMATION)
    assert first.id == second.id
    assert len(registry) == 1
    assert registry.values()[0].status == SourceStatus.NEEDS_CONFIRMATION


def test_source_registry_keeps_reused_file_separate_by_period(tmp_path):
    path = tmp_path / "template.xlsx"
    path.write_bytes(b"same template")
    registry = SourceRegistry()
    first = registry.register("PAYROLL_TEMPLATE", "2026-08", path)
    second = registry.register("PAYROLL_TEMPLATE", "2026-09", path)
    assert first.id != second.id
    assert len(registry) == 2


def test_source_registry_audit_groups_semantic_views_into_one_parse_unit(tmp_path):
    path = tmp_path / "shared.xlsx"
    path.write_bytes(b"shared source")
    registry = SourceRegistry()
    registry.register("WEEKLY_REPORT", "2026-08", path, sheet="教师", source_evidence={"parse_count": 1, "parsed_once": True})
    registry.register("RENEWAL", "2026-08", path, sheet="教师", source_evidence={"parse_count": 1, "parsed_once": True})
    audit = registry.physical_file_audit()
    assert len(audit) == 1
    assert audit[0]["source_types"] == ["RENEWAL", "WEEKLY_REPORT"]
    assert audit[0]["parse_count"] == 1 and audit[0]["parsed_once"] is True


def test_package_does_not_reuse_previous_workbook_inspection_for_non_excel(tmp_path):
    workbook = _weekly_book(tmp_path / "weekly.xlsx")
    # The package scanner must keep non-Excel evidence independent of the
    # previous workbook in directory order; stale layout/formula headers make
    # audit records actively misleading.
    (tmp_path / "probe.txt").write_text("not a payroll source", encoding="utf-8")
    # A schedule is required for a valid package; the weekly workbook is a
    # useful minimal stand-in only for the adapter-level assertion below.
    from openpyxl import load_workbook
    schedule = load_workbook(workbook)
    schedule.active.title = "排课列表"
    schedule.active.delete_rows(1, schedule.active.max_row)
    schedule.active.append(["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"])
    schedule.active.append(["高二物理一对一", "一对一", "2026-08-01 10:00", "已上课", 1, "学生甲", "物理", "刘宇"])
    schedule.save(tmp_path / "排课列表.xlsx")
    package = discover_payroll_package(tmp_path, "2026-08")
    probe = next(item for item in package.source_registry if item["file_name"] == "probe.txt")
    assert probe["source_type"] == "OTHER"
    assert probe["source_evidence"]["historical_structure"]["layout"] == ""
    assert probe["source_evidence"]["formula"]["count"] == 0
    assert probe["source_evidence"]["header"] == {}


def test_package_file_counts_include_operating_records(tmp_path):
    source = _weekly_book(tmp_path / "weekly.xlsx")
    from openpyxl import load_workbook
    book = load_workbook(source)
    book.active.title = "排课列表"
    book.active.delete_rows(1, book.active.max_row)
    book.active.append(["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"])
    book.active.append(["高二物理一对一", "一对一", "2026-08-01 10:00", "已上课", 1, "学生甲", "物理", "刘宇"])
    book.save(tmp_path / "排课列表.xlsx")
    package = discover_payroll_package(tmp_path, "2026-08")
    weekly_file = next(item for item in package.files if item.kind == "WEEKLY_REPORT")
    assert weekly_file.records == len(package.weekly_reports)
    assert weekly_file.teachers == len({item["teacher"] for item in package.weekly_reports})


def test_weekly_registry_exposes_reported_value_authority(tmp_path):
    source = _weekly_book(tmp_path / "weekly.xlsx")
    from openpyxl import load_workbook
    book = load_workbook(source)
    book.active.title = "排课列表"
    book.active.delete_rows(1, book.active.max_row)
    book.active.append(["上课班级", "教学形式", "上课时间", "上课状态", "实到", "上课学员", "上课科目", "任课老师"])
    book.active.append(["高二物理一对一", "一对一", "2026-08-01 10:00", "已上课", 1, "学生甲", "物理", "刘宇"])
    book.save(tmp_path / "排课列表.xlsx")
    package = discover_payroll_package(tmp_path, "2026-08")
    record = next(item for item in package.source_registry if item["source_type"] == "WEEKLY_REPORT")
    assert record["source_evidence"]["value_authority"] == "FINAL_REPORTED_VALUE"
    assert record["source_evidence"]["suggested_fields"] == ["suggested_total_students"]


def test_public_data_center_facade_uses_the_same_package_discovery():
    assert discover_from_public_facade is discover_payroll_package
