"""Configurable class-type conversion rules.

Two separate tables, because they answer two different questions:

* 普通小班 is priced only by **实到人数** (1人 0.8、2人 1.0、3人 1.2 …). It has no
  class coefficient at all.
* 特殊班型 (1对2 / 1对3) use an explicitly configured **class type × actual
  attendance** coefficient. They never multiply the ordinary-small-group
  attendance table.

Mixing the two — storing 小班 as one fixed coefficient, or multiplying the
attendance coefficient into a special class — silently produces wrong money,
so the model forbids it rather than tolerating it.

Rules are versioned so a later edit can never rewrite an already-closed month.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


UNKNOWN_CLASS_TYPE_RULE = "UNKNOWN_CLASS_TYPE_RULE"
#: 班型已知为特殊班型，但该「班型 × 实到人数」组合没有配置。
UNKNOWN_CLASS_RULE = "UNKNOWN_CLASS_RULE"

#: Every course defaults to two hours; this factor is not per-course data.
LESSON_HOUR_FACTOR = 2

#: 主核稳定规则：普通小班的实到人数系数表。固定写在 Core，不做外部配置化。
ORDINARY_SMALL_GROUP_HEADCOUNT_COEFFICIENTS: Mapping[int, float] = {
    1: 0.8, 2: 1.0, 3: 1.2, 4: 1.4, 5: 1.7, 6: 1.9, 7: 2.1, 8: 2.3, 9: 2.5, 10: 2.7,
}
#: Backwards-compatible alias.
DEFAULT_HEADCOUNT_COEFFICIENTS: Mapping[int, float] = ORDINARY_SMALL_GROUP_HEADCOUNT_COEFFICIENTS

#: 主核稳定规则：一对一固定逻辑，不走任何系数配置。
ONE_TO_ONE_CLASS_TYPES: tuple[str, ...] = ("1对1",)
SMALL_GROUP_CLASS_TYPES: tuple[str, ...] = ("小班",)

#: 特殊班型：**必须配置化**，Core 不写死任何特殊班型系数。
#: 形状是 (班型 → 实到人数 → multiplier)：
#:   1对2：1人 0.8、2人 1.2
#:   1对3：1人 0.8、2人 1.2、3人 1.5
#: 未配置的班型或人数组合一律返回 UNKNOWN_CLASS_RULE，不猜、不默认。
DEFAULT_SPECIAL_CLASS_COEFFICIENTS: Mapping[str, Mapping[int, float]] = {}

#: 已确认的特殊班型系数，作为**配置种子**提供（不在 Core 里做查表兜底）。
CONFIRMED_SPECIAL_CLASS_COEFFICIENTS: Mapping[str, Mapping[int, float]] = {
    "1对2": {1: 0.8, 2: 1.2},
    "1对3": {1: 0.8, 2: 1.2, 3: 1.5},
    "三人班": {1: 0.8, 2: 1.2, 3: 1.5},
}

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
    def special(self) -> Mapping[str, Mapping[int, float]]:
        return normalize_special(self.rules.get(SPECIAL_RULES_KEY) or DEFAULT_SPECIAL_CLASS_COEFFICIENTS)

    def coefficient(self, class_type: str, attended: int | None = None) -> float | None:
        """Look up 特殊班型 multiplier by class type and actual attendance."""
        table = self.special.get(class_type)
        if table is None:
            return None
        if attended is None:
            return None
        return table.get(int(attended))

    def covers(self, period: str) -> bool:
        return self.effective_from <= period <= self.effective_to

    @property
    def version(self) -> str:
        return self.id


def normalize_special(raw: Mapping[str, object]) -> dict[str, dict[int, float]]:
    """Normalise 特殊班型配置 into ``{class_type: {attended: multiplier}}``."""
    table: dict[str, dict[int, float]] = {}
    for name, value in (raw or {}).items():
        if isinstance(value, Mapping):
            table[str(name)] = {int(key): float(item) for key, item in value.items()}
        else:
            # A flat coefficient is the removed, wrong model: 特殊班型 系数必须按人数配置。
            raise ValueError(f"特殊班型“{name}”必须按实到人数配置系数，不能给单一固定值。")
    return table


def structured_rules(special: Mapping[str, object]) -> dict[str, object]:
    """Only 特殊班型 is configurable; 普通小班与一对一固定在 Core。"""
    return {SPECIAL_RULES_KEY: {str(name): {str(key): float(item) for key, item in normalize_special({name: value})[name].items()} for name, value in (special or {}).items()}}


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
            source="历史代码审计（1对2 与普通小班按实到人数系数）",
            effective_from="2020-01-01", effective_to="2026-08-31",
            rules=structured_rules({"1对2": {1: 0.8, 2: 1.2}}),
            created_at="2020-01-01T00:00:00+00:00",
            notes="普通小班走主核实到人数系数；特殊 1对2 也按实到人数查该版本配置。原「小班 1.0」是无效乘数，已移除。",
        ),
        ClassTypeRuleVersion(
            id="CLASS_TYPE_RULE_2026-09",
            source="用户确认：1对3 / 三人班按实到人数配置",
            effective_from="2026-09-01", effective_to="9999-12-31",
            rules=structured_rules(CONFIRMED_SPECIAL_CLASS_COEFFICIENTS),
            created_at="2026-09-01T00:00:00+00:00",
            notes="新增 1对3 / 三人班的实到人数系数；普通小班仍按主核实到人数系数折算。",
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
        return structured_rules(DEFAULT_SPECIAL_CLASS_COEFFICIENTS)
    return dict(rules)
