"""Payroll period rules: default month, evidence-based month, coverage.

The clock is always passed in, never read from the machine, so tests are
deterministic and the default-previous-month rule can be verified for any date.
"""
from __future__ import annotations

import re
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

_PERIOD = re.compile(r"^(\d{4})-(\d{2})$")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def default_period_for(today: date) -> str:
    """Return the default accounting month for a given day.

    新建工资核算默认使用上一个自然月；跨年时 1 月回退到上一年 12 月。
    用户仍可在页面上主动改选其他工资月份。
    """
    month = today.month - 1 or 12
    year = today.year if today.month > 1 else today.year - 1
    return f"{year:04d}-{month:02d}"


def previous_period(period: str) -> str:
    year, month = _parse_period(period)
    month -= 1
    if month == 0:
        month, year = 12, year - 1
    return f"{year:04d}-{month:02d}"


def calendar_bounds(period_label: str) -> tuple[str, str]:
    """Return the legacy natural-month bounds for a salary label."""
    year, month = _parse_period(period_label)
    last = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"


def normalize_period_window(period_label: str, period_start: str | None = None,
                            period_end: str | None = None, source: str | None = None) -> dict[str, str]:
    """Validate an explicit accounting window while preserving legacy defaults."""
    start_default, end_default = calendar_bounds(period_label)
    start, end = (str(period_start or start_default), str(period_end or end_default))
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("核算周期必须使用 YYYY-MM-DD。") from exc
    if start_date > end_date:
        raise ValueError("核算周期开始日期不能晚于结束日期。")
    boundary_source = str(source or "").strip() or (
        "LEGACY_CALENDAR_DEFAULT" if (start, end) == (start_default, end_default) else "USER_CONFIRMED"
    )
    return {"period_label": period_label, "period_start": start, "period_end": end,
            "period_boundary_source": boundary_source}


def month_of(value: str) -> str | None:
    """Extract YYYY-MM from a date-ish string, or None when absent."""
    if not value:
        return None
    text = str(value)
    match = _ISO_DATE.search(text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    match = _PERIOD.match(text.strip()[:7])
    return match.group(0) if match else None


def dominant_month(values: Iterable[str]) -> str | None:
    """The month most lessons actually fall in. File content is the evidence."""
    months = [month for month in (month_of(item) for item in values) if month]
    if not months:
        return None
    counts = Counter(months)
    top = max(counts.values())
    # Ties are resolved by the earliest month so the result stays deterministic.
    return sorted(month for month, count in counts.items() if count == top)[0]


@dataclass(frozen=True)
class CoverageReport:
    period: str
    first_date: str | None
    last_date: str | None
    months: tuple[str, ...]
    lesson_count: int
    period_start: str | None = None
    period_end: str | None = None

    @property
    def cross_month(self) -> bool:
        return len(self.months) > 1

    @property
    def month_end(self) -> str | None:
        if self.period_end:
            return self.period_end
        if not self.period:
            return None
        year, month = _parse_period(self.period)
        return f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"

    @property
    def incomplete_tail(self) -> bool:
        """True when the last lesson is before the accounting month's last day.

        This is a warning only: the system cannot prove the remaining days had
        no lessons, so it must never be treated as an error by default.
        """
        return bool(self.last_date and self.month_end and self.last_date < self.month_end)

    @property
    def outside_period(self) -> bool:
        if self.period_start and self.period_end:
            return bool(
                self.first_date
                and (self.first_date < self.period_start or self.first_date > self.period_end)
            ) or bool(
                self.last_date
                and (self.last_date < self.period_start or self.last_date > self.period_end)
            )
        return bool(self.months) and self.period not in self.months

    def as_dict(self) -> dict:
        return {
            "period": self.period,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "months": list(self.months),
            "lesson_count": self.lesson_count,
            "cross_month": self.cross_month,
            "incomplete_tail": self.incomplete_tail,
            "outside_period": self.outside_period,
            "month_end": self.month_end,
            "period_start": self.period_start,
            "period_end": self.period_end,
        }


def coverage_for(
    period: str,
    dates: Iterable[str],
    *,
    period_start: str | None = None,
    period_end: str | None = None,
) -> CoverageReport:
    """Summarise which days the uploaded lessons actually cover."""
    cleaned = sorted(item for item in (month_of_day(value) for value in dates) if item)
    months = sorted({item[:7] for item in cleaned})
    return CoverageReport(
        period=period,
        first_date=cleaned[0] if cleaned else None,
        last_date=cleaned[-1] if cleaned else None,
        months=tuple(months),
        lesson_count=len(cleaned),
        period_start=period_start,
        period_end=period_end,
    )


def month_of_day(value: str) -> str | None:
    """Return a full YYYY-MM-DD when the value carries one."""
    if not value:
        return None
    match = _ISO_DATE.search(str(value))
    return match.group(0) if match else None


def _parse_period(period: str) -> tuple[int, int]:
    match = _PERIOD.match(str(period).strip()[:7])
    if not match:
        raise ValueError(f"invalid period: {period!r}")
    return int(match.group(1)), int(match.group(2))


_FILENAME_YEAR_MONTH = re.compile(r"(20\d{2})\D{0,3}(0?[1-9]|1[0-2])\s*月?")
_FILENAME_YEAR_DASH = re.compile(r"(20\d{2})[-_.]?(0[1-9]|1[0-2])(?!\d)")
_FILENAME_MONTH_ONLY = re.compile(r"(?:^|\D)(0?[1-9]|1[0-2])\s*月")


def month_from_filename(name: str) -> tuple[str | None, bool]:
    """Return (YYYY-MM or MM, has_year) parsed from a file name.

    File names are auxiliary evidence only. A month without a year cannot be
    compared with in-file dates, so it is reported with ``has_year=False``.
    """
    if not name:
        return None, False
    match = _FILENAME_YEAR_MONTH.search(name)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}", True
    match = _FILENAME_YEAR_DASH.search(name)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}", True
    match = _FILENAME_MONTH_ONLY.search(name)
    if match:
        return f"{int(match.group(1)):02d}", False
    return None, False
