"""Stable business-review cards layered on top of immutable field audits.

This module deliberately knows no payroll formulae.  It only turns the raw
``FieldCheck`` audit facts produced by payroll_core into reviewable causes and
binds a human decision to the exact inputs that were reviewed.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any


FIELD_LABELS = {
    "one_to_one": "AA 一对一", "class_value": "AC 班课", "ae": "AE 课时单价",
    "af": "AF 总课时费", "af_policy": "AF 总课时费", "rating": "教师星级",
    "rate": "AE 课时单价", "formula": "公式完整性", "av": "AV 总工资",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def root_cause_key(run_id: str, teacher: str, field: str) -> str:
    if field == "one_to_one":
        cause = "schedule_one_to_one"
    elif field == "class_value":
        cause = "schedule_class_value"
    elif field in {"ae", "rating", "rate"}:
        cause = "compensation_rate_authority"
    elif field in {"af", "af_policy"}:
        cause = "compensation_fee_policy"
    elif field == "formula":
        cause = "formula_integrity"
    else:
        cause = field
    return f"{run_id}:{teacher}:{cause}"


def group_id(cause: str) -> str:
    return "biz-" + hashlib.sha256(cause.encode()).hexdigest()[:16]


def fingerprint(run: dict, records: list[dict], rating_version: dict | None, policy_version: dict | None, bands: list[dict]) -> str:
    """Hash facts, authorities and source identities, never a display label."""
    facts = []
    for row in records:
        fact = {key: row.get(key) for key in ("teacher", "field", "expected", "actual", "status")}
        # Formula audits currently carry their cell coordinate in the reason.
        # Retain it conservatively until the audit API exposes a separate key.
        if row.get("field") == "formula":
            fact["formula_audit"] = row.get("reason")
        facts.append(fact)
    facts.sort(key=canonical)
    payload = {
        "run_id": run["id"],
        "period": run.get("period"),
        "schedule_grade_resolutions": run.get("schedule_grade_resolutions", []),
        "facts": facts,
        "source_hashes": {key: value.get("sha256") for key, value in sorted(run.get("files", {}).items())},
        "rating_version": rating_version,
        "policy_version": policy_version,
        "default_compensation_bands": bands,
    }
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def build_groups(run: dict, records: list[dict], rating_version: dict | None, policy_version: dict | None, bands: list[dict], status_labels: dict[str, str]) -> list[dict]:
    """Build stable cards without discarding individual audit records."""
    actionable = [row for row in records if row.get("status") not in {"MATCH", "FORMULA_MATCH", "RATE_MATCH", "AF_POLICY_MATCH", "READ_ONLY"}]
    buckets: dict[tuple[str, str], list[dict]] = {}
    # Group a rate and total-fee discrepancy only when both audit facts show
    # the same billable hours. Unrelated policy discrepancies stay separate.
    linked_teachers = set()
    for teacher in {row["teacher"] for row in actionable}:
        rates = [r for r in actionable if r["teacher"] == teacher and r["field"] == "rate" and r["status"] == "RATE_MISMATCH"]
        fees = [r for r in actionable if r["teacher"] == teacher and r["field"] == "af_policy" and r["status"] == "AF_POLICY_MISMATCH"]
        if len(rates) == len(fees) == 1:
            rate, fee = rates[0], fees[0]
            values = [rate.get("expected"), rate.get("actual"), fee.get("expected"), fee.get("actual")]
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in values) and rate["expected"] > 0 and rate["actual"] > 0:
                if math.isclose(fee["expected"] / rate["expected"], fee["actual"] / rate["actual"], rel_tol=0, abs_tol=0.000001):
                    linked_teachers.add(teacher)
    for row in actionable:
        cause = root_cause_key(run["id"], row["teacher"], row["field"])
        if row["teacher"] in linked_teachers and row["field"] in {"rate", "af_policy"}:
            cause = f"{run['id']}:{row['teacher']}:compensation_basis"
        buckets.setdefault((row["teacher"], cause), []).append(row)
    decisions = {item.get("group_id"): item for item in run.get("business_decisions", [])}
    output = []
    for (teacher, cause), rows in buckets.items():
        rows = sorted(rows, key=lambda row: (row["severity_rank"], row["field"], row["id"]))
        main = rows[0]
        ident = group_id(cause)
        bound = fingerprint(run, rows, rating_version, policy_version, bands)
        decision = decisions.get(ident)
        if decision and decision.get("fingerprint") != bound and decision.get("status") != "NEEDS_RECONFIRMATION":
            decision["status"] = "NEEDS_RECONFIRMATION"
        title = {
            "compensation_basis": "档位与课时费依据需要处理",
            "compensation_rate_authority": "星级与课时单价依据需要处理",
            "compensation_fee_policy": "总课时费政策依据需要处理",
            "schedule_one_to_one": "一对一折算小时需要处理",
            "schedule_class_value": "班课折算小时需要处理",
            "formula_integrity": "工资表公式异常",
        }.get(cause.rsplit(":", 1)[-1], main["title"])
        active = decision if decision and decision.get("status") != "NEEDS_RECONFIRMATION" else None
        output.append({
            "id": ident, "root_cause_key": cause, "fingerprint": bound, "teacher": teacher,
            "title": title, "fields": [FIELD_LABELS.get(row["field"], row.get("field_label", row["field"])) for row in rows],
            "affected_fields": [row["field"] for row in rows], "reason": main["reason"],
            "status_label": status_labels.get(main["status"], "需要处理"), "severity_rank": min(row["severity_rank"] for row in rows),
            "severity_label": min(rows, key=lambda row: row["severity_rank"])["severity_label"],
            "expected": main.get("expected"), "actual": main.get("actual"), "difference": main.get("difference"),
            "field_records": len(rows), "field_record_ids": [row["id"] for row in rows],
            "decision": decision, "decision_label": "依据已变化，需重新确认" if decision and not active else decision_label(active),
        })
    return sorted(output, key=lambda row: (row["severity_rank"], row["title"], row["teacher"], row["id"]))


def decision_label(decision: dict | None) -> str:
    if not decision:
        return "待处理"
    return {
        "CONFIRMED_ERROR": "已确认错误",
        "ACCEPTED_EXCEPTION": "已接受例外",
        "DEFERRED": "暂缓处理",
    }.get(decision.get("action"), "已记录意见")


def invalidate(decisions: list[dict]) -> None:
    for decision in decisions:
        decision["status"] = "NEEDS_RECONFIRMATION"
