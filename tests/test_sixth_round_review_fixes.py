from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

import pytest
from openpyxl import Workbook

from payroll_ui.service import PayrollService
from payroll_ui.server import PayrollHttpServer


def _schedule(path: Path, teachers: list[tuple[str, str, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["teacher_id", "teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"])
        for teacher_id, teacher, subject in teachers:
            writer.writerow([teacher_id, teacher, "九年级", subject, "1对1", 1, "已上课", "2026-08-05 10:00"])
    return path


def _history_salary(path: Path, teacher_id: str, value: int) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "历史工资"
    sheet.append(["历史薪资"])
    sheet.append(["教师ID", "基本工资", "岗位津贴", "工龄工资", "其他待遇", "应出勤", "实际出勤"])
    sheet.append([teacher_id, value, 2, 3, 4, 22, 21])
    book.save(path)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_with_schedule(service: PayrollService, tmp_path: Path, teachers: list[tuple[str, str, str]], *, role="DOS", group=""):
    run = service.create("2026-08", "GENERATE", operator_role=role, selected_group=group)
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / f"{run['id']}-schedule.csv", teachers)))
    return run["id"]


def test_new_math_schedule_teacher_is_auto_included_in_matching_leader_scope(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    run_id = _run_with_schedule(service, tmp_path, [("new-math", "新数学教师", "数学")], role="SUBJECT_LEADER", group="数学组")

    view = service.get(run_id)

    assert view["processing_scope"]["scope_count"] == 1
    assert view["processing_scope"]["teachers"][0]["display_name"] == "新数学教师"
    assert "CURRENT_PERIOD_SCHEDULE_PRIMARY_SUBJECT" in view["processing_scope"]["sources"]


def test_salary_basis_distinguishes_missing_explicit_no_salary_and_valid_salary(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    run_id = _run_with_schedule(service, tmp_path, [("t1", "教师甲", "数学")])
    run = service.store.get(run_id)

    assert service._salary_basis_for(run, "教师甲", "t1")["state"] == "SOURCE_UNKNOWN"

    run["support_department_snapshot"] = {"source_name": "当月支持部.xlsx", "entries": {
        "t1": {"teacher_id": "t1", "display_name": "教师甲", "base_salary": {"G": None, "H": None, "I": None, "J": None, "K": 22, "L": 21}},
    }}
    assert service._salary_basis_for(run, "教师甲", "t1")["state"] == "HOURLY_SUBMISSION_ONLY"

    run["support_department_snapshot"]["entries"]["t1"]["base_salary"].update({"G": 2400, "H": 0, "I": 0, "J": 0})
    assert service._salary_basis_for(run, "教师甲", "t1")["state"] == "HAS_BASE_SALARY"


def test_historical_salary_reference_provides_basis_evidence_without_applying_values(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    run_id = _run_with_schedule(service, tmp_path, [("t1", "教师甲", "数学")])
    run = service.store.get(run_id)
    run["historical_salary_reference_snapshots"] = [{
        "source_name": "历史工资.xlsx", "source_sha256": "history-hash", "selected_group": "数学组",
        "group_membership": {"group": "数学组", "confirmed": True, "members": [{"teacher_id": "t1", "teacher": "教师甲"}]},
        "entries": [{"teacher_id": "t1", "teacher": "教师甲", "fields": {code: {"value": (None if code in {"G", "H", "I", "J"} else 22 if code == "K" else 21)} for code in ("G", "H", "I", "J", "K", "L")}}],
    }]

    assert service._salary_basis_for(run, "教师甲", "t1")["state"] == "HOURLY_SUBMISSION_ONLY"
    assert run.get("base_salary_inputs") in (None, {})


def test_out_of_scope_teacher_is_not_inferred_hourly_from_support_row(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    run_id = _run_with_schedule(service, tmp_path, [("math", "数学教师", "数学"), ("eng", "英语教师", "英语")], role="SUBJECT_LEADER", group="数学组")
    service.confirm_staff_batch(run_id, "负责人", group_updates=[{"teacher_id": "math", "group": "数学组"}])
    run = service.store.get(run_id)
    blank_fields = {"G": None, "H": None, "I": None, "J": None, "K": None, "L": None}
    run["support_department_snapshot"] = {"source_name": "当月支持部.xlsx", "entries": {
        "math": {"teacher_id": "math", "display_name": "数学教师", "base_salary": dict(blank_fields)},
        "eng": {"teacher_id": "eng", "display_name": "英语教师", "base_salary": dict(blank_fields)},
    }}

    assert service._salary_basis_for(run, "数学教师", "math")["state"] == "HOURLY_SUBMISSION_ONLY"
    outside = service._salary_basis_for(run, "英语教师", "eng")
    assert outside["state"] == "SOURCE_UNKNOWN"
    assert "不在当前学科组处理范围" in outside["reason"]


def test_two_group_history_references_merge_without_overwriting_first_group(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    run_id = _run_with_schedule(service, tmp_path, [("math-id", "数学教师", "数学"), ("science-id", "理化教师", "物理")])
    math_source = _history_salary(tmp_path / "数学历史.xlsx", "math-id", 2400)
    science_source = _history_salary(tmp_path / "理化历史.xlsx", "science-id", 3100)

    first = service.import_base_salary_from_history(run_id, str(math_source), _sha(math_source), "负责人", selected_group="数学组")
    second = service.import_base_salary_from_history(run_id, str(science_source), _sha(science_source), "负责人", selected_group="理化组")
    assert len(second["run"]["historical_salary_reference_snapshots"]) == 2

    used_math = service.use_historical_salary_reference(run_id, "负责人", _sha(math_source), "数学组")
    assert used_math["base_salary_inputs"]["数学教师"]["fields"]["G"]["value"] == 2400
    used_both = service.use_historical_salary_reference(run_id, "负责人", _sha(science_source), "理化组")

    assert used_both["base_salary_inputs"]["数学教师"]["fields"]["G"]["value"] == 2400
    assert used_both["base_salary_inputs"]["理化教师"]["fields"]["G"]["value"] == 3100
    assert used_both["base_salary_inputs"]["数学教师"]["m"]["state"] == "DETERMINED"
    assert used_both["base_salary_inputs"]["理化教师"]["m"]["state"] == "DETERMINED"


def test_conflicting_history_reference_does_not_replace_confirmed_salary_values(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    run_id = _run_with_schedule(service, tmp_path, [("math-id", "数学教师", "数学")])
    source = _history_salary(tmp_path / "数学历史.xlsx", "math-id", 2400)
    imported = service.import_base_salary_from_history(run_id, str(source), _sha(source), "负责人", selected_group="数学组")
    service.use_historical_salary_reference(run_id, "负责人", _sha(source), "数学组")
    saved_before = service.store.get(run_id)["base_salary_inputs"]

    conflicting = {"teacher": "数学教师", "teacher_id": "math-id", "fields": {code: {"value": (2500 if code == "G" else value)} for code, value in {"G": 2400, "H": 2, "I": 3, "J": 4, "K": 22, "L": 21}.items()}}
    with pytest.raises(ValueError, match="字段冲突"):
        service.save_base_salary_inputs(run_id, [conflicting], "负责人", "第二参考", merge_existing=True)

    assert service.store.get(run_id)["base_salary_inputs"] == saved_before


def test_legacy_run_requires_explicit_role_and_archives_before_user_recalculation(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "sandbox")
    created = service.create("2026-08", "GENERATE")
    stored = service.store.get(created["id"])
    stored.pop("operator_role", None)
    stored.pop("part_time_payroll_mode", None)
    stored["core_calculation"] = {"rows": [{"teacher": "历史教师", "final": 123}]}
    stored["generated_payroll"] = {"rows": [{"teacher": "历史教师", "final": 123}]}
    stored["base_salary_inputs"] = {"历史教师": {"fields": {"G": {"value": 3200}}, "source": "历史来源"}}
    service.store.save(stored)
    salary_before = service.store.get(created["id"])["base_salary_inputs"]

    def fail_if_called(_run_id):
        raise AssertionError("角色元数据保存不得触发核算")

    monkeypatch.setattr(service, "check", fail_if_called)
    opened = service.get(created["id"])
    assert opened["operator_selection_required"] is True
    assert "旧流程记录，请选择按 DOS 或学科组长继续。" in opened["workflow_notice"]
    selected = service.select_legacy_run_operator(created["id"], "SUBJECT_LEADER", "数学组", "负责人")

    assert selected["operator_selection_required"] is False
    assert selected["operator_role"] == "SUBJECT_LEADER"
    assert selected["selected_group"] == "数学组"
    assert selected["part_time_payroll_mode"] == "GROUP_SUBMISSION_ONLY"
    assert selected["role_scope_recalculation_required"] is True
    assert selected["recalculation_required"] is True
    assert "core_calculation" not in selected
    assert "generated_payroll" not in selected
    assert selected["calculation_invalidation_history"][-1]["previous_generated_payroll"]["rows"][0]["final"] == 123
    assert selected["base_salary_inputs"] == salary_before


def test_legacy_role_selection_endpoint_persists_metadata_only(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    created = service.create("2026-08", "GENERATE")
    legacy = service.store.get(created["id"])
    legacy.pop("operator_role", None)
    legacy.pop("part_time_payroll_mode", None)
    legacy["generated_payroll"] = {"rows": [{"teacher": "历史教师", "final": 100}]}
    service.store.save(legacy)
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        request = Request(
            f"{base}/api/runs/{created['id']}/operator-role",
            data=json.dumps({"operator_role": "DOS", "selected_group": "", "confirmed_by": "负责人"}).encode(),
            headers={"X-Payroll-Token": token, "Content-Type": "application/json"},
        )
        saved = json.loads(urlopen(request).read())

        assert saved["operator_role"] == "DOS"
        assert saved["part_time_payroll_mode"] == "GROUP_SUBMISSION_ONLY"
        assert saved["role_scope_recalculation_required"] is True
        assert saved["recalculation_required"] is True
        assert "generated_payroll" not in saved
        assert saved["calculation_invalidation_history"][-1]["previous_generated_payroll"]["rows"][0]["final"] == 100
    finally:
        server.shutdown()


def test_materials_page_has_one_salary_module_with_distinct_import_entries():
    source = (Path(__file__).parents[1] / "payroll_ui/static/app.js").read_text(encoding="utf-8")
    materials = source.split("function salaryMaterialsModule()", 1)[1].split("function productionMaterialCards()", 1)[0]
    history = source.split("function historicalSalaryReferenceCard()", 1)[1].split("function savedHistoricalSalaryReferences()", 1)[0]

    assert materials.count("supportMaterialCard()") == 1
    assert materials.count("historicalSalaryReferenceCard()") == 1
    assert "导入支持部工资资料" not in history
    assert "继续添加历史工资参考" in history
    assert "openHistoricalImport()" in history
    assert "旧流程记录，请选择按 DOS 或学科组长继续。" in source
    assert "operator-role" in source
