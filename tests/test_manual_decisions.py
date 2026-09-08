from payroll_core.config.schema import PayrollConfig
from payroll_core.models.decisions import ManualDecision
from payroll_core.models.reconciliation import ReconciliationStatus
from payroll_core.reconcile.engine import ReconciliationEngine


def test_confirmed_manual_decision_explains_difference():
    decision = ManualDecision(
        period="2026-08",
        target="王五",
        field="class_value",
        system_value=10.0,
        override_value=12.0,
        reason="Confirmed special class conversion",
        source="fixture/manual_decisions.yaml",
        confirmed_by="审核人甲",
    )
    report = ReconciliationEngine(PayrollConfig(period="2026-08")).reconcile(
        {"王五": {"class_value": 10.0}},
        {"王五": {"class_value": 12.0}},
        required_fields=[("王五", "class_value")],
        decisions=[decision],
    )
    assert report.items[0].status is ReconciliationStatus.EXPLAINED_DIFFERENCE
    assert report.summary.overall_status == "PASS"


def test_mismatched_decision_does_not_hide_new_difference():
    decision = ManualDecision(
        period="2026-08",
        target="王五",
        field="class_value",
        system_value=10.0,
        override_value=12.0,
        reason="Old decision",
        source="fixture/manual_decisions.yaml",
        confirmed_by="审核人甲",
    )
    report = ReconciliationEngine(PayrollConfig(period="2026-08")).reconcile(
        {"王五": {"class_value": 10.0}},
        {"王五": {"class_value": 13.0}},
        required_fields=[("王五", "class_value")],
        decisions=[decision],
    )
    assert report.items[0].status is ReconciliationStatus.NEEDS_MANUAL_REVIEW
    assert report.summary.overall_status != "PASS"
