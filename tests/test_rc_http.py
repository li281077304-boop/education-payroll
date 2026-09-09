"""Exercise the actual local HTTP decision loop with artificial workbooks."""
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, urlopen

from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService
from test_payroll_ui_service import _prepared_run


def test_business_decision_http_save_rerun_and_reopen(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]

    def call(path, payload=None):
        req = Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"X-Payroll-Token": token, "Content-Type": "application/json"})
        return json.loads(urlopen(req).read())

    try:
        prefix = f"/api/runs/{run['id']}"
        checked = call(prefix + "/check", {})
        group = next(g for g in checked["issue_groups"] if "class_value" in str(g))
        detail = call(prefix + "/evidence?issue=" + group["id"])
        assert detail["field_records"]
        assert detail["evidence"]
        saved = call(prefix + "/decisions", {
            "issue_id": group["id"], "action": "DEFERRED", "person": "验收员",
            "reason": "人工构造样本，待核实依据，不认定工资正确或错误。",
            "fingerprint": detail["issue"]["fingerprint"],
        })
        assert saved["business_decisions"]
        rerun = call(prefix + "/check", {})
        matched = next(g for g in rerun["issue_groups"] if g["root_cause_key"] == group["root_cause_key"])
        assert matched["decision"]["status"] == "ACTIVE"
        assert rerun["status"] != "PASS"
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    reopened = PayrollService(tmp_path / "app-data").get(run["id"])
    matched = next(g for g in reopened["issue_groups"] if g["root_cause_key"] == group["root_cause_key"])
    assert matched["decision"]["reason"].startswith("人工构造样本")
