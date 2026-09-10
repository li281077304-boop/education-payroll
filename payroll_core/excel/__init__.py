"""Read-only Excel inspection, fingerprints and adapters for known payroll layouts."""
from .writeback import WritebackPreview, preview, write_new_workbook

__all__ = ["WritebackPreview", "preview", "write_new_workbook"]
