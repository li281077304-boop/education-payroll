"""Teacher employment type as a first-class, source-backed fact.

The payroll chain needs to answer one question before it can decide whether a
teacher owes a full-time base salary at all: is this person full-time or
part-time?  Reading that from a hard-coded default made part-time teachers look
like full-time teachers with missing G--L data, which is a different (and
wrong) business statement.

Priority, highest first:

1. a source document that states the employment type (支持部 / 人员资料);
2. an employment profile a human confirmed and that is effective this month;
3. a part-time rule the repository already registers (still flagged, because a
   registered rule is not the same as this month's source material);
4. ``UNKNOWN`` -- never a silent ``FULL_TIME`` guess.

``UNKNOWN`` is deliberately not resolved to full-time.  It keeps the base
salary requirement visible and asks a human, which is the honest outcome.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

FULL_TIME = "FULL_TIME"
PART_TIME = "PART_TIME"
UNKNOWN = "UNKNOWN"

EMPLOYMENT_TYPES = (FULL_TIME, PART_TIME, UNKNOWN)

# Where a resolved employment type came from.
SOURCE_DOCUMENT = "EMPLOYMENT_FROM_DOCUMENT"
SOURCE_USER_CONFIRMED = "EMPLOYMENT_USER_CONFIRMED"
SOURCE_DERIVED_PROFILE = "EMPLOYMENT_DERIVED_PROFILE"
SOURCE_REGISTERED_RULE = "EMPLOYMENT_REGISTERED_PART_TIME_RULE"
SOURCE_UNRESOLVED = "EMPLOYMENT_UNRESOLVED"

SOURCE_LABELS: dict[str, str] = {
    SOURCE_DOCUMENT: "来源资料明确标注",
    SOURCE_USER_CONFIRMED: "人工确认的教师用工性质",
    SOURCE_DERIVED_PROFILE: "沿用已保存的教师用工性质",
    SOURCE_REGISTERED_RULE: "系统已登记的兼职规则（建议确认）",
    SOURCE_UNRESOLVED: "资料未说明，需要人工确认",
}

# A human decision is required before the value may be treated as settled.
UNSETTLED_SOURCES = frozenset({SOURCE_REGISTERED_RULE, SOURCE_UNRESOLVED})

TYPE_LABELS = {FULL_TIME: "全职", PART_TIME: "兼职", UNKNOWN: "未确认"}

EMPLOYMENT_LABELS = TYPE_LABELS


def normalise_teacher(value: object) -> str:
    return "".join(str(value or "").replace("\u3000", "").split())


def coerce_employment_type(value: object) -> str:
    """Map free-text employment wording onto the three official states."""
    text = str(value or "").strip().upper()
    if not text:
        return UNKNOWN
    if text in EMPLOYMENT_TYPES:
        return text
    if any(token in text for token in ("兼职", "非全", "PART", "PT")):
        return PART_TIME
    if any(token in text for token in ("全职", "专职", "FULL", "FT")):
        return FULL_TIME
    return UNKNOWN


def name_variants(teacher: str, known_names: Iterable[str]) -> tuple[str, ...]:
    """Same-shape names that must not be merged without a human decision.

    Two names that differ by a single character at the same position are weak
    evidence of one person, and the repository's own part-time rule list
    contains such a pair.  They are surfaced as a candidate, never applied.
    """
    target = normalise_teacher(teacher)
    if len(target) < 2:
        return ()
    matches = []
    for other in known_names:
        candidate = normalise_teacher(other)
        if not candidate or candidate == target or len(candidate) != len(target):
            continue
        if candidate[0] != target[0]:
            continue
        shared = sum(1 for left, right in zip(target, candidate) if left == right)
        if shared >= len(target) - 1:
            matches.append(candidate)
    return tuple(sorted(set(matches)))


def _entry(
    employment_type: str,
    source: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    needs_confirmation: bool = False,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "employment_type": employment_type,
        "employment_label": TYPE_LABELS.get(employment_type, employment_type),
        "source": source,
        "source_label": SOURCE_LABELS.get(source, source),
        "needs_confirmation": bool(needs_confirmation),
        "detail": detail,
        "evidence": dict(evidence or {}),
    }


def resolve_employment_type(
    teacher: str,
    *,
    document: object | None = None,
    document_source: str = "",
    profile: Mapping[str, Any] | None = None,
    registered_part_time: Mapping[str, float] | None = None,
    known_names: Iterable[str] = (),
) -> dict[str, Any]:
    """Resolve one teacher's employment type without guessing."""
    registered = registered_part_time or {}
    names = tuple(known_names)

    # 1. The source material states it.
    if document not in (None, ""):
        resolved = coerce_employment_type(document)
        if resolved != UNKNOWN:
            return _entry(resolved, SOURCE_DOCUMENT, evidence={"source": document_source, "raw": str(document)})

    # 2. A profile a human already confirmed for this period.
    if isinstance(profile, Mapping):
        declared = str(profile.get("employment_type") or "")
        resolved = coerce_employment_type(declared)
        if resolved != UNKNOWN:
            settled = str(profile.get("source") or "") not in UNSETTLED_SOURCES
            return _entry(
                resolved,
                str(profile.get("source") or SOURCE_DERIVED_PROFILE),
                evidence={"profile_id": profile.get("id", ""), "confirmed_by": profile.get("confirmed_by", "")},
                needs_confirmation=not settled,
                detail=str(profile.get("reason") or ""),
            )

    # 3. A part-time rule the repository already registers.
    key = normalise_teacher(teacher)
    for registered_name, rate in registered.items():
        if normalise_teacher(registered_name) != key:
            continue
        variants = name_variants(teacher, names)
        return _entry(
            PART_TIME,
            SOURCE_REGISTERED_RULE,
            evidence={"registered_name": registered_name, "rate_per_lesson": float(rate)},
            needs_confirmation=True,
            detail=f"系统已登记 {registered_name} 为兼职（每节 {rate:g} 元）。",
        )

    # A near-miss of a registered part-time name is a candidate, not a fact.
    for registered_name in registered:
        variants = name_variants(registered_name, [key])
        if variants:
            return _entry(
                UNKNOWN,
                SOURCE_UNRESOLVED,
                evidence={"registered_name": registered_name, "candidate": variants, "kind": "SAME_PERSON_POSSIBLE_VARIANT"},
                needs_confirmation=True,
                detail=f"{teacher} 与已登记兼职 {registered_name} 只差一字，系统不擅自合并身份，请确认是否同一人。",
            )

    # 4. Nothing proves it.  Do not guess full-time.
    return _entry(
        UNKNOWN,
        SOURCE_UNRESOLVED,
        needs_confirmation=True,
        detail=f"{teacher} 没有可用的用工性质资料；请确认是{ TYPE_LABELS[FULL_TIME] }还是{ TYPE_LABELS[PART_TIME] }。",
    )


def employment_needs_confirmation(entry: Mapping[str, Any] | None) -> bool:
    if not isinstance(entry, Mapping):
        return True
    return bool(entry.get("needs_confirmation")) or str(entry.get("employment_type")) not in {
        FULL_TIME, PART_TIME,
    }
