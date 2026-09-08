from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Optional


class ReconciliationStatus(StrEnum):
    MATCH = "MATCH"
    EXPLAINED_DIFFERENCE = "EXPLAINED_DIFFERENCE"
    UNEXPLAINED_DIFFERENCE = "UNEXPLAINED_DIFFERENCE"
    MISSING_SOURCE = "MISSING_SOURCE"
    MISSING_TARGET = "MISSING_TARGET"
    NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"


@dataclass(frozen=True)
class ReconciliationItem:
    period: str
    target: str
    field: str
    expected: Any
    actual: Any
    difference: Optional[float]
    reason: str
    status: ReconciliationStatus
    source: str = ""


@dataclass(frozen=True)
class ReconciliationSummary:
    required_checks: int
    completed_checks: int
    counts: dict[str, int]
    coverage_percent: float
    coverage_complete: bool
    overall_status: str


@dataclass
class ReconciliationReport:
    items: list[ReconciliationItem] = field(default_factory=list)
    summary: Optional[ReconciliationSummary] = None

    def finalize(self, required_checks: int) -> ReconciliationSummary:
        counts = Counter(item.status.value for item in self.items)
        completed = sum(
            1
            for item in self.items
            if item.status
            not in {
                ReconciliationStatus.NEEDS_MANUAL_REVIEW,
            }
        )
        coverage_complete = required_checks == completed
        coverage = 100.0 if required_checks == 0 else round(completed / required_checks * 100, 2)
        blocking = (
            counts[ReconciliationStatus.UNEXPLAINED_DIFFERENCE.value]
            or counts[ReconciliationStatus.MISSING_SOURCE.value]
            or counts[ReconciliationStatus.MISSING_TARGET.value]
            or counts[ReconciliationStatus.NEEDS_MANUAL_REVIEW.value]
        )
        overall = "PASS" if coverage_complete and not blocking else "REVIEW_REQUIRED"
        self.summary = ReconciliationSummary(
            required_checks=required_checks,
            completed_checks=completed,
            counts=dict(counts),
            coverage_percent=coverage,
            coverage_complete=coverage_complete,
            overall_status=overall,
        )
        return self.summary
