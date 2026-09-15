"""Versioned, self-contained rules for the new payroll calculation chain.

This module is intentionally separate from the legacy ``config`` loader.  A
closed run binds one immutable CoreRules bundle; loading another bundle cannot
silently recalculate that run with later policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any, Mapping

from ..models.class_type_rules import ORDINARY_SMALL_GROUP_HEADCOUNT_COEFFICIENTS


_PERIOD = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _decimal(value: object, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} must be a decimal") from exc
    if not result.is_finite():
        raise ValueError(f"{name} must be finite")
    return result


def _period(value: object, name: str) -> str:
    if not isinstance(value, str) or not _PERIOD.fullmatch(value):
        raise ValueError(f"{name} must be YYYY-MM")
    return value


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping")
    return value


@dataclass(frozen=True)
class CourseRule:
    """A **特殊班型** rule. 一对一 and 普通小班 are Core constants, not config."""

    id: str
    treatment: str  # SPECIAL
    class_types: tuple[str, ...]
    #: 实到人数 → multiplier. A special class value depends on the attendance,
    #: so a single fixed coefficient is not representable (and not accepted).
    coefficients: Mapping[int, Decimal] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CourseRule":
        rule_id = raw.get("id")
        treatment = raw.get("treatment")
        class_types = raw.get("class_types")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError("course rule requires id")
        if treatment != "SPECIAL":
            raise ValueError(f"course rule {rule_id}: only 特殊班型 is configurable; 一对一 与 普通小班 固定在 Core")
        if not isinstance(class_types, list) or not class_types or not all(isinstance(v, str) and v for v in class_types):
            raise ValueError(f"course rule {rule_id} requires non-empty class_types")
        raw_coefficients = raw.get("coefficients")
        if not isinstance(raw_coefficients, Mapping) or not raw_coefficients:
            raise ValueError(f"course rule {rule_id} requires per-attendance coefficients")
        coefficients: dict[int, Decimal] = {}
        for key, value in raw_coefficients.items():
            try:
                attended = int(key)
            except (TypeError, ValueError):
                raise ValueError(f"course rule {rule_id} attendance key must be an integer: {key!r}") from None
            if attended < 1:
                raise ValueError(f"course rule {rule_id} attendance must be positive")
            coefficient = _decimal(value, f"course rule {rule_id} coefficient {key}")
            if coefficient <= 0:
                raise ValueError(f"course rule {rule_id} coefficient must be positive")
            coefficients[attended] = coefficient
        return cls(rule_id, treatment, tuple(class_types), coefficients)

    def multiplier_for(self, attended: int) -> Decimal | None:
        return self.coefficients.get(attended)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "treatment": self.treatment, "class_types": list(self.class_types),
            "coefficients": {str(key): str(value) for key, value in sorted(self.coefficients.items())},
        }


@dataclass(frozen=True)
class TierRule:
    id: str
    minimum: Decimal
    maximum: Decimal | None
    base: Decimal
    minimum_exclusive: bool = False

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "TierRule":
        rule_id = raw.get("id")
        if not isinstance(rule_id, str) or not rule_id:
            raise ValueError("AE tier requires id")
        minimum = _decimal(raw.get("minimum"), f"AE tier {rule_id} minimum")
        maximum = raw.get("maximum")
        max_value = None if maximum is None else _decimal(maximum, f"AE tier {rule_id} maximum")
        base = _decimal(raw.get("base"), f"AE tier {rule_id} base")
        minimum_exclusive = raw.get("minimum_exclusive", False)
        if not isinstance(minimum_exclusive, bool):
            raise ValueError(f"AE tier {rule_id} minimum_exclusive must be boolean")
        if minimum < 0 or base < 0 or (max_value is not None and max_value < minimum):
            raise ValueError(f"AE tier {rule_id} has invalid bounds")
        return cls(rule_id, minimum, max_value, base, minimum_exclusive)

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "minimum": str(self.minimum), "maximum": None if self.maximum is None else str(self.maximum), "base": str(self.base), "minimum_exclusive": self.minimum_exclusive}


@dataclass(frozen=True)
class AFPolicyCandidate:
    obligation_hours: Decimal
    source: str
    label: str

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "AFPolicyCandidate":
        obligation = _decimal(raw.get("obligation_hours"), "default AF policy obligation_hours")
        source, label = raw.get("source"), raw.get("label")
        if obligation < 0 or not isinstance(source, str) or not source or not isinstance(label, str) or not label:
            raise ValueError("default AF policy requires non-negative obligation_hours, source and label")
        return cls(obligation, source, label)

    def to_dict(self) -> dict[str, str]:
        return {"obligation_hours": str(self.obligation_hours), "source": self.source, "label": self.label}


@dataclass(frozen=True)
class CoreRules:
    schema_version: str
    rule_version_id: str
    effective_from: str
    effective_to: str
    source: str
    lesson_hour_factor: Decimal
    grade_coefficients: Mapping[str, Decimal]
    excluded_grades: tuple[str, ...]
    non_teaching_lesson_statuses: tuple[str, ...]
    course_rules: tuple[CourseRule, ...]
    small_group_headcount_coefficients: Mapping[int, Decimal]
    ae_tiers: tuple[TierRule, ...]
    star_bonuses: Mapping[int, Decimal]
    default_af_policy_candidate: AFPolicyCandidate | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "CoreRules":
        raw = _mapping(raw, "core rules")
        schema_version, version_id, source = raw.get("schema_version"), raw.get("rule_version_id"), raw.get("source")
        if schema_version != "payroll-core-rules/v1":
            raise ValueError("schema_version must be payroll-core-rules/v1")
        if not isinstance(version_id, str) or not version_id or not isinstance(source, str) or not source:
            raise ValueError("core rules require rule_version_id and source")
        effective_from = _period(raw.get("effective_from"), "effective_from")
        effective_to = _period(raw.get("effective_to"), "effective_to")
        if effective_from > effective_to:
            raise ValueError("effective_from must not be after effective_to")
        factor = _decimal(raw.get("lesson_hour_factor"), "lesson_hour_factor")
        if factor <= 0:
            raise ValueError("lesson_hour_factor must be positive")
        grades_raw = _mapping(raw.get("grade_coefficients"), "grade_coefficients")
        grades = {str(key): _decimal(value, f"grade coefficient {key}") for key, value in grades_raw.items()}
        if not grades or any(not key or value <= 0 for key, value in grades.items()):
            raise ValueError("grade_coefficients must have non-empty positive entries")
        excluded_raw = raw.get("excluded_grades", [])
        if not isinstance(excluded_raw, list) or not all(isinstance(value, str) and value for value in excluded_raw):
            raise ValueError("excluded_grades must be a list of non-empty strings")
        if len(set(excluded_raw)) != len(excluded_raw) or set(excluded_raw).intersection(grades):
            raise ValueError("excluded_grades must be unique and not have a grade coefficient")
        inactive_raw = raw.get("non_teaching_lesson_statuses", [])
        if not isinstance(inactive_raw, list) or not all(isinstance(value, str) and value for value in inactive_raw):
            raise ValueError("non_teaching_lesson_statuses must be a list of non-empty strings")
        if "已上课" in inactive_raw or len(set(inactive_raw)) != len(inactive_raw):
            raise ValueError("non_teaching_lesson_statuses must be unique and exclude 已上课")
        rules_raw = raw.get("course_rules")
        if not isinstance(rules_raw, list) or not rules_raw:
            raise ValueError("course_rules must be a non-empty list")
        course_rules = tuple(CourseRule.from_dict(_mapping(item, "course rule")) for item in rules_raw)
        seen_ids: set[str] = set()
        seen_types: set[str] = set()
        for rule in course_rules:
            if rule.id in seen_ids:
                raise ValueError(f"duplicate course rule id: {rule.id}")
            seen_ids.add(rule.id)
            overlap = seen_types.intersection(rule.class_types)
            if overlap:
                raise ValueError(f"duplicate class type rule: {sorted(overlap)[0]}")
            seen_types.update(rule.class_types)
        # 普通小班的实到人数系数表固定在 Core（主核稳定规则），不从规则包读取。
        # 规则包里只允许出现特殊班型。
        if "small_group_headcount_coefficients" in raw:
            raise ValueError("普通小班系数固定在 Core，不得放进规则包")
        people = dict(ORDINARY_SMALL_GROUP_HEADCOUNT_COEFFICIENTS)
        ae_raw = _mapping(raw.get("ae"), "ae")
        tiers_raw = ae_raw.get("tiers")
        if not isinstance(tiers_raw, list) or not tiers_raw:
            raise ValueError("ae.tiers must be a non-empty list")
        tiers = tuple(TierRule.from_dict(_mapping(item, "AE tier")) for item in tiers_raw)
        if len({item.id for item in tiers}) != len(tiers):
            raise ValueError("duplicate AE tier id")
        # Closed intervals must cover exactly without a Decimal epsilon gap.
        ordered = sorted(tiers, key=lambda item: item.minimum)
        if ordered != list(tiers) or ordered[0].minimum != 0:
            raise ValueError("AE tiers must start at 0 and be ordered")
        if ordered[0].maximum is None:
            raise ValueError("the first AE tier must declare a maximum zero threshold")
        for index, tier in enumerate(ordered):
            if tier.maximum is None and index != len(ordered) - 1:
                raise ValueError("only final AE tier may be open-ended")
            if index:
                previous = ordered[index - 1]
                if previous.maximum is None or tier.minimum != previous.maximum or not tier.minimum_exclusive:
                    raise ValueError("AE tier boundaries must touch exactly (no epsilon gap or overlap)")
        bonuses_raw = _mapping(ae_raw.get("star_bonuses"), "ae.star_bonuses")
        bonuses = {int(str(key)): _decimal(value, f"star bonus {key}") for key, value in bonuses_raw.items()}
        if not bonuses or any(rating < 1 or value < 0 for rating, value in bonuses.items()):
            raise ValueError("star bonuses must have positive ratings and non-negative values")
        af_raw = _mapping(raw.get("af", {}), "af")
        candidate_raw = af_raw.get("default_policy_candidate")
        candidate = None if candidate_raw is None else AFPolicyCandidate.from_dict(_mapping(candidate_raw, "default AF policy candidate"))
        return cls("payroll-core-rules/v1", version_id, effective_from, effective_to, source, factor, grades, tuple(excluded_raw), tuple(inactive_raw), course_rules, people, tiers, bonuses, candidate)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version, "rule_version_id": self.rule_version_id,
            "effective_from": self.effective_from, "effective_to": self.effective_to, "source": self.source,
            "lesson_hour_factor": str(self.lesson_hour_factor),
            "grade_coefficients": {key: str(value) for key, value in self.grade_coefficients.items()},
            "excluded_grades": list(self.excluded_grades),
            "non_teaching_lesson_statuses": list(self.non_teaching_lesson_statuses),
            "course_rules": [item.to_dict() for item in self.course_rules],
            "ae": {"tiers": [item.to_dict() for item in self.ae_tiers], "star_bonuses": {str(key): str(value) for key, value in self.star_bonuses.items()}},
            "af": {} if self.default_af_policy_candidate is None else {"default_policy_candidate": self.default_af_policy_candidate.to_dict()},
        }

    def covers(self, period: str) -> bool:
        return self.effective_from <= period <= self.effective_to

    def require_period(self, period: str) -> None:
        _period(period, "period")
        if not self.covers(period):
            raise ValueError(f"core rule version {self.rule_version_id} does not cover {period}")

    def course_rule(self, class_type: str) -> CourseRule | None:
        matches = [rule for rule in self.course_rules if class_type in rule.class_types]
        if len(matches) > 1:  # defensive: validates future deserialized inputs too
            raise ValueError(f"multiple course rules match class type {class_type}")
        return matches[0] if matches else None

    def ae_tier(self, hours: Decimal) -> TierRule:
        matches = [tier for tier in self.ae_tiers if (hours > tier.minimum if tier.minimum_exclusive else hours >= tier.minimum) and (tier.maximum is None or hours <= tier.maximum)]
        if len(matches) != 1:
            raise ValueError(f"AE tiers must match exactly one rule for hours={hours}")
        return matches[0]

    @property
    def ae_zero_threshold(self) -> Decimal:
        """AF/AE zero boundary is policy: the first tier's declared maximum."""
        assert self.ae_tiers[0].maximum is not None
        return self.ae_tiers[0].maximum


Rules = CoreRules


def load_core_rules(path: str | Path | None = None) -> CoreRules:
    """Load one independently portable Core rule bundle from YAML."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PyYAML is required to load core rules") from exc
    rule_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / "config" / "core_rules_2026.yaml"
    with rule_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return CoreRules.from_dict(_mapping(raw, f"core rules {rule_path}"))


def load_core_rule_bundles(directory: str | Path | None = None) -> tuple[CoreRules, ...]:
    """Load every checked-in dated Core bundle for first-run registration.

    A fresh local store must be able to create a historical Run without a
    prior UI edit.  Bundles remain separate immutable snapshots; this helper
    only discovers them and never chooses a version for a Run.
    """
    root = Path(directory) if directory is not None else Path(__file__).resolve().parents[2] / "config"
    paths = sorted(root.glob("core_rules_*.yaml"))
    bundles = tuple(load_core_rules(path) for path in paths)
    if not bundles:
        return (load_core_rules(root / "core_rules_2026.yaml"),)
    return bundles
