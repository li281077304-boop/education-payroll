"""人工月 / 工资周期 authority 的回归测试。

真实 UAT 断点（2026-09-26）：2026-08 的课表实际覆盖 8/1～8/30，系统却按自然月
8/1～8/31 判断完整性，于是把 8/30 当成"周期末缺失"，先用 PERIOD_COVERAGE_INCOMPLETE
阻断最终导出，再要求用户人工确认 8/30 是截止日。

正确关系是：工资月份 → 该月的人工月 authority →（用它筛选与判断完整性）→ 课表日期
用于校验人工月，而不是反过来定义人工月。
"""
from __future__ import annotations

import csv

from payroll_core.period import (
    AUTHORITY_MANUAL_RECORD,
    AUTHORITY_USER_CONFIRMED,
    period_authority_summary,
)
from payroll_ui.service import PayrollService

SCHEDULE_HEADERS = ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"]
PAYROLL_HEADERS = ["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"]


def _write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _schedule(path, name: str, rows):
    return _write_csv(path / name, SCHEDULE_HEADERS, rows)


def _lessons(days: list[str], teacher: str = "教师甲"):
    return [[teacher, "九年级", "数学", "1对1", 1, "已上课", f"{day} 10:00"] for day in days]


def _payroll(path, name: str, teacher: str = "教师甲"):
    return _write_csv(path / name, PAYROLL_HEADERS, [[teacher, 40, 0, 40, 30, 300, 0]])


def _august_days() -> list[str]:
    return [f"2026-08-{day:02d}" for day in range(1, 31)]


def _import_materials(service: PayrollService, run_id: str, tmp_path, schedule_path, name=None):
    """Import the minimum material set the generate flow needs."""
    service.import_file(run_id, "schedule", str(schedule_path))
    service.import_file(run_id, "math", str(_payroll(tmp_path, name or "math-2026-08.csv")))
    return service


def _authority_2026_08(service: PayrollService, start: str = "2026-08-01", end: str = "2026-08-30"):
    return service.record_period_authority(
        "2026-08", start, end, AUTHORITY_MANUAL_RECORD,
        confirmed_by="测试", reason="人工月资料：2026-08 = 8/1～8/30",
    )


# --------------------------------------------------------------------------- 绑定


def test_run_uses_the_months_authority_instead_of_the_natural_month(tmp_path):
    """人工月 authority 必须成为 Run 的边界，而不是自然月."""
    service = PayrollService(tmp_path / "data")
    _authority_2026_08(service)

    run = service.create("2026-08", "GENERATE")

    assert run["period_end"] == "2026-08-30"
    assert run["period_start"] == "2026-08-01"
    assert run["period_boundary_source"] == AUTHORITY_MANUAL_RECORD
    assert run["period_authority"]["is_fallback"] is False
    # 来源语义必须能区分：资料导入 / 人工确认 / 来源未标明 / 自然月兜底
    assert run["period_authority"]["source_label"] == "人工月资料（来源未标明）"


def test_authority_survives_reopen_and_keeps_its_identity(tmp_path):
    service = PayrollService(tmp_path / "data")
    authority = _authority_2026_08(service)
    service.create("2026-08", "GENERATE")

    reopened = PayrollService(tmp_path / "data")

    assert reopened.period_authority_for("2026-08")["id"] == authority["id"]
    stored = reopened.list()[0]
    assert stored["period_end"] == "2026-08-30"
    assert period_authority_summary(reopened.period_authority_for("2026-08"))["period_end"] == "2026-08-30"


def test_without_any_authority_the_run_says_it_is_on_the_natural_month_fallback(tmp_path):
    service = PayrollService(tmp_path / "data")

    run = service.create("2026-08", "GENERATE")

    assert run["period_start"] == "2026-08-01" and run["period_end"] == "2026-08-31"
    assert run["period_authority"]["is_fallback"] is True
    assert "自然月兜底" in run["period_authority"]["source_label"]


def test_changing_the_payroll_month_rebinds_to_that_months_authority(tmp_path):
    service = PayrollService(tmp_path / "data")
    _authority_2026_08(service)
    service.record_period_authority("2026-09", "2026-09-01", "2026-09-28", AUTHORITY_MANUAL_RECORD,
                                    confirmed_by="测试", reason="人工月资料：2026-09 = 9/1～9/28")
    run = service.create("2026-08", "GENERATE")
    assert run["period_end"] == "2026-08-30"

    changed = service.change_period(run["id"], "2026-09")

    assert changed["period"] == "2026-09"
    assert (changed["period_start"], changed["period_end"]) == ("2026-09-01", "2026-09-28")
    assert changed["period_boundary_source"] == AUTHORITY_MANUAL_RECORD


def test_an_existing_natural_month_run_heals_itself_when_the_authority_arrives(tmp_path):
    """先建 Run、后补人工月资料时，不需要用户为新 Run 再确认一次."""
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    assert run["period_end"] == "2026-08-31"

    _authority_2026_08(service)
    healed = service.ensure_period_authority(run["id"])

    assert healed["period_end"] == "2026-08-30"
    assert healed["period_authority"]["is_fallback"] is False


# --------------------------------------------------------------------------- 完整性


def test_schedule_covering_the_authority_end_is_complete(tmp_path):
    """人工月 8/1～8/30 + 课表 8/1～8/30 = 完整，不再要求确认 8/30."""
    service = PayrollService(tmp_path / "data")
    _authority_2026_08(service)
    run = service.create("2026-08", "GENERATE")
    _import_materials(service, run["id"], tmp_path, _schedule(tmp_path, "august.csv", _lessons(_august_days())))

    checked = service.check(run["id"])
    coverage = checked["period_check"]["coverage"]

    assert coverage["last_date"] == "2026-08-30"
    assert coverage["month_end"] == "2026-08-30"
    assert coverage["incomplete_tail"] is False
    assert coverage["outside_period"] is False
    assert "PERIOD_COVERAGE_INCOMPLETE" not in checked["generated_payroll"]["blockers"]
    assert checked["period_check"]["outside_authority"] is False
    assert checked["period_check"]["period_authority_is_fallback"] is False


def test_lessons_beyond_the_authority_window_are_flagged_as_out_of_period(tmp_path):
    """人工月 8/1～8/30 + 8/31 课程 = 越界提示（而不是静默算进本期）."""
    service = PayrollService(tmp_path / "data")
    _authority_2026_08(service)
    run = service.create("2026-08", "GENERATE")
    _import_materials(service, run["id"], tmp_path,
                      _schedule(tmp_path, "august-plus.csv", _lessons(_august_days() + ["2026-08-31"])))

    checked = service.check(run["id"])

    assert checked["period_check"]["outside_authority"] is True
    assert "PERIOD_OUTSIDE_AUTHORITY" in checked["generated_payroll"]["blockers"]
    assert checked["generated_payroll"]["status"] == "NEEDS_CONFIRMATION"


def test_csv_schedule_is_filtered_by_the_authority_window(tmp_path):
    """CSV 排课按人工月过滤：8/31 的行不属于该人工月."""
    service = PayrollService(tmp_path / "data")
    _authority_2026_08(service)
    run = service.create("2026-08", "GENERATE")
    schedule = _schedule(tmp_path, "cross-month.csv", _lessons(_august_days() + ["2026-09-01", "2026-08-31"]))

    imported = service.import_file(run["id"], "schedule", str(schedule))

    assert imported["files"]["schedule"]["records"] == 30
    assert imported["period_check"]["coverage"]["last_date"] == "2026-08-30"
    records = service._read_for_run("schedule", schedule, service.store.get(run["id"])).records
    assert {record.lesson_date for record in records} == set(_august_days())


def test_a_file_name_month_can_never_override_the_authority(tmp_path):
    """文件名只是低优先级辅助证据，不能改写人工月 authority."""
    service = PayrollService(tmp_path / "data")
    _authority_2026_08(service)
    run = service.create("2026-08", "GENERATE")
    mislabelled = _schedule(tmp_path, "排课列表_09月.csv", _lessons(["2026-08-10", "2026-08-11"]))

    imported = service.import_file(run["id"], "schedule", str(mislabelled))

    assert imported["period_end"] == "2026-08-30"
    assert imported["period_boundary_source"] == AUTHORITY_MANUAL_RECORD
    assert imported["period_check"]["file_name_month"] == "09"
    assert imported["files"]["schedule"]["records"] == 2


# --------------------------------------------------------------------------- 复用


def test_a_confirmed_window_becomes_the_reusable_authority_for_the_month(tmp_path):
    """人工确认一次 → 形成可复用权威记录 → 新 Run 自动沿用，不再重复确认."""
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    _import_materials(service, run["id"], tmp_path, _schedule(tmp_path, "august.csv", _lessons(_august_days())))

    service.confirm_period_window(run["id"], "2026-08-01", "2026-08-30", "核算负责人", "公司工资周期按 8/1～8/30")

    stored = service.period_authority_for("2026-08")
    assert stored is not None
    assert stored["boundary_source"] == AUTHORITY_USER_CONFIRMED
    assert (stored["period_start"], stored["period_end"]) == ("2026-08-01", "2026-08-30")

    later = service.create("2026-08", "GENERATE")
    assert later["period_end"] == "2026-08-30"
    assert later["period_boundary_source"] == AUTHORITY_USER_CONFIRMED
    assert later["period_authority"]["confirmed_by"] == "核算负责人"


def test_reconfirming_the_same_window_does_not_create_a_new_revision(tmp_path):
    service = PayrollService(tmp_path / "data")
    first = _authority_2026_08(service)
    again = service.record_period_authority("2026-08", "2026-08-01", "2026-08-30", AUTHORITY_MANUAL_RECORD,
                                            confirmed_by="第二次确认", reason="同一条事实")

    assert again["id"] == first["id"]
    assert again["revision"] == 1
    assert len(service.period_authorities()) == 1


def test_a_different_window_supersedes_the_previous_revision_but_keeps_history(tmp_path):
    service = PayrollService(tmp_path / "data")
    first = _authority_2026_08(service)

    corrected = service.record_period_authority("2026-08", "2026-08-03", "2026-08-30", AUTHORITY_USER_CONFIRMED,
                                                confirmed_by="核算负责人", reason="首课日为 8/3")

    assert corrected["revision"] == 2
    assert corrected["supersedes"] == first["id"]
    current = service.period_authority_for("2026-08")
    assert current["id"] == corrected["id"]
    # 历史版本仍留在记录里，供审计追溯。
    assert {item["authority_id"] for item in service.period_authorities()} == {first["id"], corrected["id"]}


def test_backfill_recovers_a_confirmed_window_from_an_existing_run(tmp_path):
    """历史 Run 上已经人工确认过的周期，可以被恢复为可复用人工月."""
    service = PayrollService(tmp_path / "data")
    legacy = service.create("2026-08", "GENERATE", period_start="2026-08-03", period_end="2026-08-30",
                            period_boundary_source=AUTHORITY_USER_CONFIRMED)
    assert service.period_authority_for("2026-08") is None

    dry = service.backfill_period_authorities()
    assert [item["payroll_period"] for item in dry["proposals"]] == ["2026-08"]

    service.backfill_period_authorities(apply=True)
    stored = service.period_authority_for("2026-08")
    assert (stored["period_start"], stored["period_end"]) == ("2026-08-03", "2026-08-30")
    assert stored["evidence"]["derived_from_run"] == legacy["id"]

    later = service.create("2026-08", "GENERATE")
    assert (later["period_start"], later["period_end"]) == ("2026-08-03", "2026-08-30")


def test_backfill_never_promotes_a_natural_month_run(tmp_path):
    service = PayrollService(tmp_path / "data")
    service.create("2026-08", "GENERATE")

    result = service.backfill_period_authorities(apply=True)

    assert result["proposals"] == []
    assert service.period_authority_for("2026-08") is None


def test_a_deliberate_run_window_is_not_overwritten_by_a_later_authority(tmp_path):
    """本 Run 上用户明确设定的周期优先于该月 authority，不被静默覆盖."""
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE", period_start="2026-08-03", period_end="2026-08-29",
                         period_boundary_source=AUTHORITY_USER_CONFIRMED)
    _authority_2026_08(service)

    healed = service.ensure_period_authority(run["id"])

    assert (healed["period_start"], healed["period_end"]) == ("2026-08-03", "2026-08-29")


def test_recording_an_authority_requires_an_explicit_source(tmp_path):
    service = PayrollService(tmp_path / "data")
    try:
        service.record_period_authority("2026-08", "2026-08-01", "2026-08-30", "LEGACY_CALENDAR_DEFAULT")
    except ValueError as exc:
        assert "来源" in str(exc)
    else:  # pragma: no cover - the call above must fail
        raise AssertionError("自然月兜底不能当作人工月记录保存")
