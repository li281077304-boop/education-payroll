from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class RunStore:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "payroll-ui.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def save(self, run: dict) -> None:
        run["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(run, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO runs(id,created_at,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (run["id"], run["created_at"], payload))

    def get(self, run_id: str) -> dict:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("未找到该工资核算记录。")
        return json.loads(row[0])

    def list(self) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM runs ORDER BY created_at DESC").fetchall()
        runs = [json.loads(row[0]) for row in rows]
        return sorted(runs, key=lambda item: item.get("updated_at", item["created_at"]), reverse=True)
