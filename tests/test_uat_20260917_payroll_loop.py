"""Regression coverage for the 2026-09-17 manual Payroll UAT contract."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from payroll_ui.storage import RunStore


def test_run_store_concurrent_writes_do_not_surface_database_locked(tmp_path):
    store = RunStore(tmp_path / "runs")
    payloads = [
        {"id": f"run-{index}", "created_at": "2026-09-17T00:00:00+00:00", "updated_at": str(index)}
        for index in range(24)
    ]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(store.save, payloads))
    assert len(store.list()) == len(payloads)


def test_payroll_issue_actions_expose_recovery_paths():
    source = (Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js").read_text(encoding="utf-8")
    assert "现在录入基本工资" in source
    assert "稍后上传" in source
    assert "有特殊情况 / 设置例外" in source
    assert "function showAfExceptions" in source


def test_uat_obligations_are_durable_and_machine_readable():
    path = Path(__file__).parents[1] / "docs" / "uat" / "2026-09-17" / "PAYROLL_OBLIGATIONS_2026-09-17.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["run_id"] == "payroll-uat-20260917-r1"
    assert {item["id"] for item in data["obligations"]} >= {"UAT-0917-01", "UAT-0917-12"}
