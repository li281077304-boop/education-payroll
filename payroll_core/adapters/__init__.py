"""Adapters turn source-specific rows into payroll_core models."""
from .business_results import ImportedBusinessResult, read_business_result

__all__ = ["ImportedBusinessResult", "read_business_result"]
