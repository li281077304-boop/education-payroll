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


def test_legacy_role_selection_accepts_multiple_groups_without_rewriting_old_result(tmp_path, monkeypatch):
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
    assert selected["generated_payroll"]["rows"][0]["final"] == 100


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
