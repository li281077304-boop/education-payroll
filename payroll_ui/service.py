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
from payroll_core.reconcile.payroll_scope import FieldCheck, rate_and_fee_checks, schedule_field_checks, total_salary_read_checks

from .storage import RunStore

REQUIRED = ("schedule", "math", "science")
LABELS = {"schedule": "原始排课数据", "math": "数学组工资表", "science": "理化组工资表", "check": "最终工资核对表"}
LAYOUTS = {"schedule": "SCHEDULE_EXPORT_V1", "math": "PAYROLL_SHEET_V1", "science": "PAYROLL_SHEET_V1", "check": "PAYROLL_CHECK_V1"}
STATUS = {"DRAFT": "待导入", "FILES_READY": "材料已准备", "CHECKING": "正在核对", "REVIEW_REQUIRED": "需要复核", "STALE": "文件已变化", "PASS": "字段核对完成"}


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
        run = {"id": uuid.uuid4().hex[:12], "period": period, "created_at": datetime.now(timezone.utc).isoformat(), "status": "DRAFT", "files": {}, "issues": [], "decisions": [], "management": [], "field_status": self._field_status([]), "summary": self._summary([])}
        self.store.save(run)
        return self.render(run)

    def list(self) -> list[dict]:
        return [self.render(self._load(item["id"])) for item in self.store.list()]

    def get(self, run_id: str) -> dict:
        return self.render(self._load(run_id))

    def import_file(self, run_id: str, role: str, path: str, expected_hash: str | None = None) -> dict:
        if role not in LABELS:
            raise ValueError("未知材料类别。")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("找不到原始文件。请关闭 Excel/WPS 后重新选择。")
        before = version(source)
        if expected_hash and expected_hash != before["sha256"]:
            raise ValueError("所选原文件与刚才拖放识别的文件不一致。")
        run = self._load(run_id)
        if any(key != role and item["sha256"] == before["sha256"] for key, item in run["files"].items()):
            raise ValueError("同一份文件不能同时充当两个材料类别。")
        inspection = inspect_workbook(source)
        if inspection.errors or not inspection.records:
            raise ValueError("无法识别这张表，请确认是完整的当前工资相关 Excel。")
        workbook = inspection.records[0]
        if workbook.fingerprint.layout != LAYOUTS[role]:
            raise ValueError(f"文件不属于“{LABELS[role]}”，请检查后重新选择。")
        result = self._read(role, source, run["period"])
        if result.errors:
            raise ValueError("文件缺少当前核对所需字段：" + "；".join(issue.message for issue in result.errors))
        if version(source) != before:
            raise ValueError("文件在读取期间发生变化，请关闭 Excel/WPS 后重试。")
        run["files"][role] = {"name": source.name, "path": str(source), **before, "label": LABELS[role], "records": len(result.records), "teachers": len({record.teacher for record in result.records if hasattr(record, "teacher")}), "warnings": [issue.code for issue in result.warnings], "sheets": [sheet.name for sheet in workbook.sheets], "formula_count": sum(sheet.formula_count for sheet in workbook.sheets), "missing_cache": sum(sheet.formula_cache_missing for sheet in workbook.sheets), "external_references": workbook.external_link_count + sum(sheet.external_formula_count for sheet in workbook.sheets)}
        run["issues"], run["decisions"] = [], []
        run["status"] = "FILES_READY" if all(key in run["files"] for key in REQUIRED) else "DRAFT"
        self.store.save(run)
        return self.render(run)

    def check(self, run_id: str) -> dict:
        run = self._load(run_id)
        missing = [LABELS[key] for key in REQUIRED if key not in run["files"]]
        if missing:
            raise ValueError("请先导入：" + "、".join(missing))
        run["status"] = "CHECKING"; self.store.save(run)
        reads = {key: self._read(key, Path(item["path"]), run["period"]) for key, item in run["files"].items()}
        if not self._fresh(run):
            raise ValueError("原文件在核对时发生变化，请重新导入。")
        if any(result.errors for result in reads.values()):
            raise ValueError("文件再次读取失败，请重新导入。")
        payroll = [*reads["math"].records, *reads["science"].records]
        if {row.teacher for row in reads["math"].records} & {row.teacher for row in reads["science"].records}:
            raise ValueError("两张工资表含重复教师，不能安全核对。")
        checks = schedule_field_checks(reads["schedule"].records, payroll)
        checks += rate_and_fee_checks(payroll) + total_salary_read_checks(payroll)
        checks = self._apply_decisions(checks, run["decisions"])
        run["issues"] = [self._issue(check) for check in checks if check.status not in {"MATCH", "FORMULA_MATCH", "READ_ONLY", "EXPLAINED_DIFFERENCE"}]
        run["field_status"] = self._field_status(checks)
        run["summary"] = self._summary(checks)
        # AA/AC can be verified individually.  A full pass is unavailable until
        # every displayed payroll field has an independent authority chain.
        run["status"] = "PASS" if run["summary"]["full_scope_complete"] else "REVIEW_REQUIRED"
        self.store.save(run)
        return self.render(run)

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
        run["status"] = "REVIEW_REQUIRED"; self.store.save(run)
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
        lines = [{"来源": "原始排课", "Sheet": next(iter(item.provenance.values())).sheet, "课程时间": item.lesson_time, "班级": item.class_name, "班型": item.class_type, "年级": item.grade or "待确认", "实到": item.attended, "单元格": ", ".join(value.coordinate for name, value in item.provenance.items() if name != "student")} for item in schedule if item.teacher == issue["teacher"]]
        target = next((item for item in payroll if item.teacher == issue["teacher"]), None)
        if target:
            value = target.provenance[issue["field"]]
            lines.append({"来源": "工资表", "Sheet": value.sheet, "字段": value.source_field, "工资表值": value.normalized_value, "单元格": value.coordinate, "状态": value.state.value})
        if not self._fresh(run):
            raise ValueError("文件在查看证据时发生变化，请重新导入。")
        return {"issue": issue, "evidence": lines}

    def export_csv(self, run_id: str) -> str:
        run = self._load(run_id); self._require_fresh(run)
        out = io.StringIO(); writer = csv.writer(out)
        writer.writerow(["核算月份", "项目", "字段状态", "教师", "系统值", "工资表值", "差异", "处理状态", "说明"])
        for field in run["field_status"]:
            writer.writerow([run["period"], field["label"], field["state"], "", "", "", "", "", field["note"]])
        for issue in run["issues"]:
            writer.writerow([run["period"], issue["title"], issue["status"], safe_csv(issue["teacher"]), issue["expected"], issue["actual"], issue["difference"], "待处理", safe_csv(issue["reason"])])
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
        changed = False
        for item in run.get("files", {}).values():
            path = Path(item["path"])
            if not path.is_file() or version(path) != {key: item[key] for key in ("sha256", "size", "mtime_ns")}:
                changed = True
        if changed:
            run["status"] = "STALE"; run["decisions"] = []
            self.store.save(run)
        return not changed

    def _require_fresh(self, run: dict) -> None:
        if run["status"] == "STALE":
            raise ValueError("原始文件已变化，请重新导入并重新核对。")

    @staticmethod
    def _read(role: str, path: Path, period: str):
        return {"schedule": read_schedule_excel, "math": read_payroll_excel, "science": read_payroll_excel, "check": read_check_workbook_schedule}[role](path, period)

    @staticmethod
    def _issue(item: FieldCheck) -> dict:
        difference = item.actual - item.expected if item.actual is not None and item.expected is not None else None
        return {"id": hashlib.sha256(f"{item.teacher}|{item.field}|{item.reason}".encode()).hexdigest()[:16], "teacher": item.teacher, "field": item.field, "title": {"one_to_one": "一对一折算小时差异", "class_value": "班课折算小时差异", "ae": "课时单价需确认", "af": "总课时费需确认"}.get(item.field, "需要人工处理"), "difference": difference, **asdict(item)}

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
            "unexplained": sum(row.status == "UNEXPLAINED_DIFFERENCE" for row in checks),
            "manual_review": sum(row.status in {"NEEDS_MANUAL_REVIEW", "MISSING_SOURCE", "MISSING_TARGET", "FORMULA_DIFFERENCE"} for row in checks),
            "full_scope_complete": bool(field_states) and all(row["state"].startswith("已核对") for row in field_states),
            "scope_note": "AA、AC 已接入独立排课源；AE、AF、AV 尚无完整独立权威源，不能判定整份工资核对通过。",
        }

    @staticmethod
    def _field_status(checks: list[FieldCheck]) -> list[dict]:
        labels = {"one_to_one": "AA 一对一折算小时", "class_value": "AC 班课折算小时", "ae": "AE 该档每小时金额", "af": "AF 总课时费", "av": "AV 总工资"}
        output = []
        for field in ("one_to_one", "class_value", "ae", "af", "av"):
            rows = [row for row in checks if row.field == field]
            if field in {"one_to_one", "class_value"}:
                state = "已核对" if rows and all(row.status in {"MATCH", "EXPLAINED_DIFFERENCE"} for row in rows) else "待处理"
                note = "原始排课已独立计算并与工资表比较。" if state == "已核对" else "存在差异、缺失或无法确定的排课规则。"
            elif field in {"ae", "af"}:
                state, note = "公式复算 / 待权威确认", "已按现有公式复算；星级或输入仍来自工资表，尚非独立权威源。"
            else:
                state, note = "仅读取 / 待人工确认", "总工资包含续费、退费、激励、管理奖等未接入来源。"
            output.append({"field": field, "label": labels[field], "state": state, "note": note, "read": bool(rows), "authority": field in {"one_to_one", "class_value"}, "computed": field in {"one_to_one", "class_value", "ae", "af"}, "compared": field in {"one_to_one", "class_value"}})
        return output

    @staticmethod
    def render(run: dict) -> dict:
        required = [LABELS[key] for key in REQUIRED if key not in run["files"]]
        return {**run, "status_label": STATUS[run["status"]], "health": {"ready": not required and run["status"] != "STALE", "missing": required, "readiness": round((len([key for key in REQUIRED if key in run["files"]]) / len(REQUIRED)) * 100)}}
