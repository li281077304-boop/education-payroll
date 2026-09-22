"""Semantic field mapping: which Excel column carries which business field?

Precision beats convenience. A field is mapped automatically only when exactly
one column clearly carries it; two plausible columns always become a question
for the user, never a silent guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..excel.common import GRADE_TOKENS
from ..excel.inspect import load_workbook_pair
from .requirements import ImportRequirement


STRONG_SCORE = 0.75
CANDIDATE_SCORE = 0.4
HEADER_SEARCH_ROWS = 15
SAMPLE_ROWS = 40

SUBJECT_VOCAB = ("语文", "数学", "英语", "物理", "化学", "生物", "政治", "历史", "地理", "科学", "奥数", "雅思", "托福")
CLASS_TYPE_VOCAB = ("一对一", "1对1", "一对多", "1对2", "小班", "集体班", "班课", "大班", "6人班", "8人班", "10人班", "10人以下", "线上课", "线下课")


@dataclass(frozen=True)
class ColumnCandidate:
    header: str
    column: int
    score: float


@dataclass(frozen=True)
class MappingAnalysis:
    status: str                              # MAPPED | NEEDS_CONFIRMATION | MISSING_REQUIRED | UNREADABLE
    sheet: str = ""
    header_row: int = 0
    fingerprint: str = ""
    mapping: Mapping[str, int] = field(default_factory=dict)
    mapped_headers: Mapping[str, str] = field(default_factory=dict)
    candidates: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    missing: tuple[str, ...] = ()
    detected_columns: tuple[str, ...] = ()
    column_headers: Mapping[int, str] = field(default_factory=dict)
    profile_id: str = ""
    profile_drift: bool = False
    message: str = ""

    @property
    def ready(self) -> bool:
        return self.status == "MAPPED"


def normalize_header(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", "").replace("\r", "").replace("\t", "")
    text = text.replace("（", "(").replace("）", ")").replace("：", ":").replace("，", ",")
    text = re.sub(r"[\s\.\*:：]+", "", text)
    return text.strip().lower()


def fingerprint_for(headers: Iterable[str]) -> str:
    normalized = sorted({normalize_header(item) for item in headers if normalize_header(item)})
    return sha256("|".join(normalized).encode("utf-8")).hexdigest()[:24]


def _column_values(sheet, column: int, first_data_row: int, limit: int = SAMPLE_ROWS) -> list[Any]:
    values: list[Any] = []
    for row in range(first_data_row, min(sheet.max_row, first_data_row + limit - 1) + 1):
        values.append(sheet.cell(row, column).value)
    return values


def _numeric_ratio(values: Sequence[Any]) -> float:
    present = [item for item in values if item not in (None, "")]
    if not present:
        return 0.0
    numeric = sum(1 for item in present if isinstance(item, (int, float)) or str(item).strip().replace(".", "", 1).isdigit())
    return numeric / len(present)


def _token_ratio(values: Sequence[Any], tokens: Iterable[str]) -> float:
    present = [str(item) for item in values if item not in (None, "")]
    if not present:
        return 0.0
    hits = sum(1 for item in present if any(token in item for token in tokens))
    return hits / len(present)


def _name_like_ratio(values: Sequence[Any]) -> float:
    present = [str(item).strip() for item in values if item not in (None, "")]
    if not present:
        return 0.0
    hits = sum(1 for item in present if re.fullmatch(r"[\u4e00-\u9fa5]{2,4}", item))
    return hits / len(present)


def _kind_boost(kind: str, values: Sequence[Any]) -> float:
    if kind == "count":
        return 0.25 if _numeric_ratio(values) >= 0.8 else 0.0
    if kind == "grade":
        return 0.3 if _token_ratio(values, GRADE_TOKENS) >= 0.5 else 0.0
    if kind == "class_type":
        return 0.3 if _token_ratio(values, CLASS_TYPE_VOCAB) >= 0.6 else 0.0
    if kind == "subject":
        return 0.3 if _token_ratio(values, SUBJECT_VOCAB) >= 0.5 else 0.0
    return 0.25 if _name_like_ratio(values) >= 0.6 else 0.0


def _header_score(header: str, aliases: Sequence[str], weak_tokens: Sequence[str]) -> float:
    if not header:
        return 0.0
    for alias in aliases:
        if header == normalize_header(alias):
            return 1.0
    for alias in aliases:
        token = normalize_header(alias)
        if len(token) >= 2 and token in header:
            return 0.7
    for token in weak_tokens:
        if normalize_header(token) in header:
            return 0.5
    return 0.0


def _best_header_row(sheet, requirement: ImportRequirement) -> tuple[int, int]:
    """Return (header_row, strong_hits) for the row that looks most like headers."""
    best_row, best_strong, best_total = 0, 0, 0
    for row in range(1, min(HEADER_SEARCH_ROWS, sheet.max_row) + 1):
        strong = total = 0
        for column in range(1, sheet.max_column + 1):
            header = normalize_header(sheet.cell(row, column).value)
            if not header:
                continue
            for item in requirement.fields:
                score = _header_score(header, item.aliases, item.weak_tokens)
                if score >= 1.0:
                    strong += 1
                    total += 2
                    break
                if score > 0:
                    total += 1
                    break
        if (strong, total) > (best_strong, best_total):
            best_row, best_strong, best_total = row, strong, total
    return best_row, best_strong


def analyze_mapping(
    path: str | Path,
    requirement: ImportRequirement,
    *,
    profiles: Iterable[Mapping[str, Any]] = (),
) -> MappingAnalysis:
    """Recognize the sheet, its header row and the columns carrying each field."""
    source = Path(path)
    try:
        # Read through BytesIO: real exports are often OOXML content inside a
        # .xls filename, which openpyxl refuses when handed a path.
        workbook, _cached_workbook = load_workbook_pair(source)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, never hidden
        return MappingAnalysis(status="UNREADABLE", message=f"无法读取文件：{source.name}（{type(exc).__name__}: {exc}）")
    try:
        best = max(workbook.worksheets, key=lambda sheet: _best_header_row(sheet, requirement)[1])
        header_row, strong_hits = _best_header_row(best, requirement)
        if not header_row or not strong_hits:
            return MappingAnalysis(
                status="MISSING_REQUIRED", sheet=best.title,
                detected_columns=tuple(str(best.cell(1, column).value or "") for column in range(1, best.max_column + 1) if best.cell(1, column).value),
                missing=tuple(item.field for item in requirement.required_fields),
                message="这张表里没有识别到任何已知字段表头。",
            )
        headers = {column: str(best.cell(header_row, column).value or "").strip() for column in range(1, best.max_column + 1)}
        fingerprint = fingerprint_for(headers.values())

        # A confirmed profile is reused, but never trusted blindly: every mapped
        # column must still exist, or the user is asked again.
        drift = False
        profile_id = ""
        profile = next((item for item in profiles if item.get("fingerprint") == fingerprint), None)
        if profile:
            profile_id = str(profile.get("id", ""))
            recorded = profile.get("headers") or {}
            mapped: dict[str, int] = {}
            for field, column in (profile.get("mapping") or {}).items():
                column = int(column)
                current = headers.get(column, "")
                expected = recorded.get(field, "")
                # The column must still exist AND still carry the same header:
                # a reordered sheet keeps the same headers but moves them, and
                # silently reusing the old index would read the wrong column.
                if not current or (expected and normalize_header(current) != normalize_header(expected)):
                    drift = True
                    continue
                mapped[field] = column
            drift = drift or any(item.field not in mapped for item in requirement.required_fields) or len(mapped) != len(profile.get("mapping") or {})
            if not drift:
                return MappingAnalysis(
                    status="MAPPED", sheet=best.title, header_row=header_row, fingerprint=fingerprint,
                    mapping=mapped, mapped_headers={field: headers[column] for field, column in mapped.items()},
                    detected_columns=tuple(item for item in headers.values() if item),
                    column_headers={column: text for column, text in headers.items() if text}, profile_id=profile_id,
                )

        candidates_by_field: dict[str, list[ColumnCandidate]] = {}
        for item in requirement.fields:
            scored: list[ColumnCandidate] = []
            for column, header in headers.items():
                base = _header_score(normalize_header(header), item.aliases, item.weak_tokens)
                if not base:
                    continue
                boost = _kind_boost(item.kind, _column_values(best, column, header_row + 1))
                # A weak-token guess (for example 班级人数 for 实到人数) may become
                # a candidate, but it can never be strong enough to be chosen
                # silently: only a real alias may auto-map.
                ceiling = 1.0 if base > 0.5 else 0.7
                scored.append(ColumnCandidate(header, column, round(min(ceiling, base + boost), 4)))
            candidates_by_field[item.field] = sorted(scored, key=lambda entry: (-entry.score, entry.column))

        mapping: dict[str, int] = {}
        mapped_headers: dict[str, str] = {}
        ambiguous: dict[str, tuple[str, ...]] = {}
        missing_fields: list[str] = []
        used: set[int] = set()
        for item in requirement.fields:
            options = [entry for entry in candidates_by_field.get(item.field, []) if entry.column not in used]
            viable = [entry for entry in options if entry.score >= CANDIDATE_SCORE]
            if len(viable) == 1 and viable[0].score >= STRONG_SCORE:
                chosen = viable[0]
                mapping[item.field] = chosen.column
                mapped_headers[item.field] = chosen.header
                used.add(chosen.column)
            elif viable and item.required:
                ambiguous[item.field] = tuple(entry.header for entry in viable)
            elif item.required:
                missing_fields.append(item.field)

        if drift:
            status = "NEEDS_CONFIRMATION"
        elif ambiguous:
            status = "NEEDS_CONFIRMATION"
        elif missing_fields:
            status = "MISSING_REQUIRED"
        else:
            status = "MAPPED"
        message = "已确认格式的列发生变化，需要重新确认字段。" if drift else ""
        if missing_fields and not drift:
            message = "缺少必要字段：" + "、".join(requirement.field(name).label for name in missing_fields)
        return MappingAnalysis(
            status=status, sheet=best.title, header_row=header_row, fingerprint=fingerprint,
            mapping=mapping, mapped_headers=mapped_headers, candidates=ambiguous,
            missing=tuple(missing_fields), detected_columns=tuple(item for item in headers.values() if item),
            column_headers={column: text for column, text in headers.items() if text},
            profile_id=profile_id, profile_drift=drift, message=message,
        )
    finally:
        if hasattr(workbook, "close"):
            workbook.close()
