from payroll_core.config.schema import PayrollConfig
from payroll_core.models.reconciliation import ReconciliationStatus
from payroll_core.reconcile.engine import ReconciliationEngine


def engine(rules=None):
    return ReconciliationEngine(PayrollConfig(period="2026-08", rules=rules or {}))


def test_normal_one_to_one_is_match():
    report = engine().reconcile(
        {"张三": {"one_to_one": 36.0}},
        {"张三": {"one_to_one": 36.0}},
        required_fields=[("张三", "one_to_one")],
    )
    assert report.items[0].status is ReconciliationStatus.MATCH
    assert report.summary.overall_status == "PASS"


def test_unexplained_one_to_one_difference_blocks_pass():
    report = engine().reconcile(
        {"张三": {"one_to_one": 36.0}},
        {"张三": {"one_to_one": 30.0}},
        required_fields=[("张三", "one_to_one")],
    )
    item = report.items[0]
    assert item.status is ReconciliationStatus.UNEXPLAINED_DIFFERENCE
    assert item.difference == -6.0
    assert report.summary.overall_status != "PASS"


def test_class_match_and_configured_adjustment():
    matched = engine().reconcile(
        {"李四": {"class_value": 10.2}},
        {"李四": {"class_value": 10.2}},
        required_fields=[("李四", "class_value")],
    )
    assert matched.items[0].status is ReconciliationStatus.MATCH

    adjusted = engine(
        {
            "reconciliation_adjustments": [
                {
                    "target": "李四",
                    "field": "class_value",
                    "delta": 1.0,
                    "effective_from": "2026-08",
                    "effective_to": "2026-08",
                }
            ]
        }
    ).reconcile(
        {"李四": {"class_value": 10.2}},
        {"李四": {"class_value": 11.2}},
        required_fields=[("李四", "class_value")],
    )
    assert adjusted.items[0].status is ReconciliationStatus.EXPLAINED_DIFFERENCE
    assert adjusted.summary.overall_status == "PASS"


def test_source_and_target_name_differences_are_not_silent():
    report = engine().reconcile(
        {"张三": {"one_to_one": 1.0}, "李四": {"one_to_one": 2.0}},
        {"张三": {"one_to_one": 1.0}, "王五": {"one_to_one": 2.0}},
        required_fields=[("张三", "one_to_one"), ("李四", "one_to_one"), ("王五", "one_to_one")],
    )
    statuses = {item.target: item.status for item in report.items}
    assert statuses["李四"] is ReconciliationStatus.MISSING_TARGET
    assert statuses["王五"] is ReconciliationStatus.MISSING_SOURCE
    assert report.summary.overall_status != "PASS"
