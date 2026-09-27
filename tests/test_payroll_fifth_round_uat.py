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


def test_staff_roster_batch_confirmation_persists_group_and_employment(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [
        ("教师甲", "数学", "2026-08-05"), ("教师乙", "物理", "2026-08-06"),
    ])))
    teachers = service._roster_facts(service.store.get(run["id"]))["teachers"]
    ids = {item["display_name"]: item["teacher_id"] for item in teachers}
    result = service.confirm_staff_batch(
        run["id"], "负责人",
        employment_updates=[{"teacher_id": value, "employment_type": "FULL_TIME"} for value in ids.values()],
        group_updates=[{"teacher_id": ids["教师甲"], "group": "数学组"}, {"teacher_id": ids["教师乙"], "group": "理化组"}],
        salary_basis_updates=[
            {"teacher_id": ids["教师甲"], "state": "HOURLY_SUBMISSION_ONLY", "group": "数学组"},
            {"teacher_id": ids["教师乙"], "state": "HAS_BASE_SALARY", "group": "理化组"},
        ],
    )
    assert result["employment_confirmed"] == 2
    assert result["groups_confirmed"] == 2
    reopened = PayrollService(tmp_path / "data").get(run["id"])
    by_name = {item["teacher"]: item for item in reopened["employment"]["teachers"]}
    assert by_name["教师甲"]["teacher_group"] == "数学组"
    assert by_name["教师乙"]["teacher_group"] == "理化组"
    assert all(item["employment_type"] == "FULL_TIME" for item in by_name.values())
    assert by_name["教师甲"]["salary_basis"] == "HOURLY_SUBMISSION_ONLY"
    assert by_name["教师乙"]["salary_basis"] == "HAS_BASE_SALARY"


def test_group_processing_scope_requires_confirmed_membership_not_current_schedule_subject(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", operator_role="SUBJECT_LEADER", selected_group="数学组")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [
        ("数学老师", "数学", "2026-08-05"), ("理化老师", "物理", "2026-08-06"),
    ])))

    view = service.get(run["id"])

    assert {item["display_name"] for item in view["roster_facts"]["teachers"]} == {"数学老师", "理化老师"}
    assert view["processing_scope"]["scope_count"] == 0
    assert "CURRENT_SCHEDULE_SUBJECT_CANDIDATE" not in view["processing_scope"]["sources"]
    with pytest.raises(ValueError, match="尚未确认任何属于数学组"):
        service.check(run["id"])

    service.confirm_staff_batch(run["id"], "负责人", group_updates=[{"teacher": "数学老师", "group": "数学组"}])
    view = service.get(run["id"])
    result = service.check(run["id"])

    assert view["processing_scope"]["scope_count"] == 1
    assert view["processing_scope"]["teachers"][0]["display_name"] == "数学老师"
    assert result["processing_scope_snapshot"]["teachers"] == ["数学老师"]
    assert all(item.get("teacher") != "理化老师" for item in result["issue_groups"])


def test_dos_processing_scope_remains_the_full_schedule_roster(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", operator_role="DOS")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [
        ("数学老师", "数学", "2026-08-05"), ("理化老师", "物理", "2026-08-06"),
    ])))

    result = service.check(run["id"])

    assert result["processing_scope_snapshot"]["operator_role"] == "DOS"
    assert set(result["processing_scope_snapshot"]["teachers"]) == {"数学老师", "理化老师"}


def test_non_math_group_submission_is_scoped_by_declared_group(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", operator_role="SUBJECT_LEADER", selected_group="语文组")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [
        ("语文老师", "语文", "2026-08-05"), ("数学老师", "数学", "2026-08-06"),
    ])))
    source = _group(tmp_path / "chinese-group.csv", ["语文老师"])
    preview = service.preview_subject_group_material(run["id"], str(source), "语文组")["subject_group_preview"]
    assert preview["recognized_group"] == "语文组"
    service.confirm_subject_group_material(run["id"], preview["role"], preview["source_sha256"], "组长")

    reopened = service.get(run["id"])
    assert reopened["processing_scope"]["teachers"][0]["display_name"] == "语文老师"
    assert reopened["processing_scope"]["scope_count"] == 1


def test_hourly_submission_row_reads_group_final_total_without_part_time_amount_calculation():
    row = PayrollService._build_hourly_submission_row("按课时教师", {
        "source": "脱敏组表.xlsx", "value": 1280.5,
        "fields": {"AA": 20, "AC": 3, "AD": 23, "AE": None, "AF": None, "AV": 1280.5},
        "field_provenance": {},
    })

    assert row.part_time_amount is None
    assert row.fields["PART_TIME"]["state"] == "NOT_APPLICABLE"
    assert row.final_fields["AV"]["value"] == 1280.5
    assert row.final_fields["AV"]["state"] == "DETERMINED"
    assert "不由系统重新计算" in row.final_fields["AV"]["reason"]
    assert row.final is True


def test_hourly_submission_only_run_reads_group_total_without_calculating_part_time(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", operator_role="DOS")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])))
    source = _group(tmp_path / "math.csv", ["教师甲"], amount=8)
    preview = service.preview_subject_group_material(run["id"], str(source), "数学组")["subject_group_preview"]
    service.confirm_subject_group_material(run["id"], preview["role"], preview["source_sha256"], "组长")
    roster = service._roster_facts(service.store.get(run["id"]))["teachers"]
    service.confirm_staff_batch(run["id"], "负责人", salary_basis_updates=[{
        "teacher_id": roster[0]["teacher_id"], "state": "HOURLY_SUBMISSION_ONLY", "group": "数学组",
    }])

    checked = service.check(run["id"])
    generated = service._generated_from_checked(checked)

    assert checked["hourly_submission_results"]["教师甲"]["value"] == 0
    hourly_row = next(row for row in generated.rows if row.teacher == "教师甲")
    assert hourly_row.part_time_amount is None
    assert hourly_row.final_fields["AV"]["value"] == 0
    assert not any("兼职" in blocker and "单价" in blocker for blocker in hourly_row.blockers)


def test_new_run_does_not_infer_missing_salary_basis_as_part_time(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", operator_role="DOS")
    schedule = _schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])
    service.import_file(run["id"], "schedule", str(schedule))
    service.save_employment_profile("教师甲", "PART_TIME", "旧历史事实确认人", effective_from="2026-08")
    stored = service.store.get(run["id"])

    basis = service._salary_basis_for(stored, "教师甲", "教师甲")
    fact = service._employment_types_for(stored, for_calculation=True)["教师甲"]

    assert basis["state"] == "SOURCE_UNKNOWN"
    assert fact["employment_type"] == "PART_TIME"  # person fact is retained, but it is not a salary-basis inference
    assert stored["part_time_payroll_mode"] == "GROUP_SUBMISSION_ONLY"
    checked = service.check(run["id"])
    assert not (checked.get("core_calculation") or {}).get("rows")
    assert any(issue.get("field") == "salary_basis" for issue in checked.get("issues", []))


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


def test_group_confirmation_persists_and_multiple_files_are_independent(tmp_path):
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
    assert second_preview["replacement_required"] is False
    assert second_preview["cross_file_duplicates"][0]["teacher"] == "教师甲"
    assert service.store.get(run["id"])["files"]["math"]["sha256"] == first_preview["source_sha256"]
    added = service.confirm_subject_group_material(run["id"], "math", second_preview["source_sha256"], "UAT 确认人")["run"]
    assert len([item for item in added["subject_group_materials"] if item["status"] == "CONFIRMED"]) == 2
    assert added["files"]["math"]["sha256"] == first_preview["source_sha256"]


def test_multiple_same_group_candidates_can_wait_independently(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])))
    candidates = []
    for name, amount in (("math-one.csv", 1), ("math-two.csv", 2)):
        source = _group(tmp_path / name, ["教师甲"], amount=amount)
        candidates.append(service.preview_subject_group_material(run["id"], str(source))["subject_group_preview"])
    stored = service.store.get(run["id"])["pending_subject_group_imports"]
    assert len(stored) == 2
    assert {item["source_sha256"] for item in stored.values()} == {item["source_sha256"] for item in candidates}

    for candidate in candidates:
        service.confirm_subject_group_material(run["id"], "math", candidate["source_sha256"], "负责人")
    assert not service.store.get(run["id"])["pending_subject_group_imports"]
    assert len([item for item in service.store.get(run["id"])["subject_group_materials"] if item["status"] == "CONFIRMED"]) == 2


def test_group_confirmation_reuses_reviewed_record_snapshot_instead_of_reparsing(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])))
    source = _group(tmp_path / "math.csv", ["教师甲"], amount=3)
    preview = service.preview_subject_group_material(run["id"], str(source))["subject_group_preview"]
    original_read = service._read_for_run

    def no_group_reparse(role, path, bound_run):
        if role in {"math", "science"}:
            raise AssertionError("confirmation/check should use the reviewed group snapshot")
        return original_read(role, path, bound_run)

    monkeypatch.setattr(service, "_read_for_run", no_group_reparse)
    confirmed = service.confirm_subject_group_material(run["id"], "math", preview["source_sha256"], "负责人")["run"]
    assert confirmed["subject_group_materials"][0]["record_snapshot"]
    checked = service.check(run["id"])
    assert checked["processing_scope_snapshot"]["teachers"] == ["教师甲"]


def test_group_file_duplicate_conflict_is_field_scoped_and_removal_is_audited(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv", [("教师甲", "数学", "2026-08-05")])))
    files = []
    for name, amount in (("math-a.csv", 1), ("math-b.csv", 2)):
        source = _group(tmp_path / name, ["教师甲"], amount=amount)
        preview = service.preview_subject_group_material(run["id"], str(source))["subject_group_preview"]
        confirmed = service.confirm_subject_group_material(run["id"], "math", preview["source_sha256"], "负责人")
        files.append((source, confirmed["confirmation"]))

    result = service.check(run["id"])
    assert any(item["teacher"] == "教师甲" for item in result["subject_group_source_conflicts"])
    material_id = next(item["material_id"] for item in result["subject_group_materials"] if item["source_sha256"] == files[1][1]["source_sha256"])
    removed = service.remove_subject_group_material(run["id"], material_id, "负责人")
    assert len([item for item in removed["subject_group_materials"] if item["status"] == "CONFIRMED"]) == 1
    assert any(item["material_id"] == material_id and item["status"] == "REMOVED_FROM_RUN" for item in service.store.get(run["id"])["subject_group_materials"])


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
