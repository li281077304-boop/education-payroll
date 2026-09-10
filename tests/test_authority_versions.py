"""Versioned authority corrections stay explicit and auditable."""
from pathlib import Path

from payroll_ui.service import PayrollService, version


def _seed_run(service: PayrollService, root: Path) -> dict:
    run = service.create("2026-08")
    schedule, target = root / "source.xlsx", root / "target.xlsx"
    schedule.write_bytes(b"synthetic source")
    target.write_bytes(b"synthetic payroll")
    stored = service.store.get(run["id"])
    stored["files"] = {
        "schedule": {"path": str(schedule), **version(schedule)},
        "math": {"path": str(target), **version(target)},
    }
    stored["status"] = "REVIEW_REQUIRED"
    stored["field_records"] = [
        {"id": "rate", "teacher": "教师甲", "field": "rate", "field_label": "AE", "title": "AE", "expected": 42, "actual": 32, "difference": -10, "status": "RATE_MISMATCH", "status_label": "档位金额不一致", "severity_rank": 1, "severity_label": "重要", "reason": "synthetic"},
        {"id": "fee", "teacher": "教师甲", "field": "af_policy", "field_label": "AF", "title": "AF", "expected": 1680, "actual": 1280, "difference": -400, "status": "AF_POLICY_MISMATCH", "status_label": "课时费政策不一致", "severity_rank": 1, "severity_label": "重要", "reason": "synthetic"},
    ]
    stored["issues"] = list(stored["field_records"])
    stored["audit_context"] = service._business_context(stored)
    service._refresh_business_groups(stored)
    service.store.save(stored)
    return service.get(run["id"])


def _service_with_versions(tmp_path: Path) -> PayrollService:
    service = PayrollService(tmp_path / "app")
    service.save_rating_version("2025-10", "2026-09", "脱敏星级源", "v1", [{"teacher": "教师甲", "rating": 4}])
    service.save_policy_version("2025-10", "2026-09", "脱敏政策源", [{"teacher": "教师甲", "role": "教师", "rating": 4, "obligation_hours": 30, "obligation_hours_deduction_enabled": True}])
    return service


def test_corrected_authority_version_keeps_old_version_and_usage(tmp_path):
    service = _service_with_versions(tmp_path)
    run = _seed_run(service, tmp_path)
    old_id = run["rating_version_id"]

    service.save_rating_version("2025-10", "2026-09", "脱敏星级修正版", "v2", [{"teacher": "教师甲", "rating": 3}], supersedes_version_id=old_id)

    versions = {item["id"]: item for item in service.rating_versions()}
    assert versions[old_id]["status"] == "SUPERSEDED"
    assert versions[old_id]["used_by_runs"] == [{"id": run["id"], "period": "2026-08"}]
    replacement = next(item for item in versions.values() if item.get("supersedes_version_id") == old_id)
    assert replacement["status"] == "ACTIVE"
    assert service.get(run["id"])["rating_version_id"] == old_id


def test_run_explicitly_rebinds_corrected_authority_and_invalidates_decision(tmp_path):
    service = _service_with_versions(tmp_path)
    run = _seed_run(service, tmp_path)
    group = run["issue_groups"][0]
    service.decide(run["id"], group["id"], "DEFERRED", "审核人", "人工构造决定", group["fingerprint"])
    old_id = run["rating_version_id"]
    service.save_rating_version("2025-10", "2026-09", "脱敏星级修正版", "v2", [{"teacher": "教师甲", "rating": 3}], supersedes_version_id=old_id)
    replacement = next(item for item in service.rating_versions() if item.get("supersedes_version_id") == old_id)

    # Creating a correction does not change an already-bound historical run.
    still_bound = service.get(run["id"])
    assert still_bound["rating_version_id"] == old_id
    assert still_bound["business_decisions"][0]["status"] == "ACTIVE"

    rebound = service.rebind_authority(run["id"], "rating", replacement["id"])

    assert rebound["rating_version_id"] == replacement["id"]
    assert rebound["status"] == "FILES_READY"
    assert rebound["business_decisions"][0]["status"] == "NEEDS_RECONFIRMATION"
    assert rebound["authority_rebind_history"][-1]["from_version_id"] == old_id
    assert rebound["authority_context"]["rating"]["version_id"] == replacement["id"]
