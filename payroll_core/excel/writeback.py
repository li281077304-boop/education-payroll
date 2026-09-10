"""Safe, preview-first Excel comment writeback.

The source workbook is read only. Approved candidates are applied to a newly
created workbook and then re-opened to verify both comments and formulas.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.comments import Comment


@dataclass(frozen=True)
class WritebackPreview:
    sheet: str
    cell: str
    before_comment: str
    proposed_comment: str
    strategy: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def preview(source: str | Path, candidates: Iterable[dict], *, strategy: str = "APPEND") -> list[WritebackPreview]:
    if strategy not in {"KEEP_EXISTING", "APPEND", "REPLACE_CONFIRMED"}:
        raise ValueError("未知已有批注处理方式。")
    workbook = load_workbook(source, data_only=False, read_only=False, keep_links=True)
    views: list[WritebackPreview] = []
    effective: dict[tuple[str, str], str] = {}
    for candidate in candidates:
        sheet = workbook[candidate["sheet"]]
        existing = sheet[candidate["cell"]].comment
        key = (candidate["sheet"], candidate["cell"])
        before = effective.get(key, existing.text if existing else "")
        proposed = str(candidate["content"])
        if before and strategy == "KEEP_EXISTING":
            proposed = before
        elif before and strategy == "APPEND":
            proposed = before.rstrip() + "\n\n" + proposed
        effective[key] = proposed
        views.append(WritebackPreview(candidate["sheet"], candidate["cell"], before, proposed, strategy))
    return views


def write_new_workbook(source: str | Path, output: str | Path, candidates: Iterable[dict], *, strategy: str = "APPEND", author: str = "工资核算助手") -> list[WritebackPreview]:
    source_path, output_path = Path(source), Path(output)
    if source_path.resolve() == output_path.resolve():
        raise ValueError("回填必须输出为新文件，不能覆盖原工资表。")
    if output_path.exists():
        raise ValueError("输出文件已存在，请选择新的文件名。")
    if source_path.suffix.lower() == ".xlsm":
        raise ValueError("当前版本不能可靠保留 XLSM 宏，拒绝回填。")
    if not source_path.is_file():
        raise ValueError("找不到原工资表。")
    items = list(candidates)
    if not items:
        raise ValueError("没有已确认的批注候选。")
    preview_rows = preview(source_path, items, strategy=strategy)
    original_hash = sha256(source_path)
    for item in items:
        expected = item.get("source_file_hash", "")
        if expected and expected != original_hash:
            raise ValueError("原工资表已变化，批注候选需要重新确认。")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, output_path)
    source_book = load_workbook(source_path, data_only=False, read_only=False, keep_links=True)
    book = load_workbook(output_path, data_only=False, read_only=False, keep_links=True)
    final_comments = {(row.sheet, row.cell): row.proposed_comment for row in preview_rows}
    for (sheet, cell), content in final_comments.items():
        book[sheet][cell].comment = Comment(content, author)
    book.save(output_path)
    verified = load_workbook(output_path, data_only=False, read_only=False, keep_links=True)
    for (sheet, cell), content in final_comments.items():
        actual = verified[sheet][cell].comment
        if actual is None or actual.text != content:
            raise ValueError("回填后的批注无法验证。")
    if [sheet.title for sheet in source_book.worksheets] != [sheet.title for sheet in verified.worksheets]:
        raise ValueError("回填意外改变了工作表结构。")
    target_cells = set(final_comments)
    for source_sheet, result_sheet in zip(source_book.worksheets, verified.worksheets, strict=True):
        if tuple(str(rng) for rng in source_sheet.merged_cells.ranges) != tuple(str(rng) for rng in result_sheet.merged_cells.ranges):
            raise ValueError(f"回填意外改变了合并单元格：{source_sheet.title}")
        for source_row in source_sheet.iter_rows():
            for cell in source_row:
                result = result_sheet[cell.coordinate]
                if (source_sheet.title, cell.coordinate) not in target_cells and result.value != cell.value:
                    raise ValueError(f"回填意外改变了单元格值：{source_sheet.title}!{cell.coordinate}")
                if isinstance(cell.value, str) and cell.value.startswith("=") and result.value != cell.value:
                    raise ValueError(f"回填意外改变了公式：{source_sheet.title}!{cell.coordinate}")
    return preview_rows
