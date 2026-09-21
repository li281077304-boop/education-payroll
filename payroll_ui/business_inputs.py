"""Business-input workflow: submissions, reviewed upstream results and notes.

This module owns no payroll formula. It stores source-backed business facts,
enforces review, and lets PayrollService bind approved inputs to a Run.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from payroll_core.adapters import read_business_result

from .storage import RunStore


INPUT_TYPES = {"TEACHER_SUBMISSION", "RENEWAL_RESULT", "REFUND_RESULT", "REFERRAL_RESULT", "OTHER"}
TEACHER_ITEM_TYPES = {"排课信息有误", "班课特殊核算", "续费问题", "退费说明", "推荐奖励", "其他"}
REVIEW_ACTIONS = {"START_REVIEW": "REVIEW", "APPROVE": "APPROVED", "REJECT": "REJECTED", "REQUEST_MORE_INFO": "REQUEST_MORE_INFO"}
TERMINAL_STATUSES = {"REJECTED", "SUPERSEDED"}
MANUAL_ADJUSTMENT_STATUSES = {"APPROVED", "ACTIVE", "CONFIRMED", "FINAL_CONFIRMED"}


def is_active_business_input(item: dict[str, Any]) -> bool:
    """Return whether a persisted business input may affect a Run."""
    status = str(item.get("status") or "").upper()
    if status == "APPROVED":
        return True
    return str(item.get("input_type") or "").upper() == "MANUAL_ADJUSTMENT" and status in MANUAL_ADJUSTMENT_STATUSES


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def file_version(path: Path) -> dict[str, Any]:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha.update(chunk)
    stat = path.stat()
    return {"sha256": sha.hexdigest(), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


class BusinessInputService:
    def __init__(self, store: RunStore):
        self.store = store

    def create_teacher_access(self, teacher_id: str, display_name: str = "") -> dict:
        teacher_id = teacher_id.strip()
        if not teacher_id:
            raise ValueError("教师标识不能为空。")
        token = secrets.token_urlsafe(32)
        item = {"teacher_id": teacher_id, "display_name": display_name.strip() or teacher_id, "created_at": now(), "active": True}
        self.store.save_teacher_access(teacher_id, digest(token), item)
        # The plaintext token is deliberately returned once and never stored.
        return {**item, "access_token": token}

    def teacher_identity(self, token: str) -> dict:
        item = self.store.teacher_access_by_hash(digest(token)) if token else None
        if not item or not item.get("active", True):
            raise PermissionError("教师访问码无效或已停用。")
        return item

    def submit_teacher(self, token: str, period: str, item_type: str, note: str, link: dict[str, Any] | None = None) -> dict:
        identity = self.teacher_identity(token)
        if item_type not in TEACHER_ITEM_TYPES or not note.strip():
            raise ValueError("请选择事项类型并填写说明。")
        record = {
            "id": uuid.uuid4().hex[:16], "period": self._period(period), "teacher_id": identity["teacher_id"],
            "input_type": "TEACHER_SUBMISSION", "source_type": "TEACHER_PORTAL", "source_ref": "教师自助填报",
            "source_file_hash": "", "source_row": "", "submitted_by": identity["teacher_id"], "submitted_at": now(),
            "status": "SUBMITTED", "payload": {"item_type": item_type, "note": note.strip(), "link": link or {}},
            "evidence": {"teacher_access": identity["teacher_id"]}, "reviewed_by": "", "reviewed_at": "", "review_note": "", "linked_run_id": "", "created_at": now(), "updated_at": now(),
        }
        self.store.save_business_input(record)
        self._event(record, "SUBMITTED", identity["teacher_id"], "教师提交")
        return record

    def save_teacher_draft(self, token: str, period: str, item_type: str, note: str, link: dict[str, Any] | None = None, input_id: str = "") -> dict:
        identity = self.teacher_identity(token)
        if item_type not in TEACHER_ITEM_TYPES:
            raise ValueError("请选择事项类型。")
        if input_id:
            record = self.store.get_business_input(input_id)
            if record.get("teacher_id") != identity["teacher_id"] or record.get("status") != "DRAFT":
                raise PermissionError("只能修改自己的草稿。")
            record.update({"period": self._period(period), "payload": {"item_type": item_type, "note": note.strip(), "link": link or {}}, "updated_at": now()})
        else:
            record = {
                "id": uuid.uuid4().hex[:16], "period": self._period(period), "teacher_id": identity["teacher_id"],
                "input_type": "TEACHER_SUBMISSION", "source_type": "TEACHER_PORTAL", "source_ref": "教师自助填报",
                "source_file_hash": "", "source_row": "", "submitted_by": identity["teacher_id"], "submitted_at": "", "status": "DRAFT",
                "payload": {"item_type": item_type, "note": note.strip(), "link": link or {}}, "evidence": {"teacher_access": identity["teacher_id"]},
                "reviewed_by": "", "reviewed_at": "", "review_note": "", "linked_run_id": "", "created_at": now(), "updated_at": now(),
            }
        self.store.save_business_input(record)
        self._event(record, "DRAFT_SAVED", identity["teacher_id"], "保存草稿")
        return record

    def list_teacher(self, token: str) -> list[dict]:
        identity = self.teacher_identity(token)
        return [item for item in self.store.list_business_inputs() if item["teacher_id"] == identity["teacher_id"] and item["input_type"] == "TEACHER_SUBMISSION"]

    def list_admin(self, *, period: str = "", status: str = "") -> list[dict]:
        items = self.store.list_business_inputs()
        if period:
            items = [item for item in items if item["period"] == period]
        if status:
            items = [item for item in items if item["status"] == status]
        return items

    def import_results(self, input_type: str, period: str, path: str, submitted_by: str, *, activation_scope: str = "SUPPLEMENT", replace_input_ids: list[str] | None = None) -> list[dict]:
        if input_type not in {"RENEWAL_RESULT", "REFUND_RESULT"}:
            raise ValueError("本入口只导入最终续费或退费结果。")
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ValueError("找不到要导入的最终结果表。")
        resolved_period = self._period(period)
        before = file_version(source)
        records = read_business_result(source, period=resolved_period)
        try:
            after = file_version(source)
        except OSError as exc:
            raise ValueError("结果表在读取期间不可访问，请重试。") from exc
        if before != after:
            raise ValueError("结果表在读取期间发生变化，未保存任何导入记录。")
        batch_id = uuid.uuid4().hex[:12]
        if activation_scope not in {"SUPPLEMENT", "REPLACE_SELECTED"}:
            raise ValueError("请选择补充导入或明确替代已选版本。")
        selected = set(replace_input_ids or [])
        if activation_scope == "REPLACE_SELECTED" and not selected:
            raise ValueError("替代导入必须明确选择要替代的旧记录。")
        selectable = {
            item["id"] for item in self.store.list_business_inputs()
            if item.get("input_type") == input_type and item.get("period") == resolved_period
        }
        if not selected.issubset(selectable):
            raise ValueError("只能替代同月份、同类型的既有结果记录。")
        for prior in self.store.list_business_inputs():
            if prior.get("id") in selected and prior.get("input_type") == input_type and prior.get("period") == resolved_period and prior.get("status") not in TERMINAL_STATUSES:
                prior["status"] = "SUPERSEDED"
                prior["superseded_at"] = now()
                prior["superseded_by_batch"] = batch_id
                self.store.save_business_input(prior)
                self._event(prior, "SUPERSEDED", submitted_by, f"由批次 {batch_id} 明确替代")
        created: list[dict] = []
        for row in records:
            item = {
                "id": uuid.uuid4().hex[:16], "period": resolved_period, "teacher_id": row.teacher_id,
                "input_type": input_type, "source_type": "UPSTREAM_FINAL_RESULT", "source_ref": str(source),
                "source_file_hash": after["sha256"], "source_row": row.row, "submitted_by": submitted_by.strip(), "submitted_at": now(),
                "status": "SUBMITTED", "payload": row.payload, "evidence": {**row.evidence, **after, "batch_id": batch_id, "activation_scope": activation_scope},
                "reviewed_by": "", "reviewed_at": "", "review_note": "", "linked_run_id": "", "created_at": now(), "updated_at": now(),
            }
            self.store.save_business_input(item); created.append(item)
            self._event(item, "IMPORTED", submitted_by, "导入上游最终结果")
        return created

    def review(self, input_id: str, action: str, reviewer: str, note: str = "") -> dict:
        if action not in REVIEW_ACTIONS or not reviewer.strip():
            raise ValueError("请选择审核结论并填写审核人。")
        item = self.store.get_business_input(input_id)
        if item["status"] in TERMINAL_STATUSES:
            raise ValueError("该记录已结束，不能再次审核。")
        if action == "APPROVE" and item["status"] == "DRAFT":
            raise ValueError("草稿必须先提交，不能直接审核通过。")
        if action in {"APPROVE", "REJECT", "REQUEST_MORE_INFO"} and item["status"] != "REVIEW":
            raise ValueError("记录必须先进入审核中，才能给出审核结论。")
        if action == "START_REVIEW" and item["status"] not in {"SUBMITTED", "REQUEST_MORE_INFO"}:
            raise ValueError("当前记录不能进入审核。")
        item.update({"status": REVIEW_ACTIONS[action], "reviewed_by": reviewer.strip(), "reviewed_at": now(), "review_note": note.strip()})
        self.store.save_business_input(item)
        self._event(item, REVIEW_ACTIONS[action], reviewer, note.strip())
        return item

    def bind_to_run(self, input_id: str, run: dict, *, persist: bool = True) -> tuple[dict, dict]:
        item = self.store.get_business_input(input_id)
        if not is_active_business_input(item):
            raise ValueError("只有已审核通过的业务输入才能绑定工资核算。")
        if item["period"] != run["period"]:
            raise ValueError("业务输入月份与当前工资核算月份不一致。")
        binding = {"input_id": item["id"], "input_type": item["input_type"], "source_file_hash": item.get("source_file_hash", ""), "bound_at": now()}
        run["business_input_bindings"] = [item for item in run.get("business_input_bindings", []) if item["input_id"] != binding["input_id"]] + [binding]
        item["linked_run_id"] = run["id"]
        item.setdefault("run_bindings", []).append({"run_id": run["id"], "bound_at": now()})
        if persist:
            self.store.save_business_input(item)
            self._event(item, "BOUND_TO_RUN", "系统", f"绑定核算 {run['id']}")
        return run, item

    def current(self, input_id: str, expected_hash: str = "") -> bool:
        item = self.store.get_business_input(input_id)
        if not is_active_business_input(item):
            return False
        if expected_hash and item.get("source_file_hash") != expected_hash:
            return False
        source = Path(item.get("source_ref", ""))
        if item.get("source_file_hash"):
            if not source.is_file():
                return False
            try:
                return file_version(source)["sha256"] == item["source_file_hash"]
            except OSError:
                return False
        return not item.get("source_file_hash")

    def _event(self, item: dict, event_type: str, actor: str, note: str) -> None:
        self.store.append_business_input_event(item["id"], {"created_at": now(), "event_type": event_type, "actor": actor, "note": note, "status": item.get("status")})

    @staticmethod
    def _period(period: str) -> str:
        if len(period) != 7 or period[4] != "-" or not period.replace("-", "").isdigit() or not 1 <= int(period[5:]) <= 12:
            raise ValueError("请选择有效月份。")
        return period
