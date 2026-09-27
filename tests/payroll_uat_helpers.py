"""Test helpers for the explicit subject-group confirmation contract."""
from __future__ import annotations

from pathlib import Path


def import_confirmed_subject_group(service, run_id: str, role: str, path: str | Path, actor: str = "脱敏 UAT 确认人") -> dict:
    preview = service.preview_subject_group_material(run_id, str(path))["subject_group_preview"]
    if preview["role"] != role:
        raise AssertionError(f"expected {role} preview, got {preview['role']}")
    if not preview["can_confirm"]:
        raise AssertionError(f"subject-group fixture is not confirmable: {preview}")
    return service.confirm_subject_group_material(
        run_id, role, preview["source_sha256"], actor,
        replace_existing=bool(preview.get("replacement_required")),
    )["run"]
