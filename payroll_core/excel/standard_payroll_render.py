"""Render a generated payroll model into Excel.

The workbook is written from the Core model, never copied from a teacher's
submitted sheet, and an existing file is never overwritten. Unconfirmed rows
carry their reason in the sheet so a draft can never be mistaken for a final
payroll.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from ..payroll_generation import GeneratedPayroll, STATUS_FINAL


HEADERS = (
    "教师", "AA 一对一折算小时", "AC 班课折算小时", "AD 最终授课小时",
    "AE 该档每小时金额", "AF 总课时费", "AV 总工资", "状态", "待确认原因",
)


def render_generated_payroll(payroll: GeneratedPayroll, output: str | Path) -> str:
    target = Path(output)
    if target.exists():
        raise ValueError(f"输出文件已存在，不能覆盖：{target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)

    book = Workbook()
    sheet = book.active
    sheet.title = "标准工资表"
    headline = f"{payroll.period} 标准工资表（由 Core 计算结果生成，非复制任何提交表）"
    sheet.append([headline])
    sheet["A1"].font = Font(bold=True)
    sheet.append([f"状态：{'已可直接采用' if payroll.final else '草稿 / 待确认——不得作为最终工资'}"])
    sheet.append(list(HEADERS))
    for column in range(1, len(HEADERS) + 1):
        sheet.cell(3, column).font = Font(bold=True)

    for row in payroll.rows:
        sheet.append([
            row.teacher,
            _value(row.one_to_one), _value(row.class_value), _value(row.teaching_hours),
            _value(row.ae), _value(row.af), _value(row.av),
            "待确认" if not row.final else "已计算",
            "、".join(row.blockers),
        ])
    book.save(target)
    return str(target.resolve())


def _value(number: float | None):
    return None if number is None else round(float(number), 4)
