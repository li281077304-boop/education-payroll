"""人工月接口真的能通过本地 HTTP 用起来。

界面（app.js）只通过 /api/period-authorities 和 /api/runs/<id>/period-authority
两个入口维护人工月，所以这里按浏览器的方式走一遍真实请求，而不是只测 service。
"""
from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
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
        assert rebound["period_authority"]["source_label"] == "人工月资料"
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
