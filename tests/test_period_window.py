from payroll_core.period import calendar_bounds, coverage_for, normalize_period_window
from payroll_ui.service import PayrollService


def test_period_window_defaults_are_explicit_legacy_calendar():
    assert normalize_period_window("2026-07") == {
        "period_label": "2026-07",
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "period_boundary_source": "LEGACY_CALENDAR_DEFAULT",
    }
    assert calendar_bounds("2026-02") == ("2026-02-01", "2026-02-28")


def test_new_run_persists_label_and_explicit_window(tmp_path):
    service = PayrollService(tmp_path / "data")
    run = service.create("2026-07", "GENERATE", period_start="2026-06-29", period_end="2026-08-02", period_boundary_source="SOURCE_FILE_RANGE")
    assert run["period_label"] == "2026-07"
    assert run["period"] == "2026-07"
    assert run["period_start"] == "2026-06-29"
    assert run["period_end"] == "2026-08-02"
    assert run["period_boundary_source"] == "SOURCE_FILE_RANGE"
    loaded = service.get(run["id"])
    assert loaded["period_display"] == {"label": "2026-07", "start": "2026-06-29", "end": "2026-08-02", "boundary_source": "SOURCE_FILE_RANGE"}


def test_coverage_uses_explicit_window_end_for_cross_month_run():
    coverage = coverage_for(
        "2026-07",
        ["2026-06-29", "2026-07-31", "2026-08-02"],
        period_start="2026-06-29",
        period_end="2026-08-02",
    )
    assert coverage.month_end == "2026-08-02"
    assert coverage.incomplete_tail is False
    assert coverage.outside_period is False
    assert coverage.as_dict()["period_start"] == "2026-06-29"
