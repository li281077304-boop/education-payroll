"""人工月权威资料（制度文件）的批量识别与导入。

产品逻辑：人工月是**基础权威资料**，不是每月让用户重新确认一次的东西。

优先级：已导入的人工月资料 > 已人工确认保存的人工月 > 用户本次手填 > 自然月兜底。
课表日期和文件名只用来校验，不能反过来定义人工月。
"""
from __future__ import annotations

import csv

import pytest

from payroll_ui.period_document import read_period_document
from payroll_ui.service import PayrollService

DOCUMENT = """# 测试规章制度知识库

> 本文档由对话梳理导出。

---

## 1. 工龄工资规定

| 年限 | 金额（元） |
|:---:|:---:|
| 1 年 | 100 |
| 3 年 | 300 |

---

## 2. 2026 年人工月排期表

> 人工月 = 公司的薪资计算周期（按 4 周 / 5 周划分），非自然月。

| 人工月 | 周数 | 日期范围 |
|:---:|:---:|:---|
| 7 | 5 周 | 6.29 — 8.02 |
| 8 | 4 周 | 8.03 — 8.30 |
| 9 | 4 周 | 8.31 — 9.27 |

- 全年共 **52 周**
"""

SCHEDULE_HEADERS = ["teacher", "grade", "subject", "class_type", "attended", "lesson_status", "time"]
PAYROLL_HEADERS = ["teacher", "one_to_one", "class_value", "production", "ae", "af", "av"]


def _document(tmp_path, text: str = DOCUMENT, name: str = "知识库.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _write_csv(path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _lessons(days):
    return [["核算负责人甲", "九年级", "数学", "1对1", 1, "已上课", f"{day} 10:00"] for day in days]


def _august_materials(tmp_path, days):
    schedule = _write_csv(tmp_path / "schedule.csv", SCHEDULE_HEADERS, _lessons(days))
    payroll = _write_csv(tmp_path / "math.csv", PAYROLL_HEADERS, [["核算负责人甲", 40, 0, 40, 30, 300, 0]])
    return schedule, payroll


def _import_document(service: PayrollService, path, actor: str = "核算负责人"):
    preview = service.preview_period_document(str(path))
    return service.import_period_document(str(path), preview["source"]["sha256"], actor), preview


# --------------------------------------------------------------------------- 1-2


def test_a_markdown_regulation_document_yields_its_manual_months(tmp_path):
    """1. Markdown 文件中识别人工月，并跳过无关表格。"""
    document = read_period_document(_document(tmp_path))

    assert document.can_import is True
    assert document.year == 2026
    assert document.title == "测试规章制度知识库"
    assert [(row.label, row.period_start, row.period_end, row.payroll_period) for row in document.rows] == [
        ("7", "2026-06-29", "2026-08-02", "2026-07"),
        ("8", "2026-08-03", "2026-08-30", "2026-08"),
        ("9", "2026-08-31", "2026-09-27", "2026-09"),
    ]
    # 工龄工资那张表必须被跳过
    assert all("年限" not in row.source_text for row in document.rows)


def test_the_preview_never_writes_an_authority(tmp_path):
    """2. 预览阶段不写数据库。"""
    service = PayrollService(tmp_path / "data")
    document = _document(tmp_path)

    preview = service.preview_period_document(str(document))

    assert preview["can_import"] is True
    assert len(preview["rows"]) == 3
    assert preview["counts"] == {"NEW": 3, "UPDATE": 0, "UNCHANGED": 0}
    assert service.period_authorities() == []
    assert service.store.list_period_authorities() == []


# --------------------------------------------------------------------------- 3-6


def test_one_confirmation_writes_every_recognised_month(tmp_path):
    """3. 确认后一次写入多条 authority。"""
    service = PayrollService(tmp_path / "data")
    result, _preview = _import_document(service, _document(tmp_path))

    assert result["imported"] == 3
    assert result["counts"] == {"created": 3, "updated": 0, "unchanged": 0}
    assert len(service.period_authorities()) == 3
    august = service.period_authority_for("2026-08")
    assert (august["period_start"], august["period_end"]) == ("2026-08-03", "2026-08-30")
    assert august["boundary_source"] == "MANUAL_PERIOD_DOCUMENT"


def test_reimporting_the_same_document_does_not_add_revisions(tmp_path):
    """4. 同一资料重复导入不重复生成 revision。"""
    service = PayrollService(tmp_path / "data")
    document = _document(tmp_path)
    _import_document(service, document)
    first = {item["payroll_period"]: item for item in service.period_authorities()}

    second, preview = _import_document(service, document)

    assert second["counts"] == {"created": 0, "updated": 0, "unchanged": 3}
    assert preview["counts"] == {"NEW": 0, "UPDATE": 0, "UNCHANGED": 3}
    again = {item["payroll_period"]: item for item in service.period_authorities()}
    assert {month: item["revision"] for month, item in again.items()} == {
        month: item["revision"] for month, item in first.items()
    }
    assert {month: item["authority_id"] for month, item in again.items()} == {
        month: item["authority_id"] for month, item in first.items()
    }


def test_a_changed_cycle_creates_a_new_revision_and_supersedes_the_old_one(tmp_path):
    """5. 资料内容变化 → 新 revision 并 supersede，旧版本保留。"""
    service = PayrollService(tmp_path / "data")
    document = _document(tmp_path)
    _import_document(service, document)
    original = service.period_authority_for("2026-08")

    document.write_text(DOCUMENT.replace("| 8 | 4 周 | 8.03 — 8.30 |", "| 8 | 4 周 | 8.04 — 8.30 |"), encoding="utf-8")
    result, preview = _import_document(service, document)

    assert preview["counts"]["UPDATE"] == 1
    assert result["counts"]["updated"] == 1
    updated = service.period_authority_for("2026-08")
    assert updated["period_start"] == "2026-08-04"
    assert updated["revision"] == original["revision"] + 1
    assert updated["supersedes"] == original["id"]
    history = {item["authority_id"]: item["status"] for item in service.period_authorities()}
    assert history[original["id"]] == "SUPERSEDED"
    assert history[updated["id"]] == "ACTIVE"


def test_an_imported_authority_carries_full_provenance(tmp_path):
    """6. 从资料导入的 authority 带完整来源可追溯信息。"""
    service = PayrollService(tmp_path / "data")
    document = _document(tmp_path)
    preview = service.preview_period_document(str(document))
    service.import_period_document(str(document), preview["source"]["sha256"], "核算负责人")

    source = service.period_authority_for("2026-08")["source"]

    assert source["source_type"] == "DOCUMENT"
    assert source["source_file"] == "知识库.md"
    assert source["source_hash"] == preview["source"]["sha256"]
    assert source["source_section"] == "2. 2026 年人工月排期表"
    assert source["source_row"] > 0
    assert "8.03 — 8.30" in source["source_text"]
    assert source["imported_at"]
    assert source["confirmed_by"] == "核算负责人"
    # 本机绝对路径不进入记录
    assert "/Users/" not in str(source)


# --------------------------------------------------------------------------- 7-9


def test_a_new_run_uses_the_imported_manual_month_automatically(tmp_path):
    """7. 新 Run 自动绑定人工月。"""
    service = PayrollService(tmp_path / "data")
    _import_document(service, _document(tmp_path))

    run = service.create("2026-08", "GENERATE")

    assert (run["period_start"], run["period_end"]) == ("2026-08-03", "2026-08-30")
    assert run["period_boundary_source"] == "MANUAL_PERIOD_DOCUMENT"
    assert run["period_authority"]["source_label"] == "人工月资料（制度文件导入）"
    assert run["period_authority"]["source"]["source_file"] == "知识库.md"


def test_an_existing_fallback_run_recovers_once_the_document_is_imported(tmp_path):
    """8. 已有自然月 fallback 的 Run 在资料导入后自动恢复。"""
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    assert run["period_end"] == "2026-08-31" and run["period_authority"]["is_fallback"] is True

    _import_document(service, _document(tmp_path))
    healed = service.ensure_period_authority(run["id"])

    assert (healed["period_start"], healed["period_end"]) == ("2026-08-03", "2026-08-30")
    assert healed["period_authority"]["is_fallback"] is False
    assert healed["period_authority"]["source"]["source_file"] == "知识库.md"


def test_the_official_document_replaces_a_temporary_hand_written_authority(tmp_path):
    """9. 先有临时 authority 时，正式资料按版本规则替代它。"""
    service = PayrollService(tmp_path / "data")
    temporary = service.record_period_authority(
        "2026-08", "2026-08-01", "2026-08-30", "MANUAL_PERIOD_RECORD",
        confirmed_by="核算负责人", reason="临时按 8/1 起",
    )
    assert service.period_authority_for("2026-08")["source_label"] == "人工月资料（来源未标明）"

    result, _preview = _import_document(service, _document(tmp_path))

    assert "2026-08" in [item["payroll_period"] for item in result["updated"]]
    active = service.period_authority_for("2026-08")
    assert (active["period_start"], active["period_end"]) == ("2026-08-03", "2026-08-30")
    assert active["boundary_source"] == "MANUAL_PERIOD_DOCUMENT"
    assert active["supersedes"] == temporary["id"]
    assert active["revision"] == temporary["revision"] + 1
    # 临时记录仍在历史里，可追溯
    old = next(item for item in service.period_authorities() if item["authority_id"] == temporary["id"])
    assert old["status"] == "SUPERSEDED"


# --------------------------------------------------------------------------- 10-12


def test_lessons_outside_the_manual_month_only_report_a_conflict(tmp_path):
    """10. 课表超出人工月只提示冲突，不改人工月。"""
    service = PayrollService(tmp_path / "data")
    _import_document(service, _document(tmp_path))
    run = service.create("2026-08", "GENERATE")
    before = service.period_authority_for("2026-08")
    schedule, payroll = _august_materials(tmp_path, [f"2026-08-{day:02d}" for day in range(3, 31)] + ["2026-09-01"])
    service.import_file(run["id"], "schedule", str(schedule))
    service.import_file(run["id"], "math", str(payroll))

    checked = service.check(run["id"])

    assert checked["period_check"]["outside_authority"] is True
    assert "PERIOD_OUTSIDE_AUTHORITY" in checked["generated_payroll"]["blockers"]
    after = service.period_authority_for("2026-08")
    assert (after["period_start"], after["period_end"]) == (before["period_start"], before["period_end"])
    assert after["revision"] == before["revision"]
    assert after["source"]["source_hash"] == before["source"]["source_hash"]


def test_a_hand_written_authority_is_labelled_as_manual_not_as_document(tmp_path):
    """11. 用户手填显示“人工确认”，不能显示成“人工月资料”。"""
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    schedule, payroll = _august_materials(tmp_path, [f"2026-08-{day:02d}" for day in range(1, 31)])
    service.import_file(run["id"], "schedule", str(schedule))
    service.import_file(run["id"], "math", str(payroll))

    service.confirm_period_window(run["id"], "2026-08-01", "2026-08-30", "核算负责人", "本机确认的周期")

    stored = service.period_authority_for("2026-08")
    assert stored["boundary_source"] == "USER_CONFIRMED"
    assert stored["source_label"] == "人工确认（本机手填）"
    assert stored["source_label"] != "人工月资料（制度文件导入）"
    assert stored["source"] == {}


def test_a_month_without_a_document_can_still_be_filled_in_by_hand(tmp_path):
    """12. 没有 authority 时仍可手填兜底，并且只确认一次。"""
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", "GENERATE")
    assert run["period_authority"]["is_fallback"] is True
    assert "自然月兜底" in run["period_authority"]["source_label"]

    service.record_period_authority(
        "2026-08", "2026-08-01", "2026-08-30", "USER_CONFIRMED",
        confirmed_by="核算负责人", reason="本机手填",
    )
    healed = service.ensure_period_authority(run["id"])

    assert (healed["period_start"], healed["period_end"]) == ("2026-08-01", "2026-08-30")
    assert healed["period_boundary_source"] == "USER_CONFIRMED"
    later = service.create("2026-08", "GENERATE")
    assert (later["period_start"], later["period_end"]) == ("2026-08-01", "2026-08-30")


# --------------------------------------------------------------------------- 其它资料形态


def test_csv_and_excel_documents_are_supported(tmp_path):
    service = PayrollService(tmp_path / "data")
    csv_path = _write_csv(
        tmp_path / "人工月.csv",
        ["人工月", "周数", "日期范围"],
        [[7, "5 周", "2026.06.29 - 2026.08.02"], [8, "4 周", "2026.08.03 - 2026.08.30"]],
    )
    preview = service.preview_period_document(str(csv_path))
    assert preview["source"]["source_type"] == "CSV"
    assert preview["can_import"] is True
    assert [(row["payroll_period"], row["period_start"]) for row in preview["rows"]] == [
        ("2026-07", "2026-06-29"), ("2026-08", "2026-08-03"),
    ]

    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "人工月"
    sheet.append(["人工月", "周数", "日期范围"])
    sheet.append([8, "4 周", "2026-08-03 — 2026-08-30"])
    sheet.append([9, "4 周", "2026-08-31 — 2026-09-27"])
    excel_path = tmp_path / "人工月.xlsx"
    book.save(excel_path)

    excel = service.preview_period_document(str(excel_path))
    assert excel["source"]["source_type"] == "EXCEL"
    assert [row["payroll_period"] for row in excel["rows"]] == ["2026-08", "2026-09"]


def test_a_headerless_csv_keeps_its_first_cycle(tmp_path):
    path = tmp_path / "人工月-无表头.csv"
    path.write_text("7,5 周,6.29 - 8.02\n8,4 周,8.03 - 8.30\n", encoding="utf-8")
    document = read_period_document(path, year=2026)

    assert [(row.payroll_period, row.period_start, row.period_end) for row in document.rows] == [
        ("2026-07", "2026-06-29", "2026-08-02"),
        ("2026-08", "2026-08-03", "2026-08-30"),
    ]


def test_a_cycle_crossing_the_new_year_is_kept(tmp_path):
    path = _write_csv(tmp_path / "跨年.csv", ["人工月", "周数", "日期范围"], [[12, "5 周", "11.30 — 1.03"]])
    document = read_period_document(path, year=2026)

    assert [(row.period_start, row.period_end, row.payroll_period) for row in document.rows] == [
        ("2026-11-30", "2027-01-03", "2026-12"),
    ]


def test_a_broken_document_fails_closed(tmp_path):
    service = PayrollService(tmp_path / "data")
    broken = _document(tmp_path, DOCUMENT.replace("| 8 | 4 周 | 8.03 — 8.30 |", "| 8 | 4 周 | 待定 |"))

    preview = service.preview_period_document(str(broken))

    assert preview["can_import"] is False
    assert preview["problems"]
    with pytest.raises(ValueError, match="无法识别"):
        service.import_period_document(str(broken), preview["source"]["sha256"], "核算负责人")
    assert service.period_authorities() == []


def test_importing_a_changed_file_needs_a_fresh_preview(tmp_path):
    service = PayrollService(tmp_path / "data")
    document = _document(tmp_path)
    preview = service.preview_period_document(str(document))
    document.write_text(DOCUMENT + "\n<!-- 变化 -->\n", encoding="utf-8")

    with pytest.raises(ValueError, match="已变化"):
        service.import_period_document(str(document), preview["source"]["sha256"], "核算负责人")
    assert service.period_authorities() == []


def test_importing_requires_a_confirming_person(tmp_path):
    service = PayrollService(tmp_path / "data")
    document = _document(tmp_path)
    preview = service.preview_period_document(str(document))

    with pytest.raises(ValueError, match="确认人"):
        service.import_period_document(str(document), preview["source"]["sha256"], "  ")
    assert service.period_authorities() == []
