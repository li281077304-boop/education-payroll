"""Excel import compatibility: known adapter first, semantic mapping fallback."""
from __future__ import annotations

from pathlib import Path
from shutil import copyfile

import pytest
from openpyxl import Workbook

from payroll_core.excel.schedule import read_schedule_excel
from payroll_core.mapping import SCHEDULE_AC_REQUIREMENT, analyze_mapping
from payroll_core.reconcile.payroll_scope import class_value_contribution
from payroll_ui.service import PayrollService
from tests.test_payroll_ui_service import FIXTURES, _prepared_run


def _sheet(path: Path, headers: list[str], rows: list[list[object]], title: str = "课程明细") -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


ALIAS_HEADERS = ["任课老师", "年级", "学科", "课程所属班型", "实到人数", "上课状态"]
ALIAS_ROWS = [
    ["张三", "八年级", "数学", "1对1", 1, "已上课"],
    ["李四", "高三", "物理", "集体班", 6, "已上课"],
]


def _run(tmp_path: Path):
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08")
    return service, run


def _import(service, run, path: Path, **kwargs):
    return service.import_file(run["id"], "schedule", str(path), **kwargs)


def test_known_schedule_adapter_still_works(tmp_path):
    """The original export keeps using its fast path, unchanged."""
    source = FIXTURES / "fake_schedule.xlsx"
    known = read_schedule_excel(source, "2026-08")
    assert known.ok and known.records

    service, run = _run(tmp_path)
    imported = _import(service, run, source)

    assert imported["files"]["schedule"]["records"] == len(known.records)
    assert service.preview_import_mapping(str(source), "schedule")["status"] == "KNOWN_LAYOUT"


def test_schedule_column_order_is_not_required(tmp_path):
    shuffled = ["实到人数", "课程所属班型", "学科", "年级", "任课老师"]
    path = _sheet(tmp_path / "shuffled.xlsx", shuffled, [row[::-1] for row in ALIAS_ROWS])

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    assert set(analysis.mapping) >= {"teacher", "grade", "subject", "class_type", "actual_student_count"}
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["records"] == 2


def test_schedule_header_aliases_are_supported(tmp_path):
    headers = ["授课教师", "所属年级", "科目", "班型", "到课人数"]
    path = _sheet(tmp_path / "aliases.xlsx", headers, ALIAS_ROWS)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    assert analysis.mapped_headers["teacher"] == "授课教师"
    assert analysis.mapped_headers["subject"] == "科目"
    assert analysis.mapped_headers["class_type"] == "班型"
    assert analysis.mapped_headers["actual_student_count"] == "到课人数"
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["teachers"] == 2


def test_unrelated_columns_do_not_block_import(tmp_path):
    headers = ["序号", "任课老师", "备注", "年级", "校区", "学科", "课程所属班型", "实到人数"]
    rows = [[1, "张三", "无", "八年级", "宣城二校", "数学", "1对1", 1]]
    path = _sheet(tmp_path / "extra.xlsx", headers, rows)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["records"] == 1


def test_missing_optional_columns_do_not_block_import(tmp_path):
    # No 上课时间 / 上课学员 / 上课班级 at all: optional context only.
    path = _sheet(tmp_path / "minimal.xlsx", ALIAS_HEADERS, ALIAS_ROWS)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    assert not analysis.missing
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["records"] == 2


def test_missing_required_field_is_named(tmp_path):
    # Only a class headcount exists; 实到人数 is genuinely absent.
    headers = ["任课老师", "年级", "学科", "课程所属班型", "班级人数", "备注"]
    path = _sheet(tmp_path / "no-attendance.xlsx", headers, [["张三", "八年级", "数学", "1对1", 1, "无"]])
    service, run = _run(tmp_path)

    preview = service.preview_import_mapping(str(path), "schedule")

    assert preview["status"] in {"NEEDS_CONFIRMATION", "MISSING_REQUIRED"}
    assert "实到人数" in preview["missing_labels"] or any(item["field"] == "actual_student_count" and item["needs_choice"] for item in preview["fields"])
    with pytest.raises(ValueError) as error:
        _import(service, run, path)
    message = str(error.value)
    assert "实到人数" in message and "检测到的列" in message and "班级人数" in message


def test_ambiguous_field_requires_confirmation(tmp_path):
    headers = ["教师", "任课老师", "年级", "学科", "课程所属班型", "实到人数", "班级人数"]
    path = _sheet(tmp_path / "ambiguous.xlsx", headers, [["张三", "张三", "八年级", "数学", "1对1", 1, 8]])
    service, run = _run(tmp_path)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)
    preview = service.preview_import_mapping(str(path), "schedule")

    assert analysis.status == "NEEDS_CONFIRMATION"
    assert set(analysis.candidates["teacher"]) == {"教师", "任课老师"}
    assert set(analysis.candidates["actual_student_count"]) == {"实到人数", "班级人数"}
    assert preview["status"] == "NEEDS_CONFIRMATION"
    with pytest.raises(ValueError, match="需要你确认"):
        _import(service, run, path)


def test_manual_mapping_allows_import(tmp_path):
    headers = ["教师", "任课老师", "年级", "学科", "课程所属班型", "实到人数", "班级人数"]
    path = _sheet(tmp_path / "manual.xlsx", headers, [["张三", "张三", "八年级", "数学", "1对1", 3, 8]])
    service, run = _run(tmp_path)
    preview = service.preview_import_mapping(str(path), "schedule")

    imported = _import(service, run, path, mapping={
        "sheet": preview["sheet"], "header_row": preview["header_row"],
        "mapping": {"teacher": 2, "grade": 3, "subject": 4, "class_type": 5, "actual_student_count": 6},
    })

    assert imported["files"]["schedule"]["records"] == 1
    records = service._read("schedule", Path(imported["files"]["schedule"]["path"]), "2026-08").records or []
    detail = service.get(run["id"])
    assert detail["files"]["schedule"]["records"] == 1


def test_confirmed_mapping_profile_is_reused(tmp_path):
    first = _sheet(tmp_path / "first.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    second = _sheet(tmp_path / "second.xlsx", ALIAS_HEADERS, [["王五", "高二", "英语", "小班", 4]])
    service, run = _run(tmp_path)
    preview = service.preview_import_mapping(str(first), "schedule")
    confirmed = {"sheet": preview["sheet"], "header_row": preview["header_row"], "mapping": preview["mapping"]}

    _import(service, run, first, mapping=confirmed, profile_name="二校排课格式", profile_actor="教务")
    again = service.preview_import_mapping(str(second), "schedule")

    assert again["status"] == "MAPPED"
    assert again["profile_id"]
    assert again["fields"][0]["header"] == "任课老师"
    other = service.create("2026-09")
    imported = service.import_file(other["id"], "schedule", str(second))
    assert imported["files"]["schedule"]["records"] == 1


def test_profile_drift_requires_reconfirmation(tmp_path):
    original = _sheet(tmp_path / "original.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    # Same headers, same fingerprint, but the columns have been reordered.
    moved = _sheet(tmp_path / "moved.xlsx", ALIAS_HEADERS[::-1], [row[::-1] for row in ALIAS_ROWS])
    service, run = _run(tmp_path)
    preview = service.preview_import_mapping(str(original), "schedule")
    _import(service, run, original, mapping={
        "sheet": preview["sheet"], "header_row": preview["header_row"], "mapping": preview["mapping"],
    }, profile_name="二校排课格式", profile_actor="教务")

    drift = service.preview_import_mapping(str(moved), "schedule")

    assert drift["profile_drift"] is True
    assert drift["status"] == "NEEDS_CONFIRMATION"
    other = service.create("2026-09")
    with pytest.raises(ValueError, match="重新确认"):
        service.import_file(other["id"], "schedule", str(moved))


def test_variant_layout_reaches_reconciliation(tmp_path):
    """The real acceptance: a differently formatted schedule still gets checked."""
    copyfile(FIXTURES / "fake_payroll.xlsx", tmp_path / "combined.xlsx")
    from tests.test_payroll_ui_service import _payroll_with_only_from

    math = tmp_path / "math.xlsx"
    science = tmp_path / "science.xlsx"
    _payroll_with_only_from(tmp_path / "combined.xlsx", math, 5)
    _payroll_with_only_from(tmp_path / "combined.xlsx", science, 6)
    variant = _sheet(tmp_path / "english-variant.xlsx", ["授课教师", "所属年级", "科目", "课程班型", "实际到课人数", "上课状态"],
                     [["张三", "八年级", "英语", "1对1", 1, "已上课"], ["李四", "高三", "英语", "小班", 6, "已上课"]], title="英语组课表")
    service, run = _run(tmp_path)
    _import(service, run, variant)

    for role, path in (("math", math), ("science", science)):
        service.import_file(run["id"], role, str(path))
    checked = service.check(run["id"])

    assert checked["status"] in {"REVIEW_REQUIRED", "PASS", "BLOCKED"}
    assert service.get(run["id"])["files"]["schedule"]["records"] == 2
    assert checked["field_status"]


def test_duration_is_not_required_for_two_hour_default(tmp_path):
    """Every course is two hours by default, so duration must never be required."""
    without_duration = _sheet(tmp_path / "without.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    with_duration = _sheet(tmp_path / "with.xlsx", ALIAS_HEADERS + ["上课时长"], [row + ["3小时"] for row in ALIAS_ROWS])

    plain = analyze_mapping(without_duration, SCHEDULE_AC_REQUIREMENT)
    extra = analyze_mapping(with_duration, SCHEDULE_AC_REQUIREMENT)

    assert plain.ready and extra.ready
    service, run = _run(tmp_path)
    imported = _import(service, run, without_duration)
    records = service._read("schedule", Path(imported["files"]["schedule"]["path"]), "2026-08").records
    assert len(records) == 2
    assert all(record.duration_text == "" for record in records)
    # The class-value calculation itself carries the two-hour default.
    value, calculation = class_value_contribution(records[1])
    assert value is not None and calculation.endswith(f"× 2 = {value:g}")


def test_real_binary_xls_schedule_and_semantic_mapping():
    path = FIXTURES / "sanitized_schedule.xls"
    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)
    assert analysis.ready is True
    assert analysis.mapping["teacher"] == 15
    result = read_schedule_excel(path, "2026-08", period_start="2026-08-01", period_end="2026-08-31")
    assert len(result.records) == 1
    assert result.records[0].lesson_date == "2026-08-10"
