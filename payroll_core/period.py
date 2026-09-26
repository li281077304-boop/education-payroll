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

    每月 1～20 日默认上一个自然月，21 日起默认当前月。
    这只是打开页面时的建议值；文件内容识别和用户确认仍是最终依据。
    """
    if today.day >= 21:
        month = today.month
        year = today.year
    else:
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


# --------------------------------------------------------------------------- #
# 人工月 / 工资周期 authority
#
# A payroll month ("2026-08") is *not* the same fact as the teaching window the
# money covers ("2026-08-01".."2026-08-30").  The window is the authority; the
# uploaded schedule only has to be consistent with it.  These constants name
# where an authority came from so the UI and the audit trail can say which
# evidence defined the boundary instead of silently assuming a natural month.
# --------------------------------------------------------------------------- #

PERIOD_AUTHORITY_VERSION = "PERIOD_AUTHORITY/v1"

# 人工月权威资料（知识库 / 制度文件 / CSV / Excel）导入
AUTHORITY_MANUAL_DOCUMENT = "MANUAL_PERIOD_DOCUMENT"
# 人工月资料（来源未标明的历史值，保留以解释旧记录）
AUTHORITY_MANUAL_RECORD = "MANUAL_PERIOD_RECORD"
# 用户在界面确认的实际排课周期
AUTHORITY_USER_CONFIRMED = "USER_CONFIRMED"
# 从同月已经人工确认过的历史 Run 恢复而来
AUTHORITY_DERIVED_CONFIRMED_RUN = "DERIVED_FROM_CONFIRMED_RUN"
# 没有任何人工月资料时的自然月兜底
AUTHORITY_NATURAL_MONTH_FALLBACK = "LEGACY_CALENDAR_DEFAULT"

EXPLICIT_AUTHORITY_SOURCES = frozenset({
    AUTHORITY_MANUAL_DOCUMENT,
    AUTHORITY_MANUAL_RECORD,
    AUTHORITY_USER_CONFIRMED,
    AUTHORITY_DERIVED_CONFIRMED_RUN,
})

# Sources that describe a boundary a human actually established.  Anything else
# (including the natural-month fallback) must be labelled as such in the UI.
_BOUNDARY_LABELS = {
    AUTHORITY_MANUAL_DOCUMENT: "人工月资料（制度文件导入）",
    AUTHORITY_MANUAL_RECORD: "人工月资料（来源未标明）",
    AUTHORITY_USER_CONFIRMED: "人工确认（本机手填）",
    AUTHORITY_DERIVED_CONFIRMED_RUN: "沿用同月已确认的人工周期",
    AUTHORITY_NATURAL_MONTH_FALLBACK: "自然月兜底（尚无人工月资料）",
}

# Where an authority record came from.  Kept distinct from the boundary source:
# the source says "how was this window established", this says "which evidence".
SOURCE_TYPE_DOCUMENT = "DOCUMENT"
SOURCE_TYPE_CSV = "CSV"
SOURCE_TYPE_EXCEL = "EXCEL"


def is_explicit_authority_source(source: str | None) -> bool:
    """True when the boundary came from a human-established authority."""
    return str(source or "").strip() in EXPLICIT_AUTHORITY_SOURCES


def authority_source_label(source: str | None) -> str:
    return _BOUNDARY_LABELS.get(str(source or "").strip(), "未标明来源")


def build_period_authority(
    payroll_period: str,
    period_start: str | None = None,
    period_end: str | None = None,
    source: str | None = None,
    *,
    revision: int = 1,
    authority_id: str = "",
    confirmed_by: str = "",
    reason: str = "",
    evidence: dict | None = None,
    provenance: dict | None = None,
    status: str = "ACTIVE",
    supersedes: str | None = None,
) -> dict:
    """Normalise one 人工月 record into the single stored shape.

    The window itself is validated by :func:`normalize_period_window`, so a
    stored authority can never disagree with a Run window that was built from
    the same rules.  ``provenance`` carries the traceable evidence (which file,
    which section, which hash) for authorities imported from a document.
    """
    window = normalize_period_window(payroll_period, period_start, period_end, source)
    boundary_source = window["period_boundary_source"]
    return {
        "id": authority_id,
        "version": PERIOD_AUTHORITY_VERSION,
        "payroll_period": str(payroll_period),
        "period_start": window["period_start"],
        "period_end": window["period_end"],
        "boundary_source": boundary_source,
        "is_fallback": not is_explicit_authority_source(boundary_source),
        "source_label": authority_source_label(boundary_source),
        "status": status,
        "revision": int(revision),
        "supersedes": supersedes,
        "confirmed_by": str(confirmed_by or ""),
        "reason": str(reason or ""),
        "evidence": dict(evidence or {}),
        "source": dict(provenance or {}),
    }


def natural_month_authority(payroll_period: str, *, evidence: dict | None = None) -> dict:
    """The explicit fallback: a natural month, clearly labelled as a fallback."""
    start, end = calendar_bounds(payroll_period)
    return build_period_authority(
        payroll_period, start, end, AUTHORITY_NATURAL_MONTH_FALLBACK,
        confirmed_by="系统兜底", reason="尚无该工资月份的人工月资料，暂按自然月核算。",
        evidence=evidence or {"basis": "NATURAL_MONTH"},
    )


def period_authority_summary(authority: dict | None) -> dict:
    """The small, user-facing projection of an authority (no internal noise)."""
    if not authority:
        return {}
    provenance = dict(authority.get("source") or {})
    return {
        "payroll_period": authority.get("payroll_period", ""),
        "period_start": authority.get("period_start", ""),
        "period_end": authority.get("period_end", ""),
        "boundary_source": authority.get("boundary_source", ""),
        "source_label": authority.get("source_label", ""),
        "is_fallback": bool(authority.get("is_fallback")),
        "authority_id": authority.get("id", ""),
        "revision": int(authority.get("revision") or 1),
        "confirmed_by": authority.get("confirmed_by", ""),
        "reason": authority.get("reason", ""),
        "source": {
            key: provenance.get(key, "")
            for key in ("source_type", "source_file", "source_section", "source_row", "imported_at")
        } | {"source_hash": str(provenance.get("source_hash", ""))[:16]},
    }


def period_authority_key(authority: dict | None) -> tuple:
    """The stable identity used to decide whether a Run must be re-bound.

    Deliberately excludes mutable evidence (import time, hash, reason) so
    re-importing the same document never rewrites an unrelated Run.
    """
    if not authority:
        return ()
    return (
        str(authority.get("payroll_period", "")),
        str(authority.get("period_start", "")),
        str(authority.get("period_end", "")),
        str(authority.get("boundary_source", "")),
        str(authority.get("id", "")),
    )


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
