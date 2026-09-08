from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ManualDecision:
    """A recorded human override; never infer one from a numeric difference."""

    period: str
    target: str
    field: str
    system_value: Any
    override_value: Any
    reason: str
    source: str
    confirmed_by: str
    note: str = ""

    def key(self) -> tuple[str, str, str]:
        return self.period, self.target, self.field
