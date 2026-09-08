from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator


def rows(path: str | Path) -> Iterator[dict[str, str]]:
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        yield from csv.DictReader(handle)


def optional_float(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    return float(value)


def required_int(value: str | None, field: str) -> int:
    if value is None or not value.strip():
        raise ValueError(f"Missing required integer field: {field}")
    return int(value)
