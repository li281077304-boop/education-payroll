from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isclose
from typing import Any

from ..config.schema import PayrollConfig
from ..models.decisions import ManualDecision
from ..models.reconciliation import (
    ReconciliationItem,
    ReconciliationReport,
    ReconciliationStatus,
)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


class ReconciliationEngine:
    def __init__(self, config: PayrollConfig):
        self.config = config

    def reconcile(
        self,
        expected: Mapping[str, Mapping[str, Any]],
        actual: Mapping[str, Mapping[str, Any]],
        *,
        required_fields: Iterable[tuple[str, str]],
        decisions: Iterable[ManualDecision] = (),
    ) -> ReconciliationReport:
        report = ReconciliationReport()
        decisions_by_key = {decision.key(): decision for decision in decisions}
        required = list(dict.fromkeys(required_fields))
        adjustments = self._adjustments()
        for target, field in required:
            decision = decisions_by_key.get((self.config.period, target, field))
            if target not in expected:
                report.items.append(self._missing_item(target, field, actual, decision, True))
                continue
            if target not in actual:
                report.items.append(self._missing_item(target, field, expected, decision, False))
                continue
            if field not in expected[target]:
                report.items.append(self._unknown_item(target, field, "Expected field was not supplied"))
                continue
            if field not in actual[target]:
                report.items.append(self._unknown_item(target, field, "Actual field was not supplied"))
                continue
            expected_value = expected[target][field]
            actual_value = actual[target][field]
            adjustment = adjustments.get((target, field), 0.0)
            compared_expected = expected_value + adjustment if _number(expected_value) is not None else expected_value
            raw_difference = self._difference(expected_value, actual_value)
            difference = self._difference(compared_expected, actual_value)
            if difference is None:
                status = ReconciliationStatus.NEEDS_MANUAL_REVIEW
                reason = "Non-numeric values require a field-specific adapter or review"
            elif isclose(difference, 0.0, abs_tol=self.config.tolerance):
                if adjustment and raw_difference is not None and not isclose(raw_difference, 0.0, abs_tol=self.config.tolerance):
                    status = ReconciliationStatus.EXPLAINED_DIFFERENCE
                    reason = "Configured effective-period adjustment"
                else:
                    status = ReconciliationStatus.MATCH
                    reason = "Expected and actual values match"
            elif decision is not None:
                if decision.system_value == compared_expected and decision.override_value == actual_value:
                    status = ReconciliationStatus.EXPLAINED_DIFFERENCE
                    reason = f"Confirmed manual decision: {decision.reason}"
                else:
                    status = ReconciliationStatus.NEEDS_MANUAL_REVIEW
                    reason = self._decision_reason(decision, compared_expected, actual_value)
            else:
                status = ReconciliationStatus.UNEXPLAINED_DIFFERENCE
                reason = "No configured rule or confirmed manual decision explains the difference"
            report.items.append(
                ReconciliationItem(
                    period=self.config.period,
                    target=target,
                    field=field,
                    expected=compared_expected,
                    actual=actual_value,
                    difference=difference,
                    reason=reason,
                    status=status,
                    source=decision.source if decision else "",
                )
            )
        report.finalize(len(required))
        return report

    def _adjustments(self) -> dict[tuple[str, str], float]:
        result: dict[tuple[str, str], float] = {}
        for adjustment in self.config.active_adjustments():
            target = adjustment.get("target")
            field = adjustment.get("field")
            delta = adjustment.get("delta")
            if not isinstance(target, str) or not isinstance(field, str) or not isinstance(delta, (int, float)):
                raise ValueError("Each reconciliation adjustment needs target, field and numeric delta")
            result[(target, field)] = result.get((target, field), 0.0) + float(delta)
        return result

    @staticmethod
    def _difference(expected: Any, actual: Any) -> float | None:
        left, right = _number(expected), _number(actual)
        return None if left is None or right is None else round(right - left, 10)

    def _missing_item(self, target: str, field: str, values: Mapping[str, Mapping[str, Any]], decision: ManualDecision | None, source_missing: bool) -> ReconciliationItem:
        if decision:
            return ReconciliationItem(
                period=decision.period,
                target=target,
                field=field,
                expected=decision.system_value,
                actual=decision.override_value,
                difference=None,
                reason=f"Missing {'source' if source_missing else 'target'} covered by confirmed decision: {decision.reason}",
                status=ReconciliationStatus.EXPLAINED_DIFFERENCE,
                source=decision.source,
            )
        return ReconciliationItem(
            period=self.config.period,
            target=target,
            field=field,
            expected=None if source_missing else values[target].get(field),
            actual=values[target].get(field) if source_missing else None,
            difference=None,
            reason=f"Missing {'source' if source_missing else 'target'} record",
            status=ReconciliationStatus.MISSING_SOURCE if source_missing else ReconciliationStatus.MISSING_TARGET,
        )

    def _unknown_item(self, target: str, field: str, reason: str) -> ReconciliationItem:
        return ReconciliationItem(
            period=self.config.period,
            target=target,
            field=field,
            expected=None,
            actual=None,
            difference=None,
            reason=reason,
            status=ReconciliationStatus.NEEDS_MANUAL_REVIEW,
        )

    @staticmethod
    def _decision_reason(decision: ManualDecision, expected: Any, actual: Any) -> str:
        if decision.system_value != expected or decision.override_value != actual:
            return f"Decision exists but values differ from recorded decision: {decision.reason}"
        return f"Confirmed manual decision: {decision.reason}"
