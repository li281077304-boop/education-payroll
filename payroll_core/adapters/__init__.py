"""Adapters turn source-specific rows into payroll_core models."""
from .business_results import ImportedBusinessResult, read_business_result
from .authority_tables import read_refund_2026, read_renewal_2026
from .payroll_submission import (
    CANONICAL_ALIASES,
    build_submissions,
    detect_layout,
    fingerprint_for,
    read_sheet_rows,
)

__all__ = [
    "ImportedBusinessResult",
    "read_business_result",
    "read_refund_2026",
    "read_renewal_2026",
    "CANONICAL_ALIASES",
    "build_submissions",
    "detect_layout",
    "fingerprint_for",
    "read_sheet_rows",
]
