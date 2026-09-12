"""Direct generation mode: turn the same Core results into a payroll table.

Audit mode compares Core results against a submitted payroll sheet; generate
mode renders the very same Core results. Both call ``schedule_totals`` and the
same AE/AF helpers, so the two modes cannot drift into two algorithms.

Nothing is invented here. A field without a reliable source stays empty and
the whole result is marked NEEDS_CONFIRMATION, never "final payroll correct".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Iterable, Mapping

from .models.records import ScheduleRecord
from .final_fields import FINAL_FIELD_CODES, resolve_final_fields
from .reconcile.payroll_scope import (
    expected_hourly_rate,
    expected_total_fee,
    schedule_totals,
    star_from_level,
)


STATUS_FINAL = "FINAL"
STATUS_NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"

AD_MISSING_SOURCE = "AD_MISSING_SOURCE"
AE_REQUIRES_RATING_AUTHORITY = "AE_REQUIRES_RATING_AUTHORITY"
AV_NO_INDEPENDENT_SOURCE = "AV_NO_INDEPENDENT_SOURCE"


@dataclass(frozen=True)
class CorePayrollRow:
    """One teacher's generated payroll values, all traceable to Core."""

    teacher: str
    one_to_one: float | None = None       # AA
    class_value: float | None = None      # AC
    teaching_hours: float | None = None   # AD
    ae: float | None = None               # AE
    af: float | None = None               # AF
    av: float | None = None               # AV, only when a reliable source exists
    status: str = STATUS_NEEDS_CONFIRMATION
    blockers: tuple[str, ...] = ()
    fields: Mapping[str, dict] = field(default_factory=dict)
    part_time_amount: float | None = None
    star: int | None = None
    final_fields: Mapping[str, dict] = field(default_factory=dict)

    @property
    def final(self) -> bool:
        required_fields = set(FINAL_FIELD_CODES) | {"AF"}
        if self.status != STATUS_FINAL or set(self.final_fields) != required_fields:
            return False
        payable_states = {"DETERMINED", "NOT_APPLICABLE", "ESTIMATED"}
        return all(
            isinstance(item, Mapping)
            and item.get("state") in payable_states
            for item in self.final_fields.values()
        )


@dataclass(frozen=True)
class GeneratedPayroll:
    period: str
    rows: tuple[CorePayrollRow, ...]
    status: str
    blockers: tuple[str, ...] = ()
    rule_versions: Mapping[str, str] = field(default_factory=dict)
    source_records: tuple[Mapping[str, object], ...] = ()
    formula_inputs: Mapping[str, object] = field(default_factory=dict)

    @property
    def final(self) -> bool:
        return self.status == STATUS_FINAL and bool(self.rows) and all(row.final for row in self.rows)

    def row_for(self, teacher: str) -> CorePayrollRow | None:
        return next((row for row in self.rows if row.teacher == teacher), None)


def build_legacy_generated_payroll(
    *,
    period: str,
    schedule_records: Iterable[ScheduleRecord],
    coefficients: Mapping[str, float] | None = None,
    ratings_by_teacher: Mapping[str, str] | None = None,
    confirmed_hours: Mapping[str, float] | None = None,
    available_amounts: Mapping[str, float] | None = None,
    rule_versions: Mapping[str, str] | None = None,
    business_inputs: Iterable[Mapping[str, object]] = (),
    blocked: bool = False,
) -> GeneratedPayroll:
    """Render Core results into a standard payroll model.

    ``confirmed_hours`` is the only accepted AD source: AD has no independent
    computation today, so without a human-confirmed value the row stays
    NEEDS_CONFIRMATION instead of guessing.
    """
    rules = dict(coefficients) if coefficients else None
    totals, blockers = schedule_totals(schedule_records, rules)
    ratings = dict(ratings_by_teacher or {})
    hours = dict(confirmed_hours or {})
    # Kept as a compatibility parameter for old callers.  Submitted AV is a
    # target value, not an authority, so it is intentionally never copied to
    # the generated result.
    _ = dict(available_amounts or {})
    business_inputs = tuple(business_inputs)

    rows: list[CorePayrollRow] = []
    overall: list[str] = []
    # A teacher whose only records are blocked still belongs in the result:
    # dropping the row would silently lose a person and hide the reason.
    for teacher in sorted(set(totals) | {item.teacher for item in blockers}):
        values = totals.get(teacher, {"one_to_one": 0.0, "class_value": 0.0})
        row_blockers = {
            item.status if item.status.startswith("UNKNOWN_CLASS_TYPE_RULE") else "CORE_BLOCKED"
            for item in blockers if item.teacher == teacher
        }
        ad = hours.get(teacher)
        ae = af = None
        star = None
        if ad is None:
            row_blockers.add(AD_MISSING_SOURCE)
        else:
            star = star_from_level(ratings.get(teacher, ""))
            if star is None:
                row_blockers.add(AE_REQUIRES_RATING_AUTHORITY)
            else:
                ae = expected_hourly_rate(float(ad), star)
                af = expected_total_fee(float(ad), ae)
        final_fields = resolve_final_fields(
            teacher=teacher,
            core_fields={
                "AF": {"value": af, "state": "DETERMINED" if af is not None else "NEEDS_INPUT"},
                "PART_TIME": {"value": None, "state": "NOT_APPLICABLE"},
            },
            business_inputs=business_inputs,
        )
        final_blockers = {
            str(item.get("reason") or item.get("state"))
            for item in final_fields.values()
            if item.get("state") not in {"DETERMINED", "NOT_APPLICABLE"}
        }
        row_blockers.update(final_blockers)
        rows.append(CorePayrollRow(
            teacher=teacher,
            one_to_one=round(values["one_to_one"], 6),
            class_value=round(values["class_value"], 6),
            teaching_hours=None if ad is None else round(float(ad), 6),
            ae=ae, af=af, av=None,
            status=STATUS_NEEDS_CONFIRMATION if row_blockers else STATUS_FINAL,
            blockers=tuple(sorted(row_blockers)),
            star=star,
            final_fields=final_fields,
        ))
        overall.extend(row_blockers)
    if blocked:
        overall.append("RUN_NOT_READY")
    status = STATUS_FINAL if rows and not overall and all(row.final for row in rows) else STATUS_NEEDS_CONFIRMATION
    return GeneratedPayroll(
        period=period, rows=tuple(rows), status=status,
        blockers=tuple(sorted(set(overall))), rule_versions=dict(rule_versions or {}),
    )


def generated_from_calculation(result: dict, *, business_inputs: Iterable[Mapping[str, object]] = (), default_zero_missing: bool = False) -> GeneratedPayroll:
    """Pure presentation adapter. No payroll inputs or second set of formulae."""
    rows = []
    reasons = set()
    inputs = tuple(business_inputs)
    for row in result["rows"]:
        fields = row["fields"]
        payable_states = {"DETERMINED", "NOT_APPLICABLE", "ESTIMATED"}
        blockers = tuple(sorted({str(v.get("reason") or v["state"]) for v in fields.values() if v["state"] not in payable_states}))
        reasons.update(blockers)
        def value(key: str):
            raw = fields.get(key, {}).get("value")
            if raw is None:
                return None
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return float(raw)
            try:
                return float(raw)
            except (TypeError, ValueError):
                return raw
        core_values = {key: fields.get(key, {}) for key in ("AF", "PART_TIME")}
        final_fields = resolve_final_fields(teacher=row["teacher"], core_fields=core_values, business_inputs=inputs, employment_type=str(row.get("employment_type", "FULL_TIME")), default_zero_missing=default_zero_missing)
        final_blockers = {str(item.get("reason") or item.get("state")) for item in final_fields.values() if item.get("state") not in payable_states}
        reasons.update(final_blockers)
        blockers = tuple(sorted(set(blockers) | final_blockers))
        rows.append(CorePayrollRow(teacher=row["teacher"], one_to_one=value("AA"), class_value=value("AC"), teaching_hours=value("AD"), ae=value("AE"), af=value("AF"), part_time_amount=value("PART_TIME"), star=_star_from_fields(fields), fields=fields, final_fields=final_fields, status=STATUS_NEEDS_CONFIRMATION if blockers else STATUS_FINAL, blockers=blockers))
    status = STATUS_FINAL if rows and all(row.final for row in rows) else STATUS_NEEDS_CONFIRMATION
    return GeneratedPayroll(period=result["period"], rows=tuple(rows), status=status, blockers=tuple(sorted(reasons)), rule_versions=result.get("rule_versions", {}), source_records=tuple(result.get("source_records", ())), formula_inputs=dict(result.get("formula_inputs", {})))


def _star_from_fields(fields: Mapping[str, dict]) -> int | None:
    """Extract the already-calculated rating for presentation only.

    The rating remains owned by the calculation chain.  This helper only
    exposes the value carried in AE evidence so the generated workbook can show
    which star input produced its rate without maintaining a second lookup.
    """
    ae = fields.get("AE", {})
    for evidence in ae.get("evidence", ()):
        rating = (evidence.get("inputs", {}) if isinstance(evidence, Mapping) else {}).get("rating")
        if rating not in (None, ""):
            try:
                return int(rating)
            except (TypeError, ValueError):
                return None
    return None


def build_generated_payroll(*, period: str, schedule_records: Iterable[ScheduleRecord], rules=None, ratings: Iterable = (), profiles: Iterable = (), teacher_contexts: Iterable = (), part_time_rates: Iterable = (), reference_ratings: Mapping | None = None, business_inputs: Iterable[Mapping[str, object]] = (), default_zero_missing: bool = False) -> GeneratedPayroll:
    """Public generation entry: exactly the same calculation as audit mode."""
    from .calculation import calculate_payroll, course_record_key
    from .config.core_rules import load_core_rules
    records = list(schedule_records)
    result = calculate_payroll(period=period, schedule=records, rules=rules or load_core_rules(), ratings=ratings, profiles=profiles, teacher_contexts=teacher_contexts, part_time_rates=part_time_rates, reference_ratings=reference_ratings or {})
    raw = result.as_dict()
    names = {"aa": "AA", "ac": "AC", "ad": "AD", "ae": "AE", "af": "AF", "part_time_fee": "PART_TIME"}
    rows = [{"teacher": row["teacher"], "employment_type": row.get("employment_type", "FULL_TIME"), "fields": {code: {**row[key], "value": None if row[key]["value"] is None else float(row[key]["value"])} for key, code in names.items()}} for row in raw["rows"]]
    source_records = [{
        "record_key": course_record_key(record),
        "teacher": record.teacher,
        "source": record.source,
        "provenance": {field: asdict(evidence) if hasattr(evidence, "__dataclass_fields__") else dict(evidence) for field, evidence in record.provenance.items()},
    } for record in records]
    return generated_from_calculation({"period": period, "rows": rows, "rule_versions": {"core": result.rule_version_id}, "source_records": source_records}, business_inputs=business_inputs, default_zero_missing=default_zero_missing)
