"""Release checks for the fixed, uniquely applicable Payroll V1 star roster."""

from __future__ import annotations

import csv
from pathlib import Path

from payroll_ui.service import MONTHLY_FLOW_SUBMISSION_FIRST, PayrollService


def _schedule(path: Path, period: str) -> Path:
    day = f"{period}-05"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["teacher_id", "teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"])
        writer.writerow(["inside", "名单内教师", "九年级", "数学", "1对1", 1, "已上课", f"{day} 10:00"])
        writer.writerow(["outside", "名单外教师", "九年级", "数学", "1对1", 1, "已上课", f"{day} 11:00"])
    return path


def _submission(path: Path) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"])
        writer.writerow(["名单内教师", 1, 0, 1, 30, 40, 0])
        writer.writerow(["名单外教师", 1, 0, 1, 30, 40, 0])
    return path


def test_august_september_october_runs_bind_one_fixed_59_person_roster(tmp_path: Path) -> None:
    service = PayrollService(tmp_path / "private-payroll-store")
    ratings = [{"teacher": f"名单内教师{i:02d}", "rating": (i % 6) + 1} for i in range(59)]
    ratings[0]["teacher"] = "名单内教师"
    fixed = service.save_rating_version("2026-08", "2027-09", "Payroll V1 固定 59 人名单", "fixed-59", ratings)[0]

    for period in ("2026-08", "2026-09", "2026-10"):
        service.record_period_authority(period, f"{period}-05", f"{period}-05", "USER_CONFIRMED",
                                        confirmed_by="脱敏 Release UAT", reason="合成周期验证。")
        run = service.create(period, "GENERATE", operator_role="DOS",
                             monthly_flow_version=MONTHLY_FLOW_SUBMISSION_FIRST)
        assert run["rating_version_id"] == fixed["id"]
        service.import_file(run["id"], "schedule", str(_schedule(tmp_path / f"schedule-{period}.csv", period)))
        service.confirm_af_policy(run["id"], "脱敏 Release UAT")
        service.import_material_file(run["id"], "subject_group", str(_submission(tmp_path / f"group-{period}.csv")))

        checked = service.check(run["id"])
        assert checked["authority_context"]["rating"]["binding_status"] == "BOUND"
        assert checked["rating_version_id"] == fixed["id"]
        roster = service.store.get_rating_version(fixed["id"])["ratings"]
        assert len(roster) == 59
        rating_by_teacher = {item["teacher"]: item["rating"] for item in roster}
        assert rating_by_teacher["名单内教师"] == 1
        assert "名单外教师" not in rating_by_teacher

    active_for_period = {
        period: [item for item in service.store.list_rating_versions()
                 if item.get("status", "ACTIVE") == "ACTIVE"
                 and item["effective_from"] <= period <= item["effective_to"]]
        for period in ("2026-08", "2026-09", "2026-10")
    }
    assert {period: len(versions) for period, versions in active_for_period.items()} == {
        "2026-08": 1, "2026-09": 1, "2026-10": 1,
    }
