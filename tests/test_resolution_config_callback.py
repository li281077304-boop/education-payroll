"""Compatibility tests for version-bound AC resolution calculations."""
from __future__ import annotations

import pytest

from payroll_core.models.records import ScheduleRecord
from payroll_core.reconcile.ac_resolution import (
    ACContribution,
    compare_contribution_structure,
    resolve_ac,
)
from payroll_core.reconcile.payroll_scope import class_value_contribution


def _record(*, class_type: str = "小班") -> ScheduleRecord:
    return ScheduleRecord(
        period="2026-08",
        teacher="教师甲",
        grade="八年级",
        subject="数学",
        class_type=class_type,
        attended=2,
        lesson_status="已上课",
        source="schedule.xlsx",
    )


def _contribution(record_id: str, value: float | None) -> ACContribution:
    record = _record()
    return ACContribution(
        source_record_id=record_id,
        original=record,
        effective=record,
        default_contribution=value,
        effective_contribution=value,
        calculation="测试计算",
    )


def test_resolve_ac_accepts_version_bound_contribution_calculator():
    record = _record(class_type="special1对3")

    legacy = resolve_ac(
        [record], run_id="run-a", period="2026-08",
        source_hashes={record.source: "hash-a"},
    )
    assert legacy.effective_total is None

    calls: list[ScheduleRecord] = []

    def versioned_calculator(item: ScheduleRecord) -> tuple[float | None, str]:
        calls.append(item)
        return 7.5, "版本 grade-v1 / size-v2 / class-v3"

    resolved = resolve_ac(
        [record], run_id="run-a", period="2026-08",
        source_hashes={record.source: "hash-a"},
        contribution_calculator=versioned_calculator,
    )

    assert len(calls) == 2, "原始事实与有效事实必须使用同一版本化计算器"
    assert resolved.original_total == pytest.approx(7.5)
    assert resolved.corrected_total == pytest.approx(7.5)
    assert resolved.effective_total == pytest.approx(7.5)
    assert resolved.contributions[0].calculation == "版本 grade-v1 / size-v2 / class-v3"


def test_resolve_ac_default_calculator_remains_legacy_compatible():
    record = _record()
    expected, calculation = class_value_contribution(record)

    result = resolve_ac(
        [record], run_id="run-a", period="2026-08",
        source_hashes={record.source: "hash-a"},
    )

    assert result.effective_total == pytest.approx(expected)
    assert result.contributions[0].calculation == calculation


def test_unknown_contribution_requires_input_instead_of_becoming_zero():
    comparison = compare_contribution_structure(
        [_contribution("course-1", None)], {"course-1": 0.0},
    )

    assert comparison.status == "NEEDS_INPUT"
    assert comparison.system_total is None
    assert comparison.mismatched_record_ids == ("course-1",)


@pytest.mark.parametrize(
    ("contributions", "reference", "expected_ids"),
    [
        ([_contribution("course-1", 0.0)], {}, ("course-1",)),
        ([], {"course-1": 0.0}, ("course-1",)),
        ([], {}, ()),
    ],
)
def test_missing_structure_never_matches_an_implicit_zero(contributions, reference, expected_ids):
    comparison = compare_contribution_structure(contributions, reference)

    assert comparison.status == "CONTRIBUTION_STRUCTURE_MISMATCH"
    assert comparison.mismatched_record_ids == expected_ids


def test_complete_zero_valued_structure_can_still_match():
    comparison = compare_contribution_structure(
        [_contribution("course-1", 0.0)], {"course-1": 0.0},
    )

    assert comparison.status == "STRUCTURE_MATCH"
    assert comparison.system_total == pytest.approx(0.0)
