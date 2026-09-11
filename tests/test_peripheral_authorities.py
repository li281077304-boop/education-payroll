from pathlib import Path

from payroll_ui.service import PayrollService
from openpyxl import load_workbook
from tests.test_business_inputs_writeback import _csv
from tests.test_payroll_ui_service import _prepared_run


def _approve(service, item):
    service.review_business_input(item["id"], "START_REVIEW", "审核员")
    return service.review_business_input(item["id"], "APPROVE", "审核员")


def test_authoritative_results_are_components_not_core_rules(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    source = _csv(tmp_path / "renewal.csv", "教师,工资金额\n张三,88\n")
    item = _approve(service, service.import_business_results("RENEWAL_RESULT", "2026-08", str(source), "业务员", amount_column="工资金额")[0])
    service.bind_business_input(run["id"], item["id"])
    result = service.peripheral_payroll(run["id"])
    assert result["teachers"]["张三"]["components"][0]["code"] == "RENEWAL"
    assert result["teachers"]["张三"]["total"] == "88"


def test_hr_allowance_and_attendance_are_authority_backed(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    allowance = _approve(service, service.import_business_results("HR_ALLOWANCE", "2026-08", str(_csv(tmp_path / "allowance.csv", "教师,金额\n张三,50\n")), "HR", amount_column="金额")[0])
    attendance = _approve(service, service.import_business_results("HR_ATTENDANCE", "2026-08", str(_csv(tmp_path / "attendance.csv", "教师,金额\n张三,-20\n")), "HR", amount_column="金额")[0])
    service.bind_business_input(run["id"], allowance["id"])
    service.bind_business_input(run["id"], attendance["id"])
    result = service.peripheral_payroll(run["id"])
    assert result["teachers"]["张三"]["total"] == "30"


def test_result_without_explicit_payroll_amount_is_source_ready(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    item = _approve(service, service.import_business_results("REFUND_RESULT", "2026-08", str(_csv(tmp_path / "refund.csv", "教师,退费金额\n张三,100\n")), "业务员")[0])
    service.bind_business_input(run["id"], item["id"])
    result = service.peripheral_payroll(run["id"])
    assert result["teachers"]["张三"]["status"] == "SOURCE_READY"
    assert result["teachers"]["张三"]["total"] == "0"


def test_generate_includes_authority_components_without_changing_core(tmp_path):
    service, run, _ = _prepared_run(tmp_path)
    item = _approve(service, service.import_business_results("HR_ALLOWANCE", "2026-08", str(_csv(tmp_path / "allowance.csv", "教师,金额\n张三,50\n")), "HR", amount_column="金额")[0])
    service.bind_business_input(run["id"], item["id"])
    output = tmp_path / "generated.xlsx"
    generated = service.generate_payroll(run["id"], str(output))
    row = next(row for row in generated["rows"] if row["teacher"] == "张三")
    assert row["peripheral_total"] == 50.0
    assert row["payroll_total"] == row["af"] + 50.0
    assert any("外围合计" in str(cell.value) for cell in load_workbook(output)["标准工资表"][3])
