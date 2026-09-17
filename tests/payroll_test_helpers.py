"""Shared test helpers for the template-bound export contract."""
from __future__ import annotations

from pathlib import Path
from shutil import copyfile

from openpyxl import load_workbook


TEMPLATE_PATH = Path("/Users/macos/Desktop/payroll_read_test/薪资表模板.xlsx")
if not TEMPLATE_PATH.is_file():
    TEMPLATE_PATH = Path(__file__).parent / "fixtures" / "excel" / "fake_payroll.xlsx"


def bind_template(service, run):
    """Bind the checked-in sanitized company-template fixture to a run."""
    current = service.store.get(run["id"])
    bound = service.store.path.parent / "脱敏公司工资模板.xlsx"
    copyfile(TEMPLATE_PATH, bound)
    book = load_workbook(bound)
    book.worksheets[0].title = "标准工资表"
    book.save(bound)
    current["template_path"] = str(bound.resolve())
    current["template"] = {
        "name": bound.name,
        "path": str(bound.resolve()),
        "source": "测试用脱敏公司工资模板",
    }
    service.store.save(current)
    return current
