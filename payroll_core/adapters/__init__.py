"""Adapters turn source-specific rows into payroll_core models."""
from .business_results import ImportedBusinessResult, read_business_result
from .payroll_submission import (
    CANONICAL_ALIASES,
    build_submissions,
    detect_layout,
    fingerprint_for,
    read_sheet_rows,
)

from .assessment import AssessmentReportRecord, read_assessment_report
from .personnel import (
    DEFAULT_PART_TIME_RATES,
    IdentityConflict,
    PersonnelRecord,
    default_part_time_records,
    identity_conflicts,
    read_personnel,
)
from .refund import RefundReportRecord, read_refund_report
from .renewal_report import RenewalReportRecord, read_renewal_report
from .weekly_report import WeeklyReportRecord, read_weekly_report

__all__ = [
    "ImportedBusinessResult", "read_business_result",
    "CANONICAL_ALIASES", "build_submissions", "detect_layout",
    "fingerprint_for", "read_sheet_rows",
    "AssessmentReportRecord", "read_assessment_report",
    "DEFAULT_PART_TIME_RATES", "IdentityConflict", "PersonnelRecord",
    "default_part_time_records", "identity_conflicts", "read_personnel",
    "RefundReportRecord", "read_refund_report",
    "RenewalReportRecord", "read_renewal_report",
    "WeeklyReportRecord", "read_weekly_report",
]
