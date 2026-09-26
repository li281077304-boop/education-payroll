"""Render a generated payroll model into Excel.

The workbook is written from the Core model, never copied from a teacher's
submitted sheet, and an existing file is never overwritten. Unconfirmed rows
carry their reason in the sheet so a draft can never be mistaken for a final
payroll.
"""
from __future__ import annotations

import json
import re
from math import isclose
from pathlib import Path
from typing import Any, Mapping

from copy import copy
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font
from openpyxl.utils.cell import column_index_from_string

from ..final_fields import FINAL_FIELD_CODES, FIELD_LABELS
from ..models.manual_adjustments import adjustment_by_teacher_field
from ..models.annotations import comment_text, normalize_annotations
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


def _is_part_time_row(row: Any) -> bool:
    fields = getattr(row, "final_fields", {}) or {}
    m_field = fields.get("M") if isinstance(fields, Mapping) else None
    return any(
        isinstance(item, Mapping) and item.get("kind") == "EMPLOYMENT_TYPE" and item.get("employment_type") == "PART_TIME"
        for item in (m_field.get("evidence", ()) if isinstance(m_field, Mapping) else ())
    )


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


def render_generated_payroll(
    payroll: GeneratedPayroll,
    output: str | Path,
    *,
    template_path: str | Path | None = None,
    manual_adjustments: Any = (),
    support_snapshot: Mapping[str, Any] | None = None,
) -> str:
    # Preserve prior exports; collisions receive the next numbered name.
    target = safe_output_path(output)
    if not payroll.rows:
        raise ValueError("没有可生成的教师记录，不能创建空的标准工资表。")
    rows = _ordered_rows(payroll)
    target.parent.mkdir(parents=True, exist_ok=True)

    if template_path:
        return _render_with_template(payroll, rows, target, Path(template_path), manual_adjustments=manual_adjustments, support_snapshot=support_snapshot)

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


def _header_column(sheet, labels: tuple[str, ...]) -> int | None:
    """Find one optional column by its Chinese header without requiring it."""
    normalized = {str(item).replace("\n", "").strip() for item in labels}
    for column in range(1, sheet.max_column + 1):
        values = {str(sheet.cell(row, column).value or "").replace("\n", "").strip() for row in (3, 4)}
        if values.intersection(normalized):
            return column
    return None


def is_payroll_template(path: str | Path) -> bool:
    """Return whether a local workbook satisfies the production template contract.

    This is intentionally a read-only shape check.  It does not treat any
    values in the workbook as payroll authority; the renderer clears the data
    area and writes the current Run's Core result.
    """
    try:
        book = load_workbook(path, data_only=False, read_only=False, keep_links=True)
        if not book.worksheets:
            return False
        _template_headers(book.worksheets[0])
        return True
    except Exception:
        return False


def _manual_value(row: Any, code: str, adjustments: Mapping[tuple[str, str], Any]) -> object:
    key = ("".join(str(row.teacher).split()), code)
    adjustment = adjustments.get(key)
    if adjustment is not None:
        return adjustment.final_value
    return _field_value(row, code)


def _source_annotation(row: Any, field_code: str, label: str, text: str, *, source_type: str, source_file: str = "", source_sheet: str = "", source_row: str = "", source_field: str = "", generated_from: str = "") -> dict[str, str]:
    return {
        "teacher_id": str(getattr(row, "teacher", "")), "teacher": str(getattr(row, "teacher", "")),
        "field_code": field_code, "display_label": label, "text": text,
        "source_type": source_type, "source_file": Path(source_file).name if source_file else "",
        "source_sheet": source_sheet, "source_row": source_row, "source_field": source_field,
        "generated_from": generated_from,
    }


def _refund_annotations_for_row(row: Any, inputs: Any, period: str) -> list[dict[str, str]]:
    """Build AN notes from the same approved, current-period result rows as AN."""
    final_fields = getattr(row, "final_fields", {}) or {}
    an_field = final_fields.get("AN") if isinstance(final_fields, Mapping) else None
    if not isinstance(an_field, Mapping) or an_field.get("state") != "DETERMINED" or an_field.get("value") is None:
        return []
    teacher = "".join(str(row.teacher).split())
    annotations: list[dict[str, str]] = []
    for item in inputs or ():
        if not isinstance(item, Mapping):
            continue
        if str(item.get("input_type") or "").upper() != "REFUND_RESULT" or str(item.get("status") or "").upper() != "APPROVED":
            continue
        if str(item.get("period") or period) != period:
            continue
        bound = "".join(str(item.get("teacher_id") or item.get("teacher_name") or "").split())
        if bound != teacher:
            continue
        payload = item.get("payload") if isinstance(item.get("payload"), Mapping) else item
        student = str(payload.get("student") or payload.get("学生") or payload.get("学生姓名") or payload.get("学员") or payload.get("姓名") or "").strip()
        business_type = str(payload.get("business_type") or payload.get("item_type") or payload.get("业务类型") or payload.get("事项") or "").strip()
        if not business_type:
            business_type = " / ".join(str(payload.get(key) or "").strip() for key in ("退费科目", "科目类型", "新签/续费") if str(payload.get(key) or "").strip()) or "退费"
        reason = str(payload.get("note") or payload.get("备注") or payload.get("退费原因") or "").strip()
        head = payload.get("headcount_amount", payload.get("人头", payload.get("退费人头")))
        performance = payload.get("performance_amount", payload.get("业绩", payload.get("退费业绩")))
        parts = []
        if head not in (None, "", 0, 0.0):
            parts.append(f"人头金额：{head:g} 元" if isinstance(head, (int, float)) else f"人头金额：{head} 元")
        if performance not in (None, "", 0, 0.0):
            parts.append(f"业绩金额：{performance:g} 元" if isinstance(performance, (int, float)) else f"业绩金额：{performance} 元")
        raw_total = payload.get("AN", payload.get("refund_total", payload.get("退费合计")))
        if not parts and raw_total not in (None, ""):
            parts.append(f"退费合计：{raw_total} 元")
        if not parts:
            continue
        source_row = str(item.get("source_row") or "")
        source_sheet, _, row_text = source_row.partition("!")
        input_evidence = item.get("evidence") if isinstance(item.get("evidence"), Mapping) else {}
        source_sheet = source_sheet or str(input_evidence.get("sheet") or "")
        if source_sheet:
            source_row = row_text or str(input_evidence.get("row") or "")
        lines = [f"教师：{row.teacher}"]
        if student:
            lines.append(f"学生：{student}")
        lines.append(f"业务类型：{business_type}")
        if reason:
            lines.append(f"备注：{reason}")
        lines.extend(parts)
        try:
            components = [value for value in (head, performance) if value not in (None, "")]
            total = sum(float(value) for value in components) if components else float(raw_total)
            lines.append(f"本条计入 AN：{total:g} 元")
        except (TypeError, ValueError):
            pass
        annotations.append(_source_annotation(
            row, "AN", "AN｜退费", "\n".join(lines), source_type="APPROVED_REFUND_RESULT",
            source_file=str(item.get("source_ref") or ""), source_sheet=source_sheet or str(payload.get("source_sheet") or ""),
            source_row=source_row, source_field="人头金额/业绩金额/退费合计", generated_from="AN_APPROVED_REFUND_INPUT",
        ))
    return annotations


def _core_annotations_for_row(row: Any, payroll: GeneratedPayroll) -> list[dict[str, str]]:
    annotations: list[dict[str, str]] = []
    fields = getattr(row, "final_fields", {}) or {}
    core_fields = getattr(row, "fields", {}) or {}
    # Renewal inputs and AK's derived amount remain traceable in the actual
    # workbook, not just in the JSON reconciliation view.
    for code in ("AH", "AI", "AJ", "AK"):
        field = fields.get(code) if isinstance(fields, Mapping) else None
        if not isinstance(field, Mapping) or field.get("value") is None:
            continue
        evidence = [item for item in (field.get("evidence") or []) if isinstance(item, Mapping)]
        if code == "AK":
            inputs = evidence[0].get("inputs", {}) if evidence else {}
            text = f"AK = AH×1 + AI×1.5 + AJ×0.75；本次 AH={inputs.get('AH', '—')}，AI={inputs.get('AI', '—')}，AJ={inputs.get('AJ', '—')}。"
            annotations.append(_source_annotation(row, code, "AK｜续费绩效", text, source_type="PAYROLL_DERIVATION", source_field="AH/AI/AJ", generated_from="AK_CALCULATION"))
            continue
        source = evidence[0] if evidence else {}
        source_name = str(source.get("source") or "")
        source_row = str(source.get("source_row") or "")
        source_sheet, _, source_row = source_row.partition("!")
        values = source.get("inputs") if isinstance(source.get("inputs"), Mapping) else {}
        detail = next(iter(values.values()), field.get("value"))
        label = {"AH": "AH｜一对一续费", "AI": "AI｜班课续费", "AJ": "AJ｜领航续费"}[code]
        text = f"本期确认值：{detail}。来源：{Path(source_name).name or '已确认续费快照'}。"
        annotations.append(_source_annotation(row, code, label, text, source_type="CONFIRMED_RENEWAL", source_file=source_name, source_sheet=source_sheet, source_row=source_row, source_field=str(source.get("field") or code), generated_from="RUN_RENEWAL_RESULT_SNAPSHOT"))

    # Explain class-course AC from the existing Core contribution evidence;
    # no new calculation is performed here.
    ac = core_fields.get("AC") if isinstance(core_fields, Mapping) else None
    if isinstance(ac, Mapping) and ac.get("state") == "DETERMINED" and ac.get("value") is not None:
        evidence = [item for item in (ac.get("evidence") or []) if isinstance(item, Mapping) and item.get("kind") == "COURSE_CALCULATION"]
        if evidence:
            record_sources = {
                str(item.get("record_key") or ""): item
                for item in payroll.source_records if isinstance(item, Mapping)
            }
            grouped: dict[tuple[str, str], dict[str, Any]] = {}
            source_names: set[str] = set()
            source_sheets: set[str] = set()
            source_rows: set[str] = set()
            for item in evidence:
                inputs = item.get("inputs") if isinstance(item.get("inputs"), Mapping) else {}
                key = (str(item.get("formula") or "已确认班课规则"), json.dumps(inputs, ensure_ascii=False, sort_keys=True))
                bucket = grouped.setdefault(key, {"count": 0, "value": 0.0})
                bucket["count"] += 1
                try:
                    bucket["value"] += float(str(item.get("detail", "")).rsplit("=", 1)[-1].strip())
                except (TypeError, ValueError):
                    pass
                source = record_sources.get(str(item.get("record_key") or ""), {})
                if isinstance(source, Mapping):
                    if source.get("source"):
                        source_names.add(Path(str(source["source"])).name)
                    provenance = source.get("provenance") if isinstance(source.get("provenance"), Mapping) else {}
                    for source_item in provenance.values():
                        if not isinstance(source_item, Mapping):
                            continue
                        if source_item.get("sheet"):
                            source_sheets.add(str(source_item["sheet"]))
                        coordinate = str(source_item.get("coordinate") or "")
                        row_match = re.search(r"(\d+)$", coordinate)
                        if row_match:
                            source_rows.add(row_match.group(1))
            lines = [f"AC 合计：{float(ac['value']):g} 小时，共 {len(evidence)} 条确定的班课贡献。"]
            for (formula, inputs_json), summary in list(grouped.items())[:6]:
                inputs = json.loads(inputs_json)
                basis = "，".join(f"{name}={value}" for name, value in inputs.items() if name not in {"record_key"})
                lines.append(f"{summary['count']} 条：{basis or formula}；小计 {summary['value']:g} 小时。")
            annotations.append(_source_annotation(row, "AC", "AC｜班课折算小时", "\n".join(lines), source_type="CORE_CLASS_CALCULATION", source_file="、".join(sorted(source_names)), source_sheet="、".join(sorted(source_sheets)), source_row=",".join(sorted(source_rows, key=lambda value: int(value))), source_field="年级/班型/实到/状态", generated_from="CORE_AC_EVIDENCE"))

    # AF carries the current part-time decision or current Core result; a
    # deferred choice stays blank but remains explicitly explained.
    af = fields.get("AF") if isinstance(fields, Mapping) else None
    if _is_part_time_row(row) and isinstance(af, Mapping) and (af.get("value") is not None or af.get("state") == "DEFERRED"):
        amount = af.get("value")
        text = f"本月兼职工资：{amount} 元。" if amount is not None else "本月兼职工资暂时留白，待补充；未按 0 计算。"
        if af.get("reason"):
            text += f"\n依据：{af['reason']}"
        source_file = ""
        source_field = "兼职工资决定"
        for item in af.get("evidence", ()):
            if isinstance(item, Mapping):
                source_file = str(item.get("source") or source_file)
                if item.get("inputs"):
                    source_field = ", ".join(str(key) for key in item["inputs"] if key not in {"confirmed_by", "confirmed_at", "reason"}) or source_field
        annotations.append(_source_annotation(row, "AF", "AF｜兼职工资", text, source_type="PART_TIME_PAY_DECISION", source_file=source_file, source_field=source_field, generated_from="CURRENT_RUN_PART_TIME_DECISION"))
    return annotations


def _annotation_column(sheet, field_code: str, columns: Mapping[str, int]) -> int | None:
    code = str(field_code or "").strip().upper()
    if code == "TEACHER":
        return columns.get("teacher")
    if code.lower() in columns:
        return columns[code.lower()]
    if code in FINAL_FIELD_CODES:
        return 33 + FINAL_FIELD_CODES.index(code)
    try:
        return column_index_from_string(code)
    except ValueError:
        return None


def _support_entry(snapshot: Mapping[str, Any] | None, teacher: str) -> Mapping[str, Any] | None:
    """The 支持部 snapshot row for one teacher, if the source is bound."""
    if not isinstance(snapshot, Mapping):
        return None
    entries = snapshot.get("entries")
    if not isinstance(entries, Mapping):
        return None
    entry = entries.get(teacher)
    if isinstance(entry, Mapping):
        return entry
    return next(
        (item for item in entries.values() if isinstance(item, Mapping) and str(item.get("display_name", "")) == teacher),
        None,
    )


def _render_with_template(
    payroll: GeneratedPayroll,
    rows: tuple[Any, ...],
    target: Path,
    template: Path,
    *,
    manual_adjustments: Any = (),
    support_snapshot: Mapping[str, Any] | None = None,
) -> str:
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
    adjustments = adjustment_by_teacher_field(manual_adjustments)
    for row_number in range(first_data_row, sheet.max_row + 1):
        for column in range(1, sheet.max_column + 1):
            cell = sheet.cell(row_number, column)
            cell.value = None
            cell.comment = None
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
        # B 科组 / D 邮箱 / E 入职日期 / F 教师级别.  In normal operation the
        # support department supplies all four, so they are inherited verbatim
        # from the same reviewed workbook rather than retyped.  Nothing else is
        # copied from that file: the payroll amounts stay this Run's own result.
        support = _support_entry(support_snapshot, str(row.teacher))
        support_level = None
        if support is not None:
            identity = support.get("identity") if isinstance(support.get("identity"), Mapping) else {}
            for key, headers in (("group", ("科组",)), ("email", ("邮箱",)), ("hire_date", ("入职日期",))):
                header = _header_column(sheet, headers)
                value = identity.get(key)
                if header and value not in (None, ""):
                    sheet.cell(row_number, header).value = value
            support_level = identity.get("teacher_level")
        base_inputs = {}
        m_field = row.final_fields.get("M", {}) if isinstance(getattr(row, "final_fields", None), Mapping) else {}
        is_part_time = _is_part_time_row(row)
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
        # F 教师级别: the support department's own wording wins when that
        # reviewed workbook is bound (its level text is the source the payroll
        # office reads).  Otherwise the rating authority's display is used, so
        # a Run without a support source keeps working exactly as before.
        if support_level not in (None, ""):
            sheet.cell(row_number, columns["star"]).value = support_level
        elif star_display is not None:
            sheet.cell(row_number, columns["star"]).value = star_display
        sheet.cell(row_number, columns["aa"]).value = _formula_for_row(row, "AA", row_number)
        sheet.cell(row_number, columns["ac"]).value = _value(row.class_value)
        sheet.cell(row_number, columns["ad"]).value = _formula_for_row(row, "AD", row_number)
        sheet.cell(row_number, columns["ae"]).value = _value(row.ae)
        # AF may be an ESTIMATED Core value when the package supplies a
        # historical rating.  Keep that visible in the payroll column; the
        # evidence/status columns still make clear that it is not final.
        af_field = row.final_fields.get("AF", {}) if isinstance(getattr(row, "final_fields", None), Mapping) else {}
        sheet.cell(row_number, columns["af"]).value = (
            _value(af_field.get("value")) if is_part_time and af_field.get("state") == "DETERMINED"
            else None if is_part_time
            else _formula_for_row(row, "AF", row_number)
        )
        # Keep blocked M rows visibly unresolved instead of letting Excel's
        # blank-cell arithmetic silently display a misleading zero.  Once the
        # Run snapshot has supplied every G:L input, retain the canonical
        # template formula verbatim.
        sheet.cell(row_number, columns["m"]).value = (
            _formula_for_row(row, "M", row_number)
            if m_field.get("state") == "DETERMINED" else None
        )
        av_field = row.final_fields.get("AV", {}) if isinstance(getattr(row, "final_fields", None), Mapping) else {}
        ak_field = row.final_fields.get("AK", {}) if isinstance(getattr(row, "final_fields", None), Mapping) else {}
        sheet.cell(row_number, columns["av"]).value = (
            _formula_for_row(row, "AV", row_number)
            if av_field.get("state") == "DETERMINED" else None
        )
        sheet.cell(row_number, 37).value = (
            _formula_for_row(row, "AK", row_number)
            if ak_field.get("state") == "DETERMINED" else None
        )
        for index, code in enumerate(FINAL_FIELD_CODES):
            if code in {"AK", "AV"}:
                continue
            sheet.cell(row_number, 33 + index).value = _value(_manual_value(row, code, adjustments))
        annotations = list((support or {}).get("annotations") or [])
        annotations.extend(_refund_annotations_for_row(row, manual_adjustments, payroll.period))
        annotations.extend(_core_annotations_for_row(row, payroll))
        by_column: dict[int, list[dict[str, Any]]] = {}
        for annotation in normalize_annotations(annotations):
            column = _annotation_column(sheet, annotation.field_code, columns)
            if column is None or column > sheet.max_column:
                continue
            by_column.setdefault(column, []).append(annotation.as_dict())
        for column, cell_annotations in by_column.items():
            text = comment_text(cell_annotations)
            if text:
                sheet.cell(row_number, column).comment = Comment(text, "工资核算助手")
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
                if code == "AF" and _is_part_time_row(expected):
                    wanted_af = _field_value(expected, "AF")
                    if not _same_output_value(actual, wanted_af):
                        errors.append(f"{expected.teacher} 的兼职 AF 静态金额或留白不一致")
                    continue
                state = (expected.final_fields.get(code, {}) if isinstance(getattr(expected, "final_fields", None), Mapping) else {}).get("state")
                expected_formula = golden_formula_for_row(expected, code, offset) if code != "AV" or state == "DETERMINED" else None
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


def _fresh_sheet(book: Workbook, title: str):
    """Reuse the template's own sheet, or create it when it is absent.

    ``create_sheet`` with an existing title makes openpyxl append a second
    sheet called ``核验与来源1``.  The company template already ships these
    two sheets, so blindly creating them silently changed the approved
    workbook layout.  Reusing the sheet keeps the template's own structure.
    """
    if title in book.sheetnames:
        sheet = book[title]
        for row in sheet.iter_rows():
            for cell in row:
                cell.value = None
                cell.comment = None
        return sheet
    return book.create_sheet(title)


def _write_evidence_sheet(book: Workbook, payroll: GeneratedPayroll, rows: tuple[Any, ...]) -> None:
    sheet = _fresh_sheet(book, "核验与来源")
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
    for row in rows:
        for field_name, field in {**row.fields, **row.final_fields}.items():
            sheet.append([
                row.teacher,
                field_name,
                _value(field.get("value")),
                field.get("state", ""),
                field.get("reason", ""),
                json.dumps(field.get("evidence", []), ensure_ascii=False, sort_keys=True, default=str),
                payroll.rule_versions.get("core", ""),
            ])
    # A compact source index lets a reviewer resolve the opaque record_key in
    # course evidence back to the source file and source cells.
    start = sheet.max_row + 2
    sheet.cell(start, 1, "课程记录来源索引").font = Font(bold=True)
    for column, value in enumerate(("record_key", "教师", "源文件", "来源证据(JSON)"), start=1):
        sheet.cell(start + 1, column, value).font = Font(bold=True)
    for item in payroll.source_records:
        sheet.append([
            item.get("record_key", ""), item.get("teacher", ""), item.get("source", ""),
            json.dumps(item.get("provenance", {}), ensure_ascii=False, sort_keys=True, default=str),
        ])
    _set_widths(sheet, {1: 18, 2: 12, 3: 18, 4: 18, 5: 46, 6: 80, 7: 26})


def _write_boundary_sheet(book: Workbook, payroll: GeneratedPayroll, rows: tuple[Any, ...]) -> None:
    sheet = _fresh_sheet(book, "外围字段状态")
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
        expected_detail = [
            [
                row.teacher,
                field_name,
                _value(field.get("value")),
                field.get("state", ""),
                field.get("reason", ""),
                json.dumps(field.get("evidence", []), ensure_ascii=False, sort_keys=True, default=str),
                payroll.rule_versions.get("core", ""),
            ]
            for row in expected_rows
            for field_name, field in {**row.fields, **row.final_fields}.items()
        ]
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
        source_start = 9 + len(expected_detail)
        if evidence_sheet.cell(source_start, 1).value != "课程记录来源索引":
            errors.append("缺少课程记录来源索引")
        source_headers = ["record_key", "教师", "源文件", "来源证据(JSON)"]
        if [evidence_sheet.cell(source_start + 1, column).value for column in range(1, 5)] != source_headers:
            errors.append("课程记录来源索引表头发生变化")
        expected_sources = [
            [
                item.get("record_key", ""), item.get("teacher", ""), item.get("source", ""),
                json.dumps(item.get("provenance", {}), ensure_ascii=False, sort_keys=True, default=str),
            ]
            for item in payroll.source_records
        ]
        for row_number, wanted_row in enumerate(expected_sources, start=source_start + 2):
            actual_row = [evidence_sheet.cell(row_number, column).value for column in range(1, 5)]
            if actual_row != wanted_row:
                errors.append(f"课程记录来源索引第 {row_number} 行发生变化")
        expected_max_row = source_start + 1 + len(expected_sources)
        if evidence_sheet.max_row != expected_max_row:
            errors.append("核验与来源行数发生变化")
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
