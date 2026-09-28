from __future__ import annotations

from pathlib import Path

from ..models.evidence import CellValueState, SourceEvidence
from ..models.records import PayrollRecord
from ._csv import optional_float, rows


def read_payroll_csv(path: str | Path, period: str) -> list[PayrollRecord]:
    """Read the normalized fixture shape.

    Real Excel adapters are intentionally not guessed here. The current workbook
    has multiple layouts and external links; that mapping remains an explicit TODO.
    """
    output = []
    source = str(path)
    field_codes = ("B", "D", "E", "F", "G", "H", "I", "J", "K", "L")
    for row_number, row in enumerate(rows(path), start=2):
        additional = {code: row.get(code.lower(), row.get(code)) for code in field_codes if code.lower() in row or code in row}
        provenance = {
            code: SourceEvidence(source, "CSV", str(row_number), code,
                                 row.get(code.lower(), row.get(code)),
                                 row.get(code.lower(), row.get(code)), CellValueState.RAW_VALUE)
            for code in additional
        }
        output.append(PayrollRecord(
            period=period,
            teacher=row["teacher"].strip(),
            one_to_one=optional_float(row.get("one_to_one")),
            class_value=optional_float(row.get("class_value")),
            production=optional_float(row.get("production")),
            ae=optional_float(row.get("ae")),
            af=optional_float(row.get("af")),
            av=optional_float(row.get("av")),
            source=source,
            provenance=provenance,
            additional_fields=additional,
        ))
    return output
