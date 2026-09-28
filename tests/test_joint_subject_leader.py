from __future__ import annotations

import csv
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from openpyxl import Workbook

from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService


GROUPS = ["数学组", "理化组", "语文组", "英语组", "其它"]


def _schedule(path: Path, people: list[tuple[str, str, str]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["teacher_id", "teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"])
        for teacher_id, teacher, subject in people:
            writer.writerow([teacher_id, teacher, "九年级", subject, "1对1", 1, "已上课", "2026-08-05 10:00"])
    return path


def _group_file(path: Path, teacher: str) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"])
        writer.writerow([teacher, 1, 0, 1, 30, 40, 0])
    return path


def _history(path: Path, teacher_id: str, salary: int = 2400) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "历史工资"
    sheet.append(["历史薪资"])
    sheet.append(["教师ID", "基本工资", "岗位津贴", "工龄工资", "其他待遇", "应出勤", "实际出勤"])
    sheet.append([teacher_id, salary, 2, 3, 4, 22, 21])
    book.save(path)
    return path


def _run(service: PayrollService, tmp_path: Path, *, groups: list[str] | None = None, selected_group: str = "") -> str:
    run = service.create("2026-08", "GENERATE", operator_role="SUBJECT_LEADER",
                         selected_groups=groups, selected_group=selected_group)
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / f"{run['id']}-schedule.csv", [
        ("math-id", "数学教师", "数学"), ("science-id", "理化教师", "物理"), ("chinese-id", "语文教师", "语文"),
    ])))
    return run["id"]


def test_joint_run_stores_two_groups_and_legacy_group_is_empty(tmp_path):
    service = PayrollService(tmp_path / "data")
    created = service.create("2026-08", "GENERATE", operator_role="SUBJECT_LEADER",
                             selected_groups=["数学组", "理化组"])

    assert created["selected_groups"] == ["数学组", "理化组"]
    assert created["selected_group"] == ""
    assert created["processing_scope"]["selected_groups"] == ["数学组", "理化组"]


def test_joint_processing_scope_unions_confirmed_group_authorities_and_snapshots_selection(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    service.confirm_staff_batch(run_id, "负责人", group_updates=[
        {"teacher_id": "math-id", "group": "数学组"},
        {"teacher_id": "science-id", "group": "理化组"},
    ])

    checked = service.check(run_id)

    assert checked["processing_scope_snapshot"]["selected_groups"] == ["数学组", "理化组"]
    assert set(checked["processing_scope_snapshot"]["teachers"]) == {"数学教师", "理化教师"}
    assert "语文教师" not in checked["processing_scope_snapshot"]["teachers"]


def test_first_two_group_confirmations_before_any_check_do_not_lock_recalculation(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    math_path = _group_file(tmp_path / "math-first.csv", "数学教师")
    science_path = _group_file(tmp_path / "science-first.csv", "理化教师")
    math_candidate = service.preview_subject_group_material(run_id, str(math_path), "数学组")["subject_group_preview"]
    science_candidate = service.preview_subject_group_material(run_id, str(science_path), "理化组")["subject_group_preview"]

    service.confirm_subject_group_material(run_id, "math", math_candidate["source_sha256"], "负责人",
                                           selected_group="数学组", candidate_id=math_candidate["candidate_id"])
    after_first = service.store.get(run_id)
    assert not after_first.get("recalculation_required")
    assert not after_first.get("calculation_invalidation_history")
    assert science_candidate["candidate_id"] in after_first["pending_subject_group_imports"]

    service.confirm_subject_group_material(run_id, science_candidate["role"], science_candidate["source_sha256"], "负责人",
                                           selected_group="理化组", candidate_id=science_candidate["candidate_id"])
    after_second = service.store.get(run_id)
    assert not after_second.get("recalculation_required")
    assert len(after_second["subject_group_materials"]) == 2

    checked = service.check(run_id)
    assert set(checked["processing_scope_snapshot"]["teachers"]) == {"数学教师", "理化教师"}
    assert not checked.get("recalculation_required")


def test_first_history_reference_confirmation_does_not_block_second_group_reference(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    math_source = _history(tmp_path / "math-history.xlsx", "math-id", 2400)
    science_source = _history(tmp_path / "science-history.xlsx", "science-id", 3100)

    service.stage_historical_salary_reference_preview(run_id, str(math_source), "数学组")
    math_pending = service.store.get(run_id)["historical_salary_reference_pending_preview"]
    service.import_base_salary_from_history(run_id, str(math_source), math_pending["source_sha256"], "负责人", selected_group="数学组")
    after_first = service.store.get(run_id)
    assert not after_first.get("recalculation_required")
    assert not after_first.get("calculation_invalidation_history")
    assert after_first["historical_salary_reference_snapshots"][0]["selected_group"] == "数学组"

    service.stage_historical_salary_reference_preview(run_id, str(science_source), "理化组")
    science_pending = service.store.get(run_id)["historical_salary_reference_pending_preview"]
    service.import_base_salary_from_history(run_id, str(science_source), science_pending["source_sha256"], "负责人", selected_group="理化组")
    after_second = service.store.get(run_id)
    assert not after_second.get("recalculation_required")
    assert {item["selected_group"] for item in after_second["historical_salary_reference_snapshots"]} == {"数学组", "理化组"}


def test_joint_processing_scope_unions_history_membership_and_confirmed_materials(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    run = service.store.get(run_id)
    run["historical_salary_reference_snapshots"] = [{
        "source_sha256": "history", "group_membership": {
            "group": "理化组", "confirmed": True,
            "members": [{"teacher_id": "science-id", "teacher": "理化教师"}],
        },
    }]
    run["subject_group_materials"] = [{
        "material_id": "math-material", "recognized_group": "数学组", "recognized_role": "math",
        "status": "CONFIRMED", "period": "2026-08", "teacher_names": ["数学教师"],
    }]
    service.store.save(run)

    scope = service._processing_scope(service.store.get(run_id))

    assert {item["display_name"] for item in scope["teachers"]} == {"数学教师", "理化教师"}
    assert scope["selected_group"] == ""
    assert scope["selected_groups"] == ["数学组", "理化组"]


def test_confirming_new_group_after_check_archives_and_invalidates_active_results(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    service.confirm_staff_batch(run_id, "负责人", group_updates=[{"teacher_id": "math-id", "group": "数学组"}])
    service.check(run_id)
    before = service.store.get(run_id)
    assert before.get("core_calculation") or before.get("generated_payroll")
    before["business_decisions"] = [{"group_id": "old-group", "status": "ACTIVE", "action": "ACCEPTED_EXCEPTION"}]
    before["decisions"] = [{"issue_id": "old-issue", "action": "defer"}]
    service.store.save(before)

    monkeypatch.setattr(service, "check", lambda _run_id: pytest.fail("确认人员归组不得自动重算"))
    service.confirm_staff_batch(run_id, "负责人", group_updates=[{"teacher_id": "science-id", "group": "理化组"}])

    after = service.store.get(run_id)
    history = after["calculation_invalidation_history"][-1]
    assert "core_calculation" not in after
    assert "generated_payroll" not in after
    assert history["previous_core_calculation"] or history["previous_generated_payroll"]
    assert after["recalculation_required"] is True
    assert "processing_scope_snapshot" not in after
    assert history["previous_processing_scope_snapshot"]
    assert after["summary"]["automatic_required"] == 0
    assert after["status"] in {"FILES_READY", "DRAFT"}
    assert after["business_decisions"][0]["status"] == "NEEDS_RECONFIRMATION"
    assert after["decisions"] == []
    assert after["calculation_invalidation_history"][-1]["previous_decisions"]

    history_count = len(after["calculation_invalidation_history"])
    pending_source = _group_file(tmp_path / "follow-up-pending.csv", "理化教师")
    pending = service.preview_subject_group_material(run_id, str(pending_source), "理化组")["subject_group_preview"]
    service.confirm_subject_group_material(run_id, pending["role"], pending["source_sha256"], "负责人",
                                           selected_group="理化组", candidate_id=pending["candidate_id"])
    after_material = service.store.get(run_id)
    assert after_material["recalculation_required"] is True
    assert len(after_material["calculation_invalidation_history"]) == history_count
    monkeypatch.undo()
    checked = service.check(run_id)
    assert not checked.get("recalculation_required")


def test_confirming_history_membership_invalidates_existing_results_without_recheck(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    service.confirm_staff_batch(run_id, "负责人", group_updates=[{"teacher_id": "math-id", "group": "数学组"}])
    service.check(run_id)
    before = service.store.get(run_id)
    source = _history(tmp_path / "science-history.xlsx", "science-id", 3100)
    service.stage_historical_salary_reference_preview(run_id, str(source), "理化组")
    monkeypatch.setattr(service, "check", lambda _run_id: pytest.fail("确认历史组籍不得自动重算"))

    pending = service.store.get(run_id)["historical_salary_reference_pending_preview"]
    service.import_base_salary_from_history(run_id, str(source), pending["source_sha256"],
                                            "负责人", selected_group="理化组")

    after = service.store.get(run_id)
    assert "core_calculation" not in after
    assert "generated_payroll" not in after
    assert after["calculation_invalidation_history"][-1]["previous_core_calculation"] or before.get("generated_payroll")
    assert after["recalculation_required"] is True
    assert after["historical_salary_reference_snapshots"][-1]["group_membership"]["group"] == "理化组"


@pytest.mark.parametrize("next_state", ["HOURLY_SUBMISSION_ONLY", "HAS_BASE_SALARY"])
def test_salary_basis_change_invalidates_existing_results_without_recheck(tmp_path, monkeypatch, next_state):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    service.confirm_staff_batch(run_id, "负责人", group_updates=[{"teacher_id": "math-id", "group": "数学组"}])
    service.check(run_id)
    before = service.store.get(run_id)
    assert service._salary_basis_for(before, "数学教师", "math-id")["state"] == "SOURCE_UNKNOWN"
    monkeypatch.setattr(service, "check", lambda _run_id: pytest.fail("确认工资基础不得自动重算"))

    service.confirm_staff_batch(run_id, "负责人", salary_basis_updates=[{
        "teacher_id": "math-id", "state": next_state, "group": "数学组",
    }])

    after = service.store.get(run_id)
    assert "core_calculation" not in after
    assert "generated_payroll" not in after
    assert after["calculation_invalidation_history"][-1]["previous_core_calculation"] or before.get("generated_payroll")
    assert after["recalculation_required"] is True
    assert after["summary"]["automatic_required"] == 0


def test_joint_leader_cannot_assign_group_outside_responsibility_but_dos_can(tmp_path):
    service = PayrollService(tmp_path / "data")
    joint_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    with pytest.raises(ValueError, match="不能把教师归入当前学科组长职责范围之外的科组"):
        service.confirm_staff_batch(joint_id, "负责人", group_updates=[{"teacher_id": "math-id", "group": "语文组"}])

    dos = service.create("2026-08", "GENERATE", operator_role="DOS")
    service.import_file(dos["id"], "schedule", str(_schedule(tmp_path / "dos-schedule.csv", [
        ("math-id", "数学教师", "数学"),
    ])))
    saved = service.confirm_staff_batch(dos["id"], "负责人", group_updates=[{"teacher_id": "math-id", "group": "语文组"}])
    assert saved["groups_confirmed"] == 1


def test_http_staff_batch_rejects_out_of_scope_group(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
    request = Request(
        f"{base}/api/runs/{run_id}/staff-batch",
        data=json.dumps({"confirmed_by": "负责人", "group_updates": [{"teacher_id": "math-id", "group": "语文组"}]}).encode(),
        headers={"X-Payroll-Token": token, "Content-Type": "application/json"},
    )
    try:
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 400
        assert "不能把教师归入当前学科组长职责范围之外的科组" in json.loads(error.value.read())["error"]
    finally:
        server.shutdown()


def test_same_sha_candidates_for_two_groups_confirm_and_cancel_by_exact_candidate(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "语文组"])
    source = _group_file(tmp_path / "same-source.csv", "数学教师")
    math = service.preview_subject_group_material(run_id, str(source), "数学组")["subject_group_preview"]
    chinese = service.preview_subject_group_material(run_id, str(source), "语文组")["subject_group_preview"]
    assert math["source_sha256"] == chinese["source_sha256"]
    assert math["candidate_id"] != chinese["candidate_id"]

    service.confirm_subject_group_material(run_id, "math", chinese["source_sha256"], "负责人",
                                           selected_group="语文组", candidate_id=chinese["candidate_id"])
    pending = service.store.get(run_id)["pending_subject_group_imports"]
    assert len(pending) == 1
    assert next(iter(pending.values()))["candidate_id"] == math["candidate_id"]

    service.cancel_subject_group_material(run_id, "math", math["source_sha256"], candidate_id=math["candidate_id"],
                                          selected_group="数学组")
    final = service.store.get(run_id)
    assert final["pending_subject_group_imports"] == {}
    assert [item["candidate_id"] for item in final["subject_group_materials"]] == [chinese["candidate_id"]]


def test_cancel_rejects_ambiguous_role_sha_without_candidate_id(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "语文组"])
    source = _group_file(tmp_path / "same-source.csv", "数学教师")
    math = service.preview_subject_group_material(run_id, str(source), "数学组")["subject_group_preview"]
    service.preview_subject_group_material(run_id, str(source), "语文组")

    with pytest.raises(ValueError, match="candidate_id"):
        service.cancel_subject_group_material(run_id, "math", math["source_sha256"])


def test_http_candidate_id_confirms_and_cancels_only_the_selected_group(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "语文组"])
    source = _group_file(tmp_path / "same-source.csv", "数学教师")
    math = service.preview_subject_group_material(run_id, str(source), "数学组")["subject_group_preview"]
    chinese = service.preview_subject_group_material(run_id, str(source), "语文组")["subject_group_preview"]
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]

    def call(action: str, payload: dict):
        request = Request(f"{base}/api/runs/{run_id}/{action}", data=json.dumps(payload).encode(),
                          headers={"X-Payroll-Token": token, "Content-Type": "application/json"})
        return json.loads(urlopen(request).read())

    try:
        confirmed = call("subject-group-confirm", {
            "role": "math", "source_sha256": chinese["source_sha256"], "selected_group": "语文组",
            "candidate_id": chinese["candidate_id"], "confirmed_by": "负责人",
        })
        assert confirmed["confirmation"]["candidate_id"] == chinese["candidate_id"]
        pending = service.store.get(run_id)["pending_subject_group_imports"]
        assert [item["candidate_id"] for item in pending.values()] == [math["candidate_id"]]
        removed = call("subject-group-cancel", {
            "role": "math", "source_sha256": math["source_sha256"], "selected_group": "数学组",
            "candidate_id": math["candidate_id"],
        })
        assert removed["pending_subject_group_imports"] == {}
        assert [item["candidate_id"] for item in removed["subject_group_materials"]] == [chinese["candidate_id"]]
    finally:
        server.shutdown()


@pytest.mark.parametrize("groups", [[], ["数学组", "非合法科组"]])
def test_joint_run_rejects_empty_or_illegal_group_selection(tmp_path, groups):
    service = PayrollService(tmp_path / "data")
    with pytest.raises(ValueError):
        service.create("2026-08", "GENERATE", operator_role="SUBJECT_LEADER", selected_groups=groups)


def test_single_group_and_legacy_selected_group_remain_compatible(tmp_path):
    service = PayrollService(tmp_path / "data")
    single = service.create("2026-08", "GENERATE", operator_role="SUBJECT_LEADER", selected_group="数学组")
    assert single["selected_groups"] == ["数学组"]
    assert single["selected_group"] == "数学组"

    old_run = service.store.get(single["id"])
    old_run.pop("selected_groups")
    service.store.save(old_run)
    reopened = service.get(single["id"])
    assert service._selected_groups(reopened) == ["数学组"]


def test_dos_always_persists_empty_group_selection_and_full_scope(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", operator_role="DOS", selected_groups=["数学组"])

    assert run["selected_groups"] == []
    assert run["selected_group"] == ""
    assert run["processing_scope"]["scope_kind"] == "FULL_DEPARTMENT"


def test_joint_group_submission_requires_one_owned_group_and_rejects_outside_group(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    source = _group_file(tmp_path / "chinese.csv", "语文教师")

    with pytest.raises(ValueError, match="明确选择"):
        service.preview_subject_group_material(run_id, str(source))
    with pytest.raises(ValueError, match="不在当前学科组长负责范围"):
        service.preview_subject_group_material(run_id, str(source), "语文组")

    allowed = _group_file(tmp_path / "math.csv", "数学教师")
    preview = service.preview_subject_group_material(run_id, str(allowed), "数学组")["subject_group_preview"]
    assert preview["recognized_group"] == "数学组"
    service.confirm_subject_group_material(run_id, preview["role"], preview["source_sha256"], "负责人", selected_group="数学组")


def test_joint_history_reference_requires_owned_group_per_file(tmp_path):
    service = PayrollService(tmp_path / "data")
    run_id = _run(service, tmp_path, groups=["数学组", "理化组"])
    source = _history(tmp_path / "history.xlsx", "math-id")

    with pytest.raises(ValueError, match="明确选择"):
        service.preview_base_salary_import(run_id, str(source))
    with pytest.raises(ValueError, match="不在当前学科组长负责范围"):
        service.stage_historical_salary_reference_preview(run_id, str(source), "语文组")

    service.stage_historical_salary_reference_preview(run_id, str(source), "数学组")
    assert service.store.get(run_id)["historical_salary_reference_pending_preview"]["selected_group"] == "数学组"


def test_legacy_role_selection_archives_old_result_and_accepts_multiple_groups(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    created = service.create("2026-08", "GENERATE")
    old = service.store.get(created["id"])
    old.pop("operator_role")
    old.pop("part_time_payroll_mode")
    old["generated_payroll"] = {"rows": [{"teacher": "历史教师", "final": 100}]}
    service.store.save(old)
    monkeypatch.setattr(service, "check", lambda _run_id: pytest.fail("角色保存不应重算"))

    selected = service.select_legacy_run_operator(created["id"], "SUBJECT_LEADER", "", "负责人",
                                                  selected_groups=["数学组", "理化组"])

    assert selected["selected_groups"] == ["数学组", "理化组"]
    assert selected["selected_group"] == ""
    assert "generated_payroll" not in selected
    assert selected["recalculation_required"] is True
    assert selected["calculation_invalidation_history"][-1]["event"] == "LEGACY_RUN_ROLE_SCOPE_CHANGED"
    assert selected["calculation_invalidation_history"][-1]["previous_generated_payroll"]["rows"][0]["final"] == 100


def test_legacy_run_archives_old_result_then_explicit_check_creates_new_result(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    created = service.create("2026-08", "GENERATE", operator_role="DOS")
    service.import_file(created["id"], "schedule", str(_schedule(tmp_path / "migration-schedule.csv", [
        ("math-id", "数学教师", "数学"),
    ])))
    service.confirm_staff_batch(created["id"], "负责人", group_updates=[{"teacher_id": "math-id", "group": "数学组"}])
    legacy = service.store.get(created["id"])
    legacy.pop("operator_role")
    legacy.pop("part_time_payroll_mode")
    legacy["core_calculation"] = {"rows": [{"teacher": "旧名单教师"}]}
    legacy["generated_payroll"] = {"rows": [{"teacher": "旧名单教师", "final": 345}]}
    legacy["processing_scope_snapshot"] = {"teachers": ["旧名单教师"]}
    legacy["field_records"] = [{"teacher": "旧名单教师", "field": "old"}]
    legacy["issue_groups"] = [{"id": "old-group", "teacher": "旧名单教师"}]
    legacy["audit_context"] = {"scope": ["旧名单教师"]}
    service.store.save(legacy)
    monkeypatch.setattr(service, "check", lambda _run_id: pytest.fail("角色迁移不得自动核算"))

    selected = service.select_legacy_run_operator(created["id"], "SUBJECT_LEADER", "数学组", "负责人")
    archived = selected["calculation_invalidation_history"][-1]
    assert selected["role_scope_recalculation_required"] is True
    assert selected["recalculation_required"] is True
    assert all(key not in selected for key in ("core_calculation", "generated_payroll", "processing_scope_snapshot", "audit_context"))
    assert selected["issue_groups"] == [] and selected["field_records"] == []
    assert archived["previous_generated_payroll"]["rows"][0]["final"] == 345
    assert archived["previous_issue_groups"][0]["teacher"] == "旧名单教师"

    monkeypatch.undo()
    checked = service.check(created["id"])
    assert checked["processing_scope_snapshot"]["teachers"] == ["数学教师"]
    assert checked.get("core_calculation")
    assert not checked.get("recalculation_required")
    assert not checked.get("role_scope_recalculation_required")
    assert len(checked["calculation_invalidation_history"]) == 1
    assert checked["calculation_invalidation_history"][0]["previous_generated_payroll"]["rows"][0]["final"] == 345


def test_legacy_role_recalculation_does_not_block_existing_pending_group_confirmation(tmp_path):
    service = PayrollService(tmp_path / "sandbox")
    created = service.create("2026-08", "GENERATE")
    service.import_file(created["id"], "schedule", str(_schedule(tmp_path / "legacy-schedule.csv", [
        ("math-id", "数学教师", "数学"),
    ])))
    source = _group_file(tmp_path / "legacy-math.csv", "数学教师")
    candidate = service.preview_subject_group_material(created["id"], str(source), "数学组")["subject_group_preview"]
    legacy = service.store.get(created["id"])
    legacy.pop("operator_role", None)
    legacy.pop("part_time_payroll_mode", None)
    legacy["core_calculation"] = {"rows": [{"teacher": "旧范围教师"}]}
    legacy["generated_payroll"] = {"rows": [{"teacher": "旧范围教师"}]}
    service.store.save(legacy)

    selected = service.select_legacy_run_operator(created["id"], "SUBJECT_LEADER", "数学组", "负责人")
    assert selected["role_scope_recalculation_required"] is True
    assert selected["recalculation_required"] is True
    assert "core_calculation" not in selected and "generated_payroll" not in selected
    assert len(selected["calculation_invalidation_history"]) == 1
    assert selected["calculation_invalidation_history"][0]["previous_generated_payroll"]["rows"][0]["teacher"] == "旧范围教师"
    assert candidate["candidate_id"] in selected["pending_subject_group_imports"]

    confirmed = service.confirm_subject_group_material(
        created["id"], candidate["role"], candidate["source_sha256"], "负责人",
        selected_group="数学组", candidate_id=candidate["candidate_id"],
    )
    assert confirmed["confirmation"]["candidate_id"] == candidate["candidate_id"]
    after = service.store.get(created["id"])
    assert after["role_scope_recalculation_required"] is True
    assert len(after["calculation_invalidation_history"]) == 1
    assert "generated_payroll" not in after
    assert not after["pending_subject_group_imports"]


def test_http_create_and_legacy_operator_accept_joint_groups_and_reject_illegal_group(tmp_path):
    service = PayrollService(tmp_path / "data")
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]

    def call(path: str, payload: dict):
        request = Request(base + path, data=json.dumps(payload).encode(),
                          headers={"X-Payroll-Token": token, "Content-Type": "application/json"})
        return json.loads(urlopen(request).read())

    try:
        created = call("/api/runs", {"period": "2026-08", "mode": "GENERATE", "operator_role": "SUBJECT_LEADER",
                                      "selected_groups": ["数学组", "理化组"], "selected_group": ""})
        assert created["selected_groups"] == ["数学组", "理化组"]
        assert created["selected_group"] == ""
        legacy = service.create("2026-08", "GENERATE")
        stored = service.store.get(legacy["id"])
        stored.pop("operator_role")
        stored.pop("part_time_payroll_mode")
        service.store.save(stored)
        upgraded = call(f"/api/runs/{legacy['id']}/operator-role", {
            "operator_role": "SUBJECT_LEADER", "selected_groups": ["数学组", "理化组"], "confirmed_by": "负责人",
        })
        assert upgraded["selected_groups"] == ["数学组", "理化组"]
        request = Request(base + "/api/runs", data=json.dumps({
            "period": "2026-08", "mode": "GENERATE", "operator_role": "SUBJECT_LEADER",
            "selected_groups": ["数学组", "非合法科组"],
        }).encode(), headers={"X-Payroll-Token": token, "Content-Type": "application/json"})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 400
    finally:
        server.shutdown()


def test_ui_exposes_multi_group_run_and_scoped_per_file_group_choices():
    app = (Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-run-group" in app
    assert "data-legacy-run-group" in app
    assert "selected_groups: operatorRole === \"SUBJECT_LEADER\" ? selectedGroups : []" in app
    assert "学科组长 · ${escapeHtml(runGroupsLabel(current, \"待选科组\"))}" in app
    assert "请为每份历史参考选择一个所属科组" in app
    assert "每份提交资料需单独指定所属科组" in app
    assert 'const editableGroups = current.operator_role === "SUBJECT_LEADER" ? selectedRunGroups(current) : payrollGroups;' in app
    assert "批量识别辅助资料（可选）" in app
    assert "工资资料和学科组提交表仍需在对应区域逐份确认" in app
    assert "资料包已自动识别并绑定到本次核算" not in app
