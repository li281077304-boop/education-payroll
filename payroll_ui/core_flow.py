"""Version binding and orchestration; payroll mathematics stays in Core."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from .business import invalidate


def valid_period(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value))


class CoreFlow:
    @staticmethod
    def _policy_snapshot_hash(snapshot: dict) -> str:
        payload = {key: value for key, value in snapshot.items() if key != "sha256"}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()

    def _build_run_policy_snapshot(self, run: dict) -> dict:
        """Freeze the effective compensation policies at Run creation.

        The calculation engines remain the authority for payroll arithmetic;
        this snapshot only freezes which dated policy records they receive.
        Older Runs without this field deliberately retain their legacy
        version-id lookup behaviour.
        """
        period = run["period"]
        default_hours = 30.0
        core = self._calculation_version(run, "core")
        if core:
            candidate = (core.get("rules") or {}).get("af", {}).get("default_policy_candidate") or {}
            try:
                if candidate.get("obligation_hours") is not None:
                    default_hours = float(candidate["obligation_hours"])
            except (TypeError, ValueError):
                default_hours = 30.0
        personal = self._policy_version_for_run_legacy(run)
        personal_profiles = []
        if personal and personal.get("effective_from", period) <= period <= personal.get("effective_to", period):
            personal_profiles = copy.deepcopy(personal.get("profiles") or [])
        part_time = self._calculation_version_legacy(run, "part_time")
        part_profiles = []
        if part_time and part_time.get("effective_from", period) <= period <= part_time.get("effective_to", period):
            part_profiles = copy.deepcopy(part_time.get("profiles") or [])
        snapshot = {
            "version": "RUN_POLICY_SNAPSHOT/v1",
            "run_id": run["id"],
            "period": period,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "default_full_time": {
                "policy_type": "DEFAULT_FULL_TIME",
                "obligation_hours": default_hours,
                "unit": "HOURS",
                "source": (core or {}).get("source", "Core AF 默认政策候选"),
                "source_hash": (core or {}).get("sha256", ""),
                "status": "ACTIVE",
            },
            "personal_policies": personal_profiles,
            "part_time_rates": part_profiles,
            "policy_version_id": run.get("policy_version_id"),
            "part_time_rate_version_id": run.get("part_time_rate_version_id"),
            "core_rule_version_id": run.get("core_rule_version_id"),
        }
        snapshot["sha256"] = self._policy_snapshot_hash(snapshot)
        return snapshot

    def _policy_version_for_run_legacy(self, run: dict) -> dict | None:
        version_id = run.get("policy_version_id")
        return self.store.get_policy_version(version_id) if version_id else None

    def _calculation_version_legacy(self, run: dict, kind: str) -> dict | None:
        key = {"core": "core_rule_version_id", "part_time": "part_time_rate_version_id"}[kind]
        bound = run.get(key)
        if not bound:
            return None
        return next((item for item in self.store.calculation_versions(kind) if item["id"] == bound), None)

    def _configured_calculation(self, run: dict, schedule: list, payroll: list, effective_ac: dict | None = None) -> dict:
        from payroll_core.calculation import calculate_payroll
        from payroll_core.config.core_rules import CoreRules
        from payroll_core.reconcile.payroll_scope import star_from_level
        rule_version = self._calculation_version(run, "core")
        rating = self._rating_version_for_run(run)
        policy = self._policy_version_for_run(run)
        part_time = self._calculation_version(run, "part_time")
        teachers = {r.teacher for r in schedule} | {r.teacher for r in payroll}
        if run.get("mode") == "GENERATE":
            teachers.update(p["teacher"] for p in (policy or {}).get("profiles", []))
        employment_facts = self._employment_types_for(run, teachers=sorted(teachers))
        profiles, contexts = [], []
        af_confirmation = run.get("af_policy_confirmation") or {}
        af_exceptions = af_confirmation.get("exceptions") or {}
        af_confirmed = bool(af_confirmation.get("confirmed"))
        try:
            af_default_hours = float(af_confirmation.get("default_obligation_hours", 30))
        except (TypeError, ValueError):
            af_default_hours = 30.0
        af_source = str(af_confirmation.get("source") or "本次核算义务课时确认")
        af_effective_from = str(af_confirmation.get("effective_from") or run["period"])
        af_effective_to = str(af_confirmation.get("effective_to") or run["period"])
        # A dated PART_TIME_RATE version is itself an explicit employment
        # signal when no separate personal policy record exists.  Keep the
        # existing policy/profile path authoritative when present, but do not
        # silently treat a teacher with an approved per-lesson policy as a
        # full-time teacher (which would skip the part-time calculation).
        part_time_profiles = (part_time or {}).get("profiles", [])
        personnel_contexts = {
            str(item.get("teacher", "")): item
            for item in (run.get("personnel_contexts") or [])
            if item.get("teacher")
        }
        for teacher in sorted(teachers):
            matching = [p for p in (policy or {}).get("profiles", []) if p["teacher"] == teacher]
            if len(matching) > 1:
                raise ValueError("个人工资政策同一教师存在重复记录，请先确认权威版本。")
            profile = matching[0] if matching else {}
            employment_fact = employment_facts.get(teacher) or {}
            resolved_employment = employment_fact.get("employment_type")
            rate_matches = [p for p in part_time_profiles if p.get("teacher") == teacher]
            if not profile and rate_matches:
                profile = {
                    "teacher": teacher,
                    "role": "教师",
                    "employment_type": "PART_TIME",
                    "allow_no_teaching": False,
                    "source": part_time.get("source", "兼职定价政策"),
                    "effective_from": part_time.get("effective_from", run["period"]),
                    "effective_to": part_time.get("effective_to", run["period"]),
                    "policy_type": "PART_TIME_RATE",
                }
            # Employment identity is a separate durable fact from the dated
            # AF/pay policy profile. A prior policy row defaulted to
            # FULL_TIME must not turn a teacher with an explicit long-term
            # PART_TIME profile back into the full-time AA/AC/AF chain.
            if resolved_employment == "PART_TIME":
                profile = {
                    **profile,
                    "teacher": teacher,
                    "role": profile.get("role", "教师"),
                    "employment_type": "PART_TIME",
                    "allow_no_teaching": False,
                    "source": employment_fact.get("source_label") or employment_fact.get("source") or "已确认的兼职用工性质",
                    "effective_from": run["period"],
                    "effective_to": run["period"],
                }
            elif resolved_employment == "FULL_TIME" and profile.get("employment_type") == "PART_TIME":
                # A current authoritative support/personnel source can also
                # correct an obsolete part-time flag. Preserve the remaining
                # dated policy fields and replace only the employment type.
                profile = {
                    **profile,
                    "teacher": teacher,
                    "employment_type": "FULL_TIME",
                    "source": employment_fact.get("source_label") or employment_fact.get("source") or "当前工资资料明确的全职身份",
                }
            elif not profile and personnel_contexts.get(teacher, {}).get("employment_type") == "PART_TIME":
                # A personnel source can establish the employment type even
                # when its rate is missing.  Keep the teacher on the
                # PART_TIME path so Core reports NEEDS_INPUT rather than
                # silently calculating a full-time salary.
                source_context = personnel_contexts[teacher]
                profile = {
                    "teacher": teacher,
                    "role": "教师",
                    "employment_type": "PART_TIME",
                    "allow_no_teaching": False,
                    "source": source_context.get("source", "人员资料"),
                    "effective_from": source_context.get("effective_from", run["period"]),
                    "effective_to": source_context.get("effective_to", run["period"]),
                    "policy_type": "PART_TIME_RATE",
                }
            # A confirmed Run-level default supplies the missing full-time
            # policy without replacing an existing dated personal profile.
            # Explicit exceptions intentionally override that profile for this
            # Run only; the immutable policy version remains untouched.
            exception = af_exceptions.get(teacher)
            if af_confirmed and exception is not None:
                profile = {
                    **profile,
                    "teacher": teacher,
                    "role": profile.get("role", "教师"),
                    "employment_type": profile.get("employment_type", "FULL_TIME"),
                    "obligation_hours": float(exception.get("obligation_hours", af_default_hours)),
                    "obligation_hours_deduction_enabled": bool(exception.get("deduction_enabled", True)),
                    "source": af_source,
                    "effective_from": af_effective_from,
                    "effective_to": af_effective_to,
                    "note": str(exception.get("reason", "")),
                    "run_level_confirmation": True,
                }
            elif af_confirmed and not profile:
                profile = {
                    "teacher": teacher,
                    "role": "教师",
                    "employment_type": "FULL_TIME",
                    "obligation_hours": af_default_hours,
                    "obligation_hours_deduction_enabled": True,
                    "source": af_source,
                    "effective_from": af_effective_from,
                    "effective_to": af_effective_to,
                    "note": str(af_confirmation.get("reason", "")),
                    "run_level_confirmation": True,
                }
            metadata = {k: policy[k] for k in ("effective_from", "effective_to", "source")} if policy else {}
            context = {"teacher": teacher, "employment_type": profile.get("employment_type", "FULL_TIME"), "allow_no_teaching": profile.get("allow_no_teaching", False), **metadata}
            # Management is a teaching-activity context, not a deduction rule.
            if context["allow_no_teaching"] and context["employment_type"] == "FULL_TIME":
                context["employment_type"] = "MANAGEMENT"
            contexts.append(context)
            if profile:
                normalized_profile = {**metadata, **profile}
                profiles.append({**normalized_profile, "version": policy["id"] if policy else "run-af-policy", "approved_by": profile.get("approved_by", profile.get("special_approval", af_confirmation.get("confirmed_by", ""))), "approved_at": profile.get("approved_at", af_confirmation.get("confirmed_at", policy.get("created_at", "") if policy else ""))})
        ratings = [{**p, "effective_from": rating["effective_from"], "effective_to": rating["effective_to"], "source": rating["source"], "source_version": rating.get("source_version", rating["id"])} for p in (rating or {}).get("ratings", []) if p["teacher"] in teachers]
        rates = [{**p, "grade": p.get("grade_scope", p.get("grade", "*")), "rate_per_lesson": p.get("rate_per_session", p.get("fixed_rate", p.get("base_rate"))), "effective_from": part_time["effective_from"], "effective_to": part_time["effective_to"], "source": part_time["source"], "version": part_time["id"], "approved_by": part_time.get("actor", ""), "approved_at": part_time.get("created_at", "")} for p in (part_time or {}).get("profiles", [])]
        # An explicit personal pricing policy outranks the shared
        # teacher×grade rate while preserving the same Core calculation path.
        for profile in (policy or {}).get("profiles", []):
            if profile.get("employment_type") == "PART_TIME" and (profile.get("fixed_rate") is not None or profile.get("base_rate") is not None or profile.get("override_rate") is not None):
                rates.append({**profile, "grade": profile.get("grade_scope", "*"), "rate_per_lesson": profile.get("fixed_rate", profile.get("base_rate")), "effective_from": policy["effective_from"], "effective_to": policy["effective_to"], "source": policy["source"], "version": policy["id"], "approved_by": profile.get("special_approval", ""), "approved_at": policy.get("created_at", "")})
        # A Run-level hand-entered per-lesson rate is an explicit input to the
        # same Core calculation. The arithmetic and course eligibility rules
        # remain unchanged; only the chosen rate source is different.
        for decision in (run.get("part_time_pay_decisions") or {}).values():
            if decision.get("method") != "MANUAL" or decision.get("manual_kind") != "UNIT_RATE" or decision.get("status") != "CONFIRMED":
                continue
            teacher = str(decision.get("teacher") or "")
            unit_price = decision.get("amount")
            if not teacher or unit_price is None:
                continue
            rates.append({
                "teacher": teacher, "teacher_id": decision.get("teacher_id", teacher),
                "grade": "*", "grade_scope": "*", "pricing_mode": "FIXED_GRADE_RATE",
                "fixed_rate": unit_price, "rate_per_lesson": unit_price,
                "effective_from": run["period"], "effective_to": run["period"],
                "source": decision.get("source", "本次 Run 手动兼职单价"),
                "version": decision.get("version", "RUN_PART_TIME_PAY_DECISION/v1"),
                "policy_type": "RUN_MANUAL_PART_TIME", "approved_by": decision.get("confirmed_by", ""),
                "approved_at": decision.get("confirmed_at", ""),
                "provenance": {"run_id": run["id"], "reason": decision.get("reason", "")},
            })
        if not rule_version:
            reason = "当前月份没有唯一绑定的核心规则版本，请到基础资料选择生效版本。"
            return {"period": run["period"], "rows": [{"teacher": t, "fields": {f: {"value": None, "state": "NEEDS_INPUT", "reason": reason, "evidence": []} for f in ("AA", "AC", "AD", "AE", "AF", "PART_TIME")}} for t in sorted(teachers)], "course_contributions": [], "rule_versions": {}}
        # Package-discovered historical ratings are persisted on the Run and
        # become the fallback layer for this calculation.  The submitted
        # payroll sheet remains an additional reference only; neither source
        # can silently replace an independent system-authority rating.
        references = dict(run.get("reference_ratings") or {})
        references.update({p.teacher: star_from_level(p.teacher_level) for p in payroll if star_from_level(p.teacher_level) is not None})
        result = calculate_payroll(period=run["period"], schedule=schedule, rules=CoreRules.from_dict(rule_version["rules"]), ratings=ratings, profiles=profiles, reference_ratings=references, teacher_contexts=contexts, part_time_rates=rates, effective_ac=effective_ac or {})
        raw = result.as_dict()
        def value(item: dict) -> dict:
            return {**item, "value": None if item["value"] is None else float(item["value"])}
        names = {"aa": "AA", "ac": "AC", "ad": "AD", "ae": "AE", "af": "AF", "part_time_fee": "PART_TIME"}
        part_time_decisions = run.get("part_time_pay_decisions") or {}
        rows = []
        for row in raw["rows"]:
            fields = {code: value(row[key]) for key, code in names.items()}
            decision = part_time_decisions.get(row["teacher"], {})
            if row.get("employment_type") == "PART_TIME":
                if decision.get("method") == "MANUAL" and decision.get("manual_kind") == "TOTAL" and decision.get("status") == "CONFIRMED":
                    fields["PART_TIME"] = {
                        "value": float(decision["amount"]), "state": "DETERMINED",
                        "reason": "兼职工资按本次确认的月工资总额录入。",
                        "evidence": [{"kind": "RUN_PART_TIME_MANUAL_TOTAL", "source": decision.get("source", ""), "source_result_id": decision.get("version", ""), "inputs": {"period": run["period"], "confirmed_by": decision.get("confirmed_by", ""), "reason": decision.get("reason", ""), "amount": str(decision.get("amount", ""))}}],
                    }
                elif decision.get("method") == "DEFERRED":
                    fields["PART_TIME"] = {
                        "value": None, "state": "DEFERRED",
                        "reason": "兼职工资待补充；本次保留空白，不按 0 计算。",
                        "evidence": [{"kind": "RUN_PART_TIME_DEFERRED", "source": decision.get("source", ""), "inputs": {"period": run["period"], "confirmed_by": decision.get("confirmed_by", ""), "reason": decision.get("reason", "")}}],
                    }
                elif decision.get("method") == "COMPANY_STANDARD" and decision.get("status") == "WAITING_FOR_AUTHORITY":
                    fields["PART_TIME"] = {
                        "value": None, "state": "NEEDS_INPUT",
                        "reason": "尚无适用本月和该教师的公司兼职标准；可手动填写或暂时留白。",
                        "evidence": [{"kind": "PART_TIME_AUTHORITY_MISSING", "source": decision.get("source", ""), "inputs": {"period": run["period"]}}],
                    }
            rows.append({"teacher": row["teacher"], "employment_type": row.get("employment_type", "FULL_TIME"), "fields": fields})
        return {"period": run["period"], "rows": rows, "course_contributions": [value(c) for c in raw["course_contributions"]], "formula_inputs": raw.get("formula_inputs", {}), "rule_versions": {"core": rule_version["id"], "rating": (rating or {}).get("id", ""), "policy": (policy or {}).get("id", ""), "part_time": (part_time or {}).get("id", "")}}

    def _configured_contribution(self, run: dict):
        from payroll_core.calculation import calculate_course
        from payroll_core.config.core_rules import CoreRules
        from payroll_core.reconcile.payroll_scope import class_value_contribution
        if run.get("calculation_engine") != "CONFIGURED_V1":
            return class_value_contribution
        version = self._calculation_version(run, "core")
        if not version:
            return lambda record: (None, "缺少绑定的核心规则版本。")
        rules = CoreRules.from_dict(version["rules"])
        def contribution(record):
            item = calculate_course(record, rules)
            if item.state == "NOT_APPLICABLE":
                return 0.0, item.reason
            if item.field != "ac" or item.value is None:
                return None, item.reason
            return float(item.value), item.reason
        return contribution

    @staticmethod
    def _core_checks(result: dict, payroll: list, mode: str) -> list:
        from payroll_core.reconcile.payroll_scope import FieldCheck
        targets = {row.teacher: row for row in payroll}
        names = {"AA": "one_to_one", "AC": "class_value", "AD": "teaching_hours", "AE": "rate", "AF": "af_policy", "PART_TIME": "part_time"}
        attributes = {"AE": "ae", "AF": "af"}
        checks = []
        for row in result["rows"]:
            target = targets.get(row["teacher"])
            for code, field in names.items():
                value = row["fields"].get(code)
                if value is None:
                    continue
                actual = getattr(target, attributes.get(code, field), None) if target else None
                expected = value["value"]
                if code == "PART_TIME" and value["state"] == "DEFERRED":
                    # The user explicitly chose to leave this monthly amount
                    # blank. Keep it visible in the final-field result, but
                    # do not reopen it as an unexplained issue on every pass.
                    status = "NOT_APPLICABLE"
                elif value["state"] == "NOT_APPLICABLE":
                    status = "NOT_APPLICABLE"
                elif target is not None and actual is not None and expected is not None and math.isclose(expected, actual, rel_tol=0, abs_tol=1e-6):
                    # A zero-difference comparison is conclusive even when
                    # the independent source is marked estimated (for
                    # example, a default AF policy).  Keep the source state
                    # in Core evidence, but do not turn an already matching
                    # value into a user action.
                    status = {"AE": "RATE_MATCH", "AF": "AF_POLICY_MATCH"}.get(code, "MATCH")
                elif value["state"] != "DETERMINED":
                    status = "NEEDS_MANUAL_REVIEW"
                elif mode == "GENERATE":
                    status = "DETERMINED"
                elif target is None:
                    status = "MISSING_TARGET"
                elif actual is None and code in {"AA", "AC", "AD"} and "管理岗位已明确允许无教学活动" in value.get("reason", ""):
                    status = "NOT_APPLICABLE"
                elif actual is None:
                    status = "MISSING_PAYROLL_VALUE"
                else:
                    status = {"AE": "RATE_MISMATCH", "AF": "AF_POLICY_MISMATCH"}.get(code, "UNEXPLAINED_DIFFERENCE")
                reason = str(value.get("reason", ""))
                checks.append(FieldCheck(row["teacher"], field, expected, actual, status, reason or f"{code} 来自同一条独立排课工资计算链。"))
        return checks

    @staticmethod
    def _core_field_status(result: dict, checks: list) -> list[dict]:
        names = {"AA": "one_to_one", "AC": "class_value", "AD": "teaching_hours", "AE": "rate", "AF": "af_policy", "PART_TIME": "part_time"}
        labels = {"AA": "AA 一对一折算小时", "AC": "AC 班课折算小时", "AD": "AD 授课小时合计", "AE": "AE 课时单价", "AF": "AF（总课时费）", "PART_TIME": "兼职按节课时费"}
        output = []
        for code, field in names.items():
            values = [row["fields"][code] for row in result["rows"] if code in row["fields"]]
            relevant = [v for v in values if v["state"] != "NOT_APPLICABLE"]
            audited = [v for v in checks if v.field == field and v.status != "NOT_APPLICABLE"]
            determined = sum(v["state"] == "DETERMINED" for v in relevant)
            matches = sum(v.status in {"MATCH", "RATE_MATCH", "AF_POLICY_MATCH", "EXPLAINED_DIFFERENCE"} for v in audited)
            state = "不适用" if values and not relevant else "已核对" if relevant and matches == len(relevant) else "已独立计算" if relevant and determined == len(relevant) else "待补资料 / 含估算"
            output.append({"field": field, "label": labels[code], "state": state, "note": f"独立确定 {determined}/{len(relevant)}；与目标一致 {matches}/{len(relevant)}。估算或缺资料不计为已核对。", "read": bool(values), "authority": bool(relevant) and determined == len(relevant), "computed": any(v["value"] is not None for v in values), "compared": bool(relevant) and matches == len(relevant)})
        return output

    def _calculation_context(self, run: dict) -> dict | None:
        if run.get("calculation_engine") != "CONFIGURED_V1":
            return None
        return {"engine": "CONFIGURED_V1", "rules": self._calculation_version(run, "core"), "part_time": self._calculation_version(run, "part_time"), "af_policy_confirmation": run.get("af_policy_confirmation")}

    def _build_part_time_pricing_snapshot(self, run: dict, schedule: list, calculation: dict) -> dict:
        """Freeze lesson-level pricing inputs after a Run has been calculated."""
        version = self._calculation_version(run, "part_time")
        contributions = {item.get("record_key"): item for item in calculation.get("course_contributions", []) if item.get("field") == "part_time_fee"}
        entries = []
        rules_version = self._calculation_version(run, "core")
        if not rules_version:
            return {"version": "RUN_PART_TIME_PRICING_SNAPSHOT/v1", "run_id": run["id"], "period": run["period"], "entries": []}
        from payroll_core.calculation import course_record_key
        def number(value):
            return None if value in (None, "", "None") else float(value)
        for record in schedule:
            contribution = contributions.get(course_record_key(record))
            if contribution is None:
                continue
            evidence = (contribution.get("evidence") or [{}])[0]
            inputs = evidence.get("inputs") or {}
            entries.append({
                "record_key": course_record_key(record), "teacher": record.teacher,
                "grade": record.grade, "student_id": getattr(record, "student_id", ""), "class_id": getattr(record, "class_id", ""),
                "pricing_mode": inputs.get("pricing_mode", "FIXED_GRADE_RATE"),
                "base_rate": number(inputs.get("base_rate")),
                "fixed_rate": number(inputs.get("fixed_rate")),
                "coefficient": float(inputs.get("coefficient", "1")),
                "target_override": number(inputs.get("override_rate")),
                "final_rate": contribution.get("value"), "lesson_count": 1, "amount": contribution.get("value"),
                "source": evidence.get("source", ""),
            })
        return {"version": "RUN_PART_TIME_PRICING_SNAPSHOT/v1", "run_id": run["id"], "period": run["period"], "pricing_version_id": version.get("id") if version else None, "entries": entries, "created_at": datetime.now(timezone.utc).isoformat()}

    def core_rule_catalog(self) -> dict:
        from payroll_core.config.core_rules import load_core_rules
        seed = load_core_rules().to_dict()
        versions = self.store.calculation_versions("core")
        if not versions:
            self._append_core_rules(seed, seed["source"], "已确认规则基线")
            versions = self.store.calculation_versions("core")
        return {"versions": versions, "seed": seed}

    def _append_core_rules(self, rules: dict, source: str, actor: str) -> dict:
        from payroll_core.config.core_rules import CoreRules
        if not source.strip() or not actor.strip():
            raise ValueError("请填写规则来源与确认人。")
        snapshot = copy.deepcopy(rules)
        requested_id = str(snapshot.get("rule_version_id", "")).strip()
        existing_ids = {item.get("id") for item in self.store.calculation_versions("core")}
        # A new evidence-backed month may carry a stable semantic identifier;
        # legacy edits that reuse an existing seed id still receive a fresh
        # immutable storage id and can never overwrite that snapshot.
        snapshot["rule_version_id"] = requested_id if requested_id and requested_id not in existing_ids else uuid.uuid4().hex[:16]
        snapshot["source"] = source.strip()
        validated = CoreRules.from_dict(snapshot).to_dict()
        item = {"id": validated["rule_version_id"], "rules": validated, "effective_from": validated["effective_from"], "effective_to": validated["effective_to"], "source": source.strip(), "actor": actor.strip(), "created_at": datetime.now(timezone.utc).isoformat()}
        item["sha256"] = hashlib.sha256(json.dumps(validated, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.store.append_calculation_version("core", item)
        return item

    def save_core_rule_version(self, rules: dict, source: str, actor: str) -> dict:
        self._append_core_rules(rules, source, actor)
        return self.core_rule_catalog()

    def part_time_rate_versions(self) -> list[dict]:
        return self.store.calculation_versions("part_time")

    def save_part_time_rate_version(self, profiles: list[dict], source: str, effective_from: str, effective_to: str, actor: str) -> list[dict]:
        if not valid_period(effective_from) or not valid_period(effective_to) or effective_to < effective_from or not source.strip() or not actor.strip() or not profiles:
            raise ValueError("请填写兼职单价、生效月份、来源与确认人。")
        cleaned, seen = [], set()
        for profile in profiles:
            teacher = str(profile.get("teacher", "")).strip()
            grade = str(profile.get("grade_scope", "*")).strip()
            mode = str(profile.get("pricing_mode", "FIXED_GRADE_RATE")).strip() or "FIXED_GRADE_RATE"
            if mode not in {"COEFFICIENT_BASED", "FIXED_GRADE_RATE"}:
                raise ValueError("兼职定价方式只能是 COEFFICIENT_BASED 或 FIXED_GRADE_RATE。")
            raw_rate = profile.get("base_rate") if mode == "COEFFICIENT_BASED" else (profile.get("fixed_rate") if profile.get("fixed_rate") is not None else profile.get("rate_per_session"))
            try:
                rate = float(raw_rate)
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError("请填写有效的每节单价。") from exc
            teacher_id = str(profile.get("teacher_id", "")).strip()
            target_id = str(profile.get("student_id", "")).strip() or str(profile.get("class_id", "")).strip()
            if not teacher or not grade or not math.isfinite(rate) or rate < 0 or (teacher_id, teacher, grade, target_id) in seen:
                raise ValueError("教师、身份、年级范围或单价无效，不能重复配置同一范围。")
            seen.add((teacher_id, teacher, grade, target_id))
            cleaned.append({"teacher": teacher, "teacher_id": teacher_id, "grade_scope": grade, "pricing_mode": mode, "base_rate": rate if mode == "COEFFICIENT_BASED" else None, "fixed_rate": rate if mode == "FIXED_GRADE_RATE" else None, "rate_per_session": rate, "student_id": str(profile.get("student_id", "")).strip(), "class_id": str(profile.get("class_id", "")).strip(), "override_rate": profile.get("override_rate"), "unit": "CNY_PER_LESSON", "policy_type": "PART_TIME_RATE", "provenance": profile.get("provenance") or {}, "notes": str(profile.get("notes", ""))})
        item = {"id": uuid.uuid4().hex[:16], "profiles": cleaned, "source": source.strip(), "source_hash": hashlib.sha256(json.dumps(cleaned, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest(), "effective_from": effective_from, "effective_to": effective_to, "actor": actor.strip(), "created_at": datetime.now(timezone.utc).isoformat(), "status": "ACTIVE"}
        self.store.append_calculation_version("part_time", item)
        return self.part_time_rate_versions()

    def _calculation_version(self, run: dict, kind: str) -> dict | None:
        snapshot = run.get("run_policy_snapshot")
        if snapshot and snapshot.get("sha256") == self._policy_snapshot_hash(snapshot):
            if kind == "part_time":
                if not snapshot.get("part_time_rate_version_id"):
                    return None
                return {
                    "id": snapshot["part_time_rate_version_id"],
                    "profiles": copy.deepcopy(snapshot.get("part_time_rates") or []),
                    "effective_from": run["period"], "effective_to": run["period"],
                    "source": "RUN_POLICY_SNAPSHOT",
                    "actor": "RUN_POLICY_SNAPSHOT",
                    "created_at": snapshot.get("created_at", ""),
                }
            if kind == "core" and snapshot.get("core_rule_version_id"):
                # Core rules remain resolved from the immutable calculation
                # version table; the snapshot only binds its identity.
                pass
        key = {"core": "core_rule_version_id", "part_time": "part_time_rate_version_id"}[kind]
        bound = run.get(key)
        if not bound:
            return None
        version = next((item for item in self.store.calculation_versions(kind) if item["id"] == bound), None)
        if version is None:
            raise ValueError("绑定的工资计算规则版本不存在，不得自动替换。")
        return version

    def _bind_new_calculation(self, run: dict) -> None:
        versions = self.core_rule_catalog()["versions"]
        for kind, key, candidates in (("core", "core_rule_version_id", versions), ("part_time", "part_time_rate_version_id", self.part_time_rate_versions())):
            matched = [item for item in candidates if item["effective_from"] <= run["period"] <= item["effective_to"]]
            # Two possible revisions require explicit selection, not latest wins.
            run[key] = matched[0]["id"] if len(matched) == 1 else None
        run["calculation_engine"] = "CONFIGURED_V1"

    def rebind_calculation(self, run_id: str, kind: str, version_id: str) -> dict:
        if kind not in {"core", "part_time"}:
            raise ValueError("未知规则类别。")
        run = self._load(run_id)
        self._require_fresh(run)
        item = next((v for v in self.store.calculation_versions(kind) if v["id"] == version_id), None)
        if not item or not item["effective_from"] <= run["period"] <= item["effective_to"]:
            raise ValueError("所选版本不适用于当前月份。")
        key = {"core": "core_rule_version_id", "part_time": "part_time_rate_version_id"}[kind]
        if run.get(key) == version_id:
            return self.render(run)
        when = datetime.now(timezone.utc).isoformat()
        run.setdefault("authority_rebind_history", []).append({"kind": kind, "from_version_id": run.get(key), "to_version_id": version_id, "changed_at": when})
        run[key] = version_id
        run["calculation_engine"] = "CONFIGURED_V1"
        # The immutable Run policy snapshot is also a calculation input. Keep
        # it synchronized with the explicit binding so a newly selected
        # part-time authority cannot be hidden behind a still-valid stale
        # snapshot hash.
        run["run_policy_snapshot"] = self._build_run_policy_snapshot(run)
        invalidate(run.setdefault("business_decisions", []))
        if kind == "core":
            for resolution in run.get("resolutions", []):
                if resolution.get("status") == "ACTIVE":
                    run.setdefault("resolution_history", []).append({**resolution, "history_event": "RULE_CHANGED"})
                    resolution.update(status="NEEDS_RECONFIRMATION", invalidated_at=when)
        run["business_context_stale"] = True
        if run.get("generated_payroll"):
            run["generated_payroll"]["status"] = "NEEDS_RECONFIRMATION"
        run["status"] = "FILES_READY" if self._materials_ready(run) else "DRAFT"
        self.store.save(run)
        return self.check(run_id) if self._materials_ready(run) else self.render(run)
