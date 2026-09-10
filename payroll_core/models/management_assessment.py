"""Management assessment input and its formal result.

A management assessment is uploaded and confirmed by a group leader only.
It is a business input to payroll, never a teacher's personal payroll sheet,
and it lives in its own model so the two flows can never be confused.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


RULE_NOT_CONFIGURED = "RULE_NOT_CONFIGURED"


class AssessmentRole(StrEnum):
    GROUP_LEADER = "GROUP_LEADER"


class AssessmentStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AssessmentResultStatus(StrEnum):
    DRAFT = "DRAFT"
    NEEDS_MANUAL_CONFIRMATION = "NEEDS_MANUAL_CONFIRMATION"
    FINAL = "FINAL"


@dataclass(frozen=True)
class AssessmentRecord:
    id: str
    period: str
    teacher_id: str                      # the group leader who owns this assessment
    role: AssessmentRole
    source_file: str
    source_sheet: str = ""
    source_row: str = ""
    source_file_hash: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    status: AssessmentStatus = AssessmentStatus.DRAFT
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""
    linked_run_id: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class AssessmentFinding:
    code: str
    severity: str                        # ERROR or WARNING
    teacher_id: str
    message: str
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ManagementAssessmentResult:
    """The formal, payroll-ready result of one group leader assessment."""

    id: str
    period: str
    teacher_id: str
    role: AssessmentRole
    source_input_ids: tuple[str, ...]
    rule_version: str
    reviewer: str
    reviewed_at: str
    objective_score: float
    subjective_score: float
    final_score: float
    final_amount: float | None
    amount_status: str                   # CONFIGURED or RULE_NOT_CONFIGURED
    status: AssessmentResultStatus
    evidence: Mapping[str, Any] = field(default_factory=dict)
    linked_run_id: str = ""
    created_at: str = ""
