from __future__ import annotations

from pathlib import Path

from ..models.records import RenewalRecord
from ._csv import optional_float, rows


def read_renewal_csv(path: str | Path, period: str) -> list[RenewalRecord]:
    return [
        RenewalRecord(
            period=period,
            teacher=row["teacher"].strip(),
            one_to_one_hours=optional_float(row.get("one_to_one_hours")),
            class_hours=optional_float(row.get("class_hours")),
            mentor_hours=optional_float(row.get("mentor_hours")),
            source=str(path),
        )
        for row in rows(path)
    ]
