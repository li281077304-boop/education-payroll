"""Minimal, source-preserving assessment field identification.

This adapter deliberately stops at explicit fields.  It does not approve,
score, deduct pay, or create a new assessment policy.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..models.evidence import AdapterIssue, AdapterResult
from .weekly_report import _column, _load_rows, _number, _text, _sheet_row_number


@dataclass(frozen=True)
class AssessmentReportRecord:
    period: str
    person: str
    month: str
    metric: str
    score: float | None
    amount: float | None
    status: str
    source_file: str
    sheet: str
    cell: str
    range: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def read_assessment_report(path: str | Path, period: str) -> AdapterResult[AssessmentReportRecord]:
    source = Path(path).expanduser().resolve()
    result: AdapterResult[AssessmentReportRecord] = AdapterResult()
    try:
        rows = _load_rows(source)
    except (OSError, ValueError) as exc:
        result.errors.append(AdapterIssue("UNREADABLE_ASSESSMENT", str(exc)))
        return result
    found = next((
        (index, sheet, [_text(value) for value in row])
        for index, (sheet, row) in enumerate(rows)
        if _is_assessment_header(row)
    ), None)
    if found is None:
        result.errors.append(AdapterIssue("UNRECOGNIZED_ASSESSMENT", "没有找到人员、指标或得分字段。"))
        return result
    header_index, sheet, headers = found
    person_col = _exact_column(headers, "人员", "教师", "姓名", "组长", "学科组", "校区")
    metric_col = _column(headers, "指标", "考核项目", "项目")
    score_col = _column(headers, "得分", "分数", "评分")
    amount_col = _column(headers, "金额", "奖励金额", "考核金额")
    status_col = _column(headers, "状态", "审核状态")
    month_col = _column(headers, "月份", "考核月份", "期间")
    if person_col is None:
        result.errors.append(AdapterIssue("ASSESSMENT_PERSON_MISSING", "考核表缺少人员字段。", sheet=sheet))
        return result
    for absolute_index, (row_sheet, row) in enumerate(rows[header_index + 1:], start=header_index + 1):
        if row_sheet != sheet or person_col >= len(row):
            continue
        row_number = _sheet_row_number(rows, absolute_index, sheet)
        person = _text(row[person_col])
        if not person or person in {"人员", "姓名", "合计"}:
            continue
        get = lambda index: row[index] if index is not None and index < len(row) else None
        base = {"period": period, "person": person, "month": _text(get(month_col)) or period,
                "status": _text(get(status_col)), "source_file": source.name, "sheet": sheet,
                "cell": f"{sheet}!{_col(person_col + 1)}{row_number}",
                "range": f"{sheet}!A{row_number}:{_col(len(headers))}{row_number}",
                "evidence": {"headers": headers, "row": row_number}}
        # A management/subject-group assessment has one row and several
        # explicit metric columns.  Preserve each numeric metric separately;
        # formulas or blanks remain visible as unpopulated, not as zero.
        metric_columns = [index for index, header in enumerate(headers)
                          if index != person_col and _is_metric_header(header)]
        if metric_columns:
            for index in metric_columns:
                value = _number(get(index))
                if value is None and not _text(get(index)):
                    continue
                result.records.append(AssessmentReportRecord(
                    **base, metric=_text(headers[index]), score=value,
                    amount=_number(get(amount_col)) if amount_col is not None else None,
                ))
        else:
            result.records.append(AssessmentReportRecord(
                **base, metric=_text(get(metric_col)), score=_number(get(score_col)),
                amount=_number(get(amount_col)) if amount_col is not None else None,
            ))
    result.coverage = {"records": len(result.records), "scores": sum(item.score is not None for item in result.records), "amounts": sum(item.amount is not None for item in result.records), "sheet": sheet, "recognized_fields": sum(value is not None for value in (person_col, metric_col, score_col, amount_col, status_col, month_col))}
    return result


def _normalized(value: Any) -> str:
    return _text(value).replace(" ", "")


def _exact_column(headers: list[str], *names: str) -> int | None:
    targets = {_normalized(name) for name in names}
    return next((index for index, header in enumerate(headers) if _normalized(header) in targets), None)


def _is_metric_header(value: Any) -> bool:
    text = _normalized(value)
    return bool(text) and any(token in text for token in ("总分", "进步率", "周平均", "续费", "续推", "退费", "离职率", "得分", "指标", "金额"))


def _is_assessment_header(row: list[Any]) -> bool:
    values = [_normalized(value) for value in row if _text(value)]
    has_person = any(value in {"人员", "教师", "姓名", "组长", "学科组", "校区"} for value in values)
    # Weekly/renewal summaries also contain “教师”“续费”“退费”.  Require a
    # real assessment marker, or the distinctive score-sheet combination, so
    # those operational reports are not duplicated as assessment records.
    explicit = any(value in {"指标", "考核项目", "得分", "评分", "考核金额"} for value in values)
    score_sheet = "总分" in values and any(
        any(token in value for token in ("进步率", "离职率", "周平均"))
        for value in values
    )
    return has_person and (explicit or score_sheet)


def _col(number: int) -> str:
    output = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        output = chr(65 + remainder) + output
    return output or "A"
