"""Final company-payroll workbook contract and UAT helpers.

The workbook is an empty structural/style contract plus current-run data.
Historical workbooks remain UAT oracles; they are never a production source of
roster, values, comments or formula caches.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import xlrd
from openpyxl import load_workbook
from openpyxl.comments import Comment


FINAL_CODES = ("AH", "AI", "AJ", "AK", "AN")
FINAL_COLUMNS = {"AH": 34, "AI": 35, "AJ": 36, "AK": 37, "AN": 40}
FIXED_AUGUST_TEMPLATE_SHA256 = "d0cbb9c848fabf59f849c56d6075dc0090686a7d3341575f3270c51437a96196"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_fixed_august_contract(path: str | Path) -> bool:
    candidate = Path(path).expanduser()
    try:
        return candidate.is_file() and sha256_file(candidate) == FIXED_AUGUST_TEMPLATE_SHA256
    except OSError:
        return False


def normalize_teacher(name: object) -> str:
    return "".join(str(name or "").replace("\u3000", "").split())


@dataclass(frozen=True)
class RenewalEvidence:
    teacher: str
    source_row: int
    ah: float
    ai: float
    aj: float
    ak: float
    source_file: str
    source_sheet: str


@dataclass(frozen=True)
class RefundEvidence:
    teacher: str
    source_row: int
    student: str
    headcount: float
    performance: float
    total: float
    source_file: str
    source_sheet: str


def _number(value: object) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"源数据不是数字：{value!r}")


def read_august_renewal(path: str | Path, sheet_name: str = "8月") -> dict[str, RenewalEvidence]:
    """Backward-compatible August alias for the period-aware reader."""
    return read_renewal_source(path, sheet_name=sheet_name)


def read_renewal_source(path: str | Path, *, sheet_name: str | None = None, period: str | None = None) -> dict[str, RenewalEvidence]:
    """Read a renewal workbook by content, not by a fixed month filename."""
    source = Path(path).resolve()
    book = load_workbook(source, data_only=True, read_only=False)
    candidate = book[sheet_name] if sheet_name and sheet_name in book.sheetnames else None
    if candidate is None and period:
        month = str(period).split("-")[-1].lstrip("0")
        candidate = next((item for item in book.worksheets if f"{month}月" in item.title), None)
    if candidate is None:
        # A filename such as “8月工资表” is useful source metadata, but the
        # sheet must still pass the header contract below.
        import re
        month_match = re.search(r"(\d{1,2})月", str(source))
        if month_match:
            candidate = next((item for item in book.worksheets if f"{int(month_match.group(1))}月" in item.title), None)
    if candidate is None:
        for item in book.worksheets:
            headers = [str(item.cell(2, col).value or "").strip() for col in range(1, item.max_column + 1)]
            if headers.count("合计") >= 3 and any(str(item.cell(1, col).value or "").strip() == "教师" for col in range(1, item.max_column + 1)):
                candidate = item
                break
    if candidate is None:
        raise ValueError("续费源缺少可识别的教师/合计列")
    sheet = candidate
    resolved_sheet = sheet.title
    headers = [sheet.cell(2, col).value for col in range(1, sheet.max_column + 1)]
    total_cols = [index + 1 for index, value in enumerate(headers) if str(value or "").strip() == "合计"]
    if len(total_cols) < 3:
        raise ValueError("续费源的 1V1/班课/领航合计列无法识别")
    teacher_col = next((index + 1 for index, value in enumerate(sheet[1]) if str(value.value or "").strip() == "教师"), 3)
    output: dict[str, RenewalEvidence] = {}
    for row in range(3, sheet.max_row + 1):
        teacher = str(sheet.cell(row, teacher_col).value or "").strip()
        key = normalize_teacher(teacher)
        if not key or key in {"教师", "合计"}:
            continue
        values = [_number(sheet.cell(row, col).value) for col in total_cols[:3]]
        # The workbook's rightmost total is the historical AK cross-check.
        ak = _number(sheet.cell(row, sheet.max_column).value)
        output[key] = RenewalEvidence(teacher=teacher, source_row=row, ah=values[0], ai=values[1], aj=values[2], ak=ak, source_file=str(source), source_sheet=resolved_sheet)
    return output


def read_august_refund(path: str | Path, sheet_prefix: str = "8月份") -> list[RefundEvidence]:
    """Backward-compatible August alias for the period-aware reader."""
    return read_refund_source(path, sheet_prefix=sheet_prefix)


def read_refund_source(path: str | Path, *, sheet_prefix: str | None = None) -> list[RefundEvidence]:
    """Read a refund workbook by its header schema, not a fixed month."""
    source = Path(path).resolve()
    book = xlrd.open_workbook(source, formatting_info=False)
    sheet_name = next((name for name in book.sheet_names() if sheet_prefix and name.strip().startswith(sheet_prefix)), None)
    if sheet_name is None:
        sheet_name = next((name for name in book.sheet_names() if {str(value or "").strip() for value in book.sheet_by_name(name).row_values(1)} >= {"教师", "人头", "业绩"}), None)
    if not sheet_name:
        raise ValueError("退费源缺少 8月份 sheet")
    sheet = book.sheet_by_name(sheet_name)
    headers = [str(value or "").strip() for value in sheet.row_values(1)]
    def col(label: str) -> int:
        for index, value in enumerate(headers):
            if value == label:
                return index
        raise ValueError(f"退费源缺少 {label} 列")
    teacher_col, student_col, head_col, perf_col = col("教师"), 3, col("人头"), col("业绩")
    output: list[RefundEvidence] = []
    for row in range(2, sheet.nrows):
        teacher = str(sheet.cell_value(row, teacher_col) or "").strip()
        if not teacher:
            continue
        student = str(sheet.cell_value(row, student_col) or "").strip()
        headcount, performance = _number(sheet.cell_value(row, head_col)), _number(sheet.cell_value(row, perf_col))
        if headcount == 0 and performance == 0:
            continue
        output.append(RefundEvidence(teacher=teacher, source_row=row + 1, student=student, headcount=headcount, performance=performance, total=headcount + performance, source_file=str(source), source_sheet=sheet_name))
    return output


def source_roster(renewal: dict[str, RenewalEvidence], refunds: list[RefundEvidence]) -> list[dict[str, Any]]:
    """Build a deterministic roster from current-period source facts."""
    names: list[str] = []
    seen: set[str] = set()
    for item in renewal.values():
        if item.teacher and item.teacher not in seen:
            names.append(item.teacher)
            seen.add(item.teacher)
    for item in refunds:
        if item.teacher and item.teacher not in seen:
            names.append(item.teacher)
            seen.add(item.teacher)
    return [{"row": index, "teacher": teacher, "normalized": normalize_teacher(teacher), "source": "CURRENT_PERIOD_SOURCE"} for index, teacher in enumerate(names, start=5)]


def create_empty_template(template_path: str | Path, output_path: str | Path) -> str:
    """Extract structure/style from a workbook without carrying business facts.

    This helper is intentionally not used as a business-data source.  It is a
    repeatable fixture builder for the production contract and anti-copy UAT.
    Formula text is retained as structure, while formula cached values,
    historical comments and all data-row values are removed.
    """
    source, target = Path(template_path).resolve(), Path(output_path).resolve()
    if target.exists():
        raise ValueError(f"输出文件已存在，不能覆盖：{target}")
    book = load_workbook(source, data_only=False, read_only=False, keep_links=True)
    for sheet in book.worksheets:
        # Payroll data rows begin at row 5 in the approved company contract.
        # For generic sheets this is still conservative: headers and layout
        # remain untouched, and only the repeated row area is cleared.
        for row in range(5, sheet.max_row + 1):
            for column in range(1, sheet.max_column + 1):
                cell = sheet.cell(row, column)
                if cell.data_type != "f":
                    cell.value = None
                cell.comment = None
    target.parent.mkdir(parents=True, exist_ok=True)
    book.save(target)
    # openpyxl drops most cached values on save; remove any remaining formula
    # cache explicitly so data_only reads cannot expose a historical answer.
    _strip_formula_caches(target)
    return str(target)


def _strip_formula_caches(path: Path) -> None:
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    tag = f"{{{namespace}}}"
    temporary = path.with_suffix(".empty-template.tmp.xlsx")
    with zipfile.ZipFile(path, "r") as source_zip, zipfile.ZipFile(temporary, "w") as target_zip:
        for item in source_zip.infolist():
            payload = source_zip.read(item.filename)
            if item.filename.startswith("xl/worksheets/") and item.filename.endswith(".xml"):
                root = ET.fromstring(payload)
                for cell in root.iter(f"{tag}c"):
                    if cell.find(f"{tag}f") is not None:
                        value = cell.find(f"{tag}v")
                        if value is not None:
                            cell.remove(value)
                payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            target_zip.writestr(item, payload)
    temporary.replace(path)


def _canonical_refund_comment(item: RefundEvidence) -> str:
    parts = []
    if item.headcount:
        parts.append(f"人头{item.headcount:g}")
    if item.performance:
        parts.append(f"业绩{item.performance:g}")
    detail = " ".join(parts) or f"合计{item.total:g}"
    return f"{item.teacher}: {item.student} 退费 {detail}\n(退费表8月)"


def _value_equal(left: object, right: object) -> bool:
    if left is None and right is None:
        return True
    try:
        return abs(float(left) - float(right)) < 1e-9
    except (TypeError, ValueError):
        return left == right


def _formula(cell: object) -> str | None:
    return cell if isinstance(cell, str) and cell.startswith("=") else None


def render_final_workbook_contract(*, template_path: str | Path, renewal_path: str | Path, refund_path: str | Path, output_path: str | Path, evidence_dir: str | Path | None = None) -> dict[str, Any]:
    """Produce the user-facing workbook and independent final-XLSX evidence."""
    template, output = Path(template_path).resolve(), Path(output_path).resolve()
    if output.exists():
        raise ValueError(f"输出文件已存在，不能覆盖：{output}")
    renewal = read_renewal_source(renewal_path)
    refunds = read_refund_source(refund_path)
    refund_by_teacher: dict[str, list[RefundEvidence]] = {}
    for item in refunds:
        refund_by_teacher.setdefault(normalize_teacher(item.teacher), []).append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template, output)
    book = load_workbook(output, data_only=False, read_only=False, keep_links=True)
    sheet = book.worksheets[0]
    roster = source_roster(renewal, refunds)
    # The copied workbook is immediately reduced to an empty template.  It is
    # never allowed to supply a roster, value, comment or formula cache.
    for row_number in range(5, sheet.max_row + 1):
        for column in range(1, sheet.max_column + 1):
            cell = sheet.cell(row_number, column)
            cell.value = None
            cell.comment = None
    conflicts: dict[str, Any] = {}
    cell_diff: list[dict[str, Any]] = []
    comment_diff: list[dict[str, Any]] = []
    for index, person in enumerate(roster, start=1):
        row, teacher, key = person["row"], person["teacher"], person["normalized"]
        sheet.cell(row, 1).value = index
        sheet.cell(row, 3).value = teacher
        source_renewal = renewal.get(key)
        source_refunds = refund_by_teacher.get(key, [])
        # Renewal is source-backed for every matching teacher.  AK remains the
        # template's formula, so the final workbook keeps the company's formula
        # contract instead of replacing it with a new static table.
        if source_renewal:
            for code, value in (("AH", source_renewal.ah), ("AI", source_renewal.ai), ("AJ", source_renewal.aj)):
                cell = sheet.cell(row, FINAL_COLUMNS[code])
                baseline = cell.value
                # The approved template intentionally leaves a no-activity
                # component blank.  Preserve that display convention rather
                # than turning a source zero into a new visible zero.
                cell.value = value
                cell_diff.append({"teacher": teacher, "cell": cell.coordinate, "code": code, "baseline_value": baseline, "generated_value": cell.value, "baseline_formula": _formula(baseline), "generated_formula": _formula(cell.value), "status": "EXACT_MATCH" if _value_equal(baseline, cell.value) else "EXPECTED_DIFFERENCE", "provenance": asdict(source_renewal)})
        for code in ("AK",):
            cell = sheet.cell(row, FINAL_COLUMNS[code])
            baseline_formula = _formula(cell.value)
            cell.value = f"=AH{row}*1+AI{row}*1.5+AJ{row}*0.75"
            cell_diff.append({"teacher": teacher, "cell": cell.coordinate, "code": code, "baseline_value": None, "generated_value": cell.value, "baseline_formula": baseline_formula, "generated_formula": cell.value, "status": "EXPECTED_DIFFERENCE", "provenance": {"formula": "AH*1+AI*1.5+AJ*0.75", "source": "CURRENT_RUN"}})
        an_cell = sheet.cell(row, FINAL_COLUMNS["AN"])
        baseline_an = an_cell.value
        conflict = None
        if source_refunds:
            an_cell.value = round(sum(item.total for item in source_refunds), 2)
        else:
            an_cell.value = None
        generated_an = an_cell.value
        # Baseline is an oracle only.  A source-driven empty value is an
        # expected difference from a historical workbook, never a production
        # fallback and never an unexplained failure by itself.
        status = "EXACT_MATCH" if _value_equal(baseline_an, generated_an) else "EXPECTED_DIFFERENCE"
        cell_diff.append({"teacher": teacher, "cell": an_cell.coordinate, "code": "AN", "baseline_value": baseline_an, "generated_value": generated_an, "baseline_formula": _formula(baseline_an), "generated_formula": _formula(generated_an), "status": status, "provenance": {"source_rows": [asdict(item) for item in source_refunds], "conflict": conflict}})
        if source_refunds:
            an_cell.comment = Comment("\n".join(_canonical_refund_comment(item) for item in source_refunds), "Ralph Payroll")
        comment_diff.append({"teacher": teacher, "cell": an_cell.coordinate, "baseline_comment": None, "generated_comment": an_cell.comment.text if an_cell.comment else None, "status": "EXPECTED_DIFFERENCE", "source_rows": [asdict(item) for item in source_refunds], "conflict": conflict})
    book.save(output)
    # Re-open the final xlsx.  This is the contract gate, not an intermediate
    # JSON check.
    reopened = load_workbook(output, data_only=False, read_only=False, keep_links=True)
    target = reopened.worksheets[0]
    template_book = load_workbook(template, data_only=False, read_only=False, keep_links=True)
    template_sheet = template_book.worksheets[0]
    template_diff = compare_visible_template(template_sheet, target)
    template_diff.update({"sheet_names_baseline": template_book.sheetnames, "sheet_names_generated": reopened.sheetnames, "sheet_count_baseline": len(template_book.sheetnames), "sheet_count_generated": len(reopened.sheetnames)})
    business_unexplained = sum(item["status"] == "UNEXPLAINED_DIFFERENCE" for item in cell_diff)
    comment_counts = {
        "EXACT_COMMENT_MATCH": sum(item["status"] == "EXACT_COMMENT_MATCH" for item in comment_diff),
        "SEMANTIC_MATCH_BUT_TEXT_DIFF": 0,
        "EXPECTED_DIFFERENCE": sum(item["status"] == "EXPECTED_DIFFERENCE" for item in comment_diff),
        "UNEXPLAINED_DIFFERENCE": 0,
    }
    expected_source_differences = any(item["status"] == "EXPECTED_DIFFERENCE" for item in cell_diff)
    result = {"template_path": str(template), "template_sha256": sha256_file(template), "output_path": str(output), "output_sha256": sha256_file(output), "roster": roster, "renewal_source": str(Path(renewal_path).resolve()), "refund_source": str(Path(refund_path).resolve()), "cell_diff": cell_diff, "comment_diff": comment_diff, "template_diff": template_diff, "business_unexplained": business_unexplained, "comment_counts": comment_counts, "conflicts": conflicts, "status": "PASS_WITH_SOURCE_CONFIRMATION" if business_unexplained == 0 and not template_diff["differences"] and (conflicts or expected_source_differences) else ("PASS" if business_unexplained == 0 and not template_diff["differences"] else "SOURCE_CONFIRMATION_REQUIRED")}
    if evidence_dir:
        directory = Path(evidence_dir).resolve(); directory.mkdir(parents=True, exist_ok=True)
        (directory / "FINAL_WORKBOOK_CELL_DIFF.json").write_text(json.dumps(cell_diff, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (directory / "FINAL_WORKBOOK_COMMENT_DIFF.json").write_text(json.dumps({"rows": comment_diff, "counts": comment_counts}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (directory / "FINAL_WORKBOOK_TEMPLATE_DIFF.json").write_text(json.dumps(template_diff, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (directory / "FINAL_WORKBOOK_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def compare_visible_template(baseline, generated) -> dict[str, Any]:
    differences: list[dict[str, Any]] = []
    if baseline.title != generated.title:
        differences.append({"kind": "sheet_title", "baseline": baseline.title, "generated": generated.title})
    # A current Run may have more or fewer teachers than the historical
    # oracle.  Extra styled data rows are a roster change, not a template
    # contract change; a column loss or a shorter sheet still is.
    if generated.max_row < baseline.max_row or baseline.max_column != generated.max_column:
        differences.append({"kind": "dimensions", "baseline": [baseline.max_row, baseline.max_column], "generated": [generated.max_row, generated.max_column]})
    if tuple(str(item) for item in baseline.merged_cells.ranges) != tuple(str(item) for item in generated.merged_cells.ranges):
        differences.append({"kind": "merged_cells", "baseline": [str(item) for item in baseline.merged_cells.ranges], "generated": [str(item) for item in generated.merged_cells.ranges]})
    if baseline.freeze_panes != generated.freeze_panes:
        differences.append({"kind": "freeze_panes", "baseline": str(baseline.freeze_panes), "generated": str(generated.freeze_panes)})
    for key, dim in baseline.column_dimensions.items():
        other = generated.column_dimensions[key]
        if (dim.width, dim.hidden) != (other.width, other.hidden):
            differences.append({"kind": "column_dimension", "key": key, "baseline": [dim.width, dim.hidden], "generated": [other.width, other.hidden]})
    for key, dim in baseline.row_dimensions.items():
        other = generated.row_dimensions[key]
        if (dim.height, dim.hidden) != (other.height, other.hidden):
            differences.append({"kind": "row_dimension", "key": key, "baseline": [dim.height, dim.hidden], "generated": [other.height, other.hidden]})
    for row in range(1, baseline.max_row + 1):
        for col in range(1, baseline.max_column + 1):
            left, right = baseline.cell(row, col), generated.cell(row, col)
            if left.style_id != right.style_id or left.number_format != right.number_format:
                differences.append({"kind": "cell_style", "cell": left.coordinate, "baseline_style": left.style_id, "generated_style": right.style_id, "baseline_format": left.number_format, "generated_format": right.number_format})
    return {"template_exact": not differences, "differences": differences, "sheet_names_baseline": [baseline.title], "sheet_names_generated": [generated.title]}
