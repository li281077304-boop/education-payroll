"""Direct generation mode: turn the same Core results into a payroll table.

Audit mode compares Core results against a submitted payroll sheet; generate
mode renders the very same Core results. Both call ``schedule_totals`` and the
same AE/AF helpers, so the two modes cannot drift into two algorithms.

Nothing is invented here. A field without a reliable source stays empty and
the whole result is marked NEEDS_CONFIRMATION, never "final payroll correct".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
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
BASE_SALARY_FIELDS = ("G", "H", "I", "J", "K", "L")
BASE_SALARY_BLOCKED = "BLOCKED_BY_INPUT"


def base_salary_field(teacher: str, base_salary_inputs: Mapping[str, object] | None, employment_type: str = "FULL_TIME") -> dict:
    """Calculate M from a Run-scoped, source-backed G:L snapshot.

    A part-time teacher is paid per lesson, so the full-time base salary does
    not apply to them at all.  Saying "M is missing" would be a false business
    statement, and writing M = 0 would invent a number, so the field is
    explicitly NOT_APPLICABLE instead.
    """
    if str(employment_type or "").upper() == "PART_TIME":
        return {
            "value": None,
            "state": "NOT_APPLICABLE",
            "reason": f"{teacher} 为兼职教师，按课时计酬，不适用全职基本工资（G～L）。",
            "evidence": [{"kind": "EMPLOYMENT_TYPE", "employment_type": "PART_TIME", "field": "M"}],
        }
    entry = (base_salary_inputs or {}).get(teacher) if isinstance(base_salary_inputs, Mapping) else None
    if not isinstance(entry, Mapping):
        return {"value": None, "state": BASE_SALARY_BLOCKED, "reason": f"{teacher} 的实际基本工资缺少：G、H、I、J、K、L。", "evidence": []}
    fields = entry.get("fields", entry)
    if not isinstance(fields, Mapping):
        fields = {}
    values: dict[str, Decimal] = {}
    missing: list[str] = []
    for code in BASE_SALARY_FIELDS:
        item = fields.get(code)
        raw = item.get("value") if isinstance(item, Mapping) else item
        if raw in (None, ""):
            missing.append(code)
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, ValueError):
            return {"value": None, "state": BASE_SALARY_BLOCKED, "reason": f"{teacher} 的 {code} 不是有效数字。", "evidence": []}
        if not value.is_finite():
            return {"value": None, "state": BASE_SALARY_BLOCKED, "reason": f"{teacher} 的 {code} 不是有限数字。", "evidence": []}
        values[code] = value
    if missing:
        return {"value": None, "state": BASE_SALARY_BLOCKED, "reason": f"{teacher} 的实际基本工资缺少：{', '.join(missing)}。", "evidence": []}
    if values["K"] <= 0:
        return {"value": None, "state": BASE_SALARY_BLOCKED, "reason": f"{teacher} 的 K 应出勤必须大于 0。", "evidence": []}
    if values["L"] < 0:
        return {"value": None, "state": BASE_SALARY_BLOCKED, "reason": f"{teacher} 的 L 实际出勤不能为负数。", "evidence": []}
    result = (values["G"] + values["H"] + values["I"] + values["J"]) / values["K"] * values["L"]
    evidence = {
        "kind": "BASE_SALARY_CALCULATION",
        "formula": "M = (G + H + I + J) / K × L",
        "source": entry.get("source", "") if isinstance(entry, Mapping) else "",
        "provenance": entry.get("provenance", {}) if isinstance(entry, Mapping) else {},
        "inputs": {code: str(values[code]) for code in BASE_SALARY_FIELDS},
    }
    return {"value": float(result), "state": "DETERMINED", "reason": "M 按 Run 的基本工资输入快照计算。", "evidence": [evidence]}


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
        extra_fields = set(self.final_fields) - required_fields
        if self.status != STATUS_FINAL or not required_fields.issubset(self.final_fields) or extra_fields - {"M"}:
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
    base_salary_inputs: Mapping[str, object] | None = None,
    renewal_snapshot: Mapping[str, object] | None = None,
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
        core_fields = {
            "AF": {"value": af, "state": "DETERMINED" if af is not None else "NEEDS_INPUT"},
            "PART_TIME": {"value": None, "state": "NOT_APPLICABLE"},
        }
        if base_salary_inputs is not None:
            core_fields["M"] = base_salary_field(teacher, base_salary_inputs)
        final_fields = resolve_final_fields(
            teacher=teacher,
            core_fields=core_fields,
            business_inputs=business_inputs,
            renewal_snapshot=renewal_snapshot,
            # Legacy callers may opt into the same production M snapshot.
            # The default remains missing rather than silently using zero.
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


def generated_from_calculation(result: dict, *, business_inputs: Iterable[Mapping[str, object]] = (), default_zero_missing: bool = False, base_salary_inputs: Mapping[str, object] | None = None, renewal_snapshot: Mapping[str, object] | None = None, employment_types: Mapping[str, str] | None = None, support_snapshot: Mapping[str, object] | None = None, part_time_pay_decisions: Mapping[str, Mapping[str, object]] | None = None) -> GeneratedPayroll:
    """Pure presentation adapter. No payroll inputs or second set of formulae."""
    rows = []
    reasons = set()
    inputs = tuple(business_inputs)
    employment = {str(key): str(value) for key, value in (employment_types or {}).items()}
    for row in result["rows"]:
        fields = {key: dict(value) if isinstance(value, Mapping) else value for key, value in row["fields"].items()}
        payable_states = {"DETERMINED", "NOT_APPLICABLE", "ESTIMATED"}
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
        declared = employment.get(str(row["teacher"]), str(row.get("employment_type", "FULL_TIME")))
        decision = (part_time_pay_decisions or {}).get(str(row["teacher"]), {})
        if declared == "PART_TIME" and decision.get("method") == "MANUAL" and decision.get("manual_kind") == "TOTAL" and decision.get("status") == "CONFIRMED":
            core_values["PART_TIME"] = {
                "value": decision.get("amount"), "state": "DETERMINED",
                "reason": "兼职工资按本次确认的月工资总额录入。",
                "evidence": [{"kind": "RUN_PART_TIME_MANUAL_TOTAL", "source": decision.get("source", ""), "source_result_id": decision.get("id", ""), "inputs": {"period": decision.get("period", ""), "confirmed_by": decision.get("confirmed_by", ""), "confirmed_at": decision.get("confirmed_at", ""), "reason": decision.get("reason", ""), "amount": str(decision.get("amount", ""))}}],
            }
            fields["PART_TIME"] = dict(core_values["PART_TIME"])
        elif declared == "PART_TIME" and decision.get("method") == "DEFERRED":
            core_values["PART_TIME"] = {
                "value": None, "state": "DEFERRED",
                "reason": "兼职工资待补充；本次保留空白，不按 0 计算。",
                "evidence": [{"kind": "RUN_PART_TIME_DEFERRED", "source": decision.get("source", ""), "inputs": {"period": decision.get("period", ""), "confirmed_by": decision.get("confirmed_by", ""), "confirmed_at": decision.get("confirmed_at", ""), "reason": decision.get("reason", "")}}],
            }
            fields["PART_TIME"] = dict(core_values["PART_TIME"])
        elif declared == "PART_TIME" and decision.get("method") == "COMPANY_STANDARD" and decision.get("status") == "WAITING_FOR_AUTHORITY":
            core_values["PART_TIME"] = {
                "value": None, "state": "NEEDS_INPUT",
                "reason": "尚无适用本月和该教师的公司兼职标准；可手动填写或暂时留白。",
                "evidence": [{"kind": "PART_TIME_AUTHORITY_MISSING", "source": decision.get("source", ""), "inputs": {"period": decision.get("period", "")}}],
            }
            fields["PART_TIME"] = dict(core_values["PART_TIME"])
        if base_salary_inputs is not None:
            core_values["M"] = base_salary_field(row["teacher"], base_salary_inputs, declared)
        final_fields = resolve_final_fields(teacher=row["teacher"], core_fields=core_values, business_inputs=inputs, employment_type=declared, default_zero_missing=default_zero_missing, renewal_snapshot=renewal_snapshot, support_snapshot=support_snapshot)
        blockers = tuple(sorted({str(v.get("reason") or v["state"]) for v in fields.values() if v["state"] not in payable_states}))
        final_blockers = {str(item.get("reason") or item.get("state")) for item in final_fields.values() if item.get("state") not in payable_states}
        reasons.update(blockers)
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


def build_generated_payroll(*, period: str, schedule_records: Iterable[ScheduleRecord], rules=None, ratings: Iterable = (), profiles: Iterable = (), teacher_contexts: Iterable = (), part_time_rates: Iterable = (), reference_ratings: Mapping | None = None, business_inputs: Iterable[Mapping[str, object]] = (), default_zero_missing: bool = False, base_salary_inputs: Mapping[str, object] | None = None, renewal_snapshot: Mapping[str, object] | None = None) -> GeneratedPayroll:
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
        "grade": record.grade,
        "class_type": record.class_type,
        "attended": record.attended,
        "lesson_status": record.lesson_status,
        "source": record.source,
        "provenance": {field: asdict(evidence) if hasattr(evidence, "__dataclass_fields__") else dict(evidence) for field, evidence in record.provenance.items()},
    } for record in records]
    return generated_from_calculation({"period": period, "rows": rows, "rule_versions": {"core": result.rule_version_id}, "source_records": source_records, "formula_inputs": result.as_dict().get("formula_inputs", {})}, business_inputs=business_inputs, default_zero_missing=default_zero_missing, base_salary_inputs=base_salary_inputs, renewal_snapshot=renewal_snapshot)
