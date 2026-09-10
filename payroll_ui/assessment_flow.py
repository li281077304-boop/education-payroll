"""Group-leader management assessment intake.

Only a group leader uploads a management assessment. It is a business input to
payroll, and it never mixes with teachers' personal payroll sheets.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from payroll_core.adapters.payroll_submission import read_sheet_rows
from payroll_core.assessment import (
    SCORE_RULE_VERSION,
    build_assessment_result,
    check_assessments,
    resolve_metrics,
    score_objective,
    subjective_keys,
)
from payroll_core.models.management_assessment import (
    AssessmentRecord,
    AssessmentResultStatus,
    AssessmentRole,
    AssessmentStatus,
)


METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "progress_rate": ("进步率", "进步"),
    "weekly_average": ("周平均", "周平均课次", "一对一月周均"),
    "renewal_count": ("续推人次", "续费人次", "续推"),
    "refund_count": ("退费人次", "退费"),
    "student_count": ("总学员数", "总学员", "学员数", "学生数"),
    "turnover_rate": ("离职率",),
    "renewal_rate": ("续费人次率", "续推人次率", "续费率"),
    "refund_rate": ("退费人次率", "退费率"),
}
SUBJECTIVE_MARKERS = ("主观", "人工评分", "管理评分")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_hash(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


def parse_metrics(headers: Sequence[str], row: Mapping[str, Any]) -> dict[str, Any]:
    """Read one assessment row into metric keys without inventing values."""
    metrics: dict[str, Any] = {}
    normalized = {str(item).strip(): str(item).strip() for item in headers if str(item).strip()}
    for key, aliases in METRIC_ALIASES.items():
        header = next((normalized[alias] for alias in aliases if alias in normalized), "")
        if header and row.get(header) not in (None, ""):
            metrics[key] = row[header]
    index = 1
    for header in normalized:
        if any(marker in header for marker in SUBJECTIVE_MARKERS):
            value = row.get(header)
            if value not in (None, ""):
                metrics[f"subjective_{index}"] = value
            index += 1
    return metrics


class AssessmentService:
    def __init__(self, store):
        self.store = store

    def import_assessment(self, path: str, period: str, leader_id: str, submitted_by: str) -> dict:
        """Import one group-leader assessment sheet with row-level provenance."""
        source = Path(path)
        rows = read_sheet_rows(source, data_only=False)
        if not rows:
            raise ValueError("考核表没有可识别内容。")
        sheet, row_number, row = rows[0]
        metrics = parse_metrics(list(row), row)
        record = {
            "id": uuid.uuid4().hex[:16],
            "period": period,
            "teacher_id": leader_id.strip(),
            "role": AssessmentRole.GROUP_LEADER.value,
            "source_file": source.name,
            "source_sheet": sheet,
            "source_row": row_number,
            "source_file_hash": _file_hash(source),
            "metrics": metrics,
            "evidence": {"source_file": source.name, "sheet": sheet, "row": row_number, "headers": list(row)},
            "status": AssessmentStatus.SUBMITTED.value,
            "reviewed_by": "",
            "reviewed_at": "",
            "review_note": "",
            "linked_run_id": "",
            "submitted_by": submitted_by.strip(),
            "created_at": _now(),
            "updated_at": _now(),
        }
        self.store.save_assessment_record(record)
        self._event(record["id"], "SUBMITTED", submitted_by, "导入岗位考核表")
        return self._view(record)

    def findings(self, period: str = "", expected_leaders: Iterable[str] = ()) -> list[dict]:
        records = [self._record(item) for item in self.store.list_assessment_records() if not period or item.get("period") == period]
        return [item.__dict__ for item in check_assessments(records, expected_leaders=list(expected_leaders))]

    def confirm(
        self,
        record_id: str,
        reviewer: str,
        *,
        subjective_confirmations: Mapping[str, float] | None = None,
        amount_rule: Mapping[str, Any] | None = None,
    ) -> dict:
        """Confirm subjective items by hand, then produce the formal result."""
        record = self._record(self.store.get_assessment_record(record_id))
        if record.status not in {AssessmentStatus.SUBMITTED, AssessmentStatus.NEEDS_REVIEW}:
            raise ValueError("只有已提交的考核表才能确认。")
        result = build_assessment_result(
            record,
            reviewer=reviewer.strip(),
            reviewed_at=_now(),
            identifier=uuid.uuid4().hex[:16],
            subjective_confirmations={key: float(value) for key, value in (subjective_confirmations or {}).items()},
            amount_rule=amount_rule,
        )
        payload = dict(result.__dict__)
        payload["source_input_ids"] = list(result.source_input_ids)
        payload["evidence"] = dict(result.evidence)
        payload["amount_status"] = result.amount_status
        self.store.save_assessment_result(payload)
        stored = self.store.get_assessment_record(record_id)
        stored.update({
            "status": (AssessmentStatus.APPROVED if result.status == AssessmentResultStatus.FINAL else AssessmentStatus.NEEDS_REVIEW).value,
            "reviewed_by": reviewer.strip(),
            "reviewed_at": payload["reviewed_at"],
            "updated_at": _now(),
        })
        self.store.save_assessment_record(stored)
        self._event(record_id, "CONFIRMED", reviewer, f"结果状态 {result.status.value}")
        return self._result_view(payload)

    def bind_to_run(self, result_id: str, run: dict) -> dict:
        """Bind a finalized assessment to a payroll run."""
        payload = next((item for item in self.store.list_assessment_results() if item.get("id") == result_id), None)
        if payload is None:
            raise ValueError("未找到指定考核结果。")
        if payload.get("status") != AssessmentResultStatus.FINAL.value:
            raise ValueError("只有已确认的主观项与总分才能绑定工资核算。")
        if payload.get("period") != run["period"]:
            raise ValueError("考核结果月份与当前工资核算月份不一致。")
        payload["linked_run_id"] = run["id"]
        self.store.save_assessment_result(payload)
        run["assessment_bindings"] = [
            item for item in run.get("assessment_bindings", []) if item.get("result_id") != result_id
        ] + [{"result_id": result_id, "teacher_id": payload["teacher_id"], "final_score": payload["final_score"], "amount_status": payload["amount_status"], "bound_at": _now()}]
        return run

    def results(self, period: str = "") -> list[dict]:
        return [
            self._result_view(item)
            for item in self.store.list_assessment_results()
            if not period or item.get("period") == period
        ]

    def records(self, period: str = "") -> list[dict]:
        return [
            self._view(item)
            for item in self.store.list_assessment_records()
            if not period or item.get("period") == period
        ]

    def events(self, record_id: str) -> list[dict]:
        return self.store.list_assessment_events(record_id)

    # ------------------------------------------------------------------ helper
    def _record(self, payload: dict) -> AssessmentRecord:
        values = {
            "id": payload["id"], "period": payload["period"], "teacher_id": payload["teacher_id"],
            "role": AssessmentRole(payload["role"]), "source_file": payload.get("source_file", ""),
            "source_sheet": payload.get("source_sheet", ""), "source_row": payload.get("source_row", ""),
            "source_file_hash": payload.get("source_file_hash", ""), "metrics": payload.get("metrics", {}),
            "evidence": payload.get("evidence", {}), "status": AssessmentStatus(payload.get("status", "DRAFT")),
            "reviewed_by": payload.get("reviewed_by", ""), "reviewed_at": payload.get("reviewed_at", ""),
            "review_note": payload.get("review_note", ""), "linked_run_id": payload.get("linked_run_id", ""),
            "created_at": payload.get("created_at", ""), "updated_at": payload.get("updated_at", ""),
        }
        return AssessmentRecord(**values)

    def _view(self, payload: dict) -> dict:
        record = self._record(payload)
        score = score_objective(record.metrics)
        return {
            "id": record.id, "period": record.period, "teacher_id": record.teacher_id, "role": record.role.value,
            "source_file": record.source_file, "source_sheet": record.source_sheet, "source_row": record.source_row,
            "status": record.status.value, "metrics": dict(record.metrics),
            "resolved_metrics": resolve_metrics(record.metrics),
            "objective_score": score.total, "objective_items": dict(score.items),
            "pending_subjective": list(subjective_keys(record.metrics)),
            "submitted_by": payload.get("submitted_by", ""), "created_at": record.created_at,
        }

    def _result_view(self, payload: dict) -> dict:
        return {
            "id": payload["id"], "period": payload["period"], "teacher_id": payload["teacher_id"],
            "role": payload["role"], "rule_version": payload.get("rule_version", SCORE_RULE_VERSION),
            "reviewer": payload.get("reviewer", ""), "reviewed_at": payload.get("reviewed_at", ""),
            "objective_score": payload.get("objective_score", 0.0), "subjective_score": payload.get("subjective_score", 0.0),
            "final_score": payload.get("final_score", 0.0), "final_amount": payload.get("final_amount"),
            "amount_status": payload.get("amount_status", "RULE_NOT_CONFIGURED"),
            "status": payload.get("status"), "source_input_ids": list(payload.get("source_input_ids", [])),
            "linked_run_id": payload.get("linked_run_id", ""), "evidence": dict(payload.get("evidence", {})),
        }

    def _event(self, record_id: str, event_type: str, actor: str, note: str) -> None:
        self.store.append_assessment_event(record_id, {"created_at": _now(), "event_type": event_type, "actor": actor, "note": note})
