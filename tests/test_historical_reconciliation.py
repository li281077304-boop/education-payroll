from types import SimpleNamespace

from payroll_core.models.evidence import CommentRecord
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


def test_historical_reconciliation_recovers_named_part_time_rate_from_af_comment(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="刘雨", source="july.xlsx", one_to_one=None, class_value=None,
        teaching_hours=None, ae=None, af=840.0,
        provenance={"af": SimpleNamespace(raw_value="=140*6")},
    )
    current_row = {
        "teacher": "刘雨",
        "fields": {
            "AA": {"value": 0.0}, "AC": {"value": 0.0}, "AD": {"value": 0.0},
            "AE": {"value": 0.0}, "AF": {"value": 0.0, "evidence": []},
        },
    }
    run = {
        "id": "run-3", "period": "2026-07", "period_label": "2026-07",
        "files": {"baseline": {"path": "july.xlsx"}},
        "core_calculation": {"rows": [current_row], "course_contributions": []},
    }
    comment = CommentRecord("july.xlsx", "教学部", "AF32", "刘雨", "af", "macos：高一生物 140/节\n合计840", "macos")
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda _role, _path, _run: SimpleNamespace(records=[baseline], comments=[comment])

    result = service.historical_reconciliation("run-3")

    field = result["rows"][0]["fields"]["AF"]
    assert result["category_counts"]["MISSING_SOURCE"] == 4
    assert result["category_counts"]["PART_TIME_RATE"] == 1
    assert field["difference_category"] == "PART_TIME_RATE"
    assert field["evidence"][-1]["teacher"] == "刘雨"
    assert field["evidence"][-1]["period"] == "2026-07"
    assert field["evidence"][-1]["rate"] == 140.0


def test_historical_reconciliation_classifies_each_core_field_from_its_own_evidence(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="教师甲", source="july.xlsx", one_to_one=10.0, class_value=20.0,
        teaching_hours=30.0, ae=40.0, af=0.0,
        provenance={"af": SimpleNamespace(raw_value="=(AD7-30)*AE7")},
    )
    schedule = [
        _record(record_key="aa-course"),
        SimpleNamespace(**{**_record(record_key="ac-course").__dict__, "record_key": "ac-course"}),
    ]
    run = {
        "id": "run-each-field", "period": "2026-07", "period_label": "2026-07",
        "files": {"baseline": {"path": "july.xlsx"}, "schedule": {"path": "schedule.xlsx"}},
        "core_calculation": {"rows": [{"teacher": "教师甲", "fields": {
            "AA": {"value": 12.0}, "AC": {"value": 21.0}, "AD": {"value": 33.0},
            "AE": {"value": 41.0}, "AF": {"value": 123.0, "reason": "AF：(AD − 30) × AE", "evidence": [{"inputs": {"obligation_hours": "30"}}]},
        }}], "course_contributions": [
            {"teacher": "教师甲", "field": "aa", "record_key": "aa-course", "value": 12.0, "evidence": [{"inputs": {"grade_coefficient": "1"}}]},
            {"teacher": "教师甲", "field": "ac", "record_key": "ac-course", "value": 21.0, "evidence": [{"inputs": {"grade_coefficient": "1.5"}}]},
        ]},
    }
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda role, _path, _run: SimpleNamespace(records=[baseline] if role == "baseline" else schedule)

    result = service.historical_reconciliation("run-each-field")
    fields = result["rows"][0]["fields"]

    assert fields["AA"]["difference_category"] == "COURSE_CONTRIBUTION"
    assert fields["AC"]["difference_category"] == "COURSE_CONTRIBUTION"
    assert fields["AD"]["difference_category"] == "COURSE_CONTRIBUTION"
    assert fields["AE"]["difference_category"] == "RULE_DIFFERENCE"
    assert fields["AF"]["difference_category"] == "COURSE_CONTRIBUTION"
    assert fields["AA"]["evidence"][-1]["course_contributions"][0]["field"] == "AA"
    assert fields["AD"]["evidence"][-1]["course_contributions"]


def test_historical_reconciliation_keeps_single_sided_missing_fields_pending(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="教师甲", source="july.xlsx", one_to_one=None, class_value=20.0,
        teaching_hours=None, ae=40.0, af=0.0, provenance={},
    )
    run = {
        "id": "run-missing-field", "period": "2026-07", "period_label": "2026-07",
        "files": {"baseline": {"path": "july.xlsx"}},
        "core_calculation": {"rows": [{"teacher": "教师甲", "fields": {
            "AA": {"value": 10.0}, "AC": {"value": None}, "AD": {"value": None},
            "AE": {"value": None}, "AF": {"value": None},
        }}], "course_contributions": []},
    }
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda _role, _path, _run: SimpleNamespace(records=[baseline])

    result = service.historical_reconciliation("run-missing-field")
    fields = result["rows"][0]["fields"]

    assert fields["AA"]["status"] == "NEEDS_CONFIRMATION"
    assert fields["AA"]["difference_category"] == "MISSING_SOURCE"
    assert fields["AA"]["evidence"][0]["missing_side"] == "historical"
    assert fields["AC"]["status"] == "NEEDS_CONFIRMATION"
    assert fields["AC"]["difference_category"] == "MISSING_SOURCE"
    assert fields["AC"]["evidence"][0]["missing_side"] == "current"
    assert fields["AD"]["status"] == "NEEDS_CONFIRMATION"
    assert fields["AD"]["evidence"][0]["missing_side"] == "both"
    assert fields["AE"]["status"] == "NEEDS_CONFIRMATION"
    assert fields["AE"]["evidence"][0]["missing_side"] == "current"
    assert fields["AF"]["status"] == "NEEDS_CONFIRMATION"
    assert fields["AF"]["evidence"][0]["missing_side"] == "current"
    assert result["category_counts"]["MISSING_SOURCE"] == 5
    assert result["rows"][0]["status"] == "NEEDS_CONFIRMATION"


def test_historical_reconciliation_does_not_call_empty_or_unmatched_courses_contributions(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="教师甲", source="july.xlsx", one_to_one=10.0, class_value=20.0,
        teaching_hours=30.0, ae=40.0, af=0.0, provenance={"af": SimpleNamespace(raw_value="=(AD7-30)*AE7")},
    )
    run = {
        "id": "run-no-course-source", "period": "2026-07", "period_label": "2026-07",
        "files": {"baseline": {"path": "july.xlsx"}},
        "core_calculation": {"rows": [{"teacher": "教师甲", "fields": {
            "AA": {"value": 12.0}, "AC": {"value": 21.0}, "AD": {"value": 33.0},
            "AE": {"value": 40.0}, "AF": {"value": 120.0, "evidence": [{"inputs": {"obligation_hours": "30"}}]},
        }}], "course_contributions": [
            {"teacher": "教师甲", "field": "ac", "record_key": "missing-source", "value": 21.0, "evidence": [{}]},
            {"teacher": "教师甲", "field": "aa", "record_key": "empty-value", "value": None, "evidence": [{}]},
        ]},
    }
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda _role, _path, _run: SimpleNamespace(records=[baseline])

    result = service.historical_reconciliation("run-no-course-source")
    fields = result["rows"][0]["fields"]

    assert fields["AA"]["difference_category"] == "MISSING_SOURCE"
    assert fields["AC"]["difference_category"] == "MISSING_SOURCE"
    assert fields["AD"]["difference_category"] == "MISSING_SOURCE"
    assert fields["AF"]["difference_category"] == "MISSING_SOURCE"
    for code in ("AA", "AC", "AD", "AF"):
        assert fields[code]["evidence"][-1]["course_contributions"] == []
    assert result["category_counts"]["COURSE_CONTRIBUTION"] == 0


def test_historical_reconciliation_requires_source_metadata_for_course_contribution(tmp_path):
    service = PayrollService(tmp_path / "store")
    baseline = SimpleNamespace(
        teacher="教师甲", source="july.xlsx", one_to_one=10.0, class_value=20.0,
        teaching_hours=30.0, ae=40.0, af=0.0, provenance={"af": SimpleNamespace(raw_value="=(AD7-30)*AE7")},
    )
    source_record = SimpleNamespace(**{**_record(record_key="ac-course").__dict__, "source": "", "provenance": {}})
    run = {
        "id": "run-empty-source-metadata", "period": "2026-07", "period_label": "2026-07",
        "files": {"baseline": {"path": "july.xlsx"}, "schedule": {"path": "schedule.xlsx"}},
        "core_calculation": {"rows": [{"teacher": "教师甲", "fields": {
            "AA": {"value": 10.0}, "AC": {"value": 21.0}, "AD": {"value": 31.0},
            "AE": {"value": 40.0}, "AF": {"value": 40.0, "evidence": [{"inputs": {"obligation_hours": "30"}}]},
        }}], "course_contributions": [
            {"teacher": "教师甲", "field": "ac", "record_key": "ac-course", "value": 21.0, "evidence": [{}]},
        ]},
    }
    service._load = lambda _run_id: run
    service._require_fresh = lambda _run: None
    service._read_for_run = lambda role, _path, _run: SimpleNamespace(records=[baseline] if role == "baseline" else [source_record])

    result = service.historical_reconciliation("run-empty-source-metadata")
    fields = result["rows"][0]["fields"]

    assert fields["AC"]["difference_category"] == "MISSING_SOURCE"
    assert fields["AC"]["evidence"][-1]["course_contributions"] == []
    assert result["category_counts"]["COURSE_CONTRIBUTION"] == 0
