"""Read the authoritative 人工月 / 工资周期 rows out of a company document.

The company publishes its 人工月 (salary cycle) calendar inside a regulation
document.  That document is the authority; this module only *reads* it.  The
same reader handles the three shapes the office actually has:

* a Markdown table (``杰牛集团规章制度知识库.md`` and similar),
* an exported CSV / TSV,
* an Excel sheet.

Nothing here writes payroll state — the caller stages a preview and asks a human
to confirm before any authority record is created.

Two facts are derived, and both are shown to the user before confirmation:

* the actual ``period_start`` / ``period_end`` of each 人工月;
* which payroll month (``YYYY-MM``) that cycle belongs to, derived as the month
  holding the most days of the cycle.  A 4/5-week cycle never splits two months
  evenly, so the answer is unambiguous, but the rule stays explicit and visible
  instead of being an implicit assumption.
"""
from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from payroll_core.period import SOURCE_TYPE_CSV, SOURCE_TYPE_DOCUMENT, SOURCE_TYPE_EXCEL

# Column names the office documents use.  Matching is "contains", so
# "人工月 序号" or "工资月份（YYYY-MM）" both work.
LABEL_COLUMN_NAMES = ("人工月", "序号", "月份", "周期序号", "周期")
RANGE_COLUMN_NAMES = ("日期范围", "起止日期", "时间范围", "起止", "周期日期", "日期")
WEEKS_COLUMN_NAMES = ("周数", "周")
PAYROLL_COLUMN_NAMES = ("工资月份", "核算月份", "薪资月份", "工资月")

_YEAR_PATTERN = re.compile(r"(20\d{2})\s*年")
_DATE_TOKEN = re.compile(r"(?:(20\d{2})\s*[年./\-]\s*)?(\d{1,2})\s*[月./\-]\s*(\d{1,2})\s*日?")
_RANGE_SEPARATOR = re.compile(r"—|–|~|～|至|到|\s-\s|\s--\s")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEPARATOR_ROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.、])\s*")


@dataclass(frozen=True)
class PeriodDocumentRow:
    label: str
    weeks: str
    period_start: str
    period_end: str
    payroll_period: str
    mapping_rule: str
    source_section: str
    source_row: int
    source_text: str
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "weeks": self.weeks,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "payroll_period": self.payroll_period,
            "mapping_rule": self.mapping_rule,
            "source_section": self.source_section,
            "source_row": self.source_row,
            "source_text": self.source_text,
            "problems": list(self.problems),
        }


@dataclass(frozen=True)
class PeriodDocument:
    source_type: str
    source_file: str
    source_sha256: str
    source_size: int
    title: str
    year: int | None
    rows: tuple[PeriodDocumentRow, ...] = ()
    problems: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def can_import(self) -> bool:
        return bool(self.rows) and not self.problems and all(row.ok for row in self.rows)

    def as_preview(self) -> dict:
        return {
            "source": {
                "source_type": self.source_type,
                "source_file": self.source_file,
                "sha256": self.source_sha256,
                "size": self.source_size,
            },
            "title": self.title,
            "year": self.year,
            "rows": [row.as_dict() for row in self.rows],
            "problems": list(self.problems) + [
                f"第 {row.source_row} 行（人工月 {row.label or '?'}）：{'；'.join(row.problems)}"
                for row in self.rows if row.problems
            ],
            "notes": list(self.notes),
            "can_import": self.can_import,
        }


def read_period_document(path: str | Path, *, year: int | None = None) -> PeriodDocument:
    """Read one authoritative 人工月 document without modifying anything."""
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError("找不到人工月资料文件，请确认路径后重试。")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    suffix = source.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        source_type = SOURCE_TYPE_DOCUMENT
        text = source.read_text(encoding="utf-8")
        tables = _tables_from_markdown(text)
        title = _document_title(text)
        year = year or _year_from_document(text)
        notes = _cycle_notes(text)
    elif suffix in {".csv", ".tsv"}:
        source_type = SOURCE_TYPE_CSV
        text = source.read_text(encoding="utf-8-sig")
        tables = _tables_from_delimited(text, "\t" if suffix == ".tsv" else ",")
        title = source.stem
        year = year or _year_from_document(text)
        notes = ()
    elif suffix in {".xlsx", ".xlsm", ".xls"}:
        source_type = SOURCE_TYPE_EXCEL
        tables = _tables_from_workbook(source)
        title = source.stem
        year = year or _year_from_document(" ".join(table.section for table in tables))
        notes = ()
    else:
        raise ValueError("人工月资料只支持 Markdown、CSV 或 Excel 文件。")

    rows: list[PeriodDocumentRow] = []
    problems: list[str] = []
    for table in tables:
        if not _looks_like_period_table(table.header):
            continue
        table_year = year or _year_from_document(table.section)
        columns = _resolve_columns(table.header)
        for raw in table.rows:
            rows.append(_row_from_cells(raw, columns, table_year, table.header))

    if not rows:
        problems.append("没有在资料里找到人工月表格（需要包含“人工月”和“日期范围”两列）。")
    elif any(not row.period_start or not row.period_end for row in rows):
        problems.append("有日期范围无法识别或缺少年份，请按“8.03 — 8.30”并在标题写明年份。")
    rows = list(_mark_duplicate_months(rows))

    return PeriodDocument(
        source_type=source_type,
        source_file=source.name,
        source_sha256=digest,
        source_size=source.stat().st_size,
        title=title or source.stem,
        year=year,
        rows=tuple(rows),
        problems=tuple(problems),
        notes=tuple(notes),
    )


# --------------------------------------------------------------------------- readers


@dataclass(frozen=True)
class _RawRow:
    cells: tuple[str, ...]
    section: str
    line: int
    text: str


@dataclass(frozen=True)
class _Table:
    header: tuple[str, ...]
    rows: tuple[_RawRow, ...]
    section: str
    first_line: int


def _tables_from_markdown(text: str) -> list[_Table]:
    lines = text.splitlines()
    tables: list[_Table] = []
    section = ""
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.lstrip().startswith("#"):
            section = line.lstrip("# ").strip()
        if _TABLE_ROW.match(line) and index + 1 < len(lines) and _SEPARATOR_ROW.match(lines[index + 1]):
            header = tuple(_split_table_row(line))
            body: list[_RawRow] = []
            cursor = index + 2
            while cursor < len(lines) and _TABLE_ROW.match(lines[cursor]):
                body.append(_RawRow(tuple(_split_table_row(lines[cursor])), section, cursor + 1, lines[cursor].strip()))
                cursor += 1
            tables.append(_Table(header, tuple(body), section, index + 1))
            index = cursor
            continue
        index += 1
    return tables


def _tables_from_delimited(text: str, delimiter: str) -> list[_Table]:
    rows = [
        (number, tuple(str(cell).strip() for cell in cells), delimiter.join(cells))
        for number, cells in enumerate(csv.reader(text.splitlines(), delimiter=delimiter), start=1)
        if any(str(cell).strip() for cell in cells)
    ]
    if not rows:
        return []
    first_number, first_cells, _ = rows[0]
    # A headerless export must not lose its first cycle to a fake header.
    if _header_has_period_names(first_cells):
        header, body, first_line = first_cells, rows[1:], first_number
    else:
        header, body, first_line = tuple("" for _ in first_cells), rows, first_number
    return [_Table(header, tuple(_RawRow(cells, "", number, line) for number, cells, line in body), "", first_line)]


def _tables_from_workbook(path: Path) -> list[_Table]:
    from openpyxl import load_workbook

    workbook = load_workbook(path, read_only=True, data_only=True)
    tables: list[_Table] = []
    try:
        for sheet in workbook.worksheets:
            collected: list[tuple[int, tuple[str, ...], str]] = []
            for number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = tuple("" if value is None else str(value).strip() for value in values)
                if any(cells):
                    collected.append((number, cells, " | ".join(cells)))
            if not collected:
                continue
            header_index = _first_period_header(collected)
            if header_index is None:
                continue
            number, header, _ = collected[header_index]
            body = tuple(
                _RawRow(cells, str(sheet.title or ""), row_number, text)
                for row_number, cells, text in collected[header_index + 1:]
            )
            tables.append(_Table(header, body, str(sheet.title or ""), number))
    finally:
        workbook.close()
    return tables


def _first_period_header(rows: list[tuple[int, tuple[str, ...], str]]) -> int | None:
    for position, (_number, cells, _text) in enumerate(rows[:10]):
        if any(name in cell for cell in cells for name in LABEL_COLUMN_NAMES) and any(
            name in cell for cell in cells for name in RANGE_COLUMN_NAMES
        ):
            return position
    return None


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _header_has_period_names(header: tuple[str, ...]) -> bool:
    joined = " ".join(header)
    return any(name in joined for name in LABEL_COLUMN_NAMES) and any(name in joined for name in RANGE_COLUMN_NAMES)


def _looks_like_period_table(header: tuple[str, ...]) -> bool:
    """Only tables that really are the 人工月 calendar may be parsed.

    The regulation document is full of unrelated tables (SOC flows, targets,
    weekly reports).  A table without any column names is accepted only when it
    is a headerless 2–3 column export — never because it happens to have three
    text columns.
    """
    if _header_has_period_names(header):
        return True
    return len(header) in {2, 3, 4} and all(not str(cell).strip() for cell in header)


def _find(header: tuple[str, ...], names: tuple[str, ...], exclude: set[int]) -> int:
    for index, cell in enumerate(header):
        if index in exclude:
            continue
        if any(name in str(cell) for name in names):
            return index
    return -1


@dataclass(frozen=True)
class _Columns:
    label: int
    weeks: int
    period_range: int
    payroll_period: int


def _resolve_columns(header: tuple[str, ...]) -> _Columns:
    payroll = _find(header, PAYROLL_COLUMN_NAMES, set())
    label = _find(header, LABEL_COLUMN_NAMES, {payroll})
    weeks = _find(header, WEEKS_COLUMN_NAMES, {payroll, label})
    period_range = _find(header, RANGE_COLUMN_NAMES, {payroll, label, weeks})
    if label < 0:
        label = 0
    if period_range < 0:
        period_range = 2 if len(header) >= 3 else 1
    return _Columns(label=label, weeks=weeks, period_range=period_range, payroll_period=payroll)


def _year_from_document(text: str) -> int | None:
    """The year the 人工月 table is built for.

    Taken from the heading/title when possible — a regulation document also
    mentions other years (amendment dates, other chapters), so the *largest*
    year in the file would be wrong.
    """
    for line in text.splitlines():
        if "人工月" in line:
            match = _YEAR_PATTERN.search(line)
            if match:
                return int(match.group(1))
    match = _YEAR_PATTERN.search(text)
    return int(match.group(1)) if match else None


def _document_title(text: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith("#"):
            return line.lstrip("# ").strip()
    return ""


def _cycle_notes(text: str) -> list[str]:
    notes = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("|"):
            continue
        candidate = LIST_MARKER.sub("", stripped.lstrip("> ").strip())
        if ("人工月" in candidate or "周期" in candidate) and len(candidate) <= 80:
            notes.append(candidate)
    return notes[:4]


# --------------------------------------------------------------------------- rows


def _row_from_cells(raw: _RawRow, columns: _Columns, year: int | None, header: tuple[str, ...]) -> PeriodDocumentRow:
    problems: list[str] = []
    cells = raw.cells

    def cell(index: int) -> str:
        return str(cells[index]).strip() if 0 <= index < len(cells) else ""

    label = re.sub(r"[*`\s]", "", cell(columns.label))
    weeks = re.sub(r"[*`]", "", cell(columns.weeks)) if columns.weeks >= 0 else ""
    payroll_hint = cell(columns.payroll_period) if columns.payroll_period >= 0 else ""
    start, end, date_problems = _parse_range(cell(columns.period_range), year)
    problems.extend(date_problems)
    payroll_period, rule = _payroll_period_for(start, end)
    if not label:
        problems.append("没有识别到人工月序号。")
    return PeriodDocumentRow(
        label=label, weeks=weeks, period_start=start, period_end=end,
        payroll_period=payroll_hint or payroll_period,
        mapping_rule="按资料中直接给出的工资月份" if payroll_hint else rule,
        source_section=raw.section, source_row=raw.line, source_text=raw.text,
        problems=tuple(problems),
    )


def _parse_range(value: str, year: int | None) -> tuple[str, str, list[str]]:
    parts = [part for part in _RANGE_SEPARATOR.split(value) if part.strip()]
    tokens = [token for token in (_DATE_TOKEN.search(part) for part in parts) if token]
    if len(tokens) < 2:
        return "", "", ["无法识别日期范围，请使用如 8.03 — 8.30 的写法。"]
    start_token, end_token = tokens[0], tokens[-1]
    start = _iso_date(start_token, int(start_token.group(1)) if start_token.group(1) else year)
    end_year = int(end_token.group(1)) if end_token.group(1) else year
    end = _iso_date(end_token, end_year)
    if not start or not end:
        return "", "", ["日期范围缺少年份，请在资料标题或该行写明年份。"]
    if end < start:
        # A cycle may cross the new year (for example 11.30 — 1.03).
        end = _iso_date(end_token, int(end[:4]) + 1)
    if not end or end < start:
        return "", "", ["日期范围的结束日期早于开始日期，请核对资料。"]
    return start, end, []


def _iso_date(token: re.Match[str], year: int | None) -> str:
    explicit, month, day = token.group(1), int(token.group(2)), int(token.group(3))
    effective_year = int(explicit) if explicit else year
    if effective_year is None or not 1 <= month <= 12:
        return ""
    try:
        return date(effective_year, month, day).isoformat()
    except ValueError:
        return ""


def _payroll_period_for(start: str, end: str) -> tuple[str, str]:
    """Which payroll month a cycle belongs to: the month holding most days."""
    if not start or not end:
        return "", ""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    counts: dict[str, int] = {}
    cursor = first
    while cursor <= last:
        key = f"{cursor.year:04d}-{cursor.month:02d}"
        counts[key] = counts.get(key, 0) + 1
        cursor += timedelta(days=1)
    if not counts:
        return "", ""
    best = max(counts.values())
    winners = sorted(month for month, count in counts.items() if count == best)
    return winners[0], "按周期内天数最多的月份归属工资月份"


def _mark_duplicate_months(rows: list[PeriodDocumentRow]) -> tuple[PeriodDocumentRow, ...]:
    counts: dict[str, int] = {}
    for row in rows:
        if row.payroll_period:
            counts[row.payroll_period] = counts.get(row.payroll_period, 0) + 1
    marked = []
    for row in rows:
        if row.payroll_period and counts.get(row.payroll_period, 0) > 1:
            marked.append(PeriodDocumentRow(
                label=row.label, weeks=row.weeks, period_start=row.period_start, period_end=row.period_end,
                payroll_period=row.payroll_period, mapping_rule=row.mapping_rule,
                source_section=row.source_section, source_row=row.source_row, source_text=row.source_text,
                problems=tuple(row.problems) + ("同一个月出现了多条人工月，无法自动判断，请核对资料。",),
            ))
        else:
            marked.append(row)
    return tuple(marked)
