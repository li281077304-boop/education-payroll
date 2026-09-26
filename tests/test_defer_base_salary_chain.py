"""「暂不录入，先生成工资预览」的完整状态链。

2026-09-26 UAT 断点：`deferBaseSalaryQuick()` 只保存了一个 defer 决定，然后
`tab = "payroll"` + `render`，既没有 preview 也没有 generate。按钮写着"先生成…"，
却什么都没生成，用户还得再点一次「自动核算」。

这条链必须是：点击 → 按钮 loading/disabled → 保存决定 → 自动重新核算并生成工资预览
→ 有其它阻塞走异常处理 / 无阻塞直接进工资预览 → M、AV 保持真实待补充（绝不按 0）。
"""
from __future__ import annotations

import csv

import pytest

from payroll_ui.service import PayrollService

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
    service.import_file(run["id"], "math", str(payroll))
    return service, service.get(run["id"])


def _row_field(payload: dict, code: str) -> dict:
    rows = ((payload.get("generated_payroll") or {}).get("rows")) or []
    assert rows, "暂不录入后应当已经有一份工资预览行"
    return (rows[0].get("final_fields") or {}).get(code) or {}


def test_defer_refuses_without_a_confirming_person_and_writes_nothing(tmp_path):
    service, run = _run_with_materials(tmp_path)

    with pytest.raises(ValueError, match="确认人"):
        service.defer_base_salary(run["id"], "  ")

    assert service.store.get(run["id"])["base_salary_deferred"] is False


def test_defer_reports_missing_materials_instead_of_pretending_it_ran(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")

    result = service.defer_base_salary(run["id"], "核算负责人")
    outcome = result["defer_outcome"]

    assert outcome["status"] == "BLOCKED"
    assert outcome["reason"] == "MATERIALS_MISSING"
    assert outcome["missing_materials"], "缺什么材料必须明确说出来"
    assert result["base_salary_deferred"] is True
    # 什么都没有核算出来时，也不能凭空出现工资行。
    assert not (result.get("generated_payroll") or {}).get("rows")


def test_defer_runs_the_check_itself_so_the_user_never_presses_recheck_again(tmp_path):
    """一次点击就完成核算：返回结果必须已经带着本次 Run 的计算与预览行."""
    service, run = _run_with_materials(tmp_path)

    result = service.defer_base_salary(run["id"], "核算负责人")

    assert result["base_salary_deferred"] is True
    assert result["base_salary_deferred_by"] == "核算负责人"
    assert result["base_salary_deferred_at"]
    assert result["core_calculation"]["rows"], "暂不录入必须同时完成自动核算"
    assert (result.get("generated_payroll") or {}).get("rows"), "暂不录入必须同时给出工资预览"
    assert result["defer_outcome"]["status"] in {"PREVIEW_READY", "NEEDS_ATTENTION"}


def test_defer_keeps_m_and_av_genuinely_pending_never_zero(tmp_path):
    service, run = _run_with_materials(tmp_path)

    result = service.defer_base_salary(run["id"], "核算负责人")

    m = _row_field(result, "M")
    av = _row_field(result, "AV")
    assert m.get("value") is None, "暂不录入不是 M=0"
    assert m.get("state") not in {"DETERMINED"}
    assert av.get("value") is None, "AV 也不能把缺失当成 0 汇总"
    assert av.get("state") != "DETERMINED"
    assert result["defer_outcome"]["base_salary_state"] == "MISSING_SOURCE"


def test_defer_routes_to_the_exception_flow_when_other_blockers_remain(tmp_path):
    service, run = _run_with_materials(tmp_path)

    outcome = service.defer_base_salary(run["id"], "核算负责人")["defer_outcome"]

    assert outcome["status"] == "NEEDS_ATTENTION"
    assert outcome["reason"] == "BUSINESS_BLOCKERS"
    assert outcome["blockers"], "有阻塞时必须把阻塞理由交回界面"
    assert "阻塞" in outcome["message"]


def test_a_blocked_outcome_never_claims_the_preview_is_ready(tmp_path):
    """状态只能反映真实结果：没有阻塞才允许进入工资预览."""
    service, run = _run_with_materials(tmp_path)
    result = service.defer_base_salary(run["id"], "核算负责人")
    outcome = result["defer_outcome"]
    blockers = (result.get("generated_payroll") or {}).get("blockers") or []

    if outcome["status"] == "PREVIEW_READY":
        assert blockers == []
        assert outcome["blockers"] == []
    else:
        assert blockers, "既然不是 PREVIEW_READY，就必须真的存在阻塞"


def test_a_clean_run_reaches_the_payroll_preview_in_one_click(tmp_path, monkeypatch):
    """无阻塞时，defer 的结果直接就是可查看的工资预览（不再需要第二次点击）."""
    service, run = _run_with_materials(tmp_path)
    clean = {
        "id": run["id"], "period": "2026-08", "period_authority": run.get("period_authority") or {},
        "core_calculation": {"rows": [{"teacher": "教师甲"}]},
        "generated_payroll": {
            "status": "FINAL", "blockers": [], "rule_versions": {},
            "rows": [{"teacher": "教师甲", "final_fields": {
                "M": {"value": None, "state": "BASE_SALARY_BLOCKED", "reason": "缺少 G～L"},
                "AV": {"value": None, "state": "HUMAN_REQUIRED", "reason": "M 未确定"},
            }}],
        },
    }
    monkeypatch.setattr(PayrollService, "check", lambda self, run_id: clean)

    outcome = service.defer_base_salary(run["id"], "核算负责人")["defer_outcome"]

    assert outcome["status"] == "PREVIEW_READY"
    assert outcome["blockers"] == []
    assert outcome["base_salary_state"] == "MISSING_SOURCE"


def test_defer_is_repeatable_without_losing_the_recorded_decision(tmp_path):
    service, run = _run_with_materials(tmp_path)

    service.defer_base_salary(run["id"], "核算负责人", "月末先出草稿")
    again = service.defer_base_salary(run["id"], "核算负责人", "月末先出草稿")

    stored = service.store.get(run["id"])
    assert stored["base_salary_deferred"] is True
    assert stored["base_salary_deferred_reason"] == "月末先出草稿"
    assert again["defer_outcome"]["status"] in {"PREVIEW_READY", "NEEDS_ATTENTION"}
