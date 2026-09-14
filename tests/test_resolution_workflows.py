from dataclasses import replace
from pathlib import Path

import pytest

from payroll_core.models.records import ScheduleRecord
from payroll_core.reconcile.ac_resolution import (
    ApprovedPayrollOverride,
    SourceDataCorrection,
    assess_counterfactual_cause,
    compare_contribution_structure,
    resolve_ac,
    schedule_record_id,
)
from tests.test_payroll_ui_service import _prepared_run_with_values


def _record() -> ScheduleRecord:
    return ScheduleRecord(period="2026-08", teacher="教师甲", grade="八年级", subject="数学", class_type="小班", attended=3, lesson_status="已上课", source="schedule.xlsx")


def _correction(record: ScheduleRecord, **changes) -> SourceDataCorrection:
    values = dict(run_id="run-a", period="2026-08", teacher=record.teacher, source_record_id=schedule_record_id(record), source_file_hash="hash-a", field="grade", original_value="八年级", corrected_value="七年级", reason_code="GRADE_ROLLOVER_NOT_UPDATED", reason_text="年级未同步", confirmed_by="审核人", confirmed_at="2026-08-31T00:00:00+00:00")
    values.update(changes)
    return SourceDataCorrection(**values)


def test_resolution_rejects_cross_run_teacher_period_and_forged_fingerprint():
    record = _record()
    correction = _correction(record)
    with pytest.raises(ValueError, match="another payroll run"):
        resolve_ac([record], run_id="run-b", period="2026-08", corrections=[correction], source_hashes={record.source: "hash-a"})
    with pytest.raises(ValueError, match="teacher"):
        resolve_ac([record], run_id="run-a", period="2026-08", corrections=[_correction(record, teacher="他人")], source_hashes={record.source: "hash-a"})
    with pytest.raises(ValueError, match="period"):
        resolve_ac([record], run_id="run-a", period="2026-09", corrections=[correction], source_hashes={record.source: "hash-a"})
    with pytest.raises(ValueError, match="fingerprint"):
        _correction(record, fingerprint="forged")


def test_source_hash_and_unknown_contribution_block_exact_cause():
    record = _record()
    correction = _correction(record)
    with pytest.raises(ValueError, match="hash"):
        resolve_ac([record], run_id="run-a", period="2026-08", corrections=[correction], source_hashes={record.source: "changed"})
    unknown = replace(record, grade="未知年级")
    result = resolve_ac([unknown], run_id="run-a", period="2026-08", source_hashes={unknown.source: "hash-a"})
    assert result.effective_total is None
    assert assess_counterfactual_cause(baseline_total=result.original_total, recomputed_total=result.effective_total, payroll_total=1).status == "UNEXPLAINED"


def test_counterfactual_and_structure_guards():
    assert assess_counterfactual_cause(baseline_total=10, recomputed_total=8, payroll_total=8).status == "EXACT_CAUSE"
    assert assess_counterfactual_cause(baseline_total=10, recomputed_total=9, payroll_total=8).status == "POSSIBLE_CAUSE"
    record = _record()
    result = resolve_ac([record], run_id="run-a", period="2026-08", source_hashes={record.source: "hash-a"})
    comparison = compare_contribution_structure(result.contributions, {schedule_record_id(record): 0.0})
    assert comparison.status == "CONTRIBUTION_STRUCTURE_MISMATCH"


def test_ambiguous_cause_when_baseline_already_matches_payroll():
    """A zero baseline gap proves no cause, even when recomputation moves the total."""
    assessment = assess_counterfactual_cause(baseline_total=10.0, recomputed_total=8.0, payroll_total=10.0)
    assert assessment.status == "AMBIGUOUS_CAUSE"
    assert assessment.baseline_difference == pytest.approx(0.0)


def test_override_is_persistent_run_scoped_and_closes_issue(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10.0)
    checked = service.check(run["id"])
    group = next(item for item in checked["issue_groups"] if item["teacher"] == "李四" and "class_value" in item["affected_fields"])
    evidence = service.evidence(run["id"], group["id"])
    course = evidence["resolution_courses"][0]
    resolved = service.create_resolution(run["id"], group["id"], "APPROVED_PAYROLL_OVERRIDE", course["id"], {"approved_treatment": "已批准样本口径", "approved_contribution": 10.0, "reason": "脱敏验收"}, "审核人", group["fingerprint"])
    assert not any(item["teacher"] == "李四" and item["field"] == "class_value" for item in resolved["issues"])
    stored = service.active_resolution(run["id"], service.store.get(run["id"])["resolutions"][0]["id"])
    assert stored["outcome"] == "RESOLVED_BY_APPROVED_OVERRIDE"
    reopened = type(service)(tmp_path / "app-data").get(run["id"])
    assert reopened["resolutions"][0]["outcome"] == "RESOLVED_BY_APPROVED_OVERRIDE"


def test_source_correction_preserves_fact_and_closes_issue(tmp_path):
    service, run, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=3.24)
    checked = service.check(run["id"])
    group = next(item for item in checked["issue_groups"] if item["teacher"] == "李四" and "class_value" in item["affected_fields"])
    course = service.evidence(run["id"], group["id"])["resolution_courses"][0]
    result = service.create_resolution(run["id"], group["id"], "SOURCE_DATA_CORRECTION", course["id"], {"field": "grade", "corrected_value": "高三", "reason_code": "GRADE_ROLLOVER_NOT_UPDATED", "reason": "脱敏的年级修正"}, "审核人", group["fingerprint"])
    assert not any(item["teacher"] == "李四" and item["field"] == "class_value" for item in result["issues"])
    saved = service.store.get(run["id"])["resolutions"][0]
    # August ordinary-class fallback resolves the explicit incoming grade to
    # the accepted prior-grade coefficient before a source correction is
    # recorded; the correction still preserves that resolved source fact.
    assert saved["original_value"] == "七年级"
    assert saved["corrected_value"] == "高三"
    assert saved["outcome"] == "RESOLVED_BY_SOURCE_CORRECTION"


def test_duplicate_resolution_and_source_change_require_reconfirmation(tmp_path):
    service, run, schedule, *_ = _prepared_run_with_values(tmp_path, one_to_one=1.8, class_value=10.0)
    checked = service.check(run["id"])
    group = next(item for item in checked["issue_groups"] if item["teacher"] == "李四" and "class_value" in item["affected_fields"])
    course = service.evidence(run["id"], group["id"])["resolution_courses"][0]
    payload = {"approved_treatment": "已批准样本口径", "approved_contribution": 10.0, "reason": "脱敏验收"}
    service.create_resolution(run["id"], group["id"], "APPROVED_PAYROLL_OVERRIDE", course["id"], payload, "审核人", group["fingerprint"])
    with pytest.raises(ValueError):
        service.create_resolution(run["id"], group["id"], "APPROVED_PAYROLL_OVERRIDE", course["id"], payload, "审核人", group["fingerprint"])
    service.import_file(run["id"], "schedule", str(schedule))
    assert service.store.get(run["id"])["resolutions"][0]["status"] == "NEEDS_RECONFIRMATION"
