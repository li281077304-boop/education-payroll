"""Exercise the actual local HTTP decision loop with artificial workbooks."""
import base64
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


def test_local_drag_drop_upload_stays_in_run_data_and_returns_hash(tmp_path):
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    service = PayrollService(tmp_path / "app-data")
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        content = b"teacher,grade\nDemo Teacher,Grade 8\n"
        request = Request(
            base + "/api/upload",
            data=json.dumps({"name": "脱敏课表.csv", "content_base64": base64.b64encode(content).decode()}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-Payroll-Token": token},
        )
        uploaded = json.loads(urlopen(request).read())
        path = Path(uploaded["path"])
        assert path.parent == service.root / "uploads"
        assert path.read_bytes() == content
        assert uploaded["sha256"]
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_material_ui_exposes_drag_drop_and_post_file_picker():
    source = (Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "data-drop-role" in source
    assert 'api("/api/upload"' in source
    assert 'zone.addEventListener("paste"' in source
    assert 'api("/api/pick", { method: "POST", body: "{}" })' in source
    assert 'data-drop-role="package"' in source
    assert 'data-drop-role="subject_group"' in source
    assert 'data-drop-role="${kind}"' in source
    assert 'businessMaterialCard("renewal"' in source
    assert 'businessMaterialCard("refund"' in source
    assert "uploadMaterialFiles" in source
    assert "materialBusy" in source
    assert "正在读取并识别" in source
    assert "选择按钮仅作为备用入口" in source
    assert "学科组提交表" in source
    assert "续费表" in source
    assert "退费表" in source


def test_material_ui_uses_previous_month_and_plain_start_action():
    source = (Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "function defaultPayrollPeriod" in source
    assert "开始核算并查看预览" in source
    assert "工资表汇总" not in source
    assert "核算日" not in source
