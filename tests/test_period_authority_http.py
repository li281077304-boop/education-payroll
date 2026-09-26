"""人工月接口真的能通过本地 HTTP 用起来。

界面（app.js）只通过 /api/period-authorities 和 /api/runs/<id>/period-authority
两个入口维护人工月，所以这里按浏览器的方式走一遍真实请求，而不是只测 service。
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService


def _client(tmp_path):
    service = PayrollService(tmp_path / "data")
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]

    def call(path, payload=None):
        request = Request(
            base + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"X-Payroll-Token": token, "Content-Type": "application/json"},
        )
        return json.loads(urlopen(request).read())

    return service, server, call


def test_period_authority_round_trip_over_http(tmp_path):
    service, server, call = _client(tmp_path)
    try:
        saved = call("/api/period-authorities", {
            "payroll_period": "2026-08", "period_start": "2026-08-01", "period_end": "2026-08-30",
            "boundary_source": "MANUAL_PERIOD_RECORD", "confirmed_by": "核算负责人",
            "reason": "公司工资周期按 8/1～8/30",
        })
        assert (saved["period_start"], saved["period_end"]) == ("2026-08-01", "2026-08-30")
        assert saved["is_fallback"] is False

        listed = call("/api/period-authorities")
        assert [item["payroll_period"] for item in listed["authorities"]] == ["2026-08"]

        created = call("/api/runs", {"period": "2026-08", "mode": "GENERATE"})
        assert created["period_end"] == "2026-08-30"
        assert created["period_authority"]["is_fallback"] is False
        assert created["period_authority"]["confirmed_by"] == "核算负责人"
    finally:
        server.shutdown()


def test_an_existing_run_can_be_rebound_to_the_authority_over_http(tmp_path):
    service, server, call = _client(tmp_path)
    try:
        created = call("/api/runs", {"period": "2026-08", "mode": "GENERATE",
                                     "period_start": "2026-08-03", "period_end": "2026-08-29",
                                     "period_boundary_source": "USER_CONFIRMED"})
        assert created["period_end"] == "2026-08-29"

        call("/api/period-authorities", {
            "payroll_period": "2026-08", "period_start": "2026-08-01", "period_end": "2026-08-30",
            "boundary_source": "MANUAL_PERIOD_RECORD", "confirmed_by": "核算负责人", "reason": "统一口径",
        })
        rebound = call(f"/api/runs/{created['id']}/period-authority", {"force": True})

        assert (rebound["period_start"], rebound["period_end"]) == ("2026-08-01", "2026-08-30")
        assert rebound["period_boundary_source"] == "MANUAL_PERIOD_RECORD"
        assert rebound["period_authority"]["source_label"] == "人工月资料（来源未标明）"
    finally:
        server.shutdown()


def _document(tmp_path, name: str = "知识库.md"):
    path = tmp_path / name
    path.write_text(
        "# 测试规章制度知识库\n\n"
        "## 2. 2026 年人工月排期表\n\n"
        "| 人工月 | 周数 | 日期范围 |\n|:---:|:---:|:---|\n"
        "| 7 | 5 周 | 6.29 — 8.02 |\n| 8 | 4 周 | 8.03 — 8.30 |\n| 9 | 4 周 | 8.31 — 9.27 |\n",
        encoding="utf-8",
    )
    return path


def test_the_document_preview_is_read_only_over_http(tmp_path):
    service, server, call = _client(tmp_path)
    try:
        document = _document(tmp_path)
        preview = call(f"/api/period-document/preview?path={quote(str(document))}")

        assert preview["can_import"] is True
        assert [row["payroll_period"] for row in preview["rows"]] == ["2026-07", "2026-08", "2026-09"]
        assert preview["counts"] == {"NEW": 3, "UPDATE": 0, "UNCHANGED": 0}
        # 预览阶段绝不能写入任何 authority
        assert call("/api/period-authorities")["authorities"] == []
    finally:
        server.shutdown()


def test_the_document_import_writes_every_month_over_http(tmp_path):
    service, server, call = _client(tmp_path)
    try:
        document = _document(tmp_path)
        preview = call(f"/api/period-document/preview?path={quote(str(document))}")
        imported = call("/api/period-document/import", {
            "path": str(document), "source_sha256": preview["source"]["sha256"], "confirmed_by": "核算负责人",
        })

        assert imported["imported"] == 3
        assert imported["counts"]["created"] == 3
        listed = call("/api/period-authorities")["authorities"]
        august = next(item for item in listed if item["payroll_period"] == "2026-08")
        assert (august["period_start"], august["period_end"]) == ("2026-08-03", "2026-08-30")
        assert august["source"]["source_file"] == "知识库.md"

        created = call("/api/runs", {"period": "2026-08", "mode": "GENERATE"})
        assert (created["period_start"], created["period_end"]) == ("2026-08-03", "2026-08-30")
        assert created["period_boundary_source"] == "MANUAL_PERIOD_DOCUMENT"

        # 重复导入不新增版本
        again = call("/api/period-document/import", {
            "path": str(document), "source_sha256": preview["source"]["sha256"], "confirmed_by": "核算负责人",
        })
        assert again["counts"] == {"created": 0, "updated": 0, "unchanged": 3}
    finally:
        server.shutdown()


def test_a_natural_month_fallback_can_never_be_saved_as_an_authority(tmp_path):
    service, server, call = _client(tmp_path)
    try:
        try:
            call("/api/period-authorities", {
                "payroll_period": "2026-08", "period_start": "2026-08-01", "period_end": "2026-08-31",
                "boundary_source": "LEGACY_CALENDAR_DEFAULT", "confirmed_by": "核算负责人", "reason": "兜底",
            })
        except HTTPError as exc:
            body = json.loads(exc.read())
            assert exc.code == 400 and "来源" in body["error"]
        else:  # pragma: no cover - the call above must fail
            raise AssertionError("自然月兜底不能被保存成人工月记录")
        assert service.period_authority_for("2026-08") is None
    finally:
        server.shutdown()
