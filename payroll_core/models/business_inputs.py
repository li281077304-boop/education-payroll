"""Structured, auditable business inputs that may later support payroll review.

Inputs deliberately stop short of payroll facts: a teacher submission is an
assertion, while an imported renewal/refund result remains subject to review
and explicit Run binding.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class BusinessInputType(StrEnum):
    TEACHER_SUBMISSION = "TEACHER_SUBMISSION"
    RENEWAL_RESULT = "RENEWAL_RESULT"
    REFUND_RESULT = "REFUND_RESULT"
    REFERRAL_RESULT = "REFERRAL_RESULT"
    HR_ALLOWANCE = "HR_ALLOWANCE"
    HR_ATTENDANCE = "HR_ATTENDANCE"
    OTHER = "OTHER"


class BusinessInputStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class BusinessInputRecord:
    id: str
    period: str
    teacher_id: str
    input_type: BusinessInputType
    source_type: str
    source_ref: str
    source_file_hash: str = ""
    source_row: str = ""
    submitted_by: str = ""
    submitted_at: str = ""
    status: BusinessInputStatus = BusinessInputStatus.DRAFT
    payload: Mapping[str, Any] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    reviewed_by: str = ""
    reviewed_at: str = ""
    review_note: str = ""
    linked_run_id: str = ""
    created_at: str = ""
    updated_at: str = ""


class CommentCandidateStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    WRITTEN = "WRITTEN"
    REJECTED = "REJECTED"
    NEEDS_RECONFIRMATION = "NEEDS_RECONFIRMATION"


@dataclass(frozen=True)
class CommentWritebackCandidate:
    id: str
    run_id: str
    period: str
    teacher_id: str
    comment_type: str
    source_workbook: str
    source_file_hash: str
    sheet: str
    cell: str
    content: str
    template_version: str
    source_input_ids: tuple[str, ...] = ()
    source_resolution: Mapping[str, Any] = field(default_factory=dict)
    before_comment: str = ""
    after_comment: str = ""
    status: CommentCandidateStatus = CommentCandidateStatus.PROPOSED
    created_at: str = ""
    approved_by: str = ""
    approved_at: str = ""
    written_at: str = ""
