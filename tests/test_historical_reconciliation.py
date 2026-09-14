from types import SimpleNamespace

from payroll_ui.service import PayrollService


def _record(teacher="张三", record_key="course-1"):
    return SimpleNamespace(
        teacher=teacher,
        record_key=record_key,
        grade="六年级",
        class_type="普通小班",
        attended=2,
        lesson_status="已上课",
        lesson_date="2026-07-15",
        class_name="六年级小班",
        student="甲、乙",
        source="schedule.xlsx",
        provenance={"class_name": SimpleNamespace(sheet="排课", coordinate="A2")},
    )


def test_historical_reconciliation_classifies_differences_with_evidence(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="张三",
        source="july.xlsx",
        one_to_one=10.0,
        class_value=20.0,
        teaching_hours=30.0,
        ae=40.0,
        af=1200.0,
        provenance={"af": SimpleNamespace(raw_value="=(AD2-30)*AE2")},
    )
    run = {
        "id": "run-1",
        "period": "2026-07",
        "period_label": "2026-07",
        "period_start": "2026-06-29",
        "period_end": "2026-08-02",
        "files": {"baseline": {"path": "july.xlsx"}, "schedule": {"path": "schedule.xlsx"}},
        "core_calculation": {
            "rows": [{
                "teacher": "张三",
                "fields": {
                    "AA": {"value": 10.0},
                    "AC": {"value": 21.0, "evidence": [{"inputs": {"attended": "2"}}]},
                    "AD": {"value": 31.0},
                    "AE": {"value": 40.0},
                    "AF": {"value": 40.0, "reason": "AF：(AD − 30.0) × AE", "evidence": [{"inputs": {"obligation_hours": "30"}}]},
                },
            }],
            "course_contributions": [{
                "teacher": "张三", "field": "ac", "record_key": "course-1", "value": 21.0,
                "evidence": [{"inputs": {"grade_coefficient": "1.5", "small_group_headcount_coefficient": "1.4", "lesson_hour_factor": "1"}}],
            }],
        },
    }
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda role, _path, _run: SimpleNamespace(records=[baseline] if role == "baseline" else [_record()])
    service._apply_schedule_grade_resolutions = lambda records, _run: records

    result = service.historical_reconciliation("run-1")

    assert result["teachers_compared"] == 1
    assert result["field_stats"]["AC"] == {"matches": 0, "comparable": 1}
    assert result["unexplained"] == 0
    assert result["rows"][0]["fields"]["AC"]["difference_category"] == "COURSE_CONTRIBUTION"
    assert result["rows"][0]["evidence"]


def test_historical_reconciliation_marks_personal_af_exception(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="任勇", source="july.xlsx", one_to_one=1.0, class_value=1.0,
        teaching_hours=100.0, ae=40.0, af=4000.0,
        provenance={"af": SimpleNamespace(raw_value="=AD7*AE7")},
    )
    run = {
        "id": "run-2", "period": "2026-07", "files": {"baseline": {"path": "july.xlsx"}},
        "core_calculation": {"rows": [{"teacher": "任勇", "fields": {
            "AA": {"value": 1.0}, "AC": {"value": 1.0}, "AD": {"value": 100.0}, "AE": {"value": 40.0},
            "AF": {"value": 2800.0, "reason": "AF：(AD − 30.0) × AE", "evidence": [{"inputs": {"obligation_hours": "30"}}]},
        }}], "course_contributions": []},
    }
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda _role, _path, _run: SimpleNamespace(records=[baseline])
    result = service.historical_reconciliation("run-2")
    assert result["rows"][0]["fields"]["AF"]["difference_category"] == "PERSONAL_EXCEPTION"
