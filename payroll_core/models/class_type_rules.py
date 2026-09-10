"""Configurable class-type conversion rules.

Class-type coefficients must never live in Python branches: a new class type
(a four-person premium class, a revived old class type) is a configuration
change, not a code change. Rules are versioned so a later edit can never
rewrite an already-closed month.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


UNKNOWN_CLASS_TYPE_RULE = "UNKNOWN_CLASS_TYPE_RULE"


@dataclass(frozen=True)
class ClassTypeRule:
    """One class type's conversion coefficient inside one rule version."""

    rule_id: str
    class_type: str
    coefficient: float
    effective_from: str
    effective_to: str
    status: str = "ACTIVE"          # ACTIVE or INACTIVE
    source: str = ""
    version: str = ""
    created_at: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ClassTypeRuleVersion:
    """An immutable, effective-dated set of class-type rules."""

    id: str
    source: str
    effective_from: str
    effective_to: str
    rules: Mapping[str, float]
    status: str = "ACTIVE"
    created_at: str = ""
    notes: str = ""

    def coefficient(self, class_type: str) -> float | None:
        return self.rules.get(class_type)

    def covers(self, period: str) -> bool:
        return self.effective_from <= period <= self.effective_to

    @property
    def version(self) -> str:
        return self.id


#: The baseline that matches the coefficients already in the code before this
#: change (小班 1.0, 1对2 1.2). It keeps historical months bit-for-bit stable.
BASELINE_RULES: Mapping[str, float] = {"小班": 1.0, "1对2": 1.2}


def default_rule_versions() -> tuple[ClassTypeRuleVersion, ...]:
    """Seed versions: the audited baseline, plus the newly confirmed 三人班."""
    return (
        ClassTypeRuleVersion(
            id="CLASS_TYPE_RULE_2020_BASELINE",
            source="历史代码审计（小班 1.0 / 1对2 1.2）",
            effective_from="2020-01-01", effective_to="2026-08-31",
            rules=dict(BASELINE_RULES), created_at="2020-01-01T00:00:00+00:00",
            notes="与本次改造前的代码数值完全一致，用于保证历史月份不被改写。",
        ),
        ClassTypeRuleVersion(
            id="CLASS_TYPE_RULE_2026-09",
            source="用户确认：三人班 1.5",
            effective_from="2026-09-01", effective_to="9999-12-31",
            rules={**BASELINE_RULES, "三人班": 1.5}, created_at="2026-09-01T00:00:00+00:00",
            notes="仅新增三人班；小班与 1对2 沿用审计值，未按任务描述把 小班 改成 0.8（需用户确认）。",
        ),
    )


def rule_version_for_period(versions: list[dict], period: str) -> dict | None:
    active = [
        item for item in versions
        if item.get("status", "ACTIVE") == "ACTIVE"
        and item.get("effective_from", "") <= period <= item.get("effective_to", "")
    ]
    active.sort(key=lambda item: item.get("effective_from", ""), reverse=True)
    return active[0] if active else None


def coefficients_for(rules: Mapping[str, float] | None) -> dict[str, float]:
    return dict(rules) if rules else dict(BASELINE_RULES)
