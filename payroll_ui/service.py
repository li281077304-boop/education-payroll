from __future__ import annotations

import csv
import hashlib
import io
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from payroll_core.excel.check_workbook import read_check_workbook_schedule
from payroll_core.excel.inspect import inspect_workbook
from payroll_core.excel.payroll import read_payroll_excel
from payroll_core.excel.schedule import read_schedule_excel
from payroll_core.formula_audit import audit_payroll_formulas
from payroll_core.rules.authority import TeacherRating, default_compensation_bands, rating_and_rate_checks
from payroll_core.reconcile.payroll_scope import FieldCheck, rate_and_fee_checks, schedule_field_checks, total_salary_read_checks

from .storage import RunStore

REQUIRED = ("schedule", "math", "science")
LABELS = {"schedule": "原始排课数据", "math": "数学组工资表", "science": "理化组工资表", "check": "最终工资核对表"}
LAYOUTS = {"schedule": "SCHEDULE_EXPORT_V1", "math": "PAYROLL_SHEET_V1", "science": "PAYROLL_SHEET_V1", "check": "PAYROLL_CHECK_V1"}
STATUS = {"DRAFT": "待导入", "FILES_READY": "材料已准备", "CHECKING": "正在核对", "REVIEW_REQUIRED": "需要复核", "STALE": "文件已变化", "PASS": "字段核对完成"}
ISSUE_LABELS = {
    "MATCH": "一致",
    "EXPLAINED_DIFFERENCE": "已确认",
    "UNEXPLAINED_DIFFERENCE": "差异待处理",
    "MISSING_SOURCE": "缺少原始依据",
    "MISSING_TARGET": "工资表缺少人员",
    "NEEDS_MANUAL_REVIEW": "需要人工确认",
    "FORMULA_DIFFERENCE": "公式复算不一致",
    "RATING_MISMATCH": "星级不一致",
    "RATE_MATCH": "档位金额一致",
    "RATE_MISMATCH": "档位金额不一致",
    "MISSING_AUTHORITY": "缺少权威资料",
    "MISSING_PAYROLL_VALUE": "工资表缺少值",
    "RULE_NOT_FOUND": "未找到适用规则",
    "MULTIPLE_RULES_MATCHED": "规则冲突",
    "FORMULA_REPLACED_BY_VALUE": "公式被固定值替代",
    "FORMULA_MISSING": "公式缺失",
    "FORMULA_PATTERN_MISMATCH": "公式结构不同",
    "ROW_REFERENCE_SHIFT": "公式引用错行",
    "COLUMN_REFERENCE_SHIFT": "公式引用错列",
    "FORMULA_REGION_BREAK": "公式区域异常",
}
ACTION_LABELS = {"special": "已确认特殊情况", "payroll_error": "工资表待修改", "defer": "暂时保留", "confirm_source": "来源待核实"}


def version(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    stat = path.stat()
    return {"sha256": digest.hexdigest(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def safe_csv(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return "'" + value if value.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")) else value


class PayrollService:
    def __init__(self, root: Path):
        self.store = RunStore(root)

    def create(self, period: str) -> dict:
        if len(period) != 7 or period[4] != "-" or not period.replace("-", "").isdigit() or not 1 <= int(period[5:]) <= 12:
            raise ValueError("请选择有效月份。")
        versions = [item for item in self.store.list_rating_versions() if item["effective_from"] <= period <= item["effective_to"]]
        run = {"id": uuid.uuid4().hex[:12], "period": period, "created_at": datetime.now(timezone.utc).isoformat(), "status": "DRAFT", "files": {}, "issues": [], "decisions": [], "management": [], "rating_version_id": versions[0]["id"] if len(versions) == 1 else None, "field_status": self._field_status([]), "summary": self._summary([])}
        self.store.save(run)
        return self.render(run)

    def list(self) -> list[dict]:
        return [self.render(self._load(item["id"])) for item in self.store.list()]

    def get(self, run_id: str) -> dict:
        return self.render(self._load(run_id))

    def rating_versions(self) -> list[dict]:
        return self.store.list_rating_versions()

    def save_rating_version(self, effective_from: str, effective_to: str, source: str, source_version: str, ratings: list[dict]) -> list[dict]:
        if len(effective_from) != 7 or len(effective_to) != 7 or effective_from > effective_to or not source.strip() or not ratings:
            raise ValueError("请填写生效期、来源和至少一位教师的星级。")
        cleaned = []
        for item in ratings:
            name, rating = str(item.get("teacher", "")).strip(), item.get("rating")
            if not name or not isinstance(rating, int) or rating not in range(1, 7):
                raise ValueError("星级资料必须包含教师姓名和一至六星。")
            cleaned.append({"teacher": name, "rating": rating, "role": str(item.get("role", "教师")).strip() or "教师"})
        version = {"id": uuid.uuid4().hex[:12], "effective_from": effective_from, "effective_to": effective_to, "source": source.strip(), "source_version": source_version.strip() or effective_from, "ratings": cleaned, "created_at": datetime.now(timezone.utc).isoformat()}
        self.store.save_rating_version(version)
        return self.rating_versions()

    def import_file(self, run_id: str, role: str, path: str, expected_hash: str | None = None) -> dict:
        if role not in LABELS:
            raise ValueError("未知材料类别。")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("找不到原始文件。请关闭 Excel/WPS 后重新选择。")
        try:
            before = version(source)
        except OSError as exc:
            raise ValueError(self._file_error(exc)) from exc
        if expected_hash and expected_hash != before["sha256"]:
            raise ValueError("所选原文件与刚才拖放识别的文件不一致。")
        run = self._load(run_id)
        if any(key != role and item["sha256"] == before["sha256"] for key, item in run["files"].items()):
            raise ValueError("同一份文件不能同时充当两个材料类别。")
        inspection = inspect_workbook(source)
        if inspection.errors or not inspection.records:
            raise ValueError(self._inspection_error(inspection.errors))
        workbook = inspection.records[0]
        if workbook.fingerprint.layout != LAYOUTS[role]:
            raise ValueError(f"文件不属于“{LABELS[role]}”，请检查后重新选择。")
        try:
            result = self._read(role, source, run["period"])
        except OSError as exc:
            raise ValueError(self._file_error(exc)) from exc
        if result.errors:
            raise ValueError("文件缺少当前核对所需字段：" + "；".join(issue.message for issue in result.errors))
        try:
            unchanged = version(source) == before
        except OSError as exc:
            raise ValueError(self._file_error(exc)) from exc
        if not unchanged:
            raise ValueError("文件在读取期间发生变化，请关闭 Excel/WPS 后重试。")
        run["files"][role] = {"name": source.name, "path": str(source), **before, "label": LABELS[role], "records": len(result.records), "teachers": len({record.teacher for record in result.records if hasattr(record, "teacher")}), "warnings": [issue.code for issue in result.warnings], "warning_messages": [self._warning_message(issue.code) for issue in result.warnings], "sheets": [sheet.name for sheet in workbook.sheets], "formula_count": sum(sheet.formula_count for sheet in workbook.sheets), "missing_cache": sum(sheet.formula_cache_missing for sheet in workbook.sheets), "external_references": workbook.external_link_count + sum(sheet.external_formula_count for sheet in workbook.sheets)}
        run["issues"], run["decisions"] = [], []
        run.pop("last_error", None)
        run.pop("stale_files", None)
        run["status"] = "FILES_READY" if all(key in run["files"] for key in REQUIRED) else "DRAFT"
        # Replacing one changed file must not silently clear changes in another.
        self._fresh(run)
        self.store.save(run)
        return self.render(run)

    def check(self, run_id: str) -> dict:
        run = self._load(run_id)
        missing = [LABELS[key] for key in REQUIRED if key not in run["files"]]
        if missing:
            raise ValueError("请先导入：" + "、".join(missing))
        self._require_fresh(run)
        run["status"] = "CHECKING"
        run.pop("last_error", None)
        self.store.save(run)
        try:
            return self._perform_check(run)
        except OSError as exc:
            message = self._file_error(exc)
            self._finish_failed_check(run, message)
            raise ValueError(message) from exc
        except ValueError as exc:
            self._finish_failed_check(run, str(exc))
            raise

    def _perform_check(self, run: dict) -> dict:
        reads = {key: self._read(key, Path(item["path"]), run["period"]) for key, item in run["files"].items()}
        if not self._fresh(run):
            raise ValueError("原文件在核对时发生变化，请重新导入。")
        if any(result.errors for result in reads.values()):
            raise ValueError("材料重新读取失败，请返回材料页重新选择。")
        payroll = [*reads["math"].records, *reads["science"].records]
        if {row.teacher for row in reads["math"].records} & {row.teacher for row in reads["science"].records}:
            raise ValueError("两张工资表含有重复教师，请确认分组后再核对。")
        checks = schedule_field_checks(reads["schedule"].records, payroll)
        checks += rate_and_fee_checks(payroll) + total_salary_read_checks(payroll)
        rating_version = self._rating_version_for_run(run)
        ratings = [TeacherRating(item["teacher"], item["rating"], item.get("role", "教师"), rating_version["effective_from"], rating_version["effective_to"], rating_version["source"], rating_version["source_version"]) for item in rating_version.get("ratings", [])] if rating_version else []
        checks += rating_and_rate_checks(payroll, ratings, default_compensation_bands(), run["period"])
        for role in ("math", "science"):
            for item in audit_payroll_formulas(run["files"][role]["path"]):
                checks.append(FieldCheck("工作簿", "formula", None, None, item.status, f"{Path(item.workbook).name} / {item.sheet} / {item.cell}：{item.evidence} 正常模式：{item.expected_pattern or '待确认'}；当前公式：{item.formula or '空白/固定值'}。"))
        checks = self._apply_decisions(checks, run["decisions"])
        visible_checks = [check for check in checks if check.status not in {"MATCH", "FORMULA_MATCH", "READ_ONLY"}]
        run["issues"] = self._annotate_decisions([self._issue(check) for check in visible_checks], run["decisions"])
        run["issues"].sort(key=lambda item: (item["severity_rank"], item["title"], item["teacher"]))
        run["field_status"] = self._field_status(checks)
        run["summary"] = self._summary(checks)
        run["status"] = "PASS" if run["summary"]["full_scope_complete"] else "REVIEW_REQUIRED"
        run.pop("last_error", None)
        self.store.save(run)
        return self.render(run)

    def _rating_version_for_run(self, run: dict) -> dict | None:
        version_id = run.get("rating_version_id")
        if version_id:
            return self.store.get_rating_version(version_id)
        matches = [item for item in self.store.list_rating_versions() if item["effective_from"] <= run["period"] <= item["effective_to"]]
        if len(matches) == 1:
            run["rating_version_id"] = matches[0]["id"]
            return matches[0]
        return None

    def _finish_failed_check(self, run: dict, message: str) -> None:
        if self._fresh(run):
            run["status"] = "FILES_READY"
            run["last_error"] = message
            self.store.save(run)

    def decide(self, run_id: str, issue_id: str, action: str, person: str, reason: str) -> dict:
        if action not in {"special", "payroll_error", "defer", "confirm_source"} or not person.strip() or not reason.strip():
            raise ValueError("请选择处理方式，并填写确认人和理由。")
        run = self._load(run_id)
        self._require_fresh(run)
        issue = next((item for item in run["issues"] if item["id"] == issue_id), None)
        if issue is None:
            raise ValueError("该问题已不存在，请重新核对。")
        if action == "special" and issue["status"] != "UNEXPLAINED_DIFFERENCE":
            raise ValueError("只有已有明确系统值与工资表值的差异，才能记录为特殊情况。")
        run["decisions"] = [item for item in run["decisions"] if item["issue_id"] != issue_id] + [{"issue_id": issue_id, "action": action, "person": person.strip(), "reason": reason.strip(), "teacher": issue["teacher"], "field": issue["field"], "expected": issue["expected"], "actual": issue["actual"], "versions": {key: value["sha256"] for key, value in run["files"].items()}}]
        run["issues"] = self._annotate_decisions(run["issues"], run["decisions"])
        run["status"] = "REVIEW_REQUIRED"
        self.store.save(run)
        return self.render(run)

    def evidence(self, run_id: str, issue_id: str) -> dict:
        run = self._load(run_id); self._require_fresh(run)
        issue = next((item for item in run["issues"] if item["id"] == issue_id), None)
        if issue is None:
            raise ValueError("未找到问题。")
        if issue["field"] not in {"one_to_one", "class_value"}:
            return {"issue": issue, "evidence": [], "note": "该项当前没有独立课程级来源。"}
        schedule = self._read("schedule", Path(run["files"]["schedule"]["path"]), run["period"]).records
        payroll = [*self._read("math", Path(run["files"]["math"]["path"]), run["period"]).records, *self._read("science", Path(run["files"]["science"]["path"]), run["period"]).records]
        lines = [{"来源": "原始排课", "来源文件": Path(next(iter(item.provenance.values())).source_file).name, "来源工作表": next(iter(item.provenance.values())).sheet, "课程时间": item.lesson_time, "班级": item.class_name, "班型": item.class_type, "年级": item.grade or "待确认", "实到": item.attended, "来源位置": ", ".join(value.coordinate for name, value in item.provenance.items() if name != "student")} for item in schedule if item.teacher == issue["teacher"]]
        target = next((item for item in payroll if item.teacher == issue["teacher"]), None)
        if target:
            value = target.provenance[issue["field"]]
            lines.append({"来源": "工资表", "来源文件": Path(value.source_file).name, "来源工作表": value.sheet, "字段": value.source_field, "工资表值": value.normalized_value, "来源位置": value.coordinate, "读取情况": self._cell_state(value.state.value)})
        if not self._fresh(run):
            raise ValueError("文件在查看证据时发生变化，请重新导入。")
        return {"issue": issue, "evidence": lines}

    def export_csv(self, run_id: str) -> str:
        run = self._load(run_id); self._require_fresh(run)
        out = io.StringIO(); writer = csv.writer(out)
        writer.writerow(["核算月份", "项目", "核对状态", "教师", "排课计算值", "工资表值", "差异", "处理情况", "说明"])
        for field in run["field_status"]:
            writer.writerow([run["period"], field["label"], field["state"], "", "", "", "", "", field["note"]])
        for issue in run["issues"]:
            writer.writerow([run["period"], issue["title"], issue["status_label"], safe_csv(issue["teacher"]), issue["expected"], issue["actual"], issue["difference"], issue["decision_label"], safe_csv(issue["reason"])])
        return out.getvalue()

    def save_management(self, run_id: str, values: dict[str, str], person: str) -> dict:
        """Store human confirmations; the UI never generates a suggested value."""
        if not person.strip():
            raise ValueError("请填写确认人。")
        run = self._load(run_id); self._require_fresh(run)
        allowed = {"平均课时", "续推人次", "退费人次", "管理考核说明"}
        run["management"] = [
            {"field": key, "value": str(value).strip(), "confirmed_by": person.strip()}
            for key, value in values.items() if key in allowed and str(value).strip()
        ]
        self.store.save(run)
        return self.render(run)

    def _load(self, run_id: str) -> dict:
        run = self.store.get(run_id)
        self._fresh(run)
        return run

    def _fresh(self, run: dict) -> bool:
        stale_roles: list[str] = []
        for role, item in run.get("files", {}).items():
            path = Path(item["path"])
            try:
                current = version(path) if path.is_file() else None
            except OSError:
                current = None
            if current != {key: item[key] for key in ("sha256", "size", "mtime_ns")}:
                stale_roles.append(role)
        if stale_roles:
            run["status"] = "STALE"
            run["stale_files"] = stale_roles
            run["decisions"] = []
            self.store.save(run)
        else:
            run.pop("stale_files", None)
        return not stale_roles

    def _require_fresh(self, run: dict) -> None:
        if run["status"] == "STALE":
            raise ValueError("原始文件已变化，请重新导入并重新核对。")

    @staticmethod
    def _read(role: str, path: Path, period: str):
        return {"schedule": read_schedule_excel, "math": read_payroll_excel, "science": read_payroll_excel, "check": read_check_workbook_schedule}[role](path, period)

    @staticmethod
    def _issue(item: FieldCheck) -> dict:
        difference = round(item.actual - item.expected, 6) if item.actual is not None and item.expected is not None else None
        severity = {
            "MISSING_SOURCE": (0, "严重"),
            "MISSING_TARGET": (0, "严重"),
            "UNEXPLAINED_DIFFERENCE": (1, "重要"),
            "FORMULA_DIFFERENCE": (1, "重要"),
            "RATING_MISMATCH": (1, "重要"),
            "RATE_MISMATCH": (1, "重要"),
            "FORMULA_REPLACED_BY_VALUE": (0, "严重"),
            "FORMULA_MISSING": (0, "严重"),
            "FORMULA_REGION_BREAK": (0, "严重"),
            "ROW_REFERENCE_SHIFT": (0, "严重"),
            "COLUMN_REFERENCE_SHIFT": (0, "严重"),
            "FORMULA_PATTERN_MISMATCH": (1, "重要"),
            "MISSING_AUTHORITY": (1, "重要"),
            "MISSING_PAYROLL_VALUE": (1, "重要"),
            "RULE_NOT_FOUND": (1, "重要"),
            "MULTIPLE_RULES_MATCHED": (0, "严重"),
            "NEEDS_MANUAL_REVIEW": (2, "需确认"),
            "EXPLAINED_DIFFERENCE": (3, "已确认"),
        }.get(item.status, (2, "需确认"))
        return {
            "id": hashlib.sha256(f"{item.teacher}|{item.field}|{item.reason}".encode()).hexdigest()[:16],
            "teacher": item.teacher,
            "field": item.field,
            "field_label": {"one_to_one": "AA 一对一", "class_value": "AC 班课", "ae": "AE 课时单价", "af": "AF 总课时费", "rating": "教师星级", "rate": "档位金额", "formula": "公式完整性"}.get(item.field, "其他项目"),
            "title": {"one_to_one": "一对一折算小时需要处理", "class_value": "班课折算小时需要处理", "ae": "课时单价需要确认", "af": "总课时费需要确认", "rating": "教师星级不一致", "rate": "档位金额需要处理", "formula": "工资表公式异常"}.get(item.field, "需要人工处理"),
            "difference": difference,
            "status_label": ISSUE_LABELS.get(item.status, "需要处理"),
            "severity_rank": severity[0],
            "severity_label": severity[1],
            **asdict(item),
        }

    @staticmethod
    def _annotate_decisions(issues: list[dict], decisions: list[dict]) -> list[dict]:
        by_values = {
            (item.get("teacher"), item.get("field"), item.get("expected"), item.get("actual")): item
            for item in decisions
        }
        for issue in issues:
            decision = by_values.get((issue["teacher"], issue["field"], issue["expected"], issue["actual"]))
            issue["decision"] = decision
            issue["decision_label"] = ACTION_LABELS.get(decision.get("action"), "已记录意见") if decision else "待处理"
        return issues

    @staticmethod
    def _apply_decisions(checks: list[FieldCheck], decisions: list[dict]) -> list[FieldCheck]:
        special = {
            (item.get("teacher"), item.get("field"), item.get("expected"), item.get("actual")): item
            for item in decisions if item.get("action") == "special"
        }
        output: list[FieldCheck] = []
        for check in checks:
            decision = special.get((check.teacher, check.field, check.expected, check.actual))
            if check.status == "UNEXPLAINED_DIFFERENCE" and decision:
                output.append(FieldCheck(check.teacher, check.field, check.expected, check.actual, "EXPLAINED_DIFFERENCE", f"人工确认的特殊情况：{decision['reason']}（{decision['person']}）"))
            else:
                output.append(check)
        return output

    @staticmethod
    def _summary(checks: list[FieldCheck]) -> dict:
        automatic = [row for row in checks if row.field in {"one_to_one", "class_value"}]
        completed = [row for row in automatic if row.status in {"MATCH", "EXPLAINED_DIFFERENCE"}]
        field_states = PayrollService._field_status(checks)
        return {
            "automatic_required": len(automatic),
            "automatic_completed": len(completed),
            "automatic_coverage": round(100 * len(completed) / len(automatic)) if automatic else 0,
            "automatic_pass": bool(automatic) and len(completed) == len(automatic),
            "unexplained": sum(row.status == "UNEXPLAINED_DIFFERENCE" for row in checks),
            "manual_review": sum(row.status not in {"MATCH", "FORMULA_MATCH", "RATE_MATCH", "READ_ONLY", "EXPLAINED_DIFFERENCE"} for row in checks),
            "full_scope_complete": bool(field_states) and all(row["state"].startswith("已核对") for row in field_states),
            "scope_note": "AA、AC 已接入独立排课源；AE、AF、AV 尚无完整独立权威源，不能判定整份工资核对通过。",
        }

    @staticmethod
    def _field_status(checks: list[FieldCheck]) -> list[dict]:
        labels = {"one_to_one": "AA 一对一折算小时", "class_value": "AC 班课折算小时", "ae": "AE 该档每小时金额", "af": "AF 总课时费", "av": "AV 总工资", "rating": "教师星级", "rate": "档位金额", "formula": "公式完整性"}
        output = []
        for field in ("one_to_one", "class_value", "rating", "rate", "formula", "ae", "af", "av"):
            rows = [row for row in checks if row.field == field]
            if field in {"one_to_one", "class_value"}:
                state = "已核对" if rows and all(row.status in {"MATCH", "EXPLAINED_DIFFERENCE"} for row in rows) else "待处理"
                note = "原始排课已独立计算并与工资表比较。" if state == "已核对" else "存在差异、缺失或无法确定的排课规则。"
            elif field in {"ae", "af"}:
                state, note = "公式复算 / 待权威确认", "已按现有公式复算；星级或输入仍来自工资表，尚非独立权威源。"
            elif field == "rating":
                state = "已核对" if rows and all(row.status == "MATCH" for row in rows) else "待处理"
                note = "使用按生效期保存的教师星级权威资料比较工资表。" if state == "已核对" else "缺少、过期或不一致的星级权威资料会阻止通过。"
            elif field == "rate":
                state = "已核对" if rows and all(row.status == "RATE_MATCH" for row in rows) else "待处理"
                note = "使用独立星级与生效期档位金额规则计算 AE。" if state == "已核对" else "缺少规则、规则冲突或金额不一致会阻止通过。"
            elif field == "formula":
                state = "已核对" if rows and all(row.status == "MATCH" for row in rows) else "待处理"
                note = "关键公式区域按同列结构模式扫描。" if state == "已核对" else "尚无足够公式样本，或已发现公式结构异常。"
            else:
                state, note = "仅读取 / 待人工确认", "总工资包含续费、退费、激励、管理奖等未接入来源。"
            # An empty check cannot be advertised as independently verified.
            automatic_available = field in {"one_to_one", "class_value", "rating", "rate", "formula"} and bool(rows)
            formula_recomputed = field in {"ae", "af"} and any(row.expected is not None for row in rows)
            formula_compared = field in {"ae", "af"} and any(row.expected is not None and row.actual is not None for row in rows)
            output.append({"field": field, "label": labels[field], "state": state, "note": note, "read": bool(rows), "authority": automatic_available, "computed": automatic_available or formula_recomputed, "compared": automatic_available or formula_compared})
        return output

    @staticmethod
    def _file_error(exc: OSError) -> str:
        if isinstance(exc, PermissionError):
            return "文件无法读取。请在系统设置中允许本工具访问该文件所在文件夹，然后重试。"
        if exc.errno == 4:
            return "文件读取被系统中断。请检查本工具是否有权限访问该文件所在文件夹。"
        return "文件打不开。请关闭 Excel/WPS，确认文件仍在原位置后重试。"

    @staticmethod
    def _inspection_error(errors: list) -> str:
        codes = {item.code for item in errors}
        if "UNSUPPORTED_FILE_FORMAT" in codes:
            return "文件格式暂不支持。请选择当前流程使用的 Excel 工作簿。"
        if "UNSUPPORTED_LAYOUT" in codes or "UNKNOWN_LAYOUT" in codes:
            return "无法识别这张表。请确认选择了正确类别的当前工资材料。"
        return "文件无法完成结构检查，请确认工作簿完整后重试。"

    @staticmethod
    def _warning_message(code: str) -> str:
        return {
            "MISSING_CACHE": "部分公式没有保存可读取的计算结果，相关字段不能可靠核对。",
            "EXTERNAL_REFERENCE_UNRESOLVED": "部分结果依赖其他 Excel 文件，目前无法确认是否最新。",
            "GRADE_UNRESOLVED": "部分排课无法确定年级，需要人工确认。",
            "MISSING_ATTENDANCE": "部分排课缺少可读取的实到人数，需要人工确认。",
        }.get(code, "存在需要查看的材料提示。")

    @staticmethod
    def _cell_state(state: str) -> str:
        return {
            "RAW_VALUE": "直接读取",
            "CACHED_VALUE": "读取已保存的公式结果",
            "MISSING_CACHE": "公式结果不可读取",
            "EXTERNAL_REFERENCE": "依赖其他文件",
        }.get(state, "待确认")

    @staticmethod
    def render(run: dict) -> dict:
        required = [LABELS[key] for key in REQUIRED if key not in run["files"]]
        summary = run.get("summary", PayrollService._summary([]))
        status_label = STATUS[run["status"]]
        if run["status"] == "REVIEW_REQUIRED":
            status_label = "排课项目已核对，仍需人工确认" if summary.get("automatic_pass") else "有问题待处理"
        materials = []
        for role, label in LABELS.items():
            item = run.get("files", {}).get(role)
            state = "失效" if role in run.get("stale_files", []) else "已准备" if item else "未导入"
            materials.append({"role": role, "label": label, "required": role in REQUIRED, "state": state, "file": item})
        return {
            **run,
            "status_label": status_label,
            "materials": materials,
            "health": {
                "ready": not required and run["status"] != "STALE",
                "missing": required,
                "readiness": round((len([key for key in REQUIRED if key in run["files"]]) / len(REQUIRED)) * 100),
                "warnings": [message for item in run.get("files", {}).values() for message in item.get("warning_messages", [])],
            },
        }
