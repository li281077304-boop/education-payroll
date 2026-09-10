"""Direct generation mode: turn the same Core results into a payroll table.

Audit mode compares Core results against a submitted payroll sheet; generate
mode renders the very same Core results. Both call ``schedule_totals`` and the
same AE/AF helpers, so the two modes cannot drift into two algorithms.

Nothing is invented here. A field without a reliable source stays empty and
the whole result is marked NEEDS_CONFIRMATION, never "final payroll correct".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .models.records import ScheduleRecord
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

    @property
    def final(self) -> bool:
        return self.status == STATUS_FINAL


@dataclass(frozen=True)
class GeneratedPayroll:
    period: str
    rows: tuple[CorePayrollRow, ...]
    status: str
    blockers: tuple[str, ...] = ()
    rule_versions: Mapping[str, str] = field(default_factory=dict)

    @property
    def final(self) -> bool:
        return self.status == STATUS_FINAL

    def row_for(self, teacher: str) -> CorePayrollRow | None:
        return next((row for row in self.rows if row.teacher == teacher), None)


def build_generated_payroll(
    *,
    period: str,
    schedule_records: Iterable[ScheduleRecord],
    coefficients: Mapping[str, float] | None = None,
    ratings_by_teacher: Mapping[str, str] | None = None,
    confirmed_hours: Mapping[str, float] | None = None,
    available_amounts: Mapping[str, float] | None = None,
    rule_versions: Mapping[str, str] | None = None,
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
    amounts = dict(available_amounts or {})

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
        if ad is None:
            row_blockers.add(AD_MISSING_SOURCE)
        else:
            star = star_from_level(ratings.get(teacher, ""))
            if star is None:
                row_blockers.add(AE_REQUIRES_RATING_AUTHORITY)
            else:
                ae = expected_hourly_rate(float(ad), star)
                af = expected_total_fee(float(ad), ae)
        rows.append(CorePayrollRow(
            teacher=teacher,
            one_to_one=round(values["one_to_one"], 6),
            class_value=round(values["class_value"], 6),
            teaching_hours=None if ad is None else round(float(ad), 6),
            ae=ae, af=af, av=amounts.get(teacher),
            status=STATUS_NEEDS_CONFIRMATION if row_blockers else STATUS_FINAL,
            blockers=tuple(sorted(row_blockers)),
        ))
        overall.extend(row_blockers)
    if blocked:
        overall.append("RUN_NOT_READY")
    status = STATUS_FINAL if rows and not overall else STATUS_NEEDS_CONFIRMATION
    return GeneratedPayroll(
        period=period, rows=tuple(rows), status=status,
        blockers=tuple(sorted(set(overall))), rule_versions=dict(rule_versions or {}),
    )
