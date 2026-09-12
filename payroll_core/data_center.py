"""Public data-center facade.

Keeping this import surface small lets future operating metrics consume the
same registry without adding a second file-discovery implementation.
"""
from .source_registry import (
    DataCenter,
    SOURCE_TYPES,
    SourceRecord,
    SourceRegistry,
    SourceStatus,
    SourceType,
    classify_source,
    file_hash,
)
from .excel.package import PayrollPackage, discover_payroll_package

__all__ = [
    "DataCenter", "SOURCE_TYPES", "SourceRecord", "SourceRegistry",
    "SourceStatus", "SourceType", "classify_source", "file_hash",
    "PayrollPackage", "discover_payroll_package",
]
