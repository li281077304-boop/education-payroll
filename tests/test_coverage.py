from payroll_core.config.schema import PayrollConfig
from payroll_core.models.reconciliation import ReconciliationStatus
from payroll_core.reconcile.engine import ReconciliationEngine


def test_unprovided_required_field_is_partial_not_pass():
    report = ReconciliationEngine(PayrollConfig(period="2026-08")).reconcile(
        {"张三": {"one_to_one": 36.0}},
        {"张三": {"one_to_one": 36.0}},
        required_fields=[("张三", "one_to_one"), ("张三", "refund")],
    )
    assert report.summary.coverage_percent == 50.0
    assert report.summary.coverage_complete is False
    assert report.summary.overall_status != "PASS"
    assert any(item.status is ReconciliationStatus.NEEDS_MANUAL_REVIEW for item in report.items)


def test_explained_difference_counts_as_completed_coverage():
    report = ReconciliationEngine(PayrollConfig(period="2026-08")).reconcile(
        {"张三": {"one_to_one": 36.0}},
        {"张三": {"one_to_one": 30.0}},
        required_fields=[("张三", "one_to_one")],
        decisions=[],
    )
    assert report.summary.coverage_percent == 100.0
    assert report.summary.coverage_complete is True
