from __future__ import annotations

import csv

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
