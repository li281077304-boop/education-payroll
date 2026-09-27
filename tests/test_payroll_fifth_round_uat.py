from __future__ import annotations

import csv
import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from openpyxl import Workbook

from payroll_core.period import AUTHORITY_USER_CONFIRMED
from payroll_ui.service import PayrollService
from payroll_ui.server import PayrollHttpServer


def _csv(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _schedule(path: Path, teachers: list[tuple[str, str, str]]) -> Path:
    headers = ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"]
    rows = [[name, "九年级", subject, "1对1", 1, "已上课", f"{day} 10:00"] for name, subject, day in teachers]
    return _csv(path, headers, rows)


def _group(path: Path, teachers: list[str], amount: int = 1) -> Path:
    headers = ["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"]
    return _csv(path, headers, [[name, amount, 0, amount, 30, 40, 0] for name in teachers])


def _renewal(path: Path, rows: list[list[object]]) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "8月"
    sheet.append(["教师", "AH", "AI", "AJ"])
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def test_schedule_authority_filters_period_and_survives_missing_group_data(tmp_path):
    service = PayrollService(tmp_path / "data")
    service.record_period_authority("2026-08", "2026-08-03", "2026-08-30", AUTHORITY_USER_CONFIRMED, confirmed_by="UAT 确认人", reason="测试人工月范围")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule(tmp_path / "schedule.csv", [
        (" 教师甲 ", "数学", "2026-08-05"),
        ("教师甲", "数学", "2026-08-28"),
        ("教师乙", "数学", "2026-08-10"),
        ("不应进入", "数学", "2026-08-31"),
    ])
    service.import_file(run["id"], "schedule", str(schedule))
    facts = service._roster_facts(service.store.get(run["id"]))
    assert {item["display_name"] for item in facts["teachers"]} == {"教师甲", "教师乙"}
    assert facts["schedule_record_count"] == 3
    assert next(item for item in facts["teachers"] if item["display_name"] == "教师甲")["schedule_record_count"] == 2

    group = _group(tmp_path / "math-submit.csv", ["教师甲"])
    preview = service.preview_subject_group_material(run["id"], str(group))["subject_group_preview"]
    before_confirm = service._roster_facts(service.store.get(run["id"]))
    assert preview["matched"] == [{"teacher": "教师甲", "schedule_record_count": 2}]
    assert "教师乙" in {item["teacher"] for item in preview["possible_missing"]}
    assert {item["display_name"] for item in before_confirm["teachers"]} == {"教师甲", "教师乙"}
    confirmed = service.confirm_subject_group_material(run["id"], "math", preview["source_sha256"], "UAT 确认人")["run"]
    assert {item["display_name"] for item in confirmed["roster_facts"]["teachers"]} == {"教师甲", "教师乙"}


def test_subject_group_preview_does_not_change_active_payroll_or_roster(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])
    service.import_file(run["id"], "schedule", str(schedule))
    stored = service.store.get(run["id"])
    stored["core_calculation"] = {"rows": [{"teacher": "教师甲", "fields": {"AA": {"value": 9}}}]}
    stored["generated_payroll"] = {"status": "READY", "rows": [{"teacher": "教师甲", "final_fields": {"AA": {"value": 9}}}]}
    before = service._roster_facts(stored)
    service.store.save(stored)
    source = _group(tmp_path / "math-submit.csv", ["教师甲"])

    service.preview_subject_group_material(run["id"], str(source))

    after = service.store.get(run["id"])
    assert after["status"] == "DRAFT"
    assert after["core_calculation"] == stored["core_calculation"]
    assert after["generated_payroll"] == stored["generated_payroll"]
    assert after["roster_authority"] == stored["roster_authority"]
    assert service._roster_facts(after)["teachers"] == before["teachers"]
    assert "math" not in after["files"]


def test_canceling_unconfirmed_group_returns_run_to_ready_material_state(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])))
    preview = service.preview_subject_group_material(run["id"], str(_group(tmp_path / "math-submit.csv", ["教师甲"])))
    assert preview["run"]["status"] == "DRAFT"

    cancelled = service.cancel_subject_group_material(run["id"], "math")

    assert cancelled["status"] == "FILES_READY"
    assert cancelled["health"]["ready"] is True


def test_direct_subject_group_import_is_blocked_at_service_boundary(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    with pytest.raises(ValueError, match="先预览并由负责人确认"):
        service.import_file(run["id"], "math", str(_group(tmp_path / "math.csv", ["教师甲"])))
    assert "math" not in service.store.get(run["id"])["files"]


def test_subject_group_http_file_endpoint_cannot_bypass_confirmation(tmp_path):
    server = PayrollHttpServer(("127.0.0.1", 0), PayrollService(tmp_path / "data"), Path(__file__).parents[1] / "payroll_ui" / "static")
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        request = Request(
            base + "/api/runs",
            data=json.dumps({"period": "2026-08", "mode": "GENERATE"}).encode(),
            headers={"Content-Type": "application/json", "X-Payroll-Token": token},
            method="POST",
        )
        run = json.loads(urlopen(request).read())
        request = Request(
            base + f"/api/runs/{run['id']}/files",
            data=json.dumps({"role": "math", "path": str(tmp_path / "math.csv")}).encode(),
            headers={"Content-Type": "application/json", "X-Payroll-Token": token},
            method="POST",
        )
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 409
        assert "预览并由负责人确认" in error.value.read().decode("utf-8")
        assert "math" not in server.service.store.get(run["id"])["files"]
    finally:
        server.shutdown()
        worker.join(timeout=2)
        server.server_close()


def test_schedule_same_name_with_distinct_teacher_ids_fails_closed(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    schedule = _csv(tmp_path / "schedule-with-ids.csv", [
        "teacher_id", "teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time",
    ], [
        ["T-01", "同名教师", "九年级", "数学", "1对1", 1, "已上课", "2026-08-05 10:00"],
        ["T-02", "同名教师", "九年级", "数学", "1对1", 1, "已上课", "2026-08-06 10:00"],
    ])
    service.import_file(run["id"], "schedule", str(schedule))

    facts = service._roster_facts(service.store.get(run["id"]))

    assert len(facts["teachers"]) == 1
    assert facts["identity_conflicts"]
    assert set(facts["identity_conflicts"][0]["teacher_ids"]) == {"T-01", "T-02"}
    with pytest.raises(ValueError, match="同名/教师编号冲突"):
        service.check(run["id"])


def test_group_confirmation_persists_and_replacement_needs_explicit_confirmation(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])))
    first = _group(tmp_path / "math-first.csv", ["教师甲"])
    first_preview = service.preview_subject_group_material(run["id"], str(first))["subject_group_preview"]
    service.confirm_subject_group_material(run["id"], "math", first_preview["source_sha256"], "UAT 确认人")

    reopened = PayrollService(tmp_path / "data").get(run["id"])
    confirmation = reopened["subject_group_confirmations"]["math"]
    assert confirmation["confirmed_by"] == "UAT 确认人"
    assert confirmation["period"] == "2026-08"
    assert confirmation["source_sha256"] == first_preview["source_sha256"]
    assert next(item for item in reopened["materials"] if item["role"] == "math")["confirmed_for_run"] is True

    second = _group(tmp_path / "math-second.csv", ["教师甲"], amount=2)
    second_preview = service.preview_subject_group_material(run["id"], str(second))["subject_group_preview"]
    assert second_preview["replacement_required"] is True
    assert service.store.get(run["id"])["files"]["math"]["sha256"] == first_preview["source_sha256"]
    with pytest.raises(ValueError, match="明确选择"):
        service.confirm_subject_group_material(run["id"], "math", second_preview["source_sha256"], "UAT 确认人")
    replaced = service.confirm_subject_group_material(run["id"], "math", second_preview["source_sha256"], "UAT 确认人", replace_existing=True)["run"]
    assert replaced["files"]["math"]["sha256"] == second_preview["source_sha256"]
    assert service.store.get(run["id"])["subject_group_confirmation_history"]["math"]


def test_old_group_preview_cannot_be_confirmed_after_period_change(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05"), ("教师甲", "数学", "2026-09-05")])))
    source = _group(tmp_path / "math-submit.csv", ["教师甲"])
    preview = service.preview_subject_group_material(run["id"], str(source))["subject_group_preview"]
    service.change_period(run["id"], "2026-09")

    with pytest.raises(ValueError, match="月份已变化"):
        service.confirm_subject_group_material(run["id"], "math", preview["source_sha256"], "UAT 确认人")


def test_renewal_preview_splits_matched_no_row_identity_and_outside_roster(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule(tmp_path / "schedule.csv", [
        ("教师甲", "数学", "2026-08-05"), ("教师乙", "数学", "2026-08-06"),
        ("教师丙", "数学", "2026-08-07"), ("教师丁", "数学", "2026-08-08"),
    ])
    service.import_file(run["id"], "schedule", str(schedule))
    # The source row for 甲 cannot choose between two same-name schedule identities.
    stored = service.store.get(run["id"])
    duplicate = dict(next(item for item in stored["schedule_roster_snapshot"]["teachers"] if item["display_name"] == "教师甲"))
    duplicate["teacher_id"] = "教师甲-另一身份"
    roster = list(stored["schedule_roster_snapshot"]["teachers"]) + [duplicate]
    monkeypatch.setattr(service, "_roster_facts", lambda _run, **_kwargs: {"teachers": roster})
    source = _renewal(tmp_path / "续费.xlsx", [
        ["教师甲", 2, 1, 0], ["教师丁", 1, 0, 0], ["排课外教师", 3, 0, 0],
    ])
    service.import_material_file(run["id"], "renewal", str(source))

    preview = service.preview_renewal_material(run["id"])

    assert preview["match_counts"] == {
        "matched": 1, "no_renewal_row": 2, "identity_unmatched": 1, "outside_roster": 1,
    }
    assert preview["matched"][0]["teacher"] == "教师丁"
    assert {item["teacher"] for item in preview["no_renewal_row"]} == {"教师乙", "教师丙"}
    assert preview["identity_unmatched"][0]["source_teacher"] == "教师甲"
    assert preview["outside_roster"][0]["source_teacher"] == "排课外教师"


def test_duplicate_renewal_results_are_source_conflicts_not_identity_failures(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])
    service.import_file(run["id"], "schedule", str(schedule))
    source = _renewal(tmp_path / "续费.xlsx", [["教师甲", 2, 1, 0], ["教师甲", 2, 1, 0]])
    service.import_material_file(run["id"], "renewal", str(source))

    preview = service.preview_renewal_material(run["id"])

    assert preview["identity_unmatched"] == []
    assert {item["code"] for item in preview["source_conflicts"]} == {"DUPLICATE_TEACHER_RESULT"}
    assert preview["match_counts"]["identity_unmatched"] == 0
    assert preview["can_confirm"] is False
