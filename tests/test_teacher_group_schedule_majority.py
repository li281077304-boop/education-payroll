"""Current-period subject frequency is the primary teacher-group evidence."""
from __future__ import annotations

import csv
from pathlib import Path

from payroll_ui.service import (PayrollService, OPERATOR_DOS, OPERATOR_SUBJECT_LEADER,
                               MONTHLY_FLOW_SUBMISSION_FIRST)


def _schedule(path: Path) -> Path:
    headers = ["teacher_id", "teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"]
    rows = []
    lessons = [("teacher-major", "教师甲", "数学")] * 18
    lessons += [("teacher-major", "教师甲", "物理")] * 3
    lessons += [("teacher-english", "教师乙", "英语")] * 2
    for index, (teacher_id, teacher, subject) in enumerate(lessons, start=1):
        day = ((index - 1) % 28) + 1
        hour = 8 + ((index - 1) % 10)
        rows.append([teacher_id, teacher, "九年级", subject, "1对1", 1, "已上课", f"2026-08-{day:02d} {hour:02d}:00"])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _service(tmp_path: Path) -> tuple[PayrollService, dict]:
    service = PayrollService(tmp_path / "isolated")
    service.record_period_authority("2026-08", "2026-08-01", "2026-08-31", "USER_CONFIRMED",
                                   confirmed_by="合成测试", reason="仅用于课组推断回归。")
    run = service.create("2026-08", operator_role=OPERATOR_DOS)
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv")))
    return service, run


def test_current_schedule_majority_autogroups_without_batch_confirmation(tmp_path: Path) -> None:
    service, run = _service(tmp_path)
    profile = {
        "id": "profile-conflict", "teacher_id": "teacher-major", "teacher": "教师甲",
        "group": "理化组", "effective_from": "0000-00", "effective_to": "9999-12",
        "status": "ACTIVE", "source_label": "过往确认记录", "created_at": "2026-01-01T00:00:00+00:00",
    }
    service.store.save_teacher_group_profiles_and_run([profile], service._load(run["id"]))
    overview = service.employment_overview(service.get(run["id"]))
    by_name = {item["teacher"]: item for item in overview["teachers"]}

    assert by_name["教师甲"]["teacher_group"] == "数学组"
    assert by_name["教师甲"]["teacher_group_status"] == "AUTO"
    assert "18 节" in by_name["教师甲"]["teacher_group_source"]
    assert by_name["教师乙"]["teacher_group"] == "英语组"
    assert overview["group_needs_confirmation"] == []


def test_subject_leader_scope_uses_current_schedule_majority(tmp_path: Path) -> None:
    service = PayrollService(tmp_path / "isolated")
    service.record_period_authority("2026-08", "2026-08-01", "2026-08-31", "USER_CONFIRMED",
                                   confirmed_by="合成测试", reason="仅用于课组推断回归。")
    run = service.create("2026-08", operator_role=OPERATOR_SUBJECT_LEADER,
                         selected_group="数学组", monthly_flow_version=MONTHLY_FLOW_SUBMISSION_FIRST)
    service.import_file(run["id"], "schedule", str(_schedule(tmp_path / "schedule.csv")))
    facts = service._roster_facts(service.get(run["id"]))
    scope = service._processing_scope(service.get(run["id"]), facts["teachers"])

    assert [item["display_name"] for item in scope["teachers"]] == ["教师甲"]
    assert scope["scope_count"] == 1
