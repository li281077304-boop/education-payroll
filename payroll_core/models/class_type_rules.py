"""Configurable class-type conversion rules.

Two separate tables, because they answer two different questions:

* 普通小班 is priced only by **实到人数** (1人 0.8、2人 1.0、3人 1.2 …). It has no
  class coefficient at all.
* 特殊班型 (1对2 / 1对3) carry a **fixed coefficient** and never multiply the
  attendance table. 1对2 with three attending students is still 1.2.

Mixing the two — storing 小班 as one fixed coefficient, or multiplying the
attendance coefficient into a special class — silently produces wrong money,
so the model forbids it rather than tolerating it.

Rules are versioned so a later edit can never rewrite an already-closed month.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


UNKNOWN_CLASS_TYPE_RULE = "UNKNOWN_CLASS_TYPE_RULE"

#: Every course defaults to two hours; this factor is not per-course data.
LESSON_HOUR_FACTOR = 2

#: 普通小班实到人数系数。历史资料：1人 0.8、2人 1.0、3人 1.2 ……
DEFAULT_HEADCOUNT_COEFFICIENTS: Mapping[int, float] = {
    1: 0.8, 2: 1.0, 3: 1.2, 4: 1.4, 5: 1.7, 6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5, 10: 2.7,
}

#: 特殊班型固定系数，与上面的实到人数系数互不相乘。
DEFAULT_SPECIAL_CLASS_COEFFICIENTS: Mapping[str, float] = {
    "1对2": 1.2, "1对3": 1.5, "三人班": 1.5,
}

#: 走实到人数系数的班型。
SMALL_GROUP_CLASS_TYPES: tuple[str, ...] = ("小班",)

SPECIAL_RULES_KEY = "special_class_coefficients"
HEADCOUNT_RULES_KEY = "small_group_headcount_coefficients"


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
    rules: Mapping[str, object]
    status: str = "ACTIVE"
    created_at: str = ""
    notes: str = ""

    @property
    def special(self) -> Mapping[str, float]:
        return dict(self.rules.get(SPECIAL_RULES_KEY) or DEFAULT_SPECIAL_CLASS_COEFFICIENTS)

    @property
    def headcounts(self) -> Mapping[int, float]:
        raw = self.rules.get(HEADCOUNT_RULES_KEY) or DEFAULT_HEADCOUNT_COEFFICIENTS
        return {int(key): float(value) for key, value in raw.items()}

    def coefficient(self, class_type: str) -> float | None:
        return self.special.get(class_type)

    def covers(self, period: str) -> bool:
        return self.effective_from <= period <= self.effective_to

    @property
    def version(self) -> str:
        return self.id


def structured_rules(special: Mapping[str, float], headcounts: Mapping[int, float]) -> dict[str, object]:
    return {
        SPECIAL_RULES_KEY: {str(name): float(value) for name, value in special.items()},
        HEADCOUNT_RULES_KEY: {str(key): float(value) for key, value in headcounts.items()},
    }


def default_rule_versions() -> tuple[ClassTypeRuleVersion, ...]:
    """Seed versions: the audited baseline, plus the confirmed special classes.

    The baseline keeps the numbers the code produced before this change. It no
    longer stores 小班 as a coefficient — that value was a no-op multiplier
    (1.0), so dropping it keeps every 普通小班 number identical while removing
    the misleading shape.
    """
    return (
        ClassTypeRuleVersion(
            id="CLASS_TYPE_RULE_2020_BASELINE",
            source="历史代码审计（1对2 固定 1.2；普通小班按实到人数系数）",
            effective_from="2020-01-01", effective_to="2026-08-31",
            rules=structured_rules({"1对2": 1.2}, DEFAULT_HEADCOUNT_COEFFICIENTS),
            created_at="2020-01-01T00:00:00+00:00",
            notes="与改造前数值一致：普通小班走实到人数系数，1对2 为固定系数。原「小班 1.0」是无效乘数，已移除。",
        ),
        ClassTypeRuleVersion(
            id="CLASS_TYPE_RULE_2026-09",
            source="用户确认：1对3 / 三人班 固定 1.5",
            effective_from="2026-09-01", effective_to="9999-12-31",
            rules=structured_rules({"1对2": 1.2, "1对3": 1.5, "三人班": 1.5}, DEFAULT_HEADCOUNT_COEFFICIENTS),
            created_at="2026-09-01T00:00:00+00:00",
            notes="新增 1对3 / 三人班 固定系数；普通小班仍按实到人数系数折算。",
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


def coefficients_for(rules: Mapping[str, object] | None) -> dict[str, object]:
    if not rules:
        return structured_rules(DEFAULT_SPECIAL_CLASS_COEFFICIENTS, DEFAULT_HEADCOUNT_COEFFICIENTS)
    return dict(rules)
