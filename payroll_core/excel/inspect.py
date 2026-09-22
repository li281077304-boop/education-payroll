from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Iterable
from zipfile import BadZipFile

import openpyxl

from ..models.evidence import AdapterIssue, AdapterResult


ZIP_MAGIC = b"PK\x03\x04"


@dataclass(frozen=True)
class SheetInspection:
    name: str
    max_row: int
    max_column: int
    hidden: bool
    merged_ranges: int
    hidden_rows: int
    hidden_columns: int
    formula_count: int
    external_formula_count: int
    formula_cache_missing: int
    comment_count: int
    data_validation_count: int
    header_candidates: tuple[tuple[int, tuple[str, ...]], ...]


@dataclass(frozen=True)
class WorkbookFingerprint:
    layout: str
    sheet_names: tuple[str, ...]
    matched_signals: tuple[str, ...]
    supported: bool


@dataclass(frozen=True)
class WorkbookInspection:
    source_file: str
    workbook_type: str
    fingerprint: WorkbookFingerprint
    sheets: tuple[SheetInspection, ...]
    defined_name_count: int
    external_link_count: int


def load_workbook_pair(path: str | Path):
    """Open OOXML or a genuine binary XLS workbook without altering it.

    A few WPS exports use an ``.xls`` suffix for OOXML, so OOXML remains the
    first path.  The xlrd fallback is intentionally a small read-only facade
    exposing the cell operations used by the existing adapters; it does not
    rewrite or convert the source workbook.
    """
    source = Path(path)
    payload = source.read_bytes()
    if payload.startswith(ZIP_MAGIC):
        return (
            openpyxl.load_workbook(BytesIO(payload), data_only=False, read_only=False, keep_links=True),
            openpyxl.load_workbook(BytesIO(payload), data_only=True, read_only=False, keep_links=True),
        )
    try:
        import xlrd
        return _xlrd_workbook_pair(payload)
    except (ImportError, OSError, ValueError, BadZipFile) as exc:
        raise ValueError("UNSUPPORTED_FILE_FORMAT: 仅支持可读取的 XLSX/XLS 工作簿。") from exc


class _XlrdCell:
    def __init__(self, value, coordinate: str = ""):
        self.value = value
        self.coordinate = coordinate
        self.comment = None


class _XlrdSheet:
    sheet_state = "visible"

    def __init__(self, sheet):
        self._sheet = sheet
        self.title = sheet.name
        self.max_row = sheet.nrows
        self.max_column = sheet.ncols
        self.merged_cells = type("Merged", (), {"ranges": ()})()
        self.row_dimensions = {}
        self.column_dimensions = {}
        self.data_validations = type("Validations", (), {"dataValidation": ()})()

    def cell(self, row: int, column: int) -> _XlrdCell:
        number = column
        letters = ""
        while number:
            number, remainder = divmod(number - 1, 26)
            letters = chr(65 + remainder) + letters
        return _XlrdCell(self._sheet.cell_value(row - 1, column - 1), f"{letters}{row}")

    def __getitem__(self, coordinate: str) -> _XlrdCell:
        """Provide the small coordinate lookup used by the inspector.

        ``openpyxl`` sheets support ``sheet["A1"]``; the binary-XLS facade
        must expose the same read-only seam so formula/cache inspection works
        for genuine XLS files as well as OOXML files with an ``.xls`` suffix.
        """
        match = re.fullmatch(r"([A-Za-z]+)([0-9]+)", str(coordinate))
        if not match:
            raise KeyError(coordinate)
        letters, row_text = match.groups()
        column = 0
        for char in letters.upper():
            column = column * 26 + ord(char) - ord("A") + 1
        return self.cell(int(row_text), column)

    def iter_rows(self):
        for row in range(self.max_row):
            yield tuple(self.cell(row + 1, column + 1) for column in range(self.max_column))


class _XlrdWorkbook:
    def __init__(self, book):
        self.worksheets = tuple(_XlrdSheet(book.sheet_by_index(index)) for index in range(book.nsheets))
        self.sheetnames = tuple(sheet.title for sheet in self.worksheets)
        self.defined_names = {}
        self._external_links = []

    def __getitem__(self, name: str) -> _XlrdSheet:
        return next(sheet for sheet in self.worksheets if sheet.title == name)


def _xlrd_workbook_pair(payload: bytes):
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=payload, on_demand=False)
    except Exception as exc:
        raise ValueError("不是可读取的二进制 XLS 工作簿。") from exc
    facade = _XlrdWorkbook(book)
    # Binary XLS has no separate formula cache exposed by this read-only path;
    # both views intentionally contain the values xlrd can safely provide.
    return facade, facade


def detect_fingerprint(workbook) -> WorkbookFingerprint:
    names = tuple(workbook.sheetnames)
    signals: list[str] = []
    if "排课记录" in names and "工资核对" in names:
        schedule_headers = _header_texts(workbook["排课记录"], rows=range(1, 4))
        check_headers = _header_texts(workbook["工资核对"], rows=range(1, 4))
        if {"任课老师", "课程所属班型", "实到人数"}.issubset(schedule_headers) and {"填报", "差值", "班课"}.issubset(check_headers):
            signals.extend(["排课记录", "工资核对", "核对表头"])
            return WorkbookFingerprint("PAYROLL_CHECK_V1", names, tuple(signals), True)
    for sheet_name in names:
        headers = _header_texts(workbook[sheet_name], rows=range(1, 8))
        # A near match is still a schedule layout. The schedule adapter must then
        # report the exact missing required columns instead of treating it as opaque.
        if {"上课班级", "教学形式", "上课时间", "上课状态", "任课老师"}.issubset(headers):
            return WorkbookFingerprint("SCHEDULE_EXPORT_V1", names, (f"sheet:{sheet_name}", "schedule_headers"), True)
        if {"姓名", "最终授课小时数据", "该档每小时金额", "总课时费", "总工资数"}.issubset(headers):
            return WorkbookFingerprint("PAYROLL_SHEET_V1", names, (f"sheet:{sheet_name}", "payroll_headers"), True)
        if {"学科组", "教师", "1V1课时", "总计"}.issubset(headers):
            return WorkbookFingerprint("RENEWAL_2026_V1", names, (f"sheet:{sheet_name}", "renewal_headers"), True)
    return WorkbookFingerprint("UNSUPPORTED_LAYOUT", names, (), False)


def inspect_workbook(path: str | Path) -> AdapterResult[WorkbookInspection]:
    result: AdapterResult[WorkbookInspection] = AdapterResult()
    try:
        raw, cached = load_workbook_pair(path)
    except (OSError, ValueError, openpyxl.utils.exceptions.InvalidFileException) as exc:
        result.errors.append(AdapterIssue("UNSUPPORTED_FILE_FORMAT", str(exc)))
        return result
    fingerprint = detect_fingerprint(raw)
    if not fingerprint.supported:
        result.errors.append(AdapterIssue("UNSUPPORTED_LAYOUT", "Workbook did not match a supported payroll layout"))
    sheets = tuple(_inspect_sheet(raw[name], cached[name]) for name in raw.sheetnames)
    result.records.append(
        WorkbookInspection(
            source_file=str(path),
            workbook_type="XLS" if isinstance(raw, _XlrdWorkbook) else "OOXML",
            fingerprint=fingerprint,
            sheets=sheets,
            defined_name_count=len(raw.defined_names),
            external_link_count=len(raw._external_links),
        )
    )
    return result


def _inspect_sheet(raw_sheet, cached_sheet) -> SheetInspection:
    formula_count = external_count = missing_cache = comment_count = 0
    for row in raw_sheet.iter_rows():
        for cell in row:
            if cell.comment is not None:
                comment_count += 1
            if isinstance(cell.value, str) and cell.value.startswith("="):
                formula_count += 1
                if "[" in cell.value:
                    external_count += 1
                if cached_sheet[cell.coordinate].value is None:
                    missing_cache += 1
    headers = tuple(
        (row, tuple(sorted(_row_texts(raw_sheet, row))))
        for row in range(1, min(raw_sheet.max_row, 8) + 1)
        if _row_texts(raw_sheet, row)
    )
    return SheetInspection(
        name=raw_sheet.title,
        max_row=raw_sheet.max_row,
        max_column=raw_sheet.max_column,
        hidden=raw_sheet.sheet_state != "visible",
        merged_ranges=len(raw_sheet.merged_cells.ranges),
        hidden_rows=sum(1 for dimension in raw_sheet.row_dimensions.values() if dimension.hidden),
        hidden_columns=sum(1 for dimension in raw_sheet.column_dimensions.values() if dimension.hidden),
        formula_count=formula_count,
        external_formula_count=external_count,
        formula_cache_missing=missing_cache,
        comment_count=comment_count,
        data_validation_count=len(raw_sheet.data_validations.dataValidation),
        header_candidates=headers,
    )


def _header_texts(sheet, rows: Iterable[int]) -> set[str]:
    return {value for row in rows for value in _row_texts(sheet, row)}


def _row_texts(sheet, row: int) -> set[str]:
    return {
        str(sheet.cell(row, column).value).strip().replace("\n", " ")
        for column in range(1, sheet.max_column + 1)
        if sheet.cell(row, column).value is not None
        and not (isinstance(sheet.cell(row, column).value, str) and sheet.cell(row, column).value.startswith("="))
    }
