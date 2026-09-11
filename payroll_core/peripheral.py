"""Authority-backed payroll components outside the teaching-pay Core.

This module deliberately never reads AA/AC/AD/AE/AF inputs and never derives a
renewal, refund or HR policy.  It only totals values explicitly supplied by an
approved upstream authority record.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping


COMPONENT_CODES = {
    "RENEWAL_RESULT": "RENEWAL",
    "REFUND_RESULT": "REFUND",
    "HR_ALLOWANCE": "HR_ALLOWANCE",
    "HR_ATTENDANCE": "HR_ATTENDANCE",
}


def _amount(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("权威表中的工资影响金额必须是数字。") from exc
    if not result.is_finite():
        raise ValueError("权威表中的工资影响金额必须是有限数字。")
    return result


def summarize_authority_components(records: Iterable[Mapping[str, object]]) -> dict:
    """Return per-teacher authoritative components without inventing values.

    A record with no explicit ``payroll_amount`` remains ``SOURCE_READY``: it
    is archived and traceable but cannot silently become a payroll amount.
    """
    rows: dict[str, dict] = {}
    for record in records:
        teacher = str(record.get("teacher_id", "")).strip()
        if not teacher:
            continue
        raw_code = str(record.get("component_code", ""))
        code = COMPONENT_CODES.get(raw_code, COMPONENT_CODES.get(str(record.get("input_type", "")), raw_code))
        if not code:
            continue
        row = rows.setdefault(teacher, {"teacher": teacher, "components": [], "total": Decimal("0"), "status": "DETERMINED"})
        payload = record.get("payload") or {}
        if str(record.get("input_type", "")) == "RENEWAL_RESULT" and isinstance(payload.get("payroll_fields"), Mapping):
            fields = payload["payroll_fields"]
            award = _amount(fields.get("AK"))
            if award is None:
                raise ValueError("续费推荐数据缺少推荐续费奖计算结果。")
            row["components"].append({
                "code": "RENEWAL_AWARD", "input_id": record.get("id", ""), "amount": str(award),
                "source_hash": record.get("source_file_hash", ""), "source_row": record.get("source_row", ""),
                "status": "DETERMINED", "payroll_fields": {key: str(value) for key, value in fields.items()},
            })
            row["total"] += award
            continue
        amount = _amount(payload.get("payroll_amount"))
        component = {"code": code, "input_id": record.get("id", ""), "amount": None if amount is None else str(amount), "source_hash": record.get("source_file_hash", ""), "source_row": record.get("source_row", ""), "status": "DETERMINED" if amount is not None else "SOURCE_READY"}
        row["components"].append(component)
        if amount is None:
            row["status"] = "SOURCE_READY"
        else:
            row["total"] += amount
    return {teacher: {**row, "total": str(row["total"])} for teacher, row in rows.items()}
