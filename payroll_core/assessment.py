"""Objective scoring and checking for management assessments.

Objective items follow the confirmed 2026-08-05 definitions only:
  progress  = D / 0.8 * 30   (cap 30)
  weekly    = F / 3.8 * 25   (cap 25)
  renewal   = H / 0.08 * 25  (cap 25)
  refund    = 10 at <=1%, 0 at >=3%, linear between   (cap 10)
  turnover  = 10 at <=4%, otherwise 0                 (cap 10)

Subjective items are never scored here. A result stays
NEEDS_MANUAL_CONFIRMATION until a human confirms them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .models.management_assessment import (
    RULE_NOT_CONFIGURED,
    AssessmentFinding,
    AssessmentRecord,
    AssessmentResultStatus,
    ManagementAssessmentResult,
)


SCORE_RULE_VERSION = "ASSESSMENT_SCORE_RULE_2026-08-05"

OBJECTIVE_INPUTS: tuple[str, ...] = (
    "progress_rate",
    "weekly_average",
    "renewal_rate",
    "refund_rate",
    "turnover_rate",
)
DERIVED_RATES: dict[str, tuple[str, str]] = {
    "renewal_rate": ("renewal_count", "student_count"),
    "refund_rate": ("refund_count", "student_count"),
}
SUBJECTIVE_PREFIX = "subjective_"
#: Raw inputs worth checking, including the counts a rate may be derived from.
CHECKED_INPUTS: tuple[str, ...] = OBJECTIVE_INPUTS + ("renewal_count", "refund_count", "student_count")

FULL_MARKS: dict[str, float] = {
    "progress_rate": 30.0,
    "weekly_average": 25.0,
    "renewal_rate": 25.0,
    "refund_rate": 10.0,
    "turnover_rate": 10.0,
}


@dataclass(frozen=True)
class ObjectiveScore:
    items: Mapping[str, float]
    total: float
    rule_version: str = SCORE_RULE_VERSION


def _number(metrics: Mapping[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if value is None or value == "":
        return None
    if isinstance(value, str) and value.strip().startswith("="):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_metrics(metrics: Mapping[str, Any]) -> dict[str, float]:
    """Resolve rates, deriving them from counts when only counts are supplied."""
    resolved: dict[str, float] = {}
    for key in OBJECTIVE_INPUTS:
        value = _number(metrics, key)
        if value is not None:
            resolved[key] = value
            continue
        derived = DERIVED_RATES.get(key)
        if not derived:
            continue
        numerator, denominator = _number(metrics, derived[0]), _number(metrics, derived[1])
        if numerator is not None and denominator not in (None, 0):
            resolved[key] = numerator / denominator
    resolved.setdefault("turnover_rate", 0.0)
    return resolved


def score_objective(metrics: Mapping[str, Any]) -> ObjectiveScore:
    resolved = resolve_metrics(metrics)
    items: dict[str, float] = {}
    for key, full in FULL_MARKS.items():
        value = resolved.get(key)
        if value is None:
            items[key] = 0.0
            continue
        if key == "refund_rate":
            items[key] = _refund_score(value)
        elif key == "turnover_rate":
            items[key] = full if value <= 0.04 else 0.0
        else:
            base = {"progress_rate": 0.8, "weekly_average": 3.8, "renewal_rate": 0.08}[key]
            items[key] = max(0.0, min(full, value / base * full))
    return ObjectiveScore(items=items, total=round(sum(items.values()), 4))


def _refund_score(rate: float) -> float:
    if rate <= 0.01:
        return 10.0
    if rate >= 0.03:
        return 0.0
    return round(10.0 * (0.03 - rate) / 0.02, 4)


def subjective_keys(metrics: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(key for key in metrics if str(key).startswith(SUBJECTIVE_PREFIX)))


def check_assessments(
    records: Iterable[AssessmentRecord],
    *,
    expected_leaders: Iterable[str] = (),
) -> tuple[AssessmentFinding, ...]:
    ordered = list(records)
    findings: list[AssessmentFinding] = []
    seen: dict[str, int] = {}

    for record in ordered:
        seen[record.teacher_id] = seen.get(record.teacher_id, 0) + 1
        if not record.metrics:
            findings.append(AssessmentFinding("STRUCTURE_ERROR", "ERROR", record.teacher_id, "考核表没有可识别的指标内容。"))
            findings.append(AssessmentFinding("MISSING_REQUIRED", "ERROR", record.teacher_id, "考核表缺少任何客观指标值。"))
            continue
        resolved = resolve_metrics(record.metrics)
        if not resolved:
            findings.append(AssessmentFinding("MISSING_REQUIRED", "ERROR", record.teacher_id, "考核表缺少任何客观指标值。"))
        for key in CHECKED_INPUTS:
            raw = record.metrics.get(key)
            if raw is None or raw == "":
                continue
            if isinstance(raw, str) and raw.strip().startswith("="):
                findings.append(AssessmentFinding("FORMULA_UNEVALUATED", "ERROR", record.teacher_id, f"{key} 是未计算的公式：{raw}"))
            elif _number(record.metrics, key) is None:
                findings.append(AssessmentFinding("VALUE_NOT_NUMERIC", "ERROR", record.teacher_id, f"{key} 不是数字：{raw!r}"))
            elif key.endswith("_rate") and not 0.0 <= float(raw) <= 1.0:
                findings.append(AssessmentFinding("SCORE_OUT_OF_RANGE", "WARNING", record.teacher_id, f"{key} 超出 0-100% 区间：{raw}"))
        score = score_objective(record.metrics)
        if score.total > 100.0 or score.total < 0.0:
            findings.append(AssessmentFinding("SCORE_OUT_OF_RANGE", "ERROR", record.teacher_id, f"客观总分异常：{score.total}"))

    for leader, count in seen.items():
        if count > 1:
            findings.append(AssessmentFinding("DUPLICATE", "ERROR", leader, f"{leader} 有 {count} 份考核表，需要确认使用哪一份。"))
    for leader in expected_leaders:
        if leader and leader not in seen:
            findings.append(AssessmentFinding("MISSING_SUBMISSION", "ERROR", leader, f"{leader} 没有提交岗位考核表。"))
    return tuple(findings)


def build_assessment_result(
    record: AssessmentRecord,
    *,
    reviewer: str,
    reviewed_at: str,
    identifier: str,
    subjective_confirmations: Mapping[str, float] | None = None,
    amount_rule: Mapping[str, Any] | None = None,
    linked_run_id: str = "",
) -> ManagementAssessmentResult:
    """Build the formal result. Subjective items must be confirmed by a human."""
    objective = score_objective(record.metrics)
    pending = [key for key in subjective_keys(record.metrics) if key not in (subjective_confirmations or {})]
    if pending:
        return ManagementAssessmentResult(
            id=identifier, period=record.period, teacher_id=record.teacher_id, role=record.role,
            source_input_ids=(record.id,), rule_version=SCORE_RULE_VERSION, reviewer=reviewer,
            reviewed_at=reviewed_at, objective_score=objective.total, subjective_score=0.0,
            final_score=0.0, final_amount=None, amount_status=RULE_NOT_CONFIGURED,
            status=AssessmentResultStatus.NEEDS_MANUAL_CONFIRMATION,
            evidence={"pending_subjective": pending, "objective_items": dict(objective.items)},
            linked_run_id=linked_run_id, created_at=reviewed_at,
        )
    subjective_total = round(sum(float(value) for value in (subjective_confirmations or {}).values()), 4)
    amount, amount_status = _amount_for(amount_rule, objective.total + subjective_total)
    return ManagementAssessmentResult(
        id=identifier, period=record.period, teacher_id=record.teacher_id, role=record.role,
        source_input_ids=(record.id,), rule_version=SCORE_RULE_VERSION, reviewer=reviewer,
        reviewed_at=reviewed_at, objective_score=objective.total, subjective_score=subjective_total,
        final_score=round(objective.total + subjective_total, 4), final_amount=amount,
        amount_status=amount_status, status=AssessmentResultStatus.FINAL,
        evidence={"objective_items": dict(objective.items)},
        linked_run_id=linked_run_id, created_at=reviewed_at,
    )


def _amount_for(rule: Mapping[str, Any] | None, score: float) -> tuple[float | None, str]:
    """Translate a score into money only when a confirmed rule exists."""
    if not rule:
        return None, RULE_NOT_CONFIGURED
    per_point = rule.get("amount_per_point")
    if per_point is None:
        return None, RULE_NOT_CONFIGURED
    return round(float(per_point) * score, 2), "CONFIGURED"
