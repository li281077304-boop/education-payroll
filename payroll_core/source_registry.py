"""Single source registry used by the payroll and business-data adapters.

The registry deliberately stores metadata and evidence, not a copy of an
input workbook.  A file is identified by its content hash; repeated imports
of the same hash/sheet are one source, so downstream adapters can reuse the
same parsed snapshot instead of parsing the workbook independently.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping


class SourceType(StrEnum):
    SCHEDULE = "SCHEDULE"
    GRADE_HISTORY = "GRADE_HISTORY"
    STAR = "STAR"
    PERSONNEL = "PERSONNEL"
    WEEKLY_REPORT = "WEEKLY_REPORT"
    RENEWAL = "RENEWAL"
    REFUND = "REFUND"
    ASSESSMENT = "ASSESSMENT"
    PAYROLL_BASELINE = "PAYROLL_BASELINE"
    PAYROLL_TEMPLATE = "PAYROLL_TEMPLATE"
    OTHER = "OTHER"


SOURCE_TYPES = tuple(item.value for item in SourceType)


class SourceStatus(StrEnum):
    RECOGNIZED = "RECOGNIZED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    IMPORTED = "IMPORTED"
    REPLACED = "REPLACED"
    ERROR = "ERROR"
    DELETED = "DELETED"


def file_hash(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SourceRecord:
    source_type: str
    period: str
    file_name: str
    file_hash: str
    sheet: str = ""
    import_time: str = ""
    status: str = SourceStatus.RECOGNIZED.value
    source_evidence: Mapping[str, Any] = field(default_factory=dict)
    file_path: str = ""
    id: str = ""
    created_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def source_id(file_digest: str, sheet: str = "", source_type: str = "", period: str = "") -> str:
    """Build a stable identity for one semantic view in one period.

    The same template or source workbook is commonly reused for more than
    one month.  Period therefore belongs in the registry identity; otherwise
    importing the next month would silently replace the previous month's
    evidence even though the physical file hash is unchanged.
    """
    return sha256(f"{file_digest}\0{sheet}\0{source_type}\0{period}".encode("utf-8")).hexdigest()[:24]


class SourceRegistry:
    """A deduplicating, serializable registry for one run or data center."""

    def __init__(self, records: Iterable[Mapping[str, Any] | SourceRecord] = ()):
        self._records: dict[str, SourceRecord] = {}
        for record in records:
            self.add(record)

    def add(self, record: Mapping[str, Any] | SourceRecord) -> SourceRecord:
        item = record if isinstance(record, SourceRecord) else SourceRecord(**dict(record))
        if item.source_type not in SOURCE_TYPES:
            raise ValueError(f"unsupported source_type: {item.source_type}")
        identifier = item.id or source_id(item.file_hash, item.sheet, item.source_type, item.period)
        timestamp = _now()
        values = item.as_dict()
        if not item.import_time:
            values["import_time"] = timestamp
        if not item.created_at:
            values["created_at"] = timestamp
        if not item.updated_at:
            values["updated_at"] = timestamp
        values["id"] = identifier
        item = SourceRecord(**values)
        prior = self._records.get(identifier)
        # A later status/evidence update for the same immutable file/sheet is
        # allowed, but a different hash can never silently replace it.
        if prior and (prior.file_hash != item.file_hash or prior.sheet != item.sheet or prior.period != item.period or prior.source_type != item.source_type):
            raise ValueError("source registry identity collision")
        self._records[identifier] = item
        return item

    def register(
        self,
        source_type: str | SourceType,
        period: str,
        path: str | Path,
        *,
        sheet: str = "",
        status: str | SourceStatus = SourceStatus.RECOGNIZED,
        source_evidence: Mapping[str, Any] | None = None,
        digest: str | None = None,
    ) -> SourceRecord:
        source = Path(path).expanduser().resolve()
        digest = digest or file_hash(source)
        source_type_value = str(source_type)
        return self.add(SourceRecord(
            source_type=source_type_value, period=period, file_name=source.name,
            file_hash=digest, sheet=sheet, import_time=_now(),
            status=str(status), source_evidence=dict(source_evidence or {}),
            file_path=str(source), id=source_id(digest, sheet, source_type_value, period),
        ))

    def physical_file_audit(self) -> list[dict[str, Any]]:
        """Return one audit row per physical file hash.

        Several semantic views may legitimately point at one workbook (for
        example a weekly summary also contains renewal columns).  They are
        therefore separate registry records, but the physical file remains
        one parse unit.  Package discovery records this contract explicitly
        in ``source_evidence`` and this method makes it inspectable by the UI
        and acceptance checks.
        """
        grouped: dict[str, list[SourceRecord]] = {}
        for item in self._records.values():
            grouped.setdefault(item.file_hash, []).append(item)
        return [
            {
                "file_hash": digest,
                "file_name": records[0].file_name,
                "source_types": sorted({record.source_type for record in records}),
                "sheets": sorted({record.sheet for record in records if record.sheet}),
                "registry_records": len(records),
                "parse_count": max(int(record.source_evidence.get("parse_count", 1)) for record in records),
                "parsed_once": all(bool(record.source_evidence.get("parsed_once", True)) for record in records),
            }
            for digest, records in grouped.items()
        ]

    def get(self, identifier: str) -> SourceRecord | None:
        return self._records.get(identifier)

    def find(self, *, file_hash_value: str = "", sheet: str = "", source_type: str = "") -> list[SourceRecord]:
        return [item for item in self._records.values()
                if (not file_hash_value or item.file_hash == file_hash_value)
                and (not sheet or item.sheet == sheet)
                and (not source_type or item.source_type == source_type)]

    def values(self) -> tuple[SourceRecord, ...]:
        return tuple(self._records.values())

    def as_dicts(self) -> list[dict[str, Any]]:
        return [item.as_dict() for item in self._records.values()]

    def __len__(self) -> int:
        return len(self._records)


def classify_source(*, file_name: str, sheet: str = "", headers: Iterable[str] = (), layout: str = "", text: str = "") -> tuple[str, dict[str, Any]]:
    """Classify by content signals, with filename only as a weak hint.

    Ambiguous files are explicitly returned as OTHER/NEEDS_CONFIRMATION by
    callers; this function never guesses a payroll meaning from a filename
    alone when stronger content signals disagree.
    """
    values = {str(value).strip() for value in headers if str(value).strip()}
    haystack = " ".join([file_name, sheet, text, *sorted(values)])
    signals: list[str] = []
    if layout == "SCHEDULE_EXPORT_V1" or {"上课班级", "教学形式", "上课时间", "任课老师"}.issubset(values):
        return SourceType.SCHEDULE.value, {"signals": ["schedule_headers", layout]}
    if layout == "PAYROLL_CHECK_V1" or {"排课记录", "工资核对"}.issubset(values):
        return SourceType.GRADE_HISTORY.value, {"signals": ["payroll_check_layout", layout]}
    if layout == "PAYROLL_SHEET_V1" or {"姓名", "总课时费", "总工资数"}.issubset(values):
        return SourceType.PAYROLL_BASELINE.value, {"signals": ["payroll_headers", layout]}
    if "模板" in file_name or "template" in file_name.lower():
        return SourceType.PAYROLL_TEMPLATE.value, {"signals": ["template_filename"]}
    if {"任课老师", "续费", "学生"}.intersection(values) and "续费" in haystack:
        return SourceType.RENEWAL.value, {"signals": ["renewal_headers_or_content"]}
    if any(word in haystack for word in ("考核", "得分", "指标")):
        return SourceType.ASSESSMENT.value, {"signals": ["assessment_content"]}
    if any(word in haystack for word in ("退费", "退款", "扣款教师")):
        return SourceType.REFUND.value, {"signals": ["refund_content"]}
    if any(word in haystack for word in ("星级", "一星级", "二星级", "三星级")):
        return SourceType.STAR.value, {"signals": ["rating_content"]}
    if any(word in haystack for word in ("入职日期", "雇佣类型", "兼职", "每节", "单价")):
        return SourceType.PERSONNEL.value, {"signals": ["personnel_content"]}
    if "周" in haystack and any(word in haystack for word in ("周平均", "单科数", "班课生数", "总课次")):
        return SourceType.WEEKLY_REPORT.value, {"signals": ["weekly_report_content"]}
    signals.append("no_unique_content_signal")
    return SourceType.OTHER.value, {"signals": signals, "needs_confirmation": True}


# Backward/UX-friendly name used by the data-center API.
DataCenter = SourceRegistry
