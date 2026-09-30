"""Excel import compatibility: known adapter first, semantic mapping fallback."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from shutil import copyfile
from threading import Thread
from urllib.parse import quote
from urllib.request import Request, urlopen

import pytest
from openpyxl import Workbook

from payroll_core.excel.schedule import read_schedule_excel
from payroll_core.mapping import SCHEDULE_AC_REQUIREMENT, analyze_mapping
from payroll_core.reconcile.payroll_scope import class_value_contribution
from payroll_ui.service import PayrollService
from payroll_ui.server import PayrollHttpServer
from tests.test_payroll_ui_service import FIXTURES, _prepared_run
from tests.payroll_uat_helpers import import_confirmed_subject_group


def _sheet(path: Path, headers: list[str], rows: list[list[object]], title: str = "课程明细") -> Path:
    book = Workbook()
    sheet = book.active
    sheet.title = title
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    book.save(path)
    return path


ALIAS_HEADERS = ["任课老师", "年级", "学科", "课程所属班型", "实到人数", "上课状态"]
ALIAS_ROWS = [
    ["张三", "八年级", "数学", "1对1", 1, "已上课"],
    ["李四", "高三", "物理", "集体班", 6, "已上课"],
]


def _run(tmp_path: Path):
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08")
    return service, run


def _import(service, run, path: Path, **kwargs):
    return service.import_file(run["id"], "schedule", str(path), **kwargs)


def test_known_schedule_adapter_still_works(tmp_path):
    """The original export keeps using its fast path, unchanged."""
    source = FIXTURES / "fake_schedule.xlsx"
    known = read_schedule_excel(source, "2026-08")
    assert known.ok and known.records

    service, run = _run(tmp_path)
    imported = _import(service, run, source)

    assert imported["files"]["schedule"]["records"] == len(known.records)
    assert service.preview_import_mapping(str(source), "schedule")["status"] == "KNOWN_LAYOUT"


def test_schedule_column_order_is_not_required(tmp_path):
    shuffled = ["实到人数", "课程所属班型", "学科", "年级", "任课老师"]
    path = _sheet(tmp_path / "shuffled.xlsx", shuffled, [row[::-1] for row in ALIAS_ROWS])

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    assert set(analysis.mapping) >= {"teacher", "grade", "subject", "class_type", "actual_student_count"}
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["records"] == 2


def test_schedule_header_aliases_are_supported(tmp_path):
    headers = ["授课教师", "所属年级", "科目", "班型", "到课人数"]
    path = _sheet(tmp_path / "aliases.xlsx", headers, ALIAS_ROWS)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    assert analysis.mapped_headers["teacher"] == "授课教师"
    assert analysis.mapped_headers["subject"] == "科目"
    assert analysis.mapped_headers["class_type"] == "班型"
    assert analysis.mapped_headers["actual_student_count"] == "到课人数"
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["teachers"] == 2


def test_unrelated_columns_do_not_block_import(tmp_path):
    headers = ["序号", "任课老师", "备注", "年级", "校区", "学科", "课程所属班型", "实到人数"]
    rows = [[1, "张三", "无", "八年级", "宣城二校", "数学", "1对1", 1]]
    path = _sheet(tmp_path / "extra.xlsx", headers, rows)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["records"] == 1


def test_missing_optional_columns_do_not_block_import(tmp_path):
    # No 上课时间 / 上课学员 / 上课班级 at all: optional context only.
    path = _sheet(tmp_path / "minimal.xlsx", ALIAS_HEADERS, ALIAS_ROWS)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)

    assert analysis.ready
    assert not analysis.missing
    service, run = _run(tmp_path)
    imported = _import(service, run, path)
    assert imported["files"]["schedule"]["records"] == 2


def test_missing_required_field_is_named(tmp_path):
    # Only a class headcount exists; 实到人数 is genuinely absent.
    headers = ["任课老师", "年级", "学科", "课程所属班型", "班级人数", "备注"]
    path = _sheet(tmp_path / "no-attendance.xlsx", headers, [["张三", "八年级", "数学", "1对1", 1, "无"]])
    service, run = _run(tmp_path)

    preview = service.preview_import_mapping(str(path), "schedule")

    assert preview["status"] in {"NEEDS_CONFIRMATION", "MISSING_REQUIRED"}
    assert "实到人数" in preview["missing_labels"] or any(item["field"] == "actual_student_count" and item["needs_choice"] for item in preview["fields"])
    with pytest.raises(ValueError) as error:
        _import(service, run, path)
    message = str(error.value)
    assert "实到人数" in message and "检测到的列" in message and "班级人数" in message


def test_mapping_preview_rejects_server_copy_hash_that_differs_from_upload(tmp_path):
    path = _sheet(tmp_path / "mapping-hash.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    service, run = _run(tmp_path)
    with pytest.raises(ValueError, match="字段识别前发生变化"):
        service.preview_import_mapping(str(path), "schedule", "2026-08", expected_sha256="0" * 64)


def test_ambiguous_field_requires_confirmation(tmp_path):
    headers = ["教师", "任课老师", "年级", "学科", "课程所属班型", "实到人数", "班级人数"]
    path = _sheet(tmp_path / "ambiguous.xlsx", headers, [["张三", "张三", "八年级", "数学", "1对1", 1, 8]])
    service, run = _run(tmp_path)

    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)
    preview = service.preview_import_mapping(str(path), "schedule")

    assert analysis.status == "NEEDS_CONFIRMATION"
    assert set(analysis.candidates["teacher"]) == {"教师", "任课老师"}
    assert set(analysis.candidates["actual_student_count"]) == {"实到人数", "班级人数"}
    assert preview["status"] == "NEEDS_CONFIRMATION"
    with pytest.raises(ValueError, match="需要你确认"):
        _import(service, run, path)


def test_manual_mapping_allows_import(tmp_path):
    headers = ["教师", "任课老师", "年级", "学科", "课程所属班型", "实到人数", "班级人数"]
    path = _sheet(tmp_path / "manual.xlsx", headers, [["张三", "张三", "八年级", "数学", "1对1", 3, 8]])
    service, run = _run(tmp_path)
    preview = service.preview_import_mapping(str(path), "schedule")

    imported = _import(service, run, path, mapping={
        "sheet": preview["sheet"], "header_row": preview["header_row"],
        "mapping": {"teacher": 2, "grade": 3, "subject": 4, "class_type": 5, "actual_student_count": 6},
    })

    assert imported["files"]["schedule"]["records"] == 1
    records = service._read("schedule", Path(imported["files"]["schedule"]["path"]), "2026-08").records or []
    detail = service.get(run["id"])
    assert detail["files"]["schedule"]["records"] == 1


def test_fully_unknown_headers_still_offer_columns_for_manual_mapping(tmp_path):
    headers = ["授课人", "所在学段", "学科名称", "课程类别", "签到人数", "开课日期", "授课状态"]
    path = _sheet(tmp_path / "all-unknown-headers.xlsx", headers,
                  [["张三", "九年级", "数学", "1对1", 1, "2026-08-05 10:00", "已上课"]])
    service, run = _run(tmp_path)

    preview = service.preview_import_mapping(str(path), "schedule", "2026-08")
    assert preview["status"] in {"MISSING_REQUIRED", "NEEDS_CONFIRMATION"}
    assert [item["header"] for item in preview["columns"]] == headers
    assert preview["header_row"] == 1

    imported = _import(service, run, path, mapping={
        "sheet": preview["sheet"], "header_row": preview["header_row"],
        "mapping": {"teacher": 1, "grade": 2, "subject": 3, "class_type": 4,
                    "actual_student_count": 5, "lesson_time": 6, "lesson_status": 7},
    }, profile_name="脱敏未知排课格式", profile_actor="合成测试")
    assert imported["files"]["schedule"]["records"] == 1
    next_run = service.create("2026-09")
    next_path = _sheet(tmp_path / "all-unknown-headers-next-month.xlsx", headers,
                       [["张三", "九年级", "数学", "1对1", 1, "2026-09-05 10:00", "已上课"]])
    next_preview = service.preview_import_mapping(str(next_path), "schedule", "2026-09")
    assert next_preview["status"] == "MAPPED"
    assert next_preview["profile_id"]
    next_import = service.import_file(next_run["id"], "schedule", str(next_path))
    assert next_import["files"]["schedule"]["records"] == 1


def test_manual_mapping_keeps_selected_sheet_and_nonfirst_header_row(tmp_path):
    path = tmp_path / "multi-sheet-title-row.xlsx"
    book = Workbook()
    cover = book.active
    cover.title = "说明"
    cover.append(["封面"])
    sheet = book.create_sheet("课程明细")
    sheet.append(["排课资料导出"])
    headers = ["授课人", "所在学段", "学科名称", "课程类别", "签到人数", "开课日期", "授课状态"]
    sheet.append(headers)
    sheet.append(["张三", "九年级", "数学", "1对1", 1, "2026-08-05 10:00", "已上课"])
    book.save(path)
    service, run = _run(tmp_path)

    preview = service.preview_import_mapping(str(path), "schedule", "2026-08")
    assert preview["sheet"] == "课程明细"
    assert preview["header_row"] == 2
    mapping = {"teacher": 1, "grade": 2, "subject": 3, "class_type": 4,
               "actual_student_count": 5, "lesson_time": 6, "lesson_status": 7}
    imported = service.import_file(run["id"], "schedule", str(path), mapping={
        "sheet": preview["sheet"], "header_row": preview["header_row"], "mapping": mapping,
    })
    assert imported["files"]["schedule"]["records"] == 1
    assert imported["schedule_roster_snapshot"]["teachers"][0]["display_name"] == "张三"


def test_browser_upload_copy_survives_original_removal_through_mapping_and_import(tmp_path):
    original = _sheet(
        tmp_path / "unknown-layout.xlsx",
        ["教师", "任课老师", "年级", "学科", "课程所属班型", "实到人数", "班级人数"],
        [["张三", "张三", "八年级", "数学", "1对1", 1, 1]],
    )
    service = PayrollService(tmp_path / "isolated-data")
    run = service.create("2026-08")
    server = PayrollHttpServer(("127.0.0.1", 0), service, Path(__file__).parents[1] / "payroll_ui" / "static")
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def request(path: str, payload: dict | None = None, token: str = "") -> dict:
        if payload is None:
            req = Request(base + path, headers={"X-Payroll-Token": token} if token else {})
        else:
            req = Request(base + path, data=json.dumps(payload).encode("utf-8"), method="POST",
                          headers={"Content-Type": "application/json", "X-Payroll-Token": token})
        return json.loads(urlopen(req, timeout=5).read())

    try:
        token = request("/api/bootstrap")["token"]
        uploaded = request("/api/upload", {
            "name": original.name,
            "content_base64": base64.b64encode(original.read_bytes()).decode("ascii"),
        }, token)
        original.unlink()
        preview = request(
            f"/api/import-mapping?path={quote(uploaded['path'])}&role=schedule&period=2026-08&sha256={uploaded['sha256']}", token=token
        )
        assert preview["source_sha256"] == uploaded["sha256"]
        assert preview["status"] == "NEEDS_CONFIRMATION"
        response = request(f"/api/runs/{run['id']}/files", {
            "role": "schedule", "path": uploaded["path"], "sha256": uploaded["sha256"],
            "name": uploaded["name"],
            "mapping": {"sheet": preview["sheet"], "header_row": preview["header_row"],
                        "mapping": {"teacher": 2, "grade": 3, "subject": 4,
                                    "class_type": 5, "actual_student_count": 6}},
        }, token)
        assert response["files"]["schedule"]["records"] == 1
        assert response["files"]["schedule"]["name"] == original.name
        assert response["files"]["schedule"]["path"] == uploaded["path"]
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_replacing_schedule_source_retires_old_calculation_before_showing_preview(tmp_path):
    service, run = _run(tmp_path)
    first = _sheet(tmp_path / "first-source.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    second = _sheet(tmp_path / "replacement-source.xlsx", ALIAS_HEADERS,
                    [["赵六", "高二", "英语", "小班", 4, "2026-08-06 11:00", "已上课"]])
    _import(service, run, first)
    stored = service._load(run["id"])
    stored["core_calculation"] = {"rows": [{"teacher": "旧来源教师", "fields": {}}]}
    stored["generated_payroll"] = {"path": str(tmp_path / "old-payroll.xlsx"), "rows": []}
    stored["status"] = "REVIEW_REQUIRED"
    service.store.save(stored)

    _import(service, run, second)
    refreshed = service._load(run["id"])

    assert "core_calculation" not in refreshed
    assert "generated_payroll" not in refreshed
    assert refreshed["recalculation_required"] is True
    assert refreshed["calculation_invalidation_history"][-1]["event"] == "MATERIAL_SOURCE_REPLACED"
    assert refreshed["calculation_invalidation_history"][-1]["previous_core_calculation"]["rows"][0]["teacher"] == "旧来源教师"


def test_confirmed_mapping_profile_is_reused(tmp_path):
    first = _sheet(tmp_path / "first.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    second = _sheet(tmp_path / "second.xlsx", ALIAS_HEADERS, [["王五", "高二", "英语", "小班", 4]])
    service, run = _run(tmp_path)
    preview = service.preview_import_mapping(str(first), "schedule")
    confirmed = {"sheet": preview["sheet"], "header_row": preview["header_row"], "mapping": preview["mapping"]}

    _import(service, run, first, mapping=confirmed, profile_name="二校排课格式", profile_actor="教务")
    again = service.preview_import_mapping(str(second), "schedule")

    assert again["status"] == "MAPPED"
    assert again["profile_id"]
    assert again["fields"][0]["header"] == "任课老师"
    other = service.create("2026-09")
    imported = service.import_file(other["id"], "schedule", str(second))
    assert imported["files"]["schedule"]["records"] == 1


def test_profile_drift_requires_reconfirmation(tmp_path):
    original = _sheet(tmp_path / "original.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    # Same headers, same fingerprint, but the columns have been reordered.
    moved = _sheet(tmp_path / "moved.xlsx", ALIAS_HEADERS[::-1], [row[::-1] for row in ALIAS_ROWS])
    service, run = _run(tmp_path)
    preview = service.preview_import_mapping(str(original), "schedule")
    _import(service, run, original, mapping={
        "sheet": preview["sheet"], "header_row": preview["header_row"], "mapping": preview["mapping"],
    }, profile_name="二校排课格式", profile_actor="教务")

    drift = service.preview_import_mapping(str(moved), "schedule")

    assert drift["profile_drift"] is True
    assert drift["status"] == "NEEDS_CONFIRMATION"
    other = service.create("2026-09")
    with pytest.raises(ValueError, match="重新确认"):
        service.import_file(other["id"], "schedule", str(moved))


def test_variant_layout_reaches_reconciliation(tmp_path):
    """The real acceptance: a differently formatted schedule still gets checked."""
    copyfile(FIXTURES / "fake_payroll.xlsx", tmp_path / "combined.xlsx")
    from tests.test_payroll_ui_service import _payroll_with_only_from

    math = tmp_path / "math.xlsx"
    science = tmp_path / "science.xlsx"
    _payroll_with_only_from(tmp_path / "combined.xlsx", math, 5)
    _payroll_with_only_from(tmp_path / "combined.xlsx", science, 6)
    variant = _sheet(tmp_path / "english-variant.xlsx", ["授课教师", "所属年级", "科目", "课程班型", "实际到课人数", "上课状态"],
                     [["张三", "八年级", "英语", "1对1", 1, "已上课"], ["李四", "高三", "英语", "小班", 6, "已上课"]], title="英语组课表")
    service, run = _run(tmp_path)
    _import(service, run, variant)

    for role, path in (("math", math), ("science", science)):
        import_confirmed_subject_group(service, run["id"], role, path)
    checked = service.check(run["id"])

    assert checked["status"] in {"REVIEW_REQUIRED", "PASS", "BLOCKED"}
    assert service.get(run["id"])["files"]["schedule"]["records"] == 2
    assert checked["field_status"]


def test_duration_is_not_required_for_two_hour_default(tmp_path):
    """Every course is two hours by default, so duration must never be required."""
    without_duration = _sheet(tmp_path / "without.xlsx", ALIAS_HEADERS, ALIAS_ROWS)
    with_duration = _sheet(tmp_path / "with.xlsx", ALIAS_HEADERS + ["上课时长"], [row + ["3小时"] for row in ALIAS_ROWS])

    plain = analyze_mapping(without_duration, SCHEDULE_AC_REQUIREMENT)
    extra = analyze_mapping(with_duration, SCHEDULE_AC_REQUIREMENT)

    assert plain.ready and extra.ready
    service, run = _run(tmp_path)
    imported = _import(service, run, without_duration)
    records = service._read("schedule", Path(imported["files"]["schedule"]["path"]), "2026-08").records
    assert len(records) == 2
    assert all(record.duration_text == "" for record in records)
    # The class-value calculation itself carries the two-hour default.
    value, calculation = class_value_contribution(records[1])
    assert value is not None and calculation.endswith(f"× 2 = {value:g}")


def test_real_binary_xls_schedule_and_semantic_mapping():
    path = FIXTURES / "sanitized_schedule.xls"
    analysis = analyze_mapping(path, SCHEDULE_AC_REQUIREMENT)
    assert analysis.ready is True
    assert analysis.mapping["teacher"] == 15
    result = read_schedule_excel(path, "2026-08", period_start="2026-08-01", period_end="2026-08-31")
    assert len(result.records) == 1
    assert result.records[0].lesson_date == "2026-08-10"
