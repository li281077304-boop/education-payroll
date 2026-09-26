"""Synthetic end-to-end coverage for the September 26 manual Payroll UAT."""
from __future__ import annotations

import hashlib

import pytest
from openpyxl import Workbook

from payroll_core.payroll_generation import generated_from_calculation
from payroll_ui.service import PayrollService


def _run_with_roster(service: PayrollService, period: str = "2026-08") -> dict:
    created = service.create(period, "GENERATE")
    stored = service.store.get(created["id"])
    stored["core_calculation"] = {"rows": [{"teacher": "教师甲", "teacher_id": "teacher-1"}]}
    service.store.save(stored)
    return stored


def _history_salary(path, value: int = 20):
    book = Workbook()
    sheet = book.active
    sheet.title = "历史工资"
    sheet.append(["历史薪资"])
    sheet.append(["教师ID", "基本工资", "岗位津贴", "工龄工资", "其他待遇", "应出勤", "实际出勤"])
    sheet.append(["teacher-1", value, 2, 3, 4, 22, 21])
    book.save(path)
    return path


def _monthly_renewal(path):
    book = Workbook()
    january = book.active
    january.title = "1月"
    august = book.create_sheet("8月")
    for sheet, teacher, amount in ((january, "教师甲", 99), (august, "教师甲", 5)):
        header = [None] * 30
        header[0:3] = ["序号", "学科组", "教师"]
        header[3], header[9], header[25] = "1V1课时", "班课", "小班领航伴学课次"
        sheet.append(header)
        detail = [None] * 30
        detail[8] = detail[24] = detail[28] = "合计"
        sheet.append(detail)
        values = [None] * 30
        values[0:3] = [1, "数学组", teacher]
        values[8], values[24], values[28] = amount, 2, 1
        sheet.append(values)
    book.save(path)
    return path


def test_history_salary_preview_then_confirm_uses_existing_atomic_run_path(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = _run_with_roster(service)
    source = _history_salary(tmp_path / "薪资表.xlsx")
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    preview = service.preview_base_salary_import(run["id"], str(source))
    assert preview["can_import"] is True
    assert len(preview["matched"]) == 1
    assert service.store.get(run["id"]).get("base_salary_input_snapshot") is None

    saved = service.import_base_salary_from_history(run["id"], str(source), preview["source"]["sha256"], "核算负责人")
    entry = saved["run"]["base_salary_inputs"]["教师甲"]
    assert saved["imported"] == 1
    assert entry["fields"]["G"]["value"] == 20
    assert entry["fields"]["G"]["provenance"]["source_sha256"] == original_hash
    assert entry["m"]["state"] == "DETERMINED"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert service.create("2026-09", "GENERATE")["base_salary_inputs"]["教师甲"]["fields"]["G"]["value"] == 20


def test_history_salary_confirmation_rejects_source_changed_after_preview(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = _run_with_roster(service)
    source = _history_salary(tmp_path / "薪资表.xlsx")
    preview = service.preview_base_salary_import(run["id"], str(source))
    _history_salary(source, 21)

    with pytest.raises(ValueError, match="已变化"):
        service.import_base_salary_from_history(run["id"], str(source), preview["source"]["sha256"], "核算负责人")
    assert service.store.get(run["id"]).get("base_salary_input_snapshot") is None


def test_monthly_renewal_import_is_visible_but_wage_fields_require_confirmation(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = _run_with_roster(service)
    source = _monthly_renewal(tmp_path / "年度续费.xlsx")

    imported = service.import_material_file(run["id"], "renewal", str(source))["run"]
    assert imported["renewal_material_kind"] == "MONTHLY_FINAL_CANDIDATE"
    assert len(imported["renewal_reports"]) == 1
    assert imported["renewal_reports"][0]["sheet"] == "8月"
    assert imported.get("run_renewal_result_snapshot") is None

    preview = service.preview_renewal_material(run["id"])
    assert preview["can_confirm"] is True
    assert preview["matched"][0]["AH"] == 5
    assert preview["matched"][0]["AI"] == 2
    assert preview["matched"][0]["AJ"] == 1

    confirmed = service.confirm_renewal_material(run["id"], preview["source_sha256"], "核算负责人")
    entry = confirmed["run_renewal_result_snapshot"]["entries"]["teacher-1"]
    assert entry["AH"]["value"] == 5
    assert entry["AI"]["value"] == 2
    assert entry["AJ"]["value"] == 1
    assert confirmed["renewal_source_confirmation"]["actor"] == "核算负责人"
    assert confirmed["material_inputs"]["renewal"]["records"] == 1
    generated = generated_from_calculation({"period": "2026-08", "rows": [{
        "teacher": "教师甲", "employment_type": "FULL_TIME", "fields": {
            "AA": {"value": 1, "state": "DETERMINED"}, "AC": {"value": 2, "state": "DETERMINED"},
            "AD": {"value": 3, "state": "DETERMINED"}, "AE": {"value": 40, "state": "DETERMINED"},
            "AF": {"value": 120, "state": "DETERMINED"}, "PART_TIME": {"value": None, "state": "NOT_APPLICABLE"},
        },
    }]}, renewal_snapshot=confirmed["run_renewal_result_snapshot"])
    assert generated.rows[0].final_fields["AK"]["value"] == pytest.approx(8.75)
