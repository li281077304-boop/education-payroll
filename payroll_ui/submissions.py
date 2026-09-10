"""Teacher payroll sheet intake: recognize, standardize, merge, then publish.

Three input shapes (one personal sheet, many personal sheets, one summary
workbook) all end up as StandardPayrollSubmission rows. Downstream payroll
reconciliation only ever sees the merged canonical table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Sequence

from payroll_core.adapters.payroll_submission import build_submissions, detect_layout, fingerprint_for, read_sheet_rows
from payroll_core.excel.standard_workbook import write_standard_workbook
from payroll_core.models.payroll_submission import (
    LayoutProfile,
    MergeBatchStatus,
    SubmissionSourceKind,
    SubmissionStatus,
)
from payroll_core.submissions import merge_submissions


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _file_hash(path: str | Path) -> str:
    return sha256(Path(path).read_bytes()).hexdigest()


class PayrollSubmissionService:
    def __init__(self, store):
        self.store = store

    # ------------------------------------------------------------------ import
    def import_sheets(
        self,
        paths: Sequence[str],
        period: str,
        submitted_by: str,
        *,
        default_teacher: str = "",
    ) -> dict:
        """Import one or many payroll sheets. Ambiguous layouts stop for review."""
        if not paths:
            raise ValueError("请先选择要上传的工资表。")
        batch = {
            "id": uuid.uuid4().hex[:16],
            "period": period,
            "submitted_by": submitted_by.strip(),
            "status": MergeBatchStatus.DRAFT.value,
            "files": [],
            "pending_layouts": [],
            "submission_ids": [],
            "output_workbook": "",
            "created_at": _now(),
            "updated_at": _now(),
        }
        pending: list[dict[str, Any]] = []
        for index, path in enumerate(paths):
            rows = read_sheet_rows(path)
            if not rows:
                raise ValueError(f"工资表没有可识别内容：{Path(path).name}")
            headers = list(rows[0][2])
            fingerprint = fingerprint_for(headers)
            profile = self._profile_for(fingerprint)
            detection = detect_layout(headers, profile=profile)
            if detection.needs_confirmation:
                pending.append({
                    "path": str(path),
                    "file": Path(path).name,
                    "fingerprint": fingerprint,
                    "ambiguous": {key: list(value) for key, value in detection.ambiguous.items()},
                    "missing_required": list(detection.missing_required),
                    "headers": headers,
                })
                batch["files"].append({"path": str(path), "file": Path(path).name, "hash": _file_hash(path), "status": "NEEDS_CONFIRMATION"})
                continue
            submissions, _ = build_submissions(
                path, period, SubmissionSourceKind.MULTI if len(paths) > 1 else SubmissionSourceKind.SINGLE,
                profile=profile, file_hash=_file_hash(path), default_teacher=default_teacher,
                identifier=f"{batch['id']}-{index}",
            )
            kind = (
                SubmissionSourceKind.SUMMARY
                if len({item.teacher_id for item in submissions}) > 1
                else (SubmissionSourceKind.SINGLE if len(paths) == 1 else SubmissionSourceKind.MULTI)
            )
            for item in submissions:
                self._save(batch, item, kind)
            batch["files"].append({
                "path": str(path), "file": Path(path).name, "hash": _file_hash(path),
                "status": "IMPORTED", "teachers": sorted({item.teacher_id for item in submissions}),
                "kind": kind.value, "profile_id": detection.profile_id,
            })
        batch["pending_layouts"] = pending
        batch["status"] = MergeBatchStatus.NEEDS_CONFIRMATION.value if pending else MergeBatchStatus.DRAFT.value
        self.store.save_submission_batch(batch)
        self._event(batch, "IMPORTED", submitted_by, f"导入 {len(paths)} 份工资表")
        return batch

    def confirm_layout(self, batch_id: str, fingerprint: str, mapping: dict[str, str], confirmed_by: str) -> dict:
        """Remember a confirmed layout and re-read the sheets that needed it."""
        batch = self.store.get_submission_batch(batch_id)
        pending = [item for item in batch["pending_layouts"] if item["fingerprint"] == fingerprint]
        if not pending:
            raise ValueError("没有待确认的工资表格式。")
        if not mapping.get("teacher"):
            raise ValueError("必须确认哪一列是教师。")
        profile = LayoutProfile(
            id=uuid.uuid4().hex[:12],
            name=f"{pending[0]['file']} 已确认格式",
            fingerprint=fingerprint,
            mapping=dict(mapping),
            created_by=confirmed_by.strip(),
            period=batch["period"],
            created_at=_now(),
        )
        self.store.save_layout_profile(profile.__dict__)
        for item in pending:
            submissions, _ = build_submissions(
                item["path"], batch["period"], SubmissionSourceKind.SINGLE,
                confirmed_mapping=mapping, file_hash=_file_hash(item["path"]),
                identifier=f"{batch_id}-{Path(item['path']).stem}",
            )
            for submission in submissions:
                self._save(batch, submission, SubmissionSourceKind.SINGLE)
            for file_info in batch["files"]:
                if file_info["path"] == item["path"]:
                    file_info.update({"status": "IMPORTED", "kind": SubmissionSourceKind.SINGLE.value, "profile_id": profile.id})
        batch["pending_layouts"] = [item for item in batch["pending_layouts"] if item["fingerprint"] != fingerprint]
        if not batch["pending_layouts"]:
            batch["status"] = MergeBatchStatus.DRAFT.value
        batch["updated_at"] = _now()
        self.store.save_submission_batch(batch)
        self._event(batch, "LAYOUT_CONFIRMED", confirmed_by, f"确认格式 {fingerprint}")
        return batch

    # ------------------------------------------------------------------- merge
    def preview_merge(self, batch_id: str, expected_teachers: Iterable[str] = ()) -> dict:
        batch = self.store.get_submission_batch(batch_id)
        submissions = [self._load(item) for item in self.store.list_submissions(batch_id)]
        outcome = merge_submissions(submissions, expected_teachers=list(expected_teachers))
        return {
            "batch_id": batch_id,
            "period": batch["period"],
            "merged": outcome.merged,
            "findings": [item.__dict__ for item in outcome.findings],
            "duplicate_teachers": list(outcome.duplicate_teachers),
            "missing_teachers": list(outcome.missing_teachers),
            "conflicting_teachers": list(outcome.conflicting_teachers),
            "has_errors": outcome.has_errors,
        }

    def confirm_merge(self, batch_id: str, output_path: str, reviewer: str, expected_teachers: Iterable[str] = ()) -> dict:
        """Publish the unified payroll table from the merged model, never from a copy."""
        preview = self.preview_merge(batch_id, expected_teachers=list(expected_teachers))
        if preview["has_errors"]:
            raise ValueError("合并结果仍有必须处理的问题，请先处理后再生成标准工资表。")
        batch = self.store.get_submission_batch(batch_id)
        target = write_standard_workbook(preview["merged"], batch["period"], output_path)
        batch.update({"status": MergeBatchStatus.CONFIRMED.value, "output_workbook": target, "updated_at": _now()})
        self.store.save_submission_batch(batch)
        self._event(batch, "MERGE_CONFIRMED", reviewer, f"生成标准工资表 {Path(target).name}")
        return {"batch": batch, "output_workbook": target, "teacher_count": len(preview["merged"])}

    def batches(self, period: str = "") -> list[dict]:
        items = self.store.list_submission_batches()
        return [item for item in items if not period or item.get("period") == period]

    def events(self, batch_id: str) -> list[dict]:
        return self.store.list_submission_events(batch_id)

    # ------------------------------------------------------------------ helper
    def _profile_for(self, fingerprint: str) -> LayoutProfile | None:
        for item in self.store.list_layout_profiles():
            if item.get("fingerprint") == fingerprint:
                return LayoutProfile(**{key: item[key] for key in ("id", "name", "fingerprint", "mapping", "created_by", "period", "created_at") if key in item})
        return None

    def _save(self, batch: dict, submission, kind: SubmissionSourceKind) -> None:
        payload = dict(submission.__dict__)
        payload["fields"] = dict(submission.fields)
        payload["extra"] = dict(submission.extra)
        payload["source_kind"] = kind.value
        payload["status"] = SubmissionStatus.IMPORTED.value
        payload["batch_id"] = batch["id"]
        payload["created_at"] = payload.get("created_at") or _now()
        self.store.save_submission(payload)
        batch["submission_ids"].append(submission.id)

    def _load(self, payload: dict):
        from dataclasses import fields as dataclass_fields

        from payroll_core.models.payroll_submission import StandardPayrollSubmission
        allowed = {item.name for item in dataclass_fields(StandardPayrollSubmission)}
        values = {key: value for key, value in payload.items() if key in allowed}
        values["source_kind"] = SubmissionSourceKind(values["source_kind"])
        values["status"] = SubmissionStatus(values["status"])
        return StandardPayrollSubmission(**values)

    def _event(self, batch: dict, event_type: str, actor: str, note: str) -> None:
        self.store.append_submission_event(batch["id"], {"created_at": _now(), "event_type": event_type, "actor": actor, "note": note, "status": batch.get("status")})
