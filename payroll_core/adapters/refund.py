from __future__ import annotations

from pathlib import Path

from ..models.records import RefundRecord
from ._csv import optional_float, rows


def read_refund_csv(path: str | Path, period: str) -> list[RefundRecord]:
    return [
        RefundRecord(
            period=period,
            charge_teacher=row["charge_teacher"].strip(),
            headcount_amount=optional_float(row.get("headcount_amount")),
            performance_amount=optional_float(row.get("performance_amount")),
            source=str(path),
        )
        for row in rows(path)
    ]
