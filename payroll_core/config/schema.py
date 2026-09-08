from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class PayrollConfig:
    period: str
    tolerance: float = 0.000001
    rules: Mapping[str, Any] = field(default_factory=dict)
    excluded_roles: tuple[str, ...] = ()

    def active_adjustments(self) -> tuple[Mapping[str, Any], ...]:
        adjustments = self.rules.get("reconciliation_adjustments", [])
        active: list[Mapping[str, Any]] = []
        for adjustment in adjustments:
            start = adjustment.get("effective_from", "0000-01")
            end = adjustment.get("effective_to")
            if start <= self.period and (not end or self.period <= end):
                active.append(adjustment)
        return tuple(active)
