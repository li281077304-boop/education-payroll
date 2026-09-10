"""Standardized teacher payroll submissions.

A teacher uploads their own payroll sheet. One sheet, many sheets, or an
already merged summary workbook must all converge on the same internal shape,
so the reconciliation core never learns where a row came from.

This model is deliberately separate from management assessment input: a
personal payroll sheet is a teacher payroll fact, while a group-leader
assessment is a management business input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class SubmissionSourceKind(StrEnum):
    """Where a submission came from. Downstream code must not branch on it."""

    SINGLE = "SINGLE"        # one teacher, one personal sheet
    MULTI = "MULTI"          # several personal sheets uploaded together
    SUMMARY = "SUMMARY"      # an already merged payroll workbook


class SubmissionStatus(StrEnum):
    IMPORTED = "IMPORTED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"   # field meaning is ambiguous
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class MergeBatchStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


#: The canonical payroll fields the reconciliation core understands.
CANONICAL_FIELDS: tuple[str, ...] = ("teacher", "one_to_one", "class_value", "production", "ae", "af", "av")
REQUIRED_FIELDS: tuple[str, ...] = ("teacher",)
NUMERIC_FIELDS: tuple[str, ...] = ("one_to_one", "class_value", "production", "ae", "af", "av")


@dataclass(frozen=True)
class StandardPayrollSubmission:
    """One teacher's payroll row in canonical form, with its provenance."""

    id: str
    period: str
    teacher_id: str
    fields: Mapping[str, Any]
    source_file: str
    source_sheet: str
    source_row: str
    source_file_hash: str
    source_kind: SubmissionSourceKind
    layout_profile_id: str = ""
    status: SubmissionStatus = SubmissionStatus.IMPORTED
    extra: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass(frozen=True)
class LayoutProfile:
    """A confirmed header-to-canonical mapping that can be reused next time.

    Layouts differ slightly between subject groups; a confirmed layout must be
    remembered instead of re-asking the same question every month.
    """

    id: str
    name: str
    fingerprint: str
    mapping: Mapping[str, str]          # canonical -> source header
    created_by: str
    period: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class MergeFinding:
    """A merge-time problem that a human must see before confirming."""

    code: str
    severity: str                       # ERROR or WARNING
    teacher_id: str
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LayoutDetection:
    """The result of recognizing (or failing to recognize) one sheet layout."""

    fingerprint: str
    mapping: Mapping[str, str]
    ambiguous: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    missing_required: tuple[str, ...] = ()
    profile_id: str = ""

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.ambiguous) or bool(self.missing_required)
