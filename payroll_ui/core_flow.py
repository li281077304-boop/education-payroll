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
        profiles, contexts = [], []
        for teacher in sorted(teachers):
            matching = [p for p in (policy or {}).get("profiles", []) if p["teacher"] == teacher]
            if len(matching) > 1:
                raise ValueError("个人工资政策同一教师存在重复记录，请先确认权威版本。")
            profile = matching[0] if matching else {}
            metadata = {k: policy[k] for k in ("effective_from", "effective_to", "source")} if policy else {}
            context = {"teacher": teacher, "employment_type": profile.get("employment_type", "FULL_TIME"), "allow_no_teaching": profile.get("allow_no_teaching", False), **metadata}
            # Management is a teaching-activity context, not a deduction rule.
            if context["allow_no_teaching"] and context["employment_type"] == "FULL_TIME":
                context["employment_type"] = "MANAGEMENT"
            contexts.append(context)
            if profile:
                profiles.append({**profile, **metadata, "version": policy["id"], "approved_by": profile.get("approved_by", profile.get("special_approval", "")), "approved_at": profile.get("approved_at", policy.get("created_at", ""))})
        ratings = [{**p, "effective_from": rating["effective_from"], "effective_to": rating["effective_to"], "source": rating["source"], "source_version": rating.get("source_version", rating["id"])} for p in (rating or {}).get("ratings", []) if p["teacher"] in teachers]
        rates = [{**p, "grade": p["grade_scope"], "rate_per_lesson": p["rate_per_session"], "effective_from": part_time["effective_from"], "effective_to": part_time["effective_to"], "source": part_time["source"], "version": part_time["id"], "approved_by": part_time["actor"], "approved_at": part_time["created_at"]} for p in (part_time or {}).get("profiles", [])]
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
        rows = [{"teacher": row["teacher"], "fields": {code: value(row[key]) for key, code in names.items()}} for row in raw["rows"]]
        return {"period": run["period"], "rows": rows, "course_contributions": [value(c) for c in raw["course_contributions"]], "rule_versions": {"core": rule_version["id"], "rating": (rating or {}).get("id", ""), "policy": (policy or {}).get("id", ""), "part_time": (part_time or {}).get("id", "")}}

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
                if value["state"] == "NOT_APPLICABLE":
                    status = "NOT_APPLICABLE"
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
                elif expected is not None and math.isclose(expected, actual, rel_tol=0, abs_tol=1e-6):
                    status = {"AE": "RATE_MATCH", "AF": "AF_POLICY_MATCH"}.get(code, "MATCH")
                else:
                    status = {"AE": "RATE_MISMATCH", "AF": "AF_POLICY_MISMATCH"}.get(code, "UNEXPLAINED_DIFFERENCE")
                reason = str(value.get("reason", ""))
                checks.append(FieldCheck(row["teacher"], field, expected, actual, status, reason or f"{code} 来自同一条独立排课工资计算链。"))
        return checks

    @staticmethod
    def _core_field_status(result: dict, checks: list) -> list[dict]:
        names = {"AA": "one_to_one", "AC": "class_value", "AD": "teaching_hours", "AE": "rate", "AF": "af_policy", "PART_TIME": "part_time"}
        labels = {"AA": "AA 一对一折算小时", "AC": "AC 班课折算小时", "AD": "AD 授课小时合计", "AE": "AE 课时单价", "AF": "AF 总课时费", "PART_TIME": "兼职按节课时费"}
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
        return {"engine": "CONFIGURED_V1", "rules": self._calculation_version(run, "core"), "part_time": self._calculation_version(run, "part_time")}

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
        snapshot["rule_version_id"] = uuid.uuid4().hex[:16]
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
            try:
                rate = float(profile["rate_per_session"])
            except (KeyError, ValueError, TypeError) as exc:
                raise ValueError("请填写有效的每节单价。") from exc
            if not teacher or not grade or not math.isfinite(rate) or rate < 0 or (teacher, grade) in seen:
                raise ValueError("教师、年级范围或单价无效，不能重复配置同一范围。")
            seen.add((teacher, grade))
            cleaned.append({"teacher": teacher, "grade_scope": grade, "rate_per_session": rate, "notes": str(profile.get("notes", ""))})
        item = {"id": uuid.uuid4().hex[:16], "profiles": cleaned, "source": source.strip(), "effective_from": effective_from, "effective_to": effective_to, "actor": actor.strip(), "created_at": datetime.now(timezone.utc).isoformat()}
        self.store.append_calculation_version("part_time", item)
        return self.part_time_rate_versions()

    def _calculation_version(self, run: dict, kind: str) -> dict | None:
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
