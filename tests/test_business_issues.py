"""Business-issue grouping and decision lifecycle tests using synthetic facts only."""
from copy import deepcopy
from dataclasses import replace

import pytest

from payroll_ui.business import build_groups
from payroll_ui.service import PayrollService, version
from payroll_core.models.evidence import AdapterResult
from payroll_core.models.records import PayrollRecord, ScheduleRecord


STATUS_LABELS = {
    "UNEXPLAINED_DIFFERENCE": "差异待处理",
    "RATING_MISMATCH": "星级不一致",
    "RATE_MISMATCH": "档位金额不一致",
    "AF_POLICY_MISMATCH": "课时费政策不一致",
    "FORMULA_MISSING": "公式缺失",
}


def _record(record_id, field, *, expected, actual, teacher="教师甲", status=None):
    return {
        "id": record_id,
        "teacher": teacher,
        "field": field,
        "field_label": field,
        "title": f"{field}需要处理",
        "reason": f"{field}人工构造审计事实",
        "expected": expected,
        "actual": actual,
        "difference": actual - expected if expected is not None and actual is not None else None,
        "status": status or ("RATING_MISMATCH" if field == "rating" else "UNEXPLAINED_DIFFERENCE"),
        "severity_rank": 1,
        "severity_label": "重要",
    }


def _records():
    # AE 42/32 and AF 1680/1280 both imply the same 40 billable hours.
    return [
        _record("aa", "one_to_one", expected=1.8, actual=1.2),
        _record("ac", "class_value", expected=2.16, actual=2.4),
        _record("rate", "rate", expected=42, actual=32, status="RATE_MISMATCH"),
        _record("af-policy", "af_policy", expected=1680, actual=1280, status="AF_POLICY_MISMATCH"),
        _record("formula-ae", "formula", expected=None, actual=None, status="FORMULA_MISSING"),
        _record("formula-af", "formula", expected=None, actual=None, status="FORMULA_MISSING"),
    ]


def _run(*, period="2026-08", source_hash="schedule-v1", decisions=None):
    return {
        "id": "synthetic-run",
        "period": period,
        "files": {
            "schedule": {"sha256": source_hash},
            "math": {"sha256": "payroll-v1"},
        },
        "business_decisions": decisions or [],
    }


def _context(*, rating_version="rating-v1", policy_version="policy-v1"):
    rating = {"id": rating_version, "source": "脱敏星级依据", "source_version": rating_version}
    policy = {"id": policy_version, "source": "脱敏工资政策", "effective_from": "2026-01"}
    bands = [{"band": "synthetic", "source": "脱敏档位表", "source_version": "bands-v1"}]
    return rating, policy, bands


def _groups(run, records=None, *, rating_version="rating-v1", policy_version="policy-v1"):
    rating, policy, bands = _context(rating_version=rating_version, policy_version=policy_version)
    return build_groups(run, records or _records(), rating, policy, bands, STATUS_LABELS)


def test_six_raw_fields_become_four_business_issues_without_losing_audits():
    records = _records()
    original = deepcopy(records)

    groups = _groups(_run(), records)

    assert len(groups) == 4
    compensation = next(group for group in groups if group["root_cause_key"].endswith(":compensation_basis"))
    assert set(compensation["affected_fields"]) == {"rate", "af_policy"}
    assert set(compensation["field_record_ids"]) == {"rate", "af-policy"}
    assert sum(group["field_records"] for group in groups) == 6
    assert {record_id for group in groups for record_id in group["field_record_ids"]} == {
        "aa", "ac", "rate", "af-policy", "formula-ae", "formula-af"
    }
    assert records == original


def test_rate_and_af_policy_only_merge_when_both_sides_imply_same_billable_hours():
    matching = _groups(_run())
    assert any(set(group["affected_fields"]) >= {"rate", "af_policy"} for group in matching)

    records = _records()
    next(row for row in records if row["field"] == "af_policy")["actual"] = 1200
    separated = _groups(_run(), records)
    assert not any(set(group["affected_fields"]) >= {"rate", "af_policy"} for group in separated)


def test_two_ac_audits_and_two_compensation_pairs_are_exactly_four_business_issues():
    records = [
        _record("ac-a", "class_value", teacher="教师甲", expected=2.16, actual=2.4),
        _record("ac-b", "class_value", teacher="教师乙", expected=1.92, actual=2.0),
        _record("rate-a", "rate", teacher="教师甲", expected=42, actual=32, status="RATE_MISMATCH"),
        _record("fee-a", "af_policy", teacher="教师甲", expected=1680, actual=1280, status="AF_POLICY_MISMATCH"),
        _record("rate-b", "rate", teacher="教师乙", expected=37, actual=32, status="RATE_MISMATCH"),
        _record("fee-b", "af_policy", teacher="教师乙", expected=1480, actual=1280, status="AF_POLICY_MISMATCH"),
    ]

    groups = _groups(_run(), records)

    assert len(groups) == 4
    assert sorted(tuple(group["field_record_ids"]) for group in groups) == [
        ("ac-a",),
        ("ac-b",),
        ("fee-a", "rate-a"),
        ("fee-b", "rate-b"),
    ]
    assert sum(group["field_records"] for group in groups) == 6


def test_group_identity_is_stable_across_raw_record_order():
    forward = _groups(_run(), _records())
    backward = _groups(_run(), list(reversed(_records())))

    assert [(group["id"], group["fingerprint"]) for group in forward] == [
        (group["id"], group["fingerprint"]) for group in backward
    ]


def test_fingerprint_binds_period_source_and_authority_versions():
    baseline = {group["root_cause_key"]: group["fingerprint"] for group in _groups(_run())}

    variants = [
        _groups(_run(period="2026-09")),
        _groups(_run(source_hash="schedule-v2")),
        _groups(_run(), rating_version="rating-v2"),
        _groups(_run(), policy_version="policy-v2"),
    ]
    for groups in variants:
        assert all(group["fingerprint"] != baseline[group["root_cause_key"]] for group in groups)


def test_decision_remains_active_for_same_fingerprint_then_requires_reconfirmation():
    initial = _groups(_run())
    target = next(group for group in initial if group["root_cause_key"].endswith(":compensation_basis"))
    decision = {
        "group_id": target["id"],
        "root_cause_key": target["root_cause_key"],
        "fingerprint": target["fingerprint"],
        "action": "DEFERRED",
        "status": "ACTIVE",
        "person": "验收员",
        "reason": "人工构造生命周期测试",
    }

    unchanged = _groups(_run(decisions=[decision]))
    unchanged_target = next(group for group in unchanged if group["id"] == target["id"])
    assert unchanged_target["decision"]["status"] == "ACTIVE"
    assert unchanged_target["decision_label"] == "暂缓处理"

    changed = _groups(_run(source_hash="schedule-v2", decisions=[decision]))
    changed_target = next(group for group in changed if group["id"] == target["id"])
    assert changed_target["decision"]["status"] == "NEEDS_RECONFIRMATION"
    assert changed_target["decision_label"] == "依据已变化，需重新确认"
    assert decision["reason"] == "人工构造生命周期测试"


def _service_with_compensation_pair(tmp_path):
    service = PayrollService(tmp_path / "app-data")
    created = service.create("2026-08")
    schedule = tmp_path / "synthetic-source.xlsx"
    target = tmp_path / "synthetic-target.xlsx"
    schedule.write_bytes(b"synthetic source v1")
    target.write_bytes(b"synthetic target v1")
    run = service.store.get(created["id"])
    run["files"] = {
        "schedule": {"path": str(schedule), **version(schedule)},
        "math": {"path": str(target), **version(target)},
    }
    run["status"] = "REVIEW_REQUIRED"
    run["field_records"] = [
        _record("service-rate", "rate", expected=42, actual=32, status="RATE_MISMATCH"),
        _record("service-fee", "af_policy", expected=1680, actual=1280, status="AF_POLICY_MISMATCH"),
    ]
    run["issues"] = deepcopy(run["field_records"])
    run["audit_context"] = service._business_context(run)
    service._refresh_business_groups(run)
    service.store.save(run)
    return service, run, schedule, target


def _save_pair_decision(service, run):
    group = service.get(run["id"])["issue_groups"][0]
    saved = service.decide(
        run["id"], group["id"], "DEFERRED", "验收员", "人工构造双字段处理意见",
        expected_fingerprint=group["fingerprint"],
    )
    return group, saved


def test_service_one_group_decision_is_saved_once_for_both_fields(tmp_path):
    service, run, _, _ = _service_with_compensation_pair(tmp_path)

    group, saved = _save_pair_decision(service, run)

    assert group["affected_fields"] == ["af_policy", "rate"]
    assert len(saved["business_decisions"]) == 1
    assert saved["business_decisions"][0]["affected_fields"] == ["af_policy", "rate"]
    reopened = PayrollService(tmp_path / "app-data").get(run["id"])
    assert reopened["business_decisions"][0]["status"] == "ACTIVE"
    assert reopened["issue_groups"][0]["decision"]["reason"] == "人工构造双字段处理意见"


@pytest.mark.parametrize("changed_role", ["schedule", "math"])
def test_service_source_or_target_hash_stale_retains_decision_for_reconfirmation(tmp_path, changed_role):
    service, run, schedule, target = _service_with_compensation_pair(tmp_path)
    group, _ = _save_pair_decision(service, run)
    changed = schedule if changed_role == "schedule" else target
    changed.write_bytes(changed.read_bytes() + b" changed")

    stale = service.get(run["id"])

    assert stale["status"] == "STALE"
    assert stale["stale_files"] == [changed_role]
    assert len(stale["business_decisions"]) == 1
    assert stale["business_decisions"][0]["group_id"] == group["id"]
    assert stale["business_decisions"][0]["status"] == "NEEDS_RECONFIRMATION"
    persisted = service.store.get(run["id"])
    assert persisted["business_decisions"][0]["status"] == "NEEDS_RECONFIRMATION"


def test_service_rule_version_change_requires_reconfirmation_and_persists(tmp_path, monkeypatch):
    service, run, _, _ = _service_with_compensation_pair(tmp_path)
    group, _ = _save_pair_decision(service, run)
    import payroll_ui.service as service_module

    original_bands = service_module.default_compensation_bands()
    changed_bands = [replace(item, source_version=item.source_version + "-revised") for item in original_bands]
    monkeypatch.setattr(service_module, "default_compensation_bands", lambda: changed_bands)

    changed = PayrollService(tmp_path / "app-data").get(run["id"])

    assert changed["status"] == "FILES_READY"
    assert changed["business_context_stale"] is True
    assert changed["business_decisions"][0]["group_id"] == group["id"]
    assert changed["business_decisions"][0]["status"] == "NEEDS_RECONFIRMATION"
    persisted = service.store.get(run["id"])
    assert persisted["business_decisions"][0]["status"] == "NEEDS_RECONFIRMATION"


def test_grouped_ae_af_service_decision_survives_actual_rerun_and_restart(tmp_path, monkeypatch):
    service = PayrollService(tmp_path / "app-data")
    rating = service.save_rating_version(
        "2025-10", "2026-09", "脱敏星级权威表", "rating-source-v1",
        [{"teacher": "教师甲", "rating": 4, "role": "教师"}],
    )[0]
    policy = service.save_policy_version(
        "2025-10", "2026-09", "脱敏工资政策-v1",
        [{
            "teacher": "教师甲", "role": "教师", "rating": 4,
            "obligation_hours": 30, "obligation_hours_deduction_enabled": True,
        }],
    )[0]
    created = service.create("2026-08")
    assert created["rating_version_id"] == rating["id"]
    assert created["policy_version_id"] == policy["id"]

    schedule_file = tmp_path / "mock-schedule.xlsx"
    payroll_file = tmp_path / "mock-payroll.xlsx"
    schedule_file.write_bytes(b"stable synthetic schedule")
    payroll_file.write_bytes(b"stable synthetic payroll")
    stored = service.store.get(created["id"])
    stored["files"] = {
        "schedule": {"path": str(schedule_file), **version(schedule_file)},
        "math": {"path": str(payroll_file), **version(payroll_file)},
    }
    stored["status"] = "FILES_READY"
    service.store.save(stored)

    # AD now comes from the schedule, not the submitted 70.  Supply actual
    # synthetic 35 × 2 teaching hours to retain this grouping regression.
    schedule = [ScheduleRecord("2026-08", "教师甲", "九年级", "数学", "1对1", 1, lesson_status="已上课", lesson_time=str(i)) for i in range(35)]
    payroll = [PayrollRecord(
        "2026-08", "教师甲", one_to_one=70, class_value=0,
        teaching_hours=70, teacher_level="四星", ae=32, af=1280, av=1280,
    )]

    def mock_read(role, _path, _period):
        return AdapterResult(records=schedule if role == "schedule" else payroll)

    monkeypatch.setattr(service, "_read", mock_read)
    monkeypatch.setattr(service, "_formula_audit_for_scope", lambda _path, _rows: [])

    checked = service.check(created["id"])
    group = next(item for item in checked["issue_groups"] if item["root_cause_key"].endswith(":compensation_basis"))
    assert set(group["affected_fields"]) == {"rate", "af_policy"}
    saved = service.decide(
        created["id"], group["id"], "DEFERRED", "验收员", "真实 service 重跑保留测试",
        expected_fingerprint=group["fingerprint"],
    )
    assert len(saved["business_decisions"]) == 1

    rerun = service.check(created["id"])
    rerun_group = next(item for item in rerun["issue_groups"] if item["id"] == group["id"])
    assert rerun_group["fingerprint"] == group["fingerprint"]
    assert rerun_group["decision"]["status"] == "ACTIVE"
    assert rerun_group["decision"]["affected_fields"] == ["af_policy", "rate"]

    reopened = PayrollService(tmp_path / "app-data").get(created["id"])
    reopened_group = next(item for item in reopened["issue_groups"] if item["id"] == group["id"])
    assert reopened_group["decision"]["status"] == "ACTIVE"
    assert reopened_group["decision"]["reason"] == "真实 service 重跑保留测试"
