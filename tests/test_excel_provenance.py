from pathlib import Path

from payroll_core.config.schema import PayrollConfig
from payroll_core.excel.payroll import read_payroll_excel
from payroll_core.excel.reconciliation_bridge import actual_one_to_one_from_payroll, expected_one_to_one_from_normalized_schedule
from payroll_core.excel.schedule import read_schedule_excel
from payroll_core.models.reconciliation import ReconciliationStatus
from payroll_core.reconcile.engine import ReconciliationEngine


FIXTURES = Path(__file__).parent / "fixtures" / "excel"


def test_fake_excel_chain_keeps_provenance_and_blocks_unexplained_difference():
    schedule = read_schedule_excel(FIXTURES / "fake_schedule.xlsx", period="2026-08")
    payroll = read_payroll_excel(FIXTURES / "fake_payroll.xlsx", period="2026-08")
    expected, issues = expected_one_to_one_from_normalized_schedule(schedule.records)
    actual = actual_one_to_one_from_payroll(payroll.records)
    required = [(teacher, "one_to_one") for teacher in sorted(set(expected) | set(actual))]

    report = ReconciliationEngine(PayrollConfig(period="2026-08")).reconcile(expected, actual, required_fields=required)

    assert not issues
    assert payroll.records[0].provenance["one_to_one"].source_file.endswith("fake_payroll.xlsx")
    assert any(item.status is ReconciliationStatus.UNEXPLAINED_DIFFERENCE for item in report.items)
    assert report.summary.overall_status != "PASS"
