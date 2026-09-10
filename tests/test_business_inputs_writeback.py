from __future__ import annotations

from pathlib import Path
from shutil import copyfile
import json
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from openpyxl import load_workbook
from openpyxl.comments import Comment

from payroll_ui.service import PayrollService
from payroll_ui.server import PayrollHttpServer
from tests.test_payroll_ui_service import FIXTURES, _prepared_run


def _csv(path: Path, rows: str) -> Path:
    path.write_text(rows, encoding="utf-8")
    return path


def _approved_refund(service: PayrollService, tmp_path: Path) -> dict:
    source = _csv(tmp_path / "refund.csv", "教师,学生,退费金额,说明\n教师甲,学生甲,100,已确认退费\n")
    item = service.import_business_results("REFUND_RESULT", "2026-08", str(source), "审核员")[0]
    return service.review_business_input(item["id"], "APPROVE", "审核员", "上游结果已确认")


def test_teacher_can_submit_own_business_input(tmp_path):
    service = PayrollService(tmp_path / "data")
    access = service.create_teacher_access("教师甲")
    submitted = service.teacher_submit(access["access_token"], "2026-08", "班课特殊核算", "请核实本节课程")
    assert submitted["teacher_id"] == "教师甲"
    assert submitted["status"] == "SUBMITTED"


def test_teacher_cannot_view_other_teacher_submission(tmp_path):
    service = PayrollService(tmp_path / "data")
    first, second = service.create_teacher_access("教师甲"), service.create_teacher_access("教师乙")
    service.teacher_submit(first["access_token"], "2026-08", "其他", "仅教师甲可见")
    assert service.teacher_inputs(second["access_token"]) == []


def test_teacher_submission_is_not_automatically_approved(tmp_path):
    service = PayrollService(tmp_path / "data")
    access = service.create_teacher_access("教师甲")
    record = service.teacher_submit(access["access_token"], "2026-08", "排课信息有误", "请核实")
    assert record["status"] == "SUBMITTED"


def test_teacher_can_modify_own_draft_only(tmp_path):
    service = PayrollService(tmp_path / "data")
    alpha, beta = service.create_teacher_access("教师甲"), service.create_teacher_access("教师乙")
    draft = service.teacher_save_draft(alpha["access_token"], "2026-08", "其他", "初稿")
    revised = service.teacher_save_draft(alpha["access_token"], "2026-08", "其他", "修订稿", input_id=draft["id"])
    assert revised["payload"]["note"] == "修订稿"
    with pytest.raises(PermissionError):
        service.teacher_save_draft(beta["access_token"], "2026-08", "其他", "越权", input_id=draft["id"])


def test_approved_submission_can_link_to_run(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    access = service.create_teacher_access("教师甲")
    record = service.teacher_submit(access["access_token"], "2026-08", "排课信息有误", "请核实")
    service.review_business_input(record["id"], "APPROVE", "主管")
    bound = service.bind_business_input(run["id"], record["id"])
    assert bound["business_input_bindings"][0]["input_id"] == record["id"]


def test_rejected_submission_does_not_affect_payroll(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    access = service.create_teacher_access("教师甲")
    record = service.teacher_submit(access["access_token"], "2026-08", "其他", "说明")
    service.review_business_input(record["id"], "REJECT", "主管")
    with pytest.raises(ValueError, match="已审核通过"):
        service.bind_business_input(run["id"], record["id"])


def test_renewal_import_preserves_source_provenance(tmp_path):
    service = PayrollService(tmp_path / "data")
    source = _csv(tmp_path / "renewal.csv", "教师,学生,说明\n教师甲,学生甲,最终续费\n")
    item = service.import_business_results("RENEWAL_RESULT", "2026-08", str(source), "业务员")[0]
    assert item["evidence"]["source_file"] == "renewal.csv"
    assert item["source_row"] == "2"
    assert item["source_file_hash"]


def test_renewal_new_version_does_not_delete_old_version(tmp_path):
    service = PayrollService(tmp_path / "data")
    first = _csv(tmp_path / "renewal-v1.csv", "教师,学生\n教师甲,学生甲\n")
    second = _csv(tmp_path / "renewal-v2.csv", "教师,学生\n教师甲,学生乙\n")
    old = service.import_business_results("RENEWAL_RESULT", "2026-08", str(first), "业务员")[0]
    service.review_business_input(old["id"], "APPROVE", "主管")
    fresh = service.import_business_results("RENEWAL_RESULT", "2026-08", str(second), "业务员")[0]
    assert service.store.get_business_input(old["id"])["status"] == "SUPERSEDED"
    assert service.store.get_business_input(fresh["id"])["status"] == "NEEDS_REVIEW"


def test_renewal_result_without_rule_does_not_guess_bonus(tmp_path):
    service = PayrollService(tmp_path / "data")
    item = service.import_business_results("RENEWAL_RESULT", "2026-08", str(_csv(tmp_path / "renewal.csv", "教师,学生\n教师甲,学生甲\n")), "业务员")[0]
    assert "bonus" not in item["payload"]


def test_refund_import_preserves_source_provenance(tmp_path):
    service = PayrollService(tmp_path / "data")
    refund = _approved_refund(service, tmp_path)
    assert refund["evidence"]["sheet"] == "CSV"
    assert refund["payload"]["student"] == "学生甲"


def test_refund_result_can_generate_comment_candidate(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    candidate = service.create_refund_comment_candidate(run["id"], refund["id"], "math", "Sheet1", "AC5")
    assert candidate["comment_type"] == "REFUND_NOTE"
    assert candidate["status"] == "PROPOSED"
    assert "退费" in candidate["content"]


def test_superseded_refund_invalidates_comment_candidate(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    candidate = service.create_refund_comment_candidate(run["id"], refund["id"], "math", "Sheet1", "AC5")
    service.import_business_results("REFUND_RESULT", "2026-08", str(_csv(tmp_path / "refund-v2.csv", "教师,学生\n教师甲,学生乙\n")), "业务员")
    assert service.comment_candidates(run["id"])[0]["status"] == "NEEDS_RECONFIRMATION"


def test_class_course_resolution_generates_comment_candidate(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    candidate = service.create_class_comment_candidate(run["id"], {"kind": "SOURCE_DATA_CORRECTION", "status": "RESOLVED_BY_SOURCE_CORRECTION", "teacher": "教师甲", "course_label": "高三6人班1节", "reason": "8月升年级未同步", "corrected_value": "高二", "system_value": "68.05"}, "math", "工资表", "AC5")
    assert candidate["comment_type"] == "SOURCE_CORRECTION_NOTE"
    assert "升年级" in candidate["content"]


def test_deferred_issue_does_not_generate_final_comment(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    with pytest.raises(ValueError, match="已确认"):
        service.create_class_comment_candidate(run["id"], {"kind": "SOURCE_DATA_CORRECTION", "status": "DEFERRED"}, "math", "工资表", "AC5")


def test_existing_comment_is_not_silently_overwritten(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    candidate = service.create_refund_comment_candidate(run["id"], refund["id"], "math", "工资表", "AC5")
    source = Path(run["files"]["math"]["path"])
    book = load_workbook(source); book["Sheet1"]["AC5"].comment = Comment("原批注", "原作者"); book.save(source)
    # The changed workbook hash forces a new candidate rather than overwriting.
    refreshed = service.import_file(run["id"], "math", str(source))
    candidate = service.create_refund_comment_candidate(refreshed["id"], refund["id"], "math", "Sheet1", "AC5")
    preview = service.approve_comment_candidate(candidate["id"], "审核员", "APPEND")
    assert preview["before_comment"] == "原批注"
    assert "原批注" in preview["after_comment"]


def test_comment_preview_required_before_write(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    candidate = service.create_refund_comment_candidate(run["id"], refund["id"], "math", "Sheet1", "AC5")
    with pytest.raises(ValueError, match="先在预览后确认"):
        service.writeback_comments(run["id"], run["files"]["math"]["path"], [candidate["id"]], str(tmp_path / "output.xlsx"), "审核员")


def test_writeback_creates_new_workbook_and_preserves_source_formula_cells(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    candidate = service.create_refund_comment_candidate(run["id"], refund["id"], "math", "Sheet1", "AC5")
    service.approve_comment_candidate(candidate["id"], "审核员")
    source = Path(run["files"]["math"]["path"])
    original_bytes = source.read_bytes()
    output = tmp_path / "math_系统回填.xlsx"
    result = service.writeback_comments(run["id"], str(source), [candidate["id"]], str(output), "审核员")
    assert output.is_file() and source.read_bytes() == original_bytes
    assert result["written"] == 1
    reloaded = load_workbook(output, data_only=False)
    assert reloaded["Sheet1"]["AC5"].comment is not None
    assert reloaded["Sheet1"]["AE5"].value == load_workbook(source, data_only=False)["Sheet1"]["AE5"].value


def test_written_comment_survives_reopen(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    candidate = service.create_refund_comment_candidate(run["id"], refund["id"], "math", "Sheet1", "AC5")
    service.approve_comment_candidate(candidate["id"], "审核员")
    output = tmp_path / "out.xlsx"
    service.writeback_comments(run["id"], run["files"]["math"]["path"], [candidate["id"]], str(output), "审核员")
    assert load_workbook(output)["Sheet1"]["AC5"].comment.text


def test_changed_source_marks_binding_stale(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    refund = _approved_refund(service, tmp_path)
    service.bind_business_input(run["id"], refund["id"])
    Path(refund["source_ref"]).write_text("教师,学生\n教师甲,学生变更\n", encoding="utf-8")
    assert service.get(run["id"])["status"] == "STALE"


def test_teacher_access_token_is_teacher_scoped(tmp_path):
    service = PayrollService(tmp_path / "data")
    alpha, beta = service.create_teacher_access("教师甲"), service.create_teacher_access("教师乙")
    service.teacher_submit(alpha["access_token"], "2026-08", "其他", "仅本人可见")
    assert len(service.teacher_inputs(alpha["access_token"])) == 1
    assert service.teacher_inputs(beta["access_token"]) == []


def test_teacher_cannot_access_admin_api(tmp_path):
    service = PayrollService(tmp_path / "data")
    access = service.create_teacher_access("教师甲")
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(base + "/api/runs", headers={"X-Teacher-Token": access["access_token"]})
        with pytest.raises(HTTPError) as error:
            urlopen(request)
        assert error.value.code == 403
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_sanitized_http_e2e_submission_review_refund_preview_writeback(tmp_path):
    fixture_root = tmp_path / "fixture"; fixture_root.mkdir()
    service, run, _ = _prepared_run(fixture_root)
    static = Path(__file__).parents[1] / "payroll_ui" / "static"
    server = PayrollHttpServer(("127.0.0.1", 0), service, static)
    worker = Thread(target=server.serve_forever, daemon=True); worker.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        admin = json.loads(urlopen(base + "/api/bootstrap").read())["token"]
        def post(path: str, payload: dict, headers: dict | None = None):
            request = Request(base + path, data=json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json", **(headers or {})})
            return json.loads(urlopen(request).read())
        access = post("/api/teacher-access", {"teacher_id": "教师甲"}, {"X-Payroll-Token": admin})
        submission = post("/api/teacher/inputs", {"period": "2026-08", "item_type": "班课特殊核算", "note": "脱敏测试说明"}, {"X-Teacher-Token": access["access_token"]})
        post(f"/api/business-inputs/{submission['id']}/review", {"action": "APPROVE", "reviewer": "主管"}, {"X-Payroll-Token": admin})
        post(f"/api/runs/{run['id']}/business-inputs", {"input_id": submission["id"]}, {"X-Payroll-Token": admin})
        source = _csv(tmp_path / "refund.csv", "教师,学生,说明\n教师甲,学生甲,脱敏退费\n")
        imported = post("/api/business-inputs/import", {"input_type": "REFUND_RESULT", "period": "2026-08", "path": str(source), "submitted_by": "业务员"}, {"X-Payroll-Token": admin})[0]
        post(f"/api/business-inputs/{imported['id']}/review", {"action": "APPROVE", "reviewer": "主管"}, {"X-Payroll-Token": admin})
        candidate = post(f"/api/runs/{run['id']}/comment-candidates/refund", {"input_id": imported["id"], "target_role": "math", "sheet": "Sheet1", "cell": "AC5"}, {"X-Payroll-Token": admin})
        post(f"/api/runs/{run['id']}/comment-candidates/approve", {"candidate_id": candidate["id"], "reviewer": "主管", "strategy": "APPEND"}, {"X-Payroll-Token": admin})
        output = tmp_path / "output.xlsx"
        result = post(f"/api/runs/{run['id']}/writeback", {"source_workbook": run["files"]["math"]["path"], "candidate_ids": [candidate["id"]], "output_path": str(output), "reviewer": "主管"}, {"X-Payroll-Token": admin})
        assert Path(result["output_path"]).is_file()
        assert load_workbook(output)["Sheet1"]["AC5"].comment is not None
    finally:
        server.shutdown(); server.server_close(); worker.join()
