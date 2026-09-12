"""Regression coverage for the issues real users hit during UAT.

Every case below comes from a真人 UAT finding: the default accounting month,
the uploaded file's real month, coverage completeness and export collisions.
The clock is always injected, never read from the machine.
"""
from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook

from payroll_core.excel.output_paths import safe_output_path
from payroll_core.period import coverage_for, default_period_for, dominant_month, month_from_filename
from payroll_ui.service import PayrollService


HEADERS = ["任课老师", "年级", "学科", "课程所属班型", "实到人数", "上课状态", "上课时间"]


def _schedule(path: Path, rows: list[list[object]]) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "课表"
    sheet.append(HEADERS)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def _lesson(teacher: str, day: str, class_type: str = "1对1", attended: int = 2) -> list[object]:
    return [teacher, "八年级", "数学", class_type, attended, "已上课", f"{day} 10:00"]


# --------------------------------------------------------------------- TEST 1/2
@pytest.mark.parametrize("today,expected", [
    (date(2026, 9, 1), "2026-08"),
    (date(2026, 9, 12), "2026-08"),
    (date(2026, 9, 19), "2026-08"),
    (date(2026, 9, 20), "2026-09"),
    (date(2026, 9, 30), "2026-09"),
    (date(2026, 1, 10), "2025-12"),
    (date(2026, 1, 20), "2026-01"),
])
def test_default_period_follows_the_twentieth(today, expected):
    """20 日之前默认核算上一个自然月，20 日起默认核算当前月。"""
    assert default_period_for(today) == expected


def test_default_period_rule_holds_in_the_real_ui_renderer():
    """The UI uses the same rule, exercised through the real JavaScript."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = { document: { querySelector() { return null; } }, window: { confirm() { return true; }, clearTimeout() {}, setTimeout() {} }, console };
vm.createContext(context);
vm.runInContext(source, context);
const cases = [['2026-09-01','2026-08'],['2026-09-12','2026-08'],['2026-09-19','2026-08'],
                ['2026-09-20','2026-09'],['2026-09-30','2026-09'],['2026-01-10','2025-12']];
for (const [day, expected] of cases) {
  const actual = vm.runInContext(`defaultPayrollPeriod(new Date("${day}T09:00:00"))`, context);
  assert.strictEqual(actual, expected, `${day} -> ${actual}, expected ${expected}`);
}
'''
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# ------------------------------------------------------------------- TEST 3/4/5
def test_uploading_a_previous_month_schedule_detects_the_mismatch(tmp_path):
    """UI 9 月 + 8 月真实课表 → 检测到冲突，但不报错终止。"""
    service = PayrollService(tmp_path / "app")
    run = service.create("2026-09", "GENERATE")
    path = _schedule(tmp_path / "9月排课.xlsx", [
        _lesson("张三", "2026-08-05"),
        _lesson("张三", "2026-08-12"),
        _lesson("李四", "2026-08-20", class_type="小班", attended=3),
    ])

    imported = service.import_file(run["id"], "schedule", str(path))

    check = imported["period_check"]
    assert check["run_month"] == "2026-09"
    assert check["source_month"] == "2026-08", "月份判断必须来自文件内上课日期，不是文件名"
    assert check["mismatch"] is True
    assert check["decision"] == "PENDING"
    assert check["filename_disagrees"] is True, "文件名写着 9 月，但内容属于 8 月"


def test_switching_month_keeps_files_and_state(tmp_path):
    """选择切换到 8 月 → 文件保留、状态保留、可以继续核算。"""
    service = PayrollService(tmp_path / "app")
    run = service.create("2026-09", "GENERATE")
    path = _schedule(tmp_path / "排课.xlsx", [_lesson("张三", "2026-08-05"), _lesson("张三", "2026-08-12")])
    before = service.import_file(run["id"], "schedule", str(path))

    switched = service.change_period(run["id"], "2026-08")

    assert switched["period"] == "2026-08"
    assert switched["files"]["schedule"]["path"] == str(path), "已上传文件不能丢失"
    assert switched["period_check"]["mismatch"] is False
    assert switched["period_check"]["decision"] == "SWITCHED"
    assert switched["status"] == "FILES_READY", "切换后应能直接继续核算，不要求重新上传"
    assert switched["files"]["schedule"]["records"] == before["files"]["schedule"]["records"]


def test_keeping_the_month_does_not_silently_switch(tmp_path):
    """选择仍按 9 月 → 绝不偷偷改成 8 月。"""
    service = PayrollService(tmp_path / "app")
    run = service.create("2026-09", "GENERATE")
    path = _schedule(tmp_path / "排课.xlsx", [_lesson("张三", "2026-08-05")])
    service.import_file(run["id"], "schedule", str(path))

    kept = service.resolve_period_check(run["id"], "KEEP")

    assert kept["period"] == "2026-09"
    assert kept["period_check"]["decision"] == "KEPT"
    assert kept["period_check"]["mismatch"] is True, "仍然如实记录月份不一致"


# ----------------------------------------------------------------------- TEST 6
def test_partial_month_coverage_is_a_warning_not_a_blocker(tmp_path):
    """8/1–8/30 覆盖不完整 → warning，不是默认 blocker。"""
    service = PayrollService(tmp_path / "app")
    run = service.create("2026-08", "GENERATE")
    path = _schedule(tmp_path / "排课.xlsx", [_lesson("张三", "2026-08-01"), _lesson("张三", "2026-08-30")])

    imported = service.import_file(run["id"], "schedule", str(path))

    coverage = imported["period_check"]["coverage"]
    assert coverage["first_date"] == "2026-08-01" and coverage["last_date"] == "2026-08-30"
    assert coverage["incomplete_tail"] is True
    assert coverage["outside_period"] is False
    assert imported["status"] == "FILES_READY", "只是提醒，不能阻止继续核算"


def test_coverage_flags_a_fully_covered_month_without_warning():
    coverage = coverage_for("2026-08", ["2026-08-01", "2026-08-31"])
    assert coverage.incomplete_tail is False
    assert coverage.cross_month is False


def test_cross_month_schedule_is_reported():
    coverage = coverage_for("2026-08", ["2026-08-30", "2026-09-02"])
    assert coverage.cross_month is True


def test_month_evidence_prefers_content_over_filename():
    assert dominant_month(["2026-09-03", "2026-09-05", "2026-08-29"]) == "2026-09"
    # 文件名叫 8 月，内容实际是 9 月：以内容为准。
    assert month_from_filename("8月排课.xlsx") == ("08", False)
    assert dominant_month(["2026-09-03", "2026-09-05"]) == "2026-09"


# --------------------------------------------------------------------- TEST 7/8
def test_export_appends_a_number_instead_of_failing(tmp_path):
    existing = tmp_path / "工资表.xlsx"
    existing.touch()
    assert safe_output_path(existing).name == "工资表 (2).xlsx"


def test_export_never_overwrites_any_existing_file(tmp_path):
    base = tmp_path / "工资表.xlsx"
    base.touch()
    for index in (2, 3, 4):
        (tmp_path / f"工资表 ({index}).xlsx").touch()
    chosen = safe_output_path(base)
    assert chosen.name == "工资表 (5).xlsx"
    assert not chosen.exists(), "绝不能覆盖已有文件"


def test_export_fills_gaps_without_colliding(tmp_path):
    base = tmp_path / "工资表.xlsx"
    base.touch()
    (tmp_path / "工资表 (2).xlsx").touch()
    (tmp_path / "工资表 (4).xlsx").touch()  # 空洞：缺 (3)
    assert safe_output_path(base).name == "工资表 (3).xlsx"


def test_generated_payroll_export_is_collision_safe(tmp_path):
    """End to end: generating twice must not fail or overwrite the first file."""
    service = PayrollService(tmp_path / "app")
    run = service.create("2026-08", "GENERATE")
    path = _schedule(tmp_path / "排课.xlsx", [_lesson("张三", "2026-08-05"), _lesson("张三", "2026-08-31")])
    service.import_file(run["id"], "schedule", str(path))
    target = tmp_path / "工资表.xlsx"

    first = service.generate_payroll(run["id"], str(target))
    second = service.generate_payroll(run["id"], str(target))

    assert Path(first["path"]).name == "工资表.xlsx"
    assert Path(second["path"]).name == "工资表 (2).xlsx"
    assert Path(first["path"]).exists() and Path(second["path"]).exists()
    assert first["path"] != second["path"]


def test_default_export_location_is_reachable(tmp_path):
    service = PayrollService(tmp_path / "app")
    data = service.default_export_path("标准工资表.xlsx")
    assert data["path"].endswith("标准工资表.xlsx")
    assert data["location"], "必须能告诉用户文件保存在哪里"
