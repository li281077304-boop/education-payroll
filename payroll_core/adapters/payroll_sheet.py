from __future__ import annotations

from pathlib import Path

from ..models.records import PayrollRecord
from ._csv import optional_float, rows


def read_payroll_csv(path: str | Path, period: str) -> list[PayrollRecord]:
    """Read the normalized fixture shape.

    Real Excel adapters are intentionally not guessed here. The current workbook
    has multiple layouts and external links; that mapping remains an explicit TODO.
    """
    return [
        PayrollRecord(
            period=period,
            teacher=row["teacher"].strip(),
            one_to_one=optional_float(row.get("one_to_one")),
            class_value=optional_float(row.get("class_value")),
            production=optional_float(row.get("production")),
            ae=optional_float(row.get("ae")),
            af=optional_float(row.get("af")),
            av=optional_float(row.get("av")),
            source=str(path),
        )
        for row in rows(path)
    ]
