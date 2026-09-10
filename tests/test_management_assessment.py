"""Group-leader management assessment: objective rules, manual subjective items."""
from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from payroll_core.assessment import SCORE_RULE_VERSION, score_objective
from payroll_ui.service import PayrollService
from tests.test_payroll_ui_service import _prepared_run


HEADERS = ["进步率", "周平均", "续推人次", "退费人次", "总学员数", "离职率"]


def _sheet(path: Path, headers: list[str], rows: list[list[object]]) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = "月度最佳学科组考核"
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


def _service(tmp_path: Path) -> PayrollService:
    return PayrollService(tmp_path / "data")


def test_confirmed_rule_scores_a_full_marks_case():
    score = score_objective({"progress_rate": 0.8, "weekly_average": 3.8, "renewal_count": 8, "student_count": 100, "refund_count": 0, "turnover_rate": 0})

    assert score.items == {"progress_rate": 30.0, "weekly_average": 25.0, "renewal_rate": 25.0, "refund_rate": 10.0, "turnover_rate": 10.0}
    assert score.total == 100.0
    assert score.rule_version == SCORE_RULE_VERSION


def test_refund_and_turnover_bands_follow_the_confirmed_rule():
    assert score_objective({"refund_rate": 0.01, "turnover_rate": 0.04}).items["refund_rate"] == 10.0
    assert score_objective({"refund_rate": 0.02, "turnover_rate": 0.05}).items["refund_rate"] == 5.0
    assert score_objective({"refund_rate": 0.03, "turnover_rate": 0.05}).items["refund_rate"] == 0.0
    assert score_objective({"refund_rate": 0.02, "turnover_rate": 0.05}).items["turnover_rate"] == 0.0
    assert score_objective({"refund_rate": 0.02, "turnover_rate": 0.0}).items["turnover_rate"] == 10.0


def test_objective_scores_are_capped_at_full_marks():
    score = score_objective({"progress_rate": 5.0, "weekly_average": 99.0, "renewal_rate": 0.9, "refund_rate": 0.0, "turnover_rate": 0.0})
    assert score.total == 100.0


def test_subjective_items_stay_pending_until_a_human_confirms_them(tmp_path):
    service = _service(tmp_path)
    path = _sheet(tmp_path / "leader.xlsx", HEADERS + ["主观评分"], [[0.8, 3.8, 8, 0, 100, 0, 12]])

    record = service.import_management_assessment(str(path), "2026-08", "组长甲", "组长甲")
    assert record["role"] == "GROUP_LEADER"
    assert record["objective_score"] == 100.0
    assert record["pending_subjective"] == ["subjective_1"]

    pending = service.confirm_management_assessment(record["id"], "主管")
    assert pending["status"] == "NEEDS_MANUAL_CONFIRMATION"
    assert pending["final_score"] == 0.0
    assert pending["amount_status"] == "RULE_NOT_CONFIGURED"
    assert pending["evidence"]["pending_subjective"] == ["subjective_1"]


def test_confirmed_result_never_invents_an_amount_without_a_rule(tmp_path):
    service = _service(tmp_path)
    path = _sheet(tmp_path / "leader.xlsx", HEADERS, [[0.8, 3.8, 8, 0, 100, 0]])

    record = service.import_management_assessment(str(path), "2026-08", "组长甲", "组长甲")
    result = service.confirm_management_assessment(record["id"], "主管")

    assert result["status"] == "FINAL"
    assert result["final_score"] == 100.0
    assert result["final_amount"] is None
    assert result["amount_status"] == "RULE_NOT_CONFIGURED"
    assert result["rule_version"] == SCORE_RULE_VERSION
    assert result["reviewer"] == "主管" and result["reviewed_at"]
    assert result["source_input_ids"] == [record["id"]]


def test_amount_is_produced_only_when_a_rule_is_configured(tmp_path):
    service = _service(tmp_path)
    path = _sheet(tmp_path / "leader.xlsx", HEADERS, [[0.8, 3.8, 8, 0, 100, 0]])
    record = service.import_management_assessment(str(path), "2026-08", "组长甲", "组长甲")

    result = service.confirm_management_assessment(record["id"], "主管", amount_rule={"amount_per_point": 1.5})

    assert result["amount_status"] == "CONFIGURED"
    assert result["final_amount"] == 150.0


def test_checks_report_missing_duplicate_formula_and_range_problems(tmp_path):
    service = _service(tmp_path)
    empty = _sheet(tmp_path / "empty.xlsx", ["无指标"], [["无"]])
    formula = _sheet(tmp_path / "formula.xlsx", HEADERS, [[0.8, 3.8, "=SUM(A1:A2)", 0, 100, 0]])
    ranged = _sheet(tmp_path / "range.xlsx", HEADERS, [[1.5, 3.8, 8, 0, 100, 0]])

    service.import_management_assessment(str(empty), "2026-08", "组长甲", "组长甲")
    service.import_management_assessment(str(formula), "2026-08", "组长乙", "组长乙")
    service.import_management_assessment(str(ranged), "2026-08", "组长丙", "组长丙")
    service.import_management_assessment(str(ranged), "2026-08", "组长丙", "组长丙")

    codes = {item["code"] for item in service.assessment_findings("2026-08", expected_leaders=["组长丁"])}
    assert {"STRUCTURE_ERROR", "MISSING_REQUIRED", "FORMULA_UNEVALUATED", "SCORE_OUT_OF_RANGE", "DUPLICATE", "MISSING_SUBMISSION"} <= codes


def test_only_a_final_result_can_bind_to_a_run(tmp_path):
    service, run, *_ = _prepared_run(tmp_path)
    path = _sheet(tmp_path / "leader.xlsx", HEADERS, [[0.8, 3.8, 8, 0, 100, 0]])
    subjective_path = _sheet(tmp_path / "leader-subjective.xlsx", HEADERS + ["主观评分"], [[0.8, 3.8, 8, 0, 100, 0, 12]])

    waiting = service.import_management_assessment(str(subjective_path), "2026-08", "组长丙", "组长丙")
    pending = service.confirm_management_assessment(waiting["id"], "主管")
    with pytest.raises(ValueError, match="已确认"):
        service.bind_management_assessment(run["id"], pending["id"])

    record = service.import_management_assessment(str(path), "2026-08", "组长甲", "组长甲")
    final = service.confirm_management_assessment(record["id"], "主管")
    bound = service.bind_management_assessment(run["id"], final["id"])
    assert bound["assessment_bindings"][0]["result_id"] == final["id"]
    assert bound["assessment_bindings"][0]["amount_status"] == "RULE_NOT_CONFIGURED"

    other = service.create("2026-09")
    with pytest.raises(ValueError, match="月份"):
        service.bind_management_assessment(other["id"], final["id"])


def test_assessment_never_creates_a_payroll_submission(tmp_path):
    service = _service(tmp_path)
    path = _sheet(tmp_path / "leader.xlsx", HEADERS, [[0.8, 3.8, 8, 0, 100, 0]])

    service.import_management_assessment(str(path), "2026-08", "组长甲", "组长甲")

    assert service.store.list_submissions() == []
    assert service.store.list_submission_batches() == []
