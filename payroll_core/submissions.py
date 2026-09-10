"""Merge standardized payroll submissions into one canonical table.

The merge works on the internal model only. It never copies cells from an
uploaded workbook: the unified payroll table is regenerated from merged data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Any, Iterable, Mapping

from .models.payroll_submission import (
    NUMERIC_FIELDS,
    MergeFinding,
    StandardPayrollSubmission,
)


@dataclass(frozen=True)
class MergeOutcome:
    merged: Mapping[str, Mapping[str, Any]]
    findings: tuple[MergeFinding, ...]
    duplicate_teachers: tuple[str, ...] = ()
    missing_teachers: tuple[str, ...] = ()
    conflicting_teachers: tuple[str, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(item.severity == "ERROR" for item in self.findings)


def merge_submissions(
    submissions: Iterable[StandardPayrollSubmission],
    *,
    expected_teachers: Iterable[str] = (),
) -> MergeOutcome:
    """Merge rows per teacher, flagging duplicates, conflicts and gaps."""
    ordered = list(submissions)
    by_teacher: dict[str, list[StandardPayrollSubmission]] = {}
    for item in ordered:
        by_teacher.setdefault(item.teacher_id, []).append(item)

    findings: list[MergeFinding] = []
    merged: dict[str, dict[str, Any]] = {}
    duplicates: list[str] = []
    conflicts: list[str] = []

    for teacher, items in by_teacher.items():
        if len(items) > 1:
            duplicates.append(teacher)
            findings.append(MergeFinding(
                "DUPLICATE_TEACHER", "ERROR", teacher,
                f"{teacher} 出现了 {len(items)} 条工资记录，需要确认保留哪一条。",
                {"sources": [f"{item.source_file}#{item.source_row}" for item in items]},
            ))
        combined: dict[str, Any] = {}
        for item in items:
            for name, value in item.fields.items():
                if name == "teacher" or value is None:
                    continue
                if name in combined and not _same(combined[name], value):
                    if teacher not in conflicts:
                        conflicts.append(teacher)
                    findings.append(MergeFinding(
                        "FIELD_CONFLICT", "ERROR", teacher,
                        f"{teacher} 的 {name} 在不同工资表里的值不一致：{combined[name]} 与 {value}。",
                        {"field": name, "values": [combined[name], value]},
                    ))
                combined[name] = value
        merged[teacher] = combined

        for name in NUMERIC_FIELDS:
            value = combined.get(name)
            if value is None:
                findings.append(MergeFinding(
                    "MISSING_FIELD", "WARNING", teacher,
                    f"{teacher} 的 {name} 没有值，核对时会按缺失处理。", {"field": name},
                ))
            elif not isinstance(value, (int, float)):
                findings.append(MergeFinding(
                    "VALUE_NOT_NUMERIC", "ERROR", teacher,
                    f"{teacher} 的 {name} 不是数字：{value!r}。", {"field": name},
                ))

    missing = [teacher for teacher in expected_teachers if teacher and teacher not in merged]
    for teacher in missing:
        findings.append(MergeFinding(
            "MISSING_TEACHER", "ERROR", teacher,
            f"{teacher} 没有提交工资表。", {},
        ))

    return MergeOutcome(
        merged=merged,
        findings=tuple(findings),
        duplicate_teachers=tuple(duplicates),
        missing_teachers=tuple(missing),
        conflicting_teachers=tuple(conflicts),
    )


def standard_columns(extra_columns: Iterable[str] = ()) -> tuple[str, ...]:
    return ("teacher",) + NUMERIC_FIELDS + tuple(extra_columns)


def _same(left: Any, right: Any) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return isclose(float(left), float(right), abs_tol=1e-6)
    return left == right


@dataclass(frozen=True)
class SubmissionBatchSummary:
    period: str
    teacher_count: int
    total_fields: Mapping[str, float] = field(default_factory=dict)
