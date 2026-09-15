"""Render a generated payroll model into Excel.

The workbook is written from the Core model, never copied from a teacher's
submitted sheet, and an existing file is never overwritten. Unconfirmed rows
carry their reason in the sheet so a draft can never be mistaken for a final
payroll.
"""
from __future__ import annotations

import json
from math import isclose
from pathlib import Path
from typing import Any, Mapping

from copy import copy
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from ..final_fields import FINAL_FIELD_CODES, FIELD_LABELS
from ..payroll_generation import GeneratedPayroll
from .golden_baseline import golden_formula_for_row
from .output_paths import safe_output_path


CORE_HEADERS = (
    "教师", "AA 一对一折算小时", "AC 班课折算小时", "AD 最终授课小时",
    "AE 该档每小时金额", "AF 总课时费", "AV 总工资", "状态", "待确认原因", "兼职按节课时费", "逐项确定性",
    "星级", "核心规则版本",
)
# M is a Core input-derived output and therefore appears in both generated
# workbooks and the supplied historical template; the remaining codes are the
# downstream AV fields.
FINAL_OUTPUT_CODES = ("M",) + tuple(code for code in FINAL_FIELD_CODES if code != "AV")
FINAL_OUTPUT_HEADERS = tuple(f"{code} {FIELD_LABELS[code].removeprefix(code + ' ')}" for code in FINAL_OUTPUT_CODES)
HEADERS = CORE_HEADERS + FINAL_OUTPUT_HEADERS

# These columns exist in the historical final payroll workbook, but their
# sources and complete rules are outside the current Core handoff.  They are
# listed explicitly in the output instead of being silently omitted or set to
# zero.  Keeping the list here also makes the delivery boundary testable.
OUT_OF_SCOPE_FINAL_FIELDS: tuple[str, ...] = FINAL_FIELD_CODES
HUMAN_REQUIRED = "HUMAN_REQUIRED"
EXCEL_CELL_CHAR_LIMIT = 32767


def _star_display(row: Any) -> str | None:
    """Render the selected star together with its source status."""
    if row.star is None:
        return None
    evidence = row.fields.get("AE", {}).get("evidence", ()) if isinstance(row.fields, Mapping) else ()
    kinds = {item.get("kind") for item in evidence if isinstance(item, Mapping)}
    if "DEFAULT_TWO_STAR" in kinds:
        return f"已确定/默认二星"
    if "CONFLICT_AUTHORITY_WINS" in kinds:
        return f"已确定/冲突按权威/{row.star}星"
    if "RATING_AUTHORITY" in kinds and "PAYROLL_REFERENCE_RATING" in kinds:
        return f"已确定/冲突按权威/{row.star}星"
    if "RATING_AUTHORITY" in kinds:
        return f"已核验/{row.star}星"
    if "FALLBACK_REFERENCE" in kinds:
        return f"已确定/上传资料/{row.star}星"
    return f"已确定/{row.star}星"


GRADE_COLUMNS = {
    "一年级": 14, "二年级": 15, "三年级": 16, "四年级": 17,
    "五年级": 18, "六年级": 19, "七年级": 20, "八年级": 21,
    "九年级": 22, "初一": 20, "初二": 21, "初三": 22,
    "高一": 23, "高二": 24, "高三": 25, "雅思": 26, "托福": 26,
}


def _formula_for_row(row: Any, code: str, row_number: int) -> str:
    if code == "M":
        return f"=(G{row_number}+H{row_number}+I{row_number}+J{row_number})/K{row_number}*L{row_number}"
    if code == "AA":
        return f"=(N{row_number}+O{row_number}+P{row_number}+Q{row_number}+R{row_number}+S{row_number})/3*2*0.85+(T{row_number}+U{row_number})/3*2*0.9+V{row_number}/3*2*1+W{row_number}/3*2*1.1+X{row_number}/3*2*1.25+Y{row_number}/3*2*1.35+Z{row_number}/3*2*1.5"
    if code == "AD":
        return f"=AA{row_number}+AC{row_number}"
    if code == "AF":
        obligation = 30
        for evidence in row.fields.get("AF", {}).get("evidence", ()) if isinstance(row.fields, Mapping) else ():
            raw = evidence.get("inputs", {}).get("obligation_hours") if isinstance(evidence, Mapping) else None
            if raw not in (None, ""):
                try:
                    obligation = float(raw)
                except (TypeError, ValueError):
                    pass
                break
        shown = str(int(obligation)) if float(obligation).is_integer() else str(obligation)
        return f"=MAX(0,(AD{row_number}-{shown})*AE{row_number})"
    if code == "AK":
        return f"=AH{row_number}*1+AI{row_number}*1.5+AJ{row_number}*0.75"
    if code == "AV":
        return f"=M{row_number}+AF{row_number}+AG{row_number}+AK{row_number}+AL{row_number}+AN{row_number}+AO{row_number}+AP{row_number}+AQ{row_number}+AR{row_number}+AS{row_number}+AT{row_number}+AU{row_number}+AM{row_number}"
    raise KeyError(code)


def render_generated_payroll(payroll: GeneratedPayroll, output: str | Path, *, template_path: str | Path | None = None) -> str:
    # Preserve prior exports; collisions receive the next numbered name.
    target = safe_output_path(output)
    if not payroll.rows:
        raise ValueError("没有可生成的教师记录，不能创建空的标准工资表。")
    rows = _ordered_rows(payroll)
    target.parent.mkdir(parents=True, exist_ok=True)

    if template_path:
        return _render_with_template(payroll, rows, target, Path(template_path))

    book = Workbook()
    sheet = book.active
    sheet.title = "标准工资表"
    headline = f"{payroll.period} 标准工资表（由 Core 计算结果生成，非复制任何提交表）"
    sheet.append([headline])
    sheet["A1"].font = Font(bold=True)
    sheet.append([f"状态：{'全项最终工资已计算' if payroll.final else '草稿 / 待确认——不得作为最终工资；不等于最终全项工资'}"])
    sheet.append(list(HEADERS))
    for column in range(1, len(HEADERS) + 1):
        sheet.cell(3, column).font = Font(bold=True)
    sheet.freeze_panes = "A4"
    sheet.auto_filter.ref = f"A3:{_column_letter(len(HEADERS))}{len(rows) + 3}"

    for row in rows:
        av = _field_value(row, "AV")
        detail_fields = {**row.fields, **row.final_fields}
        sheet.append([
            row.teacher,
            _value(row.one_to_one), _value(row.class_value), _value(row.teaching_hours),
            _value(row.ae), _value(_field_value(row, "AF", fallback=row.af)), _value(av),
            "待确认" if not row.final else "已计算",
            "、".join(_row_blockers(row)),
            _value(row.part_time_amount),
            "；".join(f"{key}: {item['state']}" for key, item in detail_fields.items()),
            row.star,
            payroll.rule_versions.get("core", ""),
            *[_value(_field_value(row, code)) for code in FINAL_OUTPUT_CODES],
        ])

    _write_evidence_sheet(book, payroll, rows)
    _write_boundary_sheet(book, payroll, rows)
    book.save(target)
    validation = validate_standard_payroll_workbook(target, payroll)
    if not validation["ok"]:
        raise ValueError("生成的标准工资表校验失败：" + "；".join(validation["errors"]))
    return str(target.resolve())


def _template_headers(sheet) -> dict[str, int]:
    """Map the two-row Chinese template header to its stable business columns."""
    aliases = {
        "teacher": ("姓名",), "star": ("教师级别",), "aa": ("折算小时数",),
        "ac": ("班课折算小时数",), "ad": ("最终授课小时数据",), "ae": ("该档每小时金额",),
        "af": ("总课时费",), "av": ("总工资数",),
        "g": ("基本工资",), "h": ("岗位津贴",), "i": ("工龄工资/教师等级",),
        "j": ("其他待遇",), "k": ("应出勤",), "l": ("实际出勤",), "m": ("实际基本工资",),
    }
    found: dict[str, int] = {}
    for column in range(1, sheet.max_column + 1):
        values = {str(sheet.cell(row, column).value or "").replace("\n", "").strip() for row in (3, 4)}
        for key, labels in aliases.items():
            if key not in found and values.intersection(labels):
                found[key] = column
    missing = [key for key in aliases if key not in found]
    if missing:
        raise ValueError("工资模板缺少必要列：" + "、".join(missing))
    return found


def _render_with_template(payroll: GeneratedPayroll, rows: tuple[Any, ...], target: Path, template: Path) -> str:
    if not template.is_file():
        raise ValueError("工资模板文件不存在，不能生成模板工资表。")
    try:
        book = load_workbook(template, data_only=False, read_only=False, keep_links=True)
    except Exception as exc:
        raise ValueError(f"工资模板无法打开：{exc}") from exc
    if not book.worksheets:
        raise ValueError("工资模板没有工作表。")
    sheet = book.worksheets[0]
    columns = _template_headers(sheet)
    original_sheetnames = tuple(book.sheetnames)
    original_merges = tuple(sorted(str(item) for item in sheet.merged_cells.ranges))
    # A reusable template may carry a stale example month (the checked-in
    # template currently contains an Excel date serial).  Bind the displayed
    # month to the authoritative Core period while preserving the template's
    # layout and formatting.
    for column in range(1, sheet.max_column):
        if str(sheet.cell(2, column).value or "").strip() in {"月份：", "月份:"}:
            sheet.cell(2, column + 1).value = payroll.period
            break
    # Keep the supplied title, merged cells, widths, row heights and styles.
    # Clear only the data area, because formulas in the blank template rows
    # would otherwise display stale values from the template itself.
    first_data_row = 5
    for row_number in range(first_data_row, sheet.max_row + 1):
        for column in range(1, sheet.max_column + 1):
            sheet.cell(row_number, column).value = None
    if len(rows) > sheet.max_row - first_data_row + 1:
        source_row = sheet.max_row
        for row_number in range(sheet.max_row + 1, first_data_row + len(rows)):
            sheet.row_dimensions[row_number].height = sheet.row_dimensions[source_row].height
            for column in range(1, sheet.max_column + 1):
                source = sheet.cell(source_row, column)
                destination = sheet.cell(row_number, column)
                if source.has_style:
                    destination._style = copy(source._style)
                if source.number_format:
                    destination.number_format = source.number_format
    for index, row in enumerate(rows, start=1):
        row_number = first_data_row + index - 1
        sheet.cell(row_number, 1).value = index
        sheet.cell(row_number, columns["teacher"]).value = row.teacher
        base_inputs = {}
        m_field = row.final_fields.get("M", {}) if isinstance(getattr(row, "final_fields", None), Mapping) else {}
        for evidence in m_field.get("evidence", ()) if isinstance(m_field, Mapping) else ():
            if isinstance(evidence, Mapping) and isinstance(evidence.get("inputs"), Mapping):
                base_inputs = dict(evidence["inputs"])
                break
        for code in ("G", "H", "I", "J", "K", "L"):
            sheet.cell(row_number, columns[code.lower()]).value = _value(base_inputs.get(code)) if base_inputs else None
        counts = (payroll.formula_inputs.get("one_to_one_counts", {}) if isinstance(payroll.formula_inputs, Mapping) else {}).get(row.teacher, {})
        # The supplied template labels the middle-school columns as 初一/初二/初三,
        # while the normalized schedule may use 七/八/九年级.  They are the same
        # physical formula inputs; aggregate aliases before writing so a later
        # alias cannot overwrite an earlier grade's count.
        column_counts: dict[int, int] = {}
        for grade, count in counts.items():
            column = GRADE_COLUMNS.get(grade)
            if column is not None:
                column_counts[column] = column_counts.get(column, 0) + int(count or 0)
        for column in sorted(set(GRADE_COLUMNS.values())):
            sheet.cell(row_number, column).value = column_counts.get(column, 0)
        star_display = _star_display(row)
        if star_display is not None:
            sheet.cell(row_number, columns["star"]).value = star_display
        sheet.cell(row_number, columns["aa"]).value = _formula_for_row(row, "AA", row_number)
        sheet.cell(row_number, columns["ac"]).value = _value(row.class_value)
        sheet.cell(row_number, columns["ad"]).value = _formula_for_row(row, "AD", row_number)
        sheet.cell(row_number, columns["ae"]).value = _value(row.ae)
        # AF may be an ESTIMATED Core value when the package supplies a
        # historical rating.  Keep that visible in the payroll column; the
        # evidence/status columns still make clear that it is not final.
        sheet.cell(row_number, columns["af"]).value = _formula_for_row(row, "AF", row_number)
        # Keep blocked M rows visibly unresolved instead of letting Excel's
        # blank-cell arithmetic silently display a misleading zero.  Once the
        # Run snapshot has supplied every G:L input, retain the canonical
        # template formula verbatim.
        sheet.cell(row_number, columns["m"]).value = (
            _formula_for_row(row, "M", row_number)
            if m_field.get("state") == "DETERMINED" else None
        )
        sheet.cell(row_number, columns["av"]).value = _formula_for_row(row, "AV", row_number)
        sheet.cell(row_number, 37).value = _formula_for_row(row, "AK", row_number)
        for index, code in enumerate(FINAL_FIELD_CODES):
            if code in {"AK", "AV"}:
                continue
            sheet.cell(row_number, 33 + index).value = _value(_field_value(row, code))
        sheet.cell(row_number, sheet.max_column).value = "；".join(_row_blockers(row)) or ("已计算" if row.final else "待确认")

    _write_evidence_sheet(book, payroll, rows)
    _write_boundary_sheet(book, payroll, rows)
    book.save(target)
    validation = validate_template_payroll_workbook(target, payroll, template, original_sheetnames, original_merges, columns)
    if not validation["ok"]:
        raise ValueError("按工资模板生成的工资表校验失败：" + "；".join(validation["errors"]))
    return str(target.resolve())


def validate_template_payroll_workbook(path: str | Path, payroll: GeneratedPayroll, template: str | Path, original_sheetnames: tuple[str, ...] | None = None, original_merges: tuple[str, ...] | None = None, columns: Mapping[str, int] | None = None) -> dict[str, Any]:
    """Re-open a template-based output and verify structure plus Core values."""
    errors: list[str] = []
    target = Path(path)
    try:
        book = load_workbook(target, data_only=False, read_only=False, keep_links=True)
        source = load_workbook(template, data_only=False, read_only=False, keep_links=True)
        sheet = book.worksheets[0]
        source_sheet = source.worksheets[0]
        mapped = columns or _template_headers(sheet)
    except Exception as exc:
        return {"ok": False, "errors": [f"无法重新打开模板输出：{exc}"], "rows_checked": 0, "path": str(target.resolve())}
    if original_sheetnames is not None and tuple(book.sheetnames[:len(original_sheetnames)]) != tuple(original_sheetnames):
        errors.append("模板原有工作表顺序或名称发生变化")
    if original_merges is not None and tuple(sorted(str(item) for item in sheet.merged_cells.ranges)) != tuple(original_merges):
        errors.append("模板原有合并单元格发生变化")
    for coordinate in ("A1", "A3", "C3", "F3", "AA3", "AV4"):
        if sheet[coordinate].value != source_sheet[coordinate].value:
            errors.append(f"模板表头结构发生变化：{coordinate}")
    expected_rows = _ordered_rows(payroll)
    for offset, expected in enumerate(expected_rows, start=5):
        if sheet.cell(offset, mapped["teacher"]).value != expected.teacher:
            errors.append(f"模板第 {offset} 行教师不一致")
            continue
        values = {
            "aa": expected.one_to_one, "ac": expected.class_value, "ad": expected.teaching_hours,
            "ae": expected.ae, "af": expected.af if expected.af is not None else _field_value(expected, "AF"),
            "av": _field_value(expected, "AV", fallback=expected.av),
        }
        for name, wanted in values.items():
            code = {"aa": "AA", "ad": "AD", "af": "AF", "av": "AV"}.get(name)
            actual = sheet.cell(offset, mapped[name]).value
            if code:
                expected_formula = golden_formula_for_row(expected, code, offset)
                if actual != expected_formula:
                    errors.append(f"{expected.teacher} 的模板 {name} 公式不一致")
                continue
            if not _same_output_value(actual, wanted):
                errors.append(f"{expected.teacher} 的模板 {name} 输出值不一致")
        if "M" in getattr(expected, "final_fields", {}):
            actual_m = sheet.cell(offset, mapped["m"]).value
            wanted_m = golden_formula_for_row(expected, "M", offset) if expected.final_fields.get("M", {}).get("state") == "DETERMINED" else None
            if actual_m != wanted_m:
                errors.append(f"{expected.teacher} 的模板 M 公式不一致")
    return {"ok": not errors, "errors": errors, "rows_checked": len(expected_rows), "path": str(target.resolve()), "template_sheet": sheet.title, "template_preserved": not errors}


def _value(number: float | None):
    return None if number is None else round(float(number), 4)


def _field_value(row: Any, code: str, *, fallback: object = None) -> object:
    final_fields = getattr(row, "final_fields", None)
    item = final_fields.get(code) if final_fields is not None else None
    if isinstance(item, Mapping) and item.get("value") is not None:
        value = item["value"]
        # Core's JSON-safe representation may retain Decimal values as strings;
        # normalize them before writing and validating numeric Excel cells.
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                pass
        return value
    # ``row.av`` is retained only for dataclass compatibility with old callers;
    # once final-field state exists it must never bypass the AV dependency gate.
    # An empty mapping is the legacy CorePayrollRow shape.  It has no
    # dependency-gated final-field state yet, so retain the dataclass's
    # compatibility value; a populated final-field mapping deliberately wins
    # and prevents bypassing the AV gate.
    if final_fields is None or not final_fields:
        return fallback if fallback is not None else (row.av if code == "AV" else None)
    return None


def _row_blockers(row: Any) -> tuple[str, ...]:
    reasons = set(row.blockers)
    reasons.update(
        str(item.get("reason") or item.get("state"))
        for item in getattr(row, "final_fields", {}).values()
        if item.get("state") not in {"DETERMINED", "NOT_APPLICABLE"}
    )
    return tuple(sorted(reasons))


def _ordered_rows(payroll: GeneratedPayroll) -> tuple[Any, ...]:
    rows = tuple(sorted(payroll.rows, key=lambda row: row.teacher))
    teachers = [row.teacher for row in rows]
    if len(teachers) != len(set(teachers)):
        raise ValueError("标准工资结果中教师不能重复。")
    if any(not str(teacher).strip() for teacher in teachers):
        raise ValueError("标准工资结果中教师不能为空。")
    return rows


def _column_letter(column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _write_evidence_sheet(book: Workbook, payroll: GeneratedPayroll, rows: tuple[Any, ...]) -> None:
    sheet = book.create_sheet("核验与来源")
    sheet.append(["标准工资表核验与来源"])
    sheet["A1"].font = Font(bold=True)
    sheet.append(["期间", payroll.period])
    sheet.append(["核心状态", payroll.status])
    sheet.append(["核心阻塞项", "、".join(payroll.blockers)])
    sheet.append(["规则版本", json.dumps(dict(payroll.rule_versions), ensure_ascii=False, sort_keys=True)])
    sheet.append([])
    headers = ["教师", "字段", "值", "确定性", "原因", "证据(JSON)", "规则版本"]
    sheet.append(headers)
    for column in range(1, len(headers) + 1):
        sheet.cell(7, column).font = Font(bold=True)
    detail_rows, overflow_rows = _evidence_detail_rows(payroll, rows)
    for detail_row in detail_rows:
        sheet.append(detail_row)
    # A compact source index lets a reviewer resolve the opaque record_key in
    # course evidence back to the source file and source cells.
    start = sheet.max_row + 2
    sheet.cell(start, 1, "课程记录来源索引").font = Font(bold=True)
    for column, value in enumerate(("record_key", "教师", "源文件", "来源证据(JSON)"), start=1):
        sheet.cell(start + 1, column, value).font = Font(bold=True)
    source_rows, source_overflow_rows = _source_index_rows(payroll.source_records)
    for item in source_rows:
        sheet.append(item)
    _set_widths(sheet, {1: 18, 2: 12, 3: 18, 4: 18, 5: 46, 6: 80, 7: 26})
    if overflow_rows:
        overflow_sheet = book.create_sheet("字段证据")
        overflow_sheet.append(["超出 Excel 单元格长度限制的字段证据（按明细编号拆分）"])
        overflow_sheet.append(["明细编号", "教师", "字段", "证据序号", "证据(JSON)"])
        for row in overflow_rows:
            overflow_sheet.append(row)
        _set_widths(overflow_sheet, {1: 14, 2: 18, 3: 12, 4: 12, 5: 120})
    if source_overflow_rows:
        overflow_sheet = book.create_sheet("来源证据")
        overflow_sheet.append(["超出 Excel 单元格长度限制的课程来源证据（按 record_key 拆分）"])
        overflow_sheet.append(["record_key", "教师", "证据序号", "来源证据(JSON)"])
        for row in source_overflow_rows:
            overflow_sheet.append(row)
        _set_widths(overflow_sheet, {1: 28, 2: 18, 3: 14, 4: 120})


def _json_text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _text_chunks(value: str) -> list[str]:
    return [
        value[offset:offset + EXCEL_CELL_CHAR_LIMIT]
        for offset in range(0, len(value), EXCEL_CELL_CHAR_LIMIT)
    ] or [""]


def _source_index_rows(source_records: list[dict[str, Any]]):
    """Return bounded source-index rows and lossless provenance spill rows."""
    rows = []
    overflow_rows = []
    for item in source_records:
        record_key = item.get("record_key", "")
        provenance_text = _json_text(item.get("provenance", {}))
        if len(provenance_text) <= EXCEL_CELL_CHAR_LIMIT:
            shown = provenance_text
        else:
            chunks = _text_chunks(provenance_text)
            shown = _json_text({
                "storage": "来源证据",
                "record_key": record_key,
                "chunk_count": len(chunks),
            })
            for chunk_number, chunk in enumerate(chunks, start=1):
                overflow_rows.append([
                    record_key,
                    item.get("teacher", ""),
                    f"1#{chunk_number}/{len(chunks)}",
                    chunk,
                ])
        rows.append([record_key, item.get("teacher", ""), item.get("source", ""), shown])
    return rows, overflow_rows


def _evidence_detail_rows(payroll: GeneratedPayroll, rows: tuple[Any, ...]):
    """Return detail rows plus lossless spill rows for Excel's 32,767-char limit.

    The spill table is intentionally row-oriented.  A normal evidence item
    occupies one row; a single oversized JSON item occupies ordered chunk rows
    whose sequence marker lets a reader concatenate them without losing any
    characters.  No cell written by this function exceeds Excel's limit.
    """
    detail_rows = []
    overflow_rows = []
    detail_number = 0
    for row in rows:
        for field_name, field in {**row.fields, **row.final_fields}.items():
            detail_id = f"F{detail_number:06d}"
            evidence = field.get("evidence", [])
            evidence_text = _json_text(evidence)
            reason_text = field.get("reason", "")
            if isinstance(reason_text, str) and len(reason_text) > EXCEL_CELL_CHAR_LIMIT:
                chunks = _text_chunks(reason_text)
                reason_text = _json_text({
                    "storage": "字段证据",
                    "detail_id": detail_id,
                    "kind": "reason",
                    "chunk_count": len(chunks),
                })
                for chunk_number, chunk in enumerate(chunks, start=1):
                    overflow_rows.append([
                        detail_id,
                        row.teacher,
                        field_name,
                        f"reason#{chunk_number}/{len(chunks)}",
                        chunk,
                    ])
            if len(evidence_text) > EXCEL_CELL_CHAR_LIMIT:
                evidence_text = _json_text({
                    "storage": "字段证据",
                    "detail_id": detail_id,
                    "item_count": len(evidence),
                })
                for evidence_number, item in enumerate(evidence, start=1):
                    item_text = _json_text(item)
                    chunks = _text_chunks(item_text)
                    for chunk_number, chunk in enumerate(chunks, start=1):
                        sequence = evidence_number if len(chunks) == 1 else f"{evidence_number}#{chunk_number}/{len(chunks)}"
                        overflow_rows.append([detail_id, row.teacher, field_name, sequence, chunk])
            detail_rows.append([
                row.teacher,
                field_name,
                _value(field.get("value")),
                field.get("state", ""),
                reason_text,
                evidence_text,
                payroll.rule_versions.get("core", ""),
            ])
            detail_number += 1
    return detail_rows, overflow_rows


def _write_boundary_sheet(book: Workbook, payroll: GeneratedPayroll, rows: tuple[Any, ...]) -> None:
    sheet = book.create_sheet("外围字段状态")
    sheet.append(["最终工资字段逐项状态"])
    sheet["A1"].font = Font(bold=True)
    sheet.append(["逐字段显示当前来源状态；未形成确定结果的字段保留为人工确认入口。"])
    sheet.append(["字段", "状态", "说明"])
    for column in range(1, 4):
        sheet.cell(3, column).font = Font(bold=True)
    for field_name in OUT_OF_SCOPE_FINAL_FIELDS:
        values = [row.final_fields.get(field_name, {}) for row in rows]
        states = {str(item.get("state", HUMAN_REQUIRED)) for item in values}
        status = next(iter(states)) if len(states) == 1 else HUMAN_REQUIRED
        reasons = sorted({str(item.get("reason", "")) for item in values if item.get("reason")})
        note = "；".join(reasons) or FIELD_LABELS.get(field_name, "缺少字段定义")
        sources = sorted({str(evidence.get("source_input_id", "")) for item in values for evidence in item.get("evidence", []) if evidence.get("source_input_id")})
        sheet.append([field_name, status, note, "、".join(sources)])
    _set_widths(sheet, {1: 12, 2: 20, 3: 92, 4: 24})


def _set_widths(sheet, widths: Mapping[int, int]) -> None:
    for column, width in widths.items():
        sheet.column_dimensions[chr(64 + column)].width = width


def validate_standard_payroll_workbook(path: str | Path, payroll: GeneratedPayroll) -> dict[str, Any]:
    """Re-open and validate a generated workbook against its Core model.

    This is deliberately independent of the writer's in-memory values: it
    catches truncated rows, shifted columns, unexpected formulas, and stale
    output edits before a generated file is handed off.
    """
    target = Path(path)
    errors: list[str] = []
    try:
        book = load_workbook(target, data_only=False, read_only=False, keep_links=True)
    except Exception as exc:  # openpyxl raises several format-specific types
        return {"ok": False, "errors": [f"无法重新打开输出文件：{exc}"], "warnings": [], "rows_checked": 0}
    if "标准工资表" not in book.sheetnames:
        errors.append("缺少标准工资表工作表")
        return {"ok": False, "errors": errors, "warnings": [], "rows_checked": 0}
    sheet = book["标准工资表"]
    if sheet.max_column != len(HEADERS):
        errors.append(f"标准工资表列数不一致：文件 {sheet.max_column}，模型 {len(HEADERS)}")
    actual_headers = [sheet.cell(3, column).value for column in range(1, len(HEADERS) + 1)]
    if tuple(actual_headers) != HEADERS:
        errors.append("标准工资表表头或列位发生变化")
    if "核验与来源" not in book.sheetnames:
        errors.append("缺少核验与来源工作表")
    if "外围字段状态" not in book.sheetnames:
        errors.append("缺少外围字段状态工作表")

    try:
        expected_rows = _ordered_rows(payroll)
    except ValueError as exc:
        errors.append(str(exc))
        expected_rows = tuple(sorted(payroll.rows, key=lambda row: row.teacher))
    if sheet.max_row != len(expected_rows) + 3:
        errors.append(f"教师行数不一致：文件 {max(0, sheet.max_row - 3)}，模型 {len(expected_rows)}")
    columns = {"teacher": 1, "one_to_one": 2, "class_value": 3, "teaching_hours": 4, "ae": 5, "af": 6, "av": 7, "part_time_amount": 10, "star": 12, "rule_version": 13}
    columns.update({code: 14 + index for index, code in enumerate(FINAL_OUTPUT_CODES)})
    checked = 0
    for offset, expected in enumerate(expected_rows, start=4):
        checked += 1
        if sheet.cell(offset, columns["teacher"]).value != expected.teacher:
            errors.append(f"第 {offset} 行教师不一致")
            continue
        for name, column in columns.items():
            if name in {"teacher", "star"}:
                continue
            actual = sheet.cell(offset, column).value
            if name == "av":
                wanted = _field_value(expected, "AV", fallback=expected.av)
            elif name == "af":
                wanted = _field_value(expected, "AF", fallback=expected.af)
            elif name in FINAL_OUTPUT_CODES:
                wanted = _field_value(expected, name)
            elif name == "rule_version":
                wanted = payroll.rule_versions.get("core", "")
            else:
                wanted = getattr(expected, name)
            if not _same_output_value(actual, wanted):
                errors.append(f"{expected.teacher} 的 {name} 输出值不一致")
        if sheet.cell(offset, columns["star"]).value != expected.star:
            errors.append(f"{expected.teacher} 的星级输出值不一致")
        wanted_status = "已计算" if expected.final else "待确认"
        if sheet.cell(offset, 8).value != wanted_status:
            errors.append(f"{expected.teacher} 的核心状态不一致")
        if (sheet.cell(offset, 9).value or "") != "、".join(_row_blockers(expected)):
            errors.append(f"{expected.teacher} 的待确认原因不一致")
        detail_fields = {**expected.fields, **expected.final_fields}
        wanted_detail = "；".join(f"{key}: {item['state']}" for key, item in detail_fields.items())
        if sheet.cell(offset, 11).value != wanted_detail:
            errors.append(f"{expected.teacher} 的逐项确定性不一致")
        # Generated tables must be static results; formulas belong to source
        # workbooks and would make this output depend on an unavailable engine.
        for column in range(1, len(HEADERS) + 1):
            if isinstance(sheet.cell(offset, column).value, str) and sheet.cell(offset, column).value.startswith("="):
                errors.append(f"{expected.teacher} 第 {offset} 行不应包含公式")
                break
    boundary = book["外围字段状态"] if "外围字段状态" in book.sheetnames else None
    if boundary is not None:
        for index, code in enumerate(OUT_OF_SCOPE_FINAL_FIELDS, start=4):
            values = [row.final_fields.get(code, {}) for row in expected_rows]
            states = {str(item.get("state", HUMAN_REQUIRED)) for item in values}
            wanted_state = next(iter(states)) if len(states) == 1 else HUMAN_REQUIRED
            actual = boundary.cell(index, 1).value, boundary.cell(index, 2).value
            if actual != (code, wanted_state):
                errors.append(f"外围字段 {code} 状态不一致")
            values_reasons = sorted({str(item.get("reason", "")) for item in values if item.get("reason")})
            if boundary.cell(index, 3).value != "；".join(values_reasons):
                errors.append(f"外围字段 {code} 说明不一致")
            wanted_sources = "、".join(sorted({
                str(evidence.get("source_input_id", ""))
                for item in values
                for evidence in item.get("evidence", [])
                if evidence.get("source_input_id")
            }))
            if (boundary.cell(index, 4).value or "") != wanted_sources:
                errors.append(f"外围字段 {code} 来源索引不一致")

    evidence_sheet = book["核验与来源"] if "核验与来源" in book.sheetnames else None
    if evidence_sheet is not None:
        expected_detail, expected_overflow = _evidence_detail_rows(payroll, expected_rows)
        fixed = {
            (1, 1): "标准工资表核验与来源",
            (2, 1): "期间", (2, 2): payroll.period,
            (3, 1): "核心状态", (3, 2): payroll.status,
            (4, 1): "核心阻塞项", (4, 2): "、".join(payroll.blockers),
            (5, 1): "规则版本", (5, 2): json.dumps(dict(payroll.rule_versions), ensure_ascii=False, sort_keys=True),
        }
        for (row_number, column), wanted in fixed.items():
            actual = evidence_sheet.cell(row_number, column).value
            if (actual or "") != wanted:
                errors.append(f"核验与来源固定信息 {evidence_sheet.cell(row_number, column).coordinate} 不一致")
        evidence_headers = ["教师", "字段", "值", "确定性", "原因", "证据(JSON)", "规则版本"]
        if [evidence_sheet.cell(7, column).value for column in range(1, 8)] != evidence_headers:
            errors.append("核验与来源表头发生变化")
        for row_number, wanted_row in enumerate(expected_detail, start=8):
            actual_row = [evidence_sheet.cell(row_number, column).value for column in range(1, 8)]
            if any(not _same_output_value(actual, wanted) for actual, wanted in zip(actual_row, wanted_row)):
                errors.append(f"核验与来源第 {row_number} 行发生变化")
        overflow_sheet = book["字段证据"] if "字段证据" in book.sheetnames else None
        if expected_overflow:
            if overflow_sheet is None:
                errors.append("缺少字段证据拆分工作表")
            else:
                overflow_headers = ["明细编号", "教师", "字段", "证据序号", "证据(JSON)"]
                if [overflow_sheet.cell(2, column).value for column in range(1, 6)] != overflow_headers:
                    errors.append("字段证据拆分表头发生变化")
                for row_number, wanted_row in enumerate(expected_overflow, start=3):
                    actual_row = [overflow_sheet.cell(row_number, column).value for column in range(1, 6)]
                    if actual_row != wanted_row:
                        errors.append(f"字段证据拆分第 {row_number} 行发生变化")
                if overflow_sheet.max_row != len(expected_overflow) + 2:
                    errors.append("字段证据拆分行数发生变化")
        source_start = 9 + len(expected_detail)
        if evidence_sheet.cell(source_start, 1).value != "课程记录来源索引":
            errors.append("缺少课程记录来源索引")
        source_headers = ["record_key", "教师", "源文件", "来源证据(JSON)"]
        if [evidence_sheet.cell(source_start + 1, column).value for column in range(1, 5)] != source_headers:
            errors.append("课程记录来源索引表头发生变化")
        expected_sources, expected_source_overflow = _source_index_rows(payroll.source_records)
        for row_number, wanted_row in enumerate(expected_sources, start=source_start + 2):
            actual_row = [evidence_sheet.cell(row_number, column).value for column in range(1, 5)]
            if actual_row != wanted_row:
                errors.append(f"课程记录来源索引第 {row_number} 行发生变化")
        expected_max_row = source_start + 1 + len(expected_sources)
        if evidence_sheet.max_row != expected_max_row:
            errors.append("核验与来源行数发生变化")
        source_overflow_sheet = book["来源证据"] if "来源证据" in book.sheetnames else None
        if expected_source_overflow:
            if source_overflow_sheet is None:
                errors.append("缺少来源证据拆分工作表")
            else:
                source_overflow_headers = ["record_key", "教师", "证据序号", "来源证据(JSON)"]
                if [source_overflow_sheet.cell(2, column).value for column in range(1, 5)] != source_overflow_headers:
                    errors.append("来源证据拆分表头发生变化")
                for row_number, wanted_row in enumerate(expected_source_overflow, start=3):
                    actual_row = [source_overflow_sheet.cell(row_number, column).value for column in range(1, 5)]
                    if actual_row != wanted_row:
                        errors.append(f"来源证据拆分第 {row_number} 行发生变化")
                if source_overflow_sheet.max_row != len(expected_source_overflow) + 2:
                    errors.append("来源证据拆分行数发生变化")
    # A generated workbook is a static result.  Formula text or external-link
    # metadata anywhere in its companion pages would make the result depend on
    # an unavailable spreadsheet engine, so reject it as well.
    for candidate in book.worksheets:
        for row in candidate.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value.startswith("="):
                    errors.append(f"工作表 {candidate.title} 含有不应出现的公式：{cell.coordinate}")
                    break
            else:
                continue
            break
    return {"ok": not errors, "errors": errors, "warnings": [], "rows_checked": checked, "path": str(target.resolve())}


def _same_output_value(actual: object, wanted: object) -> bool:
    if wanted is None:
        return actual in (None, "")
    if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
        return isinstance(actual, (int, float)) and isclose(float(actual), float(wanted), rel_tol=0, abs_tol=1e-4)
    return actual == wanted
