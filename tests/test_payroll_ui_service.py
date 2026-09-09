from pathlib import Path
from shutil import copyfile
from threading import Thread
from urllib.request import Request, urlopen
import json

from openpyxl import load_workbook

from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService


FIXTURES = Path(__file__).parent / "fixtures" / "excel"


def _payroll_with_only(path: Path, row: int) -> None:
    copyfile(FIXTURES / "fake_payroll.xlsx", path)
    book = load_workbook(path)
    sheet = book.active
    for remove in sorted(({5, 6} - {row}), reverse=True):
        sheet.delete_rows(remove)
    book.save(path)


def _prepared_run(tmp_path: Path):
    schedule = tmp_path / "schedule.xlsx"; copyfile(FIXTURES / "fake_schedule.xlsx", schedule)
    math = tmp_path / "math.xlsx"; _payroll_with_only(math, 5)
    science = tmp_path / "science.xlsx"; _payroll_with_only(science, 6)
    service = PayrollService(tmp_path / "app-data")
    run = service.create("2026-08")
    for role, path in (("schedule", schedule), ("math", math), ("science", science)):
        run = service.import_file(run["id"], role, str(path))
    return service, run, schedule


def test_ui_run_never_passes_when_ae_af_av_have_no_independent_authority(tmp_path):
    service, run, _ = _prepared_run(tmp_path)

    result = service.check(run["id"])

    assert result["status"] == "REVIEW_REQUIRED"
    states = {row["field"]: row["state"] for row in result["field_status"]}
    assert states["ae"] == "公式复算 / 待权威确认"
    assert states["af"] == "公式复算 / 待权威确认"
    assert states["av"] == "仅读取 / 待人工确认"


def test_ui_marks_run_stale_when_original_file_changes(tmp_path):
    service, run, schedule = _prepared_run(tmp_path)
    with schedule.open("ab") as handle:
        handle.write(b"changed")

    result = service.get(run["id"])

    assert result["status"] == "STALE"


def test_special_decision_is_rechecked_not_used_to_force_full_pass(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    checked = service.check(run["id"])
    issue = next(item for item in checked["issues"] if item["field"] == "class_value")

    service.decide(run["id"], issue["id"], "special", "审核人", "脱敏的特殊班型说明")
    rechecked = service.check(run["id"])

    assert rechecked["status"] == "REVIEW_REQUIRED"
    assert next(item for item in rechecked["field_status"] if item["field"] == "class_value")["state"] == "已核对"


def test_loopback_ui_bootstrap_and_create_run(tmp_path):
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), PayrollService(tmp_path / "app-data"), static)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        token = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        request = Request(base + "/api/runs", data=b'{"period":"2026-08"}', method="POST", headers={"Content-Type": "application/json", "X-Payroll-Token": token})
        payload = json.loads(urlopen(request).read())
        assert payload["period"] == "2026-08"
    finally:
        server.shutdown(); server.server_close(); worker.join()
