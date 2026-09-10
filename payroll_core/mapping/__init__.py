"""Generic semantic field mapping shared by every import surface.

The engine answers one question only: which Excel column carries a semantic
field? Business modules declare which fields they need, so a new campus or
subject group never needs a dedicated adapter.
"""
from .requirements import SCHEDULE_AC_REQUIREMENT, FieldRequirement, ImportRequirement
from .schedule import read_schedule_with_mapping, resolve_schedule_import
from .semantic import (
    CANDIDATE_SCORE,
    STRONG_SCORE,
    ColumnCandidate,
    MappingAnalysis,
    analyze_mapping,
    fingerprint_for,
    normalize_header,
)

__all__ = [
    "SCHEDULE_AC_REQUIREMENT",
    "FieldRequirement",
    "ImportRequirement",
    "read_schedule_with_mapping",
    "resolve_schedule_import",
    "CANDIDATE_SCORE",
    "STRONG_SCORE",
    "ColumnCandidate",
    "MappingAnalysis",
    "analyze_mapping",
    "fingerprint_for",
    "normalize_header",
]
