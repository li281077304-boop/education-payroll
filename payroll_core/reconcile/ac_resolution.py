"""Immutable, auditable resolution primitives for AC (class-value) differences.

The schedule export remains the historical source fact.  A confirmed source
correction creates an *effective* fact for one run; an approved payroll
override changes only the contribution used for that run's payroll check.
Neither action edits a :class:`~payroll_core.models.records.ScheduleRecord`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isclose, isfinite
from typing import Callable, Iterable, Mapping, Sequence

from ..models.records import ScheduleRecord
from .payroll_scope import class_value_contribution


ALLOWED_SOURCE_CORRECTION_FIELDS = frozenset({"grade", "class_type", "attended", "lesson_status"})
SOURCE_CORRECTION_REASON_CODES = frozenset({
    "GRADE_ROLLOVER_NOT_UPDATED",
    "SCHEDULING_ENTRY_ERROR",
    "OTHER_CONFIRMED_SOURCE_ERROR",
})
RUN_SCOPED = "THIS_RUN"


def _stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))


def schedule_record_id(record: ScheduleRecord) -> str:
    """Return a stable identity anchored to source provenance, not field values.

    A grade correction must not make its own target disappear.  The identity
    therefore uses the source workbook/sheet/row coordinates when available,
    and only falls back to immutable import ordering attributes for synthetic
    records that have no provenance.
    """
    locations = sorted(
        {
            (item.source_file, item.sheet, item.coordinate)
            for item in record.provenance.values()
        }
    )
    identity = {
        "period": record.period,
        "teacher": record.teacher,
        "source": record.source,
        "locations": locations,
        "fallback": [record.lesson_date, record.lesson_time, record.class_name, record.course_name, record.student],
    }
    return sha256(_stable_json(identity).encode("utf-8")).hexdigest()[:24]


def resolution_fingerprint(*, run_id: str, source_record_id: str, source_file_hash: str, kind: str, payload: Mapping[str, object]) -> str:
    """Create an immutable audit fingerprint for one correction or override."""
    value = {
        "run_id": run_id,
        "source_record_id": source_record_id,
        "source_file_hash": source_file_hash,
        "kind": kind,
        "payload": dict(payload),
    }
    return sha256(_stable_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceDataCorrection:
    """A confirmed correction to one upstream schedule fact for one payroll run."""

    run_id: str
    period: str
    teacher: str
    source_record_id: str
    source_file_hash: str
    field: str
    original_value: object
    corrected_value: object
    reason_code: str
    reason_text: str
    confirmed_by: str
    confirmed_at: str
    status: str = "ACTIVE"
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.field not in ALLOWED_SOURCE_CORRECTION_FIELDS:
            raise ValueError(f"Unsupported AC source correction field: {self.field}")
        if self.reason_code not in SOURCE_CORRECTION_REASON_CODES:
            raise ValueError(f"Unsupported source correction reason code: {self.reason_code}")
        if not self.run_id or not self.period or not self.source_record_id or not self.source_file_hash:
            raise ValueError("run_id, period, source_record_id and source_file_hash are required")
        if self.status != "ACTIVE":
            raise ValueError("Only ACTIVE source corrections may be applied")
        expected = resolution_fingerprint(
                    run_id=self.run_id,
                    source_record_id=self.source_record_id,
                    source_file_hash=self.source_file_hash,
                    kind="SOURCE_DATA_CORRECTION",
                    payload={
                        "period": self.period,
                        "field": self.field,
                        "original_value": self.original_value,
                        "corrected_value": self.corrected_value,
                        "reason_code": self.reason_code,
                        "reason_text": self.reason_text,
                        "confirmed_by": self.confirmed_by,
                        "confirmed_at": self.confirmed_at,
                    },
                )
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("Source correction fingerprint does not match its immutable contents")
        object.__setattr__(self, "fingerprint", expected)


@dataclass(frozen=True)
class ApprovedPayrollOverride:
    """A human-approved, run-scoped alternative AC contribution.

    ``approved_contribution`` is explicit on purpose.  A UI may label the
    treatment (for example ``按一对一批准口径``), but Core never silently
    changes a global class rule or rewrites the upstream schedule fact.
    """

    run_id: str
    period: str
    teacher: str
    source_record_id: str
    source_file_hash: str
    affected_field: str
    default_treatment: str
    default_contribution: float | None
    approved_treatment: str
    approved_contribution: float
    reason: str
    approved_by: str
    created_at: str
    effective_scope: str = RUN_SCOPED
    status: str = "ACTIVE"
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if self.affected_field != "class_value":
            raise ValueError("Only AC/class_value overrides are supported")
        if self.effective_scope != RUN_SCOPED:
            raise ValueError("Approved payroll overrides must be scoped to THIS_RUN")
        if not self.run_id or not self.period or not self.source_record_id or not self.source_file_hash:
            raise ValueError("run_id, period, source_record_id and source_file_hash are required")
        if self.status != "ACTIVE":
            raise ValueError("Only ACTIVE approved payroll overrides may be applied")
        if not isfinite(self.approved_contribution):
            raise ValueError("Approved contribution must be a finite number")
        expected = resolution_fingerprint(
                    run_id=self.run_id,
                    source_record_id=self.source_record_id,
                    source_file_hash=self.source_file_hash,
                    kind="APPROVED_PAYROLL_OVERRIDE",
                    payload={
                        "period": self.period,
                        "affected_field": self.affected_field,
                        "default_treatment": self.default_treatment,
                        "default_contribution": self.default_contribution,
                        "approved_treatment": self.approved_treatment,
                        "approved_contribution": self.approved_contribution,
                        "reason": self.reason,
                        "approved_by": self.approved_by,
                        "created_at": self.created_at,
                    },
                )
        if self.fingerprint and self.fingerprint != expected:
            raise ValueError("Approved override fingerprint does not match its immutable contents")
        object.__setattr__(self, "fingerprint", expected)


@dataclass(frozen=True)
class EffectiveScheduleFact:
    """One immutable source record plus its run-specific effective values."""

    source_record_id: str
    original: ScheduleRecord
    effective: ScheduleRecord
    corrections: tuple[SourceDataCorrection, ...] = ()


@dataclass(frozen=True)
class ACContribution:
    source_record_id: str
    original: ScheduleRecord
    effective: ScheduleRecord
    default_contribution: float | None
    effective_contribution: float | None
    calculation: str
    corrections: tuple[SourceDataCorrection, ...] = ()
    override: ApprovedPayrollOverride | None = None


@dataclass(frozen=True)
class ACResolutionResult:
    """A fully traceable AC calculation after corrections and overrides."""

    original_total: float | None
    corrected_total: float | None
    effective_total: float | None
    contributions: tuple[ACContribution, ...]
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class CauseAssessment:
    status: str
    baseline_total: float
    recomputed_total: float
    target_total: float
    baseline_difference: float
    recomputed_difference: float


@dataclass(frozen=True)
class ContributionStructureComparison:
    status: str
    system_total: float | None
    reference_total: float
    mismatched_record_ids: tuple[str, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _index_records(records: Iterable[ScheduleRecord]) -> dict[str, ScheduleRecord]:
    indexed: dict[str, ScheduleRecord] = {}
    for record in records:
        record_id = schedule_record_id(record)
        if record_id in indexed:
            raise ValueError("Ambiguous source schedule identity; provenance must distinguish each course record")
        indexed[record_id] = record
    return indexed


def _validate_source_hash(source_hashes: Mapping[str, str] | None, record: ScheduleRecord, expected_hash: str) -> None:
    if source_hashes is None:
        raise ValueError("Source file hashes are required to apply a correction or override")
    actual_hash = source_hashes.get(record.source)
    if actual_hash != expected_hash:
        raise ValueError("Source file hash changed; correction or override needs reconfirmation")


def effective_schedule_facts(
    records: Iterable[ScheduleRecord],
    corrections: Iterable[SourceDataCorrection] = (),
    *,
    run_id: str,
    period: str,
    source_hashes: Mapping[str, str] | None = None,
) -> tuple[EffectiveScheduleFact, ...]:
    """Apply audited corrections without mutating or replacing source facts."""
    original = _index_records(records)
    by_record: dict[str, list[SourceDataCorrection]] = {}
    for correction in corrections:
        if correction.run_id != run_id or correction.period != period:
            raise ValueError("Source correction belongs to another payroll run or period")
        if correction.source_record_id not in original:
            raise ValueError("Source correction refers to a record outside this schedule input")
        source = original[correction.source_record_id]
        if correction.teacher != source.teacher:
            raise ValueError("Source correction teacher does not match its source record")
        _validate_source_hash(source_hashes, source, correction.source_file_hash)
        by_record.setdefault(correction.source_record_id, []).append(correction)

    facts: list[EffectiveScheduleFact] = []
    for record_id, source in original.items():
        effective = source
        applied: list[SourceDataCorrection] = []
        for correction in by_record.get(record_id, []):
            observed = getattr(effective, correction.field)
            if observed != correction.original_value:
                raise ValueError(
                    f"Source correction original value no longer matches {correction.field}: "
                    f"expected {correction.original_value!r}, got {observed!r}"
                )
            effective = replace(effective, **{correction.field: correction.corrected_value})
            applied.append(correction)
        facts.append(EffectiveScheduleFact(record_id, source, effective, tuple(applied)))
    return tuple(facts)


def resolve_ac(
    records: Iterable[ScheduleRecord],
    *,
    run_id: str,
    period: str,
    corrections: Iterable[SourceDataCorrection] = (),
    overrides: Iterable[ApprovedPayrollOverride] = (),
    source_hashes: Mapping[str, str] | None = None,
    contribution_calculator: Callable[[ScheduleRecord], tuple[float | None, str]] = class_value_contribution,
) -> ACResolutionResult:
    """Recompute AC from effective facts and run-scoped approved treatments.

    Callers with a version-bound rule set may inject its calculator.  Omitting
    it preserves the historical ``class_value_contribution`` behaviour.
    """
    source_records = tuple(records)
    facts = effective_schedule_facts(source_records, corrections, run_id=run_id, period=period, source_hashes=source_hashes)
    indexed_original = _index_records(source_records)
    overrides_by_id: dict[str, ApprovedPayrollOverride] = {}
    for override in overrides:
        if override.run_id != run_id:
            raise ValueError("Approved override belongs to another payroll run")
        if override.source_record_id not in indexed_original:
            raise ValueError("Approved override refers to a record outside this schedule input")
        source = indexed_original[override.source_record_id]
        if override.teacher != source.teacher:
            raise ValueError("Approved override teacher does not match its source record")
        if override.period != source.period:
            raise ValueError("Approved override period does not match its source record")
        _validate_source_hash(source_hashes, source, override.source_file_hash)
        if override.source_record_id in overrides_by_id:
            raise ValueError("Only one active approved override may apply to a source course record")
        overrides_by_id[override.source_record_id] = override

    contributions: list[ACContribution] = []
    original_total = 0.0
    corrected_total = 0.0
    effective_total = 0.0
    blockers: list[str] = []
    for fact in facts:
        original_value, _ = contribution_calculator(fact.original)
        corrected_value, calculation = contribution_calculator(fact.effective)
        override = overrides_by_id.get(fact.source_record_id)
        if override is not None and corrected_value is None:
            raise ValueError("Cannot apply an override to a course without a deterministic default contribution")
        if override is not None and not isclose(override.default_contribution if override.default_contribution is not None else float("nan"), corrected_value if corrected_value is not None else float("nan"), abs_tol=1e-9):
            raise ValueError("Approved override default contribution no longer matches the effective source calculation")
        applied_value = override.approved_contribution if override is not None else corrected_value
        if original_value is None or corrected_value is None or applied_value is None:
            blockers.append(fact.source_record_id)
        else:
            original_total += original_value
            corrected_total += corrected_value
            effective_total += applied_value
        contributions.append(
            ACContribution(
                source_record_id=fact.source_record_id,
                original=fact.original,
                effective=fact.effective,
                default_contribution=corrected_value,
                effective_contribution=applied_value,
                calculation=calculation,
                corrections=fact.corrections,
                override=override,
            )
        )
    if blockers:
        return ACResolutionResult(None, None, None, tuple(contributions), tuple(blockers))
    return ACResolutionResult(original_total, corrected_total, effective_total, tuple(contributions))


def assess_counterfactual_cause(
    *, baseline_total: float | None,
    recomputed_total: float | None,
    payroll_total: float,
    tolerance: float = 1e-6,
) -> CauseAssessment:
    """Classify a proposed cause only when its counterfactual closes the gap."""
    if baseline_total is None or recomputed_total is None:
        return CauseAssessment("UNEXPLAINED", baseline_total or 0.0, recomputed_total or 0.0, payroll_total, 0.0, 0.0)
    before = baseline_total - payroll_total
    after = recomputed_total - payroll_total
    if isclose(before, 0.0, abs_tol=tolerance):
        status = "AMBIGUOUS_CAUSE"
    elif isclose(after, 0.0, abs_tol=tolerance) and isclose(
        baseline_total - recomputed_total, before, abs_tol=tolerance,
    ):
        status = "EXACT_CAUSE"
    elif not isclose(baseline_total, recomputed_total, abs_tol=tolerance):
        status = "POSSIBLE_CAUSE"
    else:
        status = "UNEXPLAINED"
    return CauseAssessment(status, baseline_total, recomputed_total, payroll_total, before, after)


def compare_contribution_structure(
    contributions: Iterable[ACContribution],
    reference_by_record_id: Mapping[str, float],
    *,
    tolerance: float = 1e-6,
) -> ContributionStructureComparison:
    """Detect per-course mismatches even where positive/negative errors cancel.

    The caller must supply a separately structured reference (for example an
    explicitly parseable payroll comment).  A payroll total by itself cannot
    prove per-course structure.
    """
    system = {item.source_record_id: item.effective_contribution for item in contributions}
    all_ids = set(system) | set(reference_by_record_id)
    mismatched = tuple(sorted(
        record_id for record_id in all_ids
        if record_id not in system
        or record_id not in reference_by_record_id
        or system[record_id] is None
        or not isclose(system[record_id], reference_by_record_id[record_id], abs_tol=tolerance)
    ))
    has_unknown = any(value is None for value in system.values())
    system_total = None if has_unknown else sum(value for value in system.values() if value is not None)
    reference_total = sum(reference_by_record_id.values())
    if has_unknown:
        status = "NEEDS_INPUT"
    elif not all_ids or mismatched:
        status = "CONTRIBUTION_STRUCTURE_MISMATCH"
    else:
        status = "STRUCTURE_MATCH"
    return ContributionStructureComparison(status, system_total, reference_total, mismatched)
