from pathlib import Path

import pytest

from payroll_core.final_fields import DETERMINED, renewal_fields_from_snapshot, resolve_final_fields
from payroll_core.payroll_generation import generated_from_calculation
from payroll_ui.service import PayrollService


def _core(teacher="教师甲"):
    return {"period": "2026-08", "rows": [{
        "teacher": teacher,
        "employment_type": "FULL_TIME",
        "fields": {
            "AA": {"value": 1, "state": DETERMINED},
            "AC": {"value": 2, "state": DETERMINED},
            "AD": {"value": 3, "state": DETERMINED},
            "AE": {"value": 40, "state": DETERMINED},
            "AF": {"value": 120, "state": DETERMINED},
            "PART_TIME": {"value": None, "state": "NOT_APPLICABLE"},
        },
    }]}


def _approved(teacher="教师甲", payload=None, item_id="renew-1"):
    return {
        "id": item_id, "period": "2026-08", "teacher_id": teacher,
        "input_type": "RENEWAL_RESULT", "status": "APPROVED",
        "source_ref": "renewal.csv", "source_file_hash": "hash-1", "source_row": "2",
        "payload": payload or {"one_to_one_hours": 2, "class_hours": 3, "mentor_hours": 4},
        "reviewed_by": "审核员", "reviewed_at": "2026-08-20T00:00:00+00:00",
        "evidence": {"source_file": "renewal.csv"},
    }


def test_binding_creates_frozen_run_renewal_snapshot_and_ak(tmp_path: Path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-08", mode="GENERATE")
    item = _approved()
    service.store.save_business_input(item)
    bound = service.bind_business_input(run["id"], item["id"])
    snapshot = bound["run_renewal_result_snapshot"]
    assert snapshot["version"] == "RUN_RENEWAL_RESULT_SNAPSHOT/v1"
    assert snapshot["entries"]["教师甲"]["source_result_id"] == "renew-1"
    assert snapshot["entries"]["教师甲"]["source_status"] == "APPROVED"
    generated = generated_from_calculation(_core(), renewal_snapshot=snapshot)
    final = generated.rows[0].final_fields
    assert final["AH"]["value"] == 2
    assert final["AI"]["value"] == 3
    assert final["AJ"]["value"] == 4
    assert final["AK"]["value"] == pytest.approx(9.5)
    assert final["AK"]["state"] == DETERMINED


def test_explicit_no_event_is_determined_zero_but_missing_snapshot_is_not_zero():
    snapshot = {
        "entries": {
            "教师甲": {
                "teacher_id": "教师甲", "display_name": "教师甲",
                "AH": {"value": 0, "state": DETERMINED, "reason": "NO_EVENT"},
                "AI": {"value": 0, "state": DETERMINED, "reason": "NO_EVENT"},
                "AJ": {"value": 0, "state": DETERMINED, "reason": "NO_EVENT"},
            }
        }
    }
    fields = renewal_fields_from_snapshot(snapshot, "教师甲")
    assert all(item["state"] == DETERMINED and item["value"] == 0 for item in fields.values())
    generated = generated_from_calculation(_core(), renewal_snapshot={"entries": {}})
    renewal = generated.rows[0].final_fields
    assert renewal["AH"]["state"] == "MISSING_SOURCE"
    assert renewal["AH"]["value"] is None
    assert renewal["AK"]["state"] == "HUMAN_REQUIRED"


def test_two_approved_results_with_same_display_identity_fail_closed():
    snapshot = {"entries": {
        "id-1": {"teacher_id": "id-1", "display_name": "刘雨", "AH": {"value": 1, "state": DETERMINED}, "AI": {"value": 0, "state": DETERMINED}, "AJ": {"value": 0, "state": DETERMINED}},
        "id-2": {"teacher_id": "id-2", "display_name": "刘雨", "AH": {"value": 2, "state": DETERMINED}, "AI": {"value": 0, "state": DETERMINED}, "AJ": {"value": 0, "state": DETERMINED}},
    }}
    fields = renewal_fields_from_snapshot(snapshot, "刘雨")
    assert all(item["state"] == "IDENTITY_NOT_STABLE" for item in fields.values())
