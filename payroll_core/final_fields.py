"""Final-payroll fields that sit downstream of the Core teaching chain.

This module deliberately separates two questions:

* whether a historical column has a documented meaning; and
* whether this run has an approved, bound value for that column.

Only the small set of fields with an explicit repository rule is calculated
here.  A missing source is represented as ``HUMAN_REQUIRED`` with a specific
reason.  It is never converted to zero merely to make AV add up.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


HUMAN_REQUIRED = "HUMAN_REQUIRED"
DETERMINED = "DETERMINED"
NOT_APPLICABLE = "NOT_APPLICABLE"
NEEDS_INPUT = "NEEDS_INPUT"

# Historical final-payroll columns after the Core AF value.  Keep the codes in
# workbook order so the output contract and the audit sheet cannot drift.
FINAL_FIELD_CODES: tuple[str, ...] = (
    "AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN", "AO", "AP",
    "AQ", "AR", "AS", "AT", "AU", "AV",
)

# Components used by the documented historical AV total formula.  AH/AI/AJ
# feed AK, but are not added a second time.
AV_COMPONENTS: tuple[str, ...] = (
    "AF", "AG", "AK", "AL", "AM", "AN", "AO", "AP", "AQ", "AR",
    "AS", "AT", "AU",
)

FIELD_LABELS: dict[str, str] = {
    "AG": "AG 未确认工资项目",
    "AH": "AH 续费一对一课时",
    "AI": "AI 续费班课课时",
    "AJ": "AJ 领航续费课时",
    "AK": "AK 推荐续费奖",
    "AL": "AL 未确认工资项目",
    "AM": "AM 管理团队奖",
    "AN": "AN 退费/拒收学员",
    "AO": "AO 其他",
    "AP": "AP 未确认工资项目",
    "AQ": "AQ 未确认工资项目",
    "AR": "AR 未确认工资项目",
    "AS": "AS 月度激励",
    "AT": "AT 未确认工资项目",
    "AU": "AU 未确认工资项目",
    "AV": "AV 总工资",
}

FIELD_NOTES: dict[str, str] = {
    "AG": "仓库现有资料未明确 AG 的业务含义、计算规则和权威来源。",
    "AH": "缺少已审核并绑定的续费最终结果；需要明确 1V1 合计。",
    "AI": "缺少已审核并绑定的续费最终结果；需要明确班课合计。",
    "AJ": "缺少已审核并绑定的续费最终结果；需要明确领航合计。",
    "AK": "AH、AI、AJ 必须全部由同一份已审核续费结果确定后才能计算。",
    "AL": "仓库现有资料未明确 AL 的业务含义、计算规则和权威来源。",
    "AM": "管理考核金额与管理团队奖公式的口径尚未统一；缺少可直接用于 AM 的权威金额规则。",
    "AN": "缺少已审核并绑定的退费最终结果；需要按扣款教师汇总人头和业绩。",
    "AO": "仓库现有资料未明确 AO 的业务含义、计算规则和权威来源。",
    "AP": "仓库现有资料未明确 AP 的业务含义、计算规则和权威来源。",
    "AQ": "仓库现有资料未明确 AQ 的业务含义、计算规则和权威来源。",
    "AR": "仓库现有资料未明确 AR 的业务含义、计算规则和权威来源。",
    "AS": "缺少已审核、明确标注 AS 的月度激励结果及生效期。",
    "AT": "仓库现有资料未明确 AT 的业务含义、计算规则和权威来源。",
    "AU": "仓库现有资料未明确 AU 的业务含义、计算规则和权威来源。",
    "AV": "AV 依赖 AF、AG、AK、AL、AM、AN、AO、AP、AQ、AR、AS、AT、AU 全部确定；未知项不能按 0 汇总。",
}

RENEWAL_ALIASES: dict[str, tuple[str, ...]] = {
    "AH": ("AH", "one_to_one_hours", "1V1合计", "一对一合计", "续费一对一", "续费1V1"),
    "AI": ("AI", "class_hours", "班课合计", "续费班课", "续费班课课时"),
    "AJ": ("AJ", "mentor_hours", "小班领航合计", "领航合计", "领航续费"),
}


def _empty(code: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "value": None,
        "state": HUMAN_REQUIRED,
        "reason": reason or FIELD_NOTES[code],
        "evidence": [],
    }


# In a package-backed production run, an input that has no occurrence for the
# month is a real zero, not an unresolved business decision.  This covers the
# optional renewal/refund components as well as the historically sparse
# incentive columns; explicit, approved source values still take precedence.
ZERO_WHEN_ABSENT_CODES: tuple[str, ...] = (
    "AG", "AH", "AI", "AJ", "AK", "AL", "AM", "AN", "AO", "AP",
    "AQ", "AR", "AS", "AT", "AU",
)


def _absent_zero(code: str) -> dict[str, Any]:
    return {
        "value": 0.0,
        "state": DETERMINED,
        "reason": f"本期没有 {code} 项目记录；按本月业务决定默认 0。",
        "evidence": [{"kind": "DEFAULT_ZERO_ABSENT_ACTIVITY", "field": code}],
    }


def _number(value: object, label: str) -> Decimal:
    if value is None or value == "":
        raise ValueError(f"{label} 缺少数值。")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} 不是数字：{value!r}") from exc
    if not number.is_finite():
        raise ValueError(f"{label} 不是有限数字。")
    return number


def _as_float(value: Decimal | int | float | None) -> float | None:
    return None if value is None else float(value)


def _payload(item: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = item.get("payload", {})
    return payload if isinstance(payload, Mapping) else {}


def _first(payload: Mapping[str, Any], aliases: Iterable[str]) -> tuple[str, object] | None:
    for alias in aliases:
        if alias in payload and payload[alias] not in (None, ""):
            return alias, payload[alias]
    return None


def _evidence(item: Mapping[str, Any], *, field: str, inputs: Mapping[str, object] | None = None) -> dict[str, Any]:
    return {
        "kind": "APPROVED_BUSINESS_INPUT",
        "source": item.get("source_ref", ""),
        "source_input_id": item.get("id", ""),
        "source_row": item.get("source_row", ""),
        "field": field,
        "inputs": {str(k): str(v) for k, v in (inputs or {}).items()},
    }


def _source_items(items: Iterable[Mapping[str, Any]], input_type: str, teacher: str) -> list[Mapping[str, Any]]:
    return [
        item for item in items
        if item.get("status") == "APPROVED"
        and item.get("input_type") == input_type
        and str(item.get("teacher_id", "")) == teacher
    ]


def _renewal_fields(items: list[Mapping[str, Any]], teacher: str) -> dict[str, dict[str, Any]]:
    output = {code: _empty(code) for code in ("AH", "AI", "AJ")}
    if not items:
        return output
    if len(items) > 1:
        reason = "同一教师命中多条已审核续费结果，需确认采用哪一条，不能静默相加。"
        return {code: _empty(code, reason) for code in output}
    item = items[0]
    payload = _payload(item)
    for code, aliases in RENEWAL_ALIASES.items():
        match = _first(payload, aliases)
        if match is None:
            continue
        key, raw = match
        try:
            value = _number(raw, f"{teacher} {code}")
        except ValueError as exc:
            output[code] = _empty(code, str(exc))
            continue
        if value < 0:
            output[code] = _empty(code, f"{teacher} {code} 不能为负数：{value}。")
            continue
        output[code] = {
            "value": _as_float(value),
            "state": DETERMINED,
            "reason": f"{code} 取已审核续费结果中的明确合计字段。",
            "evidence": [_evidence(item, field=code, inputs={key: value})],
        }
    return output


def _refund_field(items: list[Mapping[str, Any]], teacher: str) -> dict[str, Any]:
    if not items:
        return _empty("AN")
    total = Decimal("0")
    evidence: list[dict[str, Any]] = []
    found = False
    for item in items:
        payload = _payload(item)
        parts: dict[str, Decimal] = {}
        for key, aliases in {
            "headcount_amount": ("headcount_amount", "人头", "退费人头", "人头金额"),
            "performance_amount": ("performance_amount", "业绩", "退费业绩", "业绩金额"),
        }.items():
            match = _first(payload, aliases)
            if match is not None:
                try:
                    parts[key] = _number(match[1], f"{teacher} AN {key}")
                except ValueError as exc:
                    return _empty("AN", str(exc))
        if not parts:
            explicit = _first(payload, ("AN", "refund_total", "退费合计"))
            if explicit is not None:
                try:
                    parts["refund_total"] = _number(explicit[1], f"{teacher} AN")
                except ValueError as exc:
                    return _empty("AN", str(exc))
        if not parts:
            return _empty("AN", "退费结果没有明确的人头、业绩或退费合计字段，不能把缺失当作 0。")
        found = True
        total += sum(parts.values(), Decimal("0"))
        evidence.append(_evidence(item, field="AN", inputs=parts))
    if not found:
        return _empty("AN")
    return {
        "value": _as_float(total),
        "state": DETERMINED,
        "reason": "AN 按已审核退费结果的扣款教师归属，汇总人头和业绩金额。",
        "evidence": evidence,
    }


def _explicit_field_inputs(items: list[Mapping[str, Any]], teacher: str) -> dict[str, dict[str, Any]]:
    """Accept only an explicitly named target field from an approved result.

    This is an adapter for future source-backed fields such as AS.  It does
    not decide what an unlabeled ``amount`` belongs to, and rejects duplicate
    values instead of silently adding possibly different business concepts.
    """
    output: dict[str, dict[str, Any]] = {}
    for item in items:
        payload = _payload(item)
        raw_field = payload.get("target_field", payload.get("field"))
        if raw_field is None:
            continue
        code = str(raw_field).strip().upper()
        if code not in FINAL_FIELD_CODES or code in {"AH", "AI", "AJ", "AK", "AN", "AV"}:
            continue
        raw_value = _first(payload, ("value", "amount", code))
        if raw_value is None:
            output[code] = _empty(code, f"{teacher} 的 {code} 结果已标注字段，但没有明确金额。")
            continue
        try:
            value = _number(raw_value[1], f"{teacher} {code}")
        except ValueError as exc:
            output[code] = _empty(code, str(exc))
            continue
        if code in output:
            output[code] = _empty(code, f"{teacher} 命中多条明确指向 {code} 的结果，需确认是否合并。")
            continue
        output[code] = {
            "value": _as_float(value),
            "state": DETERMINED,
            "reason": f"{code} 取已审核结果中明确标注该字段的金额。",
            "evidence": [_evidence(item, field=code, inputs={"value": value})],
        }
    return output


def _av_field(fields: Mapping[str, Mapping[str, Any]], teacher: str) -> dict[str, Any]:
    payable_states = {DETERMINED, NOT_APPLICABLE, "ESTIMATED"}
    missing = [
        code for code in AV_COMPONENTS
        if fields.get(code, {}).get("state") not in payable_states
        or (fields.get(code, {}).get("state") in payable_states and fields.get(code, {}).get("value") is None)
    ]
    if missing:
        return _empty("AV", f"{FIELD_NOTES['AV']} 未确定组件：{', '.join(missing)}。")
    total = sum((Decimal(str(fields[code]["value"])) if fields[code].get("state") in payable_states else Decimal("0") for code in AV_COMPONENTS), Decimal("0"))
    evidence = [{"kind": "AV_CALCULATION", "formula": "AF + AG + AK + AL + AM + AN + AO + AP + AQ + AR + AS + AT + AU", "inputs": {code: str(fields[code].get("value", 0)) for code in AV_COMPONENTS}}]
    return {
        "value": _as_float(total),
        "state": DETERMINED,
        "reason": "AV 按已确定的最终工资组成项汇总；未确定项不会按 0 代替。",
        "evidence": evidence,
    }


def resolve_final_fields(
    *,
    teacher: str,
    core_fields: Mapping[str, Mapping[str, Any]],
    business_inputs: Iterable[Mapping[str, Any]] = (),
    employment_type: str = "FULL_TIME",
    default_zero_missing: bool = False,
) -> dict[str, dict[str, Any]]:
    """Resolve downstream final fields for one teacher.

    ``business_inputs`` must already be loaded from the run store.  This
    function still checks APPROVED and teacher identity, so callers cannot
    accidentally feed draft or another teacher's records into a result.
    """
    items = [item for item in business_inputs if isinstance(item, Mapping)]
    fields = {code: (_absent_zero(code) if default_zero_missing and code in ZERO_WHEN_ABSENT_CODES else _empty(code)) for code in FINAL_FIELD_CODES}
    renewal_items = _source_items(items, "RENEWAL_RESULT", teacher)
    renewal = _renewal_fields(renewal_items, teacher)
    if default_zero_missing and not renewal_items:
        renewal = {code: _absent_zero(code) for code in ("AH", "AI", "AJ")}
    fields.update(renewal)
    fields["AK"] = _empty("AK")
    if all(renewal[code].get("state") == DETERMINED for code in ("AH", "AI", "AJ")):
        values = {code: Decimal(str(renewal[code]["value"])) for code in ("AH", "AI", "AJ")}
        reward = values["AH"] + values["AI"] * Decimal("1.5") + values["AJ"] * Decimal("0.75")
        fields["AK"] = {
            "value": _as_float(reward),
            "state": DETERMINED,
            "reason": "AK = AH × 1 + AI × 1.5 + AJ × 0.75。",
            "evidence": [{"kind": "AK_CALCULATION", "formula": "AH × 1 + AI × 1.5 + AJ × 0.75", "inputs": {code: str(values[code]) for code in ("AH", "AI", "AJ")}}],
        }
    refund_items = _source_items(items, "REFUND_RESULT", teacher)
    fields["AN"] = _refund_field(refund_items, teacher)
    if default_zero_missing and not refund_items:
        fields["AN"] = _absent_zero("AN")
    fields.update(_explicit_field_inputs(_source_items(items, "OTHER", teacher), teacher))

    # The existing management-award rule names group leaders / teaching
    # owners as its applicable population.  Ordinary teachers therefore have
    # no AM component; they must not be blocked merely because no management
    # award exists.  A management row remains HUMAN_REQUIRED until its
    # conflicting/partial source policy is resolved or an explicit AM result
    # is approved.
    if not default_zero_missing and employment_type != "MANAGEMENT" and fields["AM"].get("state") == HUMAN_REQUIRED:
        fields["AM"] = {
            "value": None,
            "state": NOT_APPLICABLE,
            "reason": "AM 管理团队奖仅适用于管理岗位；当前教师岗位不适用。",
            "evidence": [],
        }

    # AM is intentionally not populated from management assessment results:
    # the repository has both a score-to-amount assessment path and a distinct
    # management-team-award formula, but no authority resolving their meaning.
    af = core_fields.get("AF", {})
    part_time = core_fields.get("PART_TIME", {})
    # Core marks the teaching-chain AF as NOT_APPLICABLE for a part-time
    # teacher because part-time pay is calculated per scheduled lesson. That
    # marker must not hide the separately determined PART_TIME amount: the
    # final-payroll AF field is still the payable amount and feeds AV.
    if employment_type == "PART_TIME" and part_time.get("state") == DETERMINED and part_time.get("value") is not None:
        fields["AF"] = {**part_time, "reason": "兼职 AF = 已上课节数 × 已确认每节单价。"}
    elif af.get("state") in {DETERMINED, NOT_APPLICABLE, "ESTIMATED"}:
        fields["AF"] = dict(af)
    else:
        fields["AF"] = {"value": None, "state": NEEDS_INPUT, "reason": "AF 核心课时费尚未确定，AV 不能继续汇总。", "evidence": []}
    fields["AV"] = _av_field(fields, teacher)
    return fields
