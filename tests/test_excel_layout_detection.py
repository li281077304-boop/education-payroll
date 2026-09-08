from pathlib import Path

from openpyxl import Workbook

from payroll_core.excel.inspect import inspect_workbook


FIXTURES = Path(__file__).parent / "fixtures" / "excel"


def test_known_workbook_layouts_are_fingerprinted():
    expected = {
        "fake_schedule.xlsx": "SCHEDULE_EXPORT_V1",
        "fake_payroll.xlsx": "PAYROLL_SHEET_V1",
        "fake_check_workbook.xlsx": "PAYROLL_CHECK_V1",
    }
    for filename, layout in expected.items():
        result = inspect_workbook(FIXTURES / filename)
        assert result.ok
        assert result.records[0].fingerprint.layout == layout


def test_unknown_layout_is_rejected_without_guessing(tmp_path):
    path = tmp_path / "unknown.xlsx"
    workbook = Workbook()
    workbook.active.title = "not-a-payroll-sheet"
    workbook.active["A1"] = "unrelated heading"
    workbook.save(path)

    result = inspect_workbook(path)

    assert not result.ok
    assert result.errors[0].code == "UNSUPPORTED_LAYOUT"
