"""“暂不录入”只保存轻量状态，不触发全量工资核算。"""
from __future__ import annotations

import csv

import pytest

from payroll_ui.service import PayrollService
from tests.payroll_uat_helpers import import_confirmed_subject_group

SCHEDULE_HEADERS = ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"]
PAYROLL_HEADERS = ["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"]


def _write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _run_with_materials(tmp_path, period: str = "2026-08") -> tuple[PayrollService, dict]:
    service = PayrollService(tmp_path / "data")
    run = service.create(period, "GENERATE")
    schedule = _write_csv(
        tmp_path / "schedule.csv", SCHEDULE_HEADERS,
        [["教师甲", "九年级", "数学", "1对1", 1, "已上课", f"2026-08-{day:02d} 10:00"] for day in range(1, 31)],
    )
    payroll = _write_csv(tmp_path / "math.csv", PAYROLL_HEADERS, [["教师甲", 40, 0, 40, 30, 300, 0]])
    service.import_file(run["id"], "schedule", str(schedule))
    import_confirmed_subject_group(service, run["id"], "math", payroll)
    return service, service.get(run["id"])


def test_defer_refuses_without_a_confirming_person_and_writes_nothing(tmp_path):
    service, run = _run_with_materials(tmp_path)

    with pytest.raises(ValueError, match="确认人"):
        service.defer_base_salary(run["id"], "  ")

    assert service.store.get(run["id"])["base_salary_deferred"] is False


def test_defer_records_choice_even_before_materials_are_ready_without_calculating(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    monkeypatch.setattr(service, "check", lambda *_args, **_kwargs: pytest.fail("暂不录入不得触发完整核算"))

    result = service.defer_base_salary(run["id"], "核算负责人")
    outcome = result["defer_outcome"]

    assert outcome["status"] == "DEFERRED"
    assert outcome["reason"] == "USER_SKIPPED_FOR_NOW"
    assert not outcome["missing_materials"]
    assert result["base_salary_deferred"] is True
    # 什么都没有核算出来时，也不能凭空出现工资行。
    assert not (result.get("generated_payroll") or {}).get("rows")


def test_defer_keeps_existing_preview_untouched_and_does_not_rerun_check(tmp_path, monkeypatch):
    service, run = _run_with_materials(tmp_path)
    before = service.store.get(run["id"])
    monkeypatch.setattr(service, "check", lambda *_args, **_kwargs: pytest.fail("不得在暂不录入时重算"))

    result = service.defer_base_salary(run["id"], "核算负责人")

    assert result["base_salary_deferred"] is True
    assert result["base_salary_deferred_by"] == "核算负责人"
    assert result["base_salary_deferred_at"]
    assert result["defer_outcome"]["status"] == "DEFERRED"
    assert "core_calculation" not in result
    assert "generated_payroll" not in result
    assert service.store.get(run["id"]).get("core_calculation") == before.get("core_calculation")
    assert service.store.get(run["id"]).get("generated_payroll") == before.get("generated_payroll")


def test_defer_does_not_create_m_or_av_values(tmp_path):
    service, run = _run_with_materials(tmp_path)

    result = service.defer_base_salary(run["id"], "核算负责人")

    assert not (result.get("generated_payroll") or {}).get("rows")
    assert result["defer_outcome"]["base_salary_state"] == "MISSING_SOURCE"


def test_defer_is_repeatable_without_losing_the_recorded_decision(tmp_path):
    service, run = _run_with_materials(tmp_path)

    service.defer_base_salary(run["id"], "核算负责人", "月末先出草稿")
    again = service.defer_base_salary(run["id"], "核算负责人", "月末先出草稿")

    stored = service.store.get(run["id"])
    assert stored["base_salary_deferred"] is True
    assert stored["base_salary_deferred_reason"] == "月末先出草稿"
    assert again["defer_outcome"]["status"] == "DEFERRED"
