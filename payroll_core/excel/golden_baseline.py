"""Independent formula contract for the supplied payroll template.

This module is intentionally separate from the renderer.  Template output
validation must compare against a stable contract rather than calling the
same writer helper that produced the workbook.
"""
from __future__ import annotations

from typing import Any, Mapping


def golden_formula_for_row(row: Any, code: str, row_number: int) -> str:
    if code == "AA":
        return f"=(N{row_number}+O{row_number}+P{row_number}+Q{row_number}+R{row_number}+S{row_number})/3*2*0.85+(T{row_number}+U{row_number})/3*2*0.9+V{row_number}/3*2*1+W{row_number}/3*2*1.1+X{row_number}/3*2*1.25+Y{row_number}/3*2*1.35+Z{row_number}/3*2*1.5"
    if code == "AD":
        return f"=AA{row_number}+AC{row_number}"
    if code == "AF":
        obligation = 30
        fields = row.fields if isinstance(getattr(row, "fields", None), Mapping) else {}
        evidence = fields.get("AF", {}).get("evidence", ()) if isinstance(fields.get("AF", {}), Mapping) else ()
        for item in evidence:
            raw = item.get("inputs", {}).get("obligation_hours") if isinstance(item, Mapping) else None
            if raw not in (None, ""):
                try:
                    obligation = float(raw)
                except (TypeError, ValueError):
                    pass
                break
        shown = str(int(obligation)) if float(obligation).is_integer() else str(obligation)
        return f"=MAX(0,(AD{row_number}-{shown})*AE{row_number})"
    if code == "AK":
        return f"=AH{row_number}*1+AI{row_number}*1.5+AJ{row_number}*0.75"
    if code == "AV":
        return f"=M{row_number}+AF{row_number}+AG{row_number}+AK{row_number}+AL{row_number}+AN{row_number}+AO{row_number}+AP{row_number}+AQ{row_number}+AR{row_number}+AS{row_number}+AT{row_number}+AU{row_number}+AM{row_number}"
    raise KeyError(code)
