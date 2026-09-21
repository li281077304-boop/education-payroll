"""Run-scoped, auditable manual adjustments for final payroll fields.

An adjustment is a business fact attached to one payroll run.  It is not a
fallback to a historical workbook and it must never be inferred from a
baseline comparison.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


ALLOWED_STATUSES = {"RAW_CALCULATED", "APPROVED", "ACTIVE", "CONFIRMED", "FINAL_CONFIRMED", "REVOKED"}
APPLYABLE_STATUSES = {"APPROVED", "ACTIVE", "CONFIRMED", "FINAL_CONFIRMED"}
ALLOWED_FIELDS = {
    "AA", "AC", "AD", "AE", "AF", "AG", "AH", "AI", "AJ", "AK", "AL",
    "AM", "AN", "AO", "AP", "AQ", "AR", "AS", "AT", "AU", "AV",
}


@dataclass(frozen=True)
class ManualAdjustment:
    adjustment_id: str
    run_id: str
    period: str
    teacher_id: str
    teacher_name: str
    field: str
    raw_calculated: Any
    adjustment_value: Any
    final_value: Any
    reason: str
    evidence: Any
    actor: str
    confirmed_at: str
    status: str = "APPROVED"

    def validate(self) -> "ManualAdjustment":
        if not self.adjustment_id or not self.run_id or not self.period:
            raise ValueError("manual adjustment requires adjustment_id, run_id and period")
        if not self.teacher_id or not self.teacher_name:
            raise ValueError("manual adjustment requires teacher identity")
        if self.field not in ALLOWED_FIELDS:
            raise ValueError(f"unsupported manual adjustment field: {self.field}")
        if not self.reason or not self.evidence or not self.actor or not self.confirmed_at:
            raise ValueError("manual adjustment requires reason, evidence, actor and confirmed_at")
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"invalid manual adjustment status: {self.status}")
        return self

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_manual_adjustment(item: Mapping[str, Any]) -> ManualAdjustment:
    """Normalize a persisted business-input record without inventing values."""
    field = str(item.get("field") or item.get("target_field") or item.get("affected_field") or "").strip().upper()
    value = item.get("final_value", item.get("adjustment_value", item.get("override_value", item.get("approved_contribution"))))
    teacher = str(item.get("teacher_name") or item.get("teacher_id") or item.get("teacher") or "").strip()
    adjustment = ManualAdjustment(
        adjustment_id=str(item.get("adjustment_id") or item.get("id") or ""),
        run_id=str(item.get("run_id") or ""),
        period=str(item.get("period") or ""),
        teacher_id=str(item.get("teacher_id") or teacher),
        teacher_name=teacher,
        field=field,
        raw_calculated=item.get("raw_calculated"),
        adjustment_value=item.get("adjustment_value", item.get("override_value")),
        final_value=value,
        reason=str(item.get("reason") or item.get("reason_text") or item.get("approved_treatment") or "").strip(),
        evidence=item.get("evidence", item.get("source_ref") or item.get("source_file_hash")),
        actor=str(item.get("actor") or item.get("approved_by") or item.get("confirmed_by") or "").strip(),
        confirmed_at=str(item.get("confirmed_at") or item.get("approved_at") or item.get("created_at") or "").strip(),
        status=str(item.get("status") or item.get("outcome") or "").upper(),
    )
    return adjustment.validate()


def approved_manual_adjustments(items: Any) -> tuple[ManualAdjustment, ...]:
    """Return only explicit approved adjustment records."""
    output: list[ManualAdjustment] = []
    for item in items or ():
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("input_type") or item.get("kind") or "").upper()
        if kind not in {"MANUAL_ADJUSTMENT", "PAYROLL_OVERRIDE", "APPROVED_PAYROLL_OVERRIDE"}:
            continue
        try:
            adjustment = normalize_manual_adjustment(item)
            if adjustment.status in APPLYABLE_STATUSES:
                output.append(adjustment)
        except ValueError:
            # Invalid adjustments are not silently applied.  The caller's
            # normal validation path will keep the affected field unresolved.
            continue
    return tuple(output)


def adjustment_by_teacher_field(items: Any) -> dict[tuple[str, str], ManualAdjustment]:
    result: dict[tuple[str, str], ManualAdjustment] = {}
    for item in approved_manual_adjustments(items):
        key = ("".join(item.teacher_name.split()), item.field)
        if key in result:
            raise ValueError(f"duplicate approved manual adjustment: {item.teacher_name} {item.field}")
        result[key] = item
    return result
