from __future__ import annotations

import csv
import pytest

from payroll_ui.service import PayrollService


def _write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def test_csv_materials_use_one_adapter_across_check_preview_generate_reopen_and_period_change(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08", mode="AUDIT")
    schedule = _write_csv(
        tmp_path / "schedule.csv",
        ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"],
        [["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026-08-10 10:00"] for _ in range(20)],
    )
    subject_group = _write_csv(
        tmp_path / "subject-group.csv",
        ["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"],
        [["教师甲", 40, 0, 40, 30, 300, 0]],
    )

    imported_schedule = service.import_file(run["id"], "schedule", str(schedule))
    imported_payroll = service.import_file(run["id"], "math", str(subject_group))
    assert imported_schedule["files"]["schedule"]["sheets"] == ["CSV"]
    assert imported_payroll["files"]["math"]["sheets"] == ["CSV"]

    checked = service.check(run["id"])
    assert checked["core_calculation"]["rows"]
    preview = service.preview_payroll(run["id"])
    assert preview["generated_payroll"]["rows"]
    generated = service.generate_payroll(run["id"], str(tmp_path / "generated.xlsx"))
    assert generated["path"]

    reopened = PayrollService(tmp_path / "app-data")
    assert reopened.get(run["id"])["files"]["schedule"]["name"] == "schedule.csv"
    assert reopened.check(run["id"])["core_calculation"]["rows"]
    changed = reopened.change_period(run["id"], "2026-09")
    assert changed["files"]["schedule"]["records"] == 0
    assert changed["files"]["math"]["records"] == 1


def test_csv_schedule_filters_each_salary_month_without_relabeling_dates(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08", mode="GENERATE")
    schedule = _write_csv(
        tmp_path / "cross-month.csv",
        ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"],
        [
            ["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026-08-31 10:00"],
            ["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026-09-01 10:00"],
        ],
    )
    first = service.import_file(run["id"], "schedule", str(schedule))
    assert first["files"]["schedule"]["records"] == 1
    assert first["period_check"]["coverage"]["first_date"] == "2026-08-31"
    changed = service.change_period(run["id"], "2026-09")
    assert changed["files"]["schedule"]["records"] == 1
    assert changed["period"] == "2026-09"
    checked = service.check(run["id"])
    assert checked["core_calculation"]["rows"]
    records = service._read_for_run("schedule", schedule, service.store.get(run["id"])).records
    assert [record.lesson_date for record in records] == ["2026-09-01"]


def test_august_csv_on_september_run_retains_source_month_and_can_switch(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-09", mode="GENERATE")
    schedule = _write_csv(
        tmp_path / "aug-only.csv",
        ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"],
        [["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026-08-10 10:00"] for _ in range(20)],
    )

    imported = service.import_file(run["id"], "schedule", str(schedule))
    assert imported["files"]["schedule"]["records"] == 0
    assert imported["period_check"]["source_month"] == "2026-08"
    assert imported["period_check"]["mismatch"] is True
    assert imported["period_check"]["decision"] == "PENDING"

    switched = service.resolve_period_check(run["id"], "SWITCH")
    assert switched["period"] == "2026-08"
    assert switched["files"]["schedule"]["records"] == 20
    assert switched["period_check"]["decision"] == "SWITCHED"


def test_csv_schedule_date_formats_and_unparseable_attended_rows_fail_closed(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08", mode="GENERATE")
    schedule = _write_csv(
        tmp_path / "date-formats.csv",
        ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"],
        [
            ["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026-8-5 10:00"],
            ["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026/08/06 10:00"],
            ["教师甲", "九年级", "数学", "1对1", 1, "已上课", "2026年8月7日 10:00"],
            ["教师甲", "九年级", "数学", "1对1", 1, "已上课", "not-a-date"],
        ],
    )

    imported = service.import_file(run["id"], "schedule", str(schedule))
    assert imported["files"]["schedule"]["records"] == 3
    assert "UNPARSEABLE_LESSON_DATE" in imported["files"]["schedule"]["warnings"]
    records = service._read_for_run("schedule", schedule, service.store.get(run["id"])).records
    assert [record.lesson_date for record in records] == ["2026-08-05", "2026-08-06", "2026-08-07"]

    invalid = _write_csv(
        tmp_path / "all-invalid.csv",
        ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"],
        [["教师甲", "九年级", "数学", "1对1", 1, "已上课", "unknown"]],
    )
    invalid_run = service.create("2026-08", mode="GENERATE")
    with pytest.raises(ValueError, match="无法识别上课日期"):
        service.import_file(invalid_run["id"], "schedule", str(invalid))
