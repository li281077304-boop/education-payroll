from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from ..models.evidence import AdapterIssue
from ..models.records import PayrollRecord, ScheduleRecord


# This is the current 8-month Q-column calculation expressed per normalized 1:1 row:
# attended × 2 hours × grade coefficient. It is deliberately narrow and documented.
GRADE_COEFFICIENTS = {
    "领航伴学": 0.6, "一年级": 0.85, "二年级": 0.85, "三年级": 0.85,
    "四年级": 0.85, "五年级": 0.85, "六年级": 0.85, "七年级": 0.9,
    "八年级": 0.9, "九年级": 1.0, "高一": 1.1, "高二": 1.25, "高三": 1.35,
    "雅思": 1.5, "托福": 1.5,
}


def expected_one_to_one_from_normalized_schedule(records: Iterable[ScheduleRecord]) -> tuple[dict[str, dict[str, float]], list[AdapterIssue]]:
    totals: dict[str, float] = defaultdict(float)
    issues: list[AdapterIssue] = []
    for record in records:
        if record.class_type != "1对1":
            continue
        coefficient = GRADE_COEFFICIENTS.get(record.grade)
        if coefficient is None:
            issues.append(AdapterIssue("GRADE_UNRESOLVED", "Cannot calculate 1:1 expected value without a recognized normalized grade", field="one_to_one"))
            continue
        if record.attended is None:
            issues.append(AdapterIssue("MISSING_ATTENDANCE", "Cannot calculate 1:1 expected value without attendance", field="one_to_one"))
            continue
        totals[record.teacher] += record.attended * 2 * coefficient
    return {teacher: {"one_to_one": round(value, 10)} for teacher, value in totals.items()}, issues


def actual_one_to_one_from_payroll(records: Iterable[PayrollRecord]) -> dict[str, dict[str, float | None]]:
    return {record.teacher: {"one_to_one": record.one_to_one} for record in records}
