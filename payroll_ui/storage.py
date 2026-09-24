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
            db.execute("CREATE TABLE IF NOT EXISTS rating_versions (id TEXT PRIMARY KEY, effective_from TEXT NOT NULL, effective_to TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS policy_versions (id TEXT PRIMARY KEY, effective_from TEXT NOT NULL, effective_to TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS business_inputs (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS comment_candidates (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS teacher_access (teacher_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS business_input_events (id INTEGER PRIMARY KEY AUTOINCREMENT, input_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS resolutions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS payroll_submissions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS layout_profiles (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS submission_batches (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS submission_events (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS import_profiles (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS class_type_rules (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS core_rule_versions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS part_time_rate_versions (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS assessment_records (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS assessment_results (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS assessment_events (id INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            # Only the minimum dated fact needed for grade inference is kept.
            # The original schedule workbook is never copied into local storage.
            db.execute("CREATE TABLE IF NOT EXISTS student_grade_evidence (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            # Export snapshots are a separate evidence type: they describe a
            # course label in one workbook version and never become student
            # grade facts by themselves.
            db.execute("CREATE TABLE IF NOT EXISTS course_export_snapshots (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS company_payroll_templates (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS teacher_base_salary_profiles (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS af_default_policies (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def count_runs(self) -> int:
        """Cheap row count used by the launcher's identity handshake.

        Reading payloads to count runs would deserialize every stored run just
        to answer a health check, so this stays a single indexed count.
        """
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT COUNT(*) FROM runs").fetchone()
        return int(row[0]) if row else 0

    def save(self, run: dict) -> None:
        run["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(run, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO runs(id,created_at,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (run["id"], run["created_at"], payload))

    def save_run_and_business_input(self, run: dict, item: dict) -> None:
        """Persist an approved binding as one SQLite transaction.

        A run must never claim an input is bound while the input cannot point
        back at that run (or vice versa), even if the process stops mid-save.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        run["updated_at"] = timestamp
        item.setdefault("created_at", timestamp)
        item["updated_at"] = timestamp
        run_payload = json.dumps(run, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        item_payload = json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO runs(id,created_at,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (run["id"], run["created_at"], run_payload))
            db.execute("INSERT INTO business_inputs(id,created_at,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (item["id"], item["created_at"], item_payload))

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

    def save_rating_version(self, version: dict) -> None:
        payload = json.dumps(version, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO rating_versions(id,effective_from,effective_to,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (version["id"], version["effective_from"], version["effective_to"], payload))

    def list_rating_versions(self) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM rating_versions ORDER BY effective_from DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_rating_version(self, version_id: str) -> dict:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM rating_versions WHERE id=?", (version_id,)).fetchone()
        if row is None:
            raise ValueError("未找到教师星级版本。")
        return json.loads(row[0])

    def save_policy_version(self, version: dict) -> None:
        payload = json.dumps(version, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO policy_versions(id,effective_from,effective_to,payload) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (version["id"], version["effective_from"], version["effective_to"], payload))

    def list_policy_versions(self) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM policy_versions ORDER BY effective_from DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_policy_version(self, version_id: str) -> dict:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM policy_versions WHERE id=?", (version_id,)).fetchone()
        if row is None:
            raise ValueError("未找到教师工资政策版本。")
        return json.loads(row[0])

    def _upsert(self, table: str, item: dict, *, key: str = "id") -> None:
        identifier = str(item[key])
        created = str(item.get("created_at") or datetime.now(timezone.utc).isoformat())
        item.setdefault("created_at", created)
        item["updated_at"] = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute(f"INSERT INTO {table}({key},created_at,payload) VALUES(?,?,?) ON CONFLICT({key}) DO UPDATE SET payload=excluded.payload", (identifier, created, payload))

    def _get_entity(self, table: str, identifier: str, *, key: str = "id") -> dict:
        with sqlite3.connect(self.path) as db:
            row = db.execute(f"SELECT payload FROM {table} WHERE {key}=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("未找到指定记录。")
        return json.loads(row[0])

    def _list_entities(self, table: str) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute(f"SELECT payload FROM {table} ORDER BY created_at DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_business_input(self, item: dict) -> None:
        self._upsert("business_inputs", item)

    def append_business_input_event(self, input_id: str, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO business_input_events(input_id,created_at,payload) VALUES(?,?,?)", (input_id, event["created_at"], payload))

    def list_business_input_events(self, input_id: str) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM business_input_events WHERE input_id=? ORDER BY id", (input_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def get_business_input(self, input_id: str) -> dict:
        return self._get_entity("business_inputs", input_id)

    def list_business_inputs(self) -> list[dict]:
        return self._list_entities("business_inputs")

    def save_comment_candidate(self, item: dict) -> None:
        self._upsert("comment_candidates", item)

    def get_comment_candidate(self, candidate_id: str) -> dict:
        return self._get_entity("comment_candidates", candidate_id)

    def list_comment_candidates(self) -> list[dict]:
        return self._list_entities("comment_candidates")

    def save_resolution(self, item: dict) -> None:
        self._upsert("resolutions", item)

    def get_resolution(self, resolution_id: str) -> dict:
        """Resolve one persisted resolution from either storage shape.

        The AC workflow keeps resolutions inside the run payload, while this
        store also offers a dedicated table.  Both must resolve to the same
        record: a class-course note may only be generated from a resolution
        that really exists, and it must never depend on which side wrote it.
        """
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM resolutions WHERE id=?", (resolution_id,)).fetchone()
        if row is not None:
            return json.loads(row[0])
        for run in self.list():
            for item in run.get("resolutions") or []:
                if str(item.get("id", "")) == resolution_id:
                    return item
        raise ValueError("未找到指定记录。")

    def save_submission(self, item: dict) -> None:
        self._upsert("payroll_submissions", item)

    def list_submissions(self, batch_id: str = "") -> list[dict]:
        items = self._list_entities("payroll_submissions")
        return [item for item in items if not batch_id or item.get("batch_id") == batch_id]

    def save_layout_profile(self, item: dict) -> None:
        self._upsert("layout_profiles", item)

    def list_layout_profiles(self) -> list[dict]:
        return self._list_entities("layout_profiles")

    def save_submission_batch(self, item: dict) -> None:
        self._upsert("submission_batches", item)

    def get_submission_batch(self, batch_id: str) -> dict:
        return self._get_entity("submission_batches", batch_id)

    def list_submission_batches(self) -> list[dict]:
        return self._list_entities("submission_batches")

    def append_submission_event(self, batch_id: str, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO submission_events(batch_id,created_at,payload) VALUES(?,?,?)", (batch_id, event["created_at"], payload))

    def list_submission_events(self, batch_id: str) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM submission_events WHERE batch_id=? ORDER BY id", (batch_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_import_profile(self, item: dict) -> None:
        self._upsert("import_profiles", item)

    def save_student_grade_evidence(self, item: dict) -> None:
        self._upsert("student_grade_evidence", item)

    def list_student_grade_evidence(self) -> list[dict]:
        return self._list_entities("student_grade_evidence")

    def save_course_export_snapshot(self, item: dict) -> None:
        self._upsert("course_export_snapshots", item)

    def list_course_export_snapshots(self) -> list[dict]:
        return self._list_entities("course_export_snapshots")

    def save_company_payroll_template(self, item: dict) -> None:
        self._upsert("company_payroll_templates", item)

    def list_company_payroll_templates(self) -> list[dict]:
        return self._list_entities("company_payroll_templates")

    def save_teacher_base_salary_profile(self, item: dict) -> None:
        self._upsert("teacher_base_salary_profiles", item)

    def save_base_salary_profiles_and_run(self, profiles: list[dict], run: dict) -> None:
        """Persist one base-salary batch and its Run snapshot atomically.

        A rejected batch must not leave the first few teachers silently
        available to future months.  This is intentionally separate from the
        single-profile helper because this workflow has a user-visible
        all-or-nothing promise.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        run["updated_at"] = timestamp
        run_payload = json.dumps(run, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            for item in profiles:
                identifier = str(item["id"])
                created = str(item.get("created_at") or timestamp)
                item.setdefault("created_at", created)
                item["updated_at"] = timestamp
                payload = json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
                db.execute(
                    "INSERT INTO teacher_base_salary_profiles(id,created_at,payload) VALUES(?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                    (identifier, created, payload),
                )
            db.execute(
                "INSERT INTO runs(id,created_at,payload) VALUES(?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (run["id"], run["created_at"], run_payload),
            )

    def list_teacher_base_salary_profiles(self) -> list[dict]:
        return self._list_entities("teacher_base_salary_profiles")

    def save_af_default_policy(self, item: dict) -> None:
        self._upsert("af_default_policies", item)

    def list_af_default_policies(self) -> list[dict]:
        return self._list_entities("af_default_policies")

    def list_import_profiles(self, requirement: str = "") -> list[dict]:
        items = self._list_entities("import_profiles")
        return [item for item in items if not requirement or item.get("requirement") == requirement]

    def save_class_type_rule_version(self, item: dict) -> None:
        self._upsert("class_type_rules", item)

    def append_calculation_version(self, kind: str, item: dict) -> None:
        """Calculation authorities are immutable snapshots, never upserted."""
        table = {"core": "core_rule_versions", "part_time": "part_time_rate_versions"}[kind]
        payload = json.dumps(item, ensure_ascii=False, allow_nan=False)
        with sqlite3.connect(self.path) as db:
            db.execute(f"INSERT INTO {table}(id,created_at,payload) VALUES(?,?,?)", (item["id"], item["created_at"], payload))

    def calculation_versions(self, kind: str) -> list[dict]:
        table = {"core": "core_rule_versions", "part_time": "part_time_rate_versions"}[kind]
        return self._list_entities(table)

    def list_class_type_rule_versions(self) -> list[dict]:
        return self._list_entities("class_type_rules")

    def save_assessment_record(self, item: dict) -> None:
        self._upsert("assessment_records", item)

    def get_assessment_record(self, record_id: str) -> dict:
        return self._get_entity("assessment_records", record_id)

    def list_assessment_records(self) -> list[dict]:
        return self._list_entities("assessment_records")

    def save_assessment_result(self, item: dict) -> None:
        self._upsert("assessment_results", item)

    def list_assessment_results(self) -> list[dict]:
        return self._list_entities("assessment_results")

    def append_assessment_event(self, record_id: str, event: dict) -> None:
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO assessment_events(record_id,created_at,payload) VALUES(?,?,?)", (record_id, event["created_at"], payload))

    def list_assessment_events(self, record_id: str) -> list[dict]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT payload FROM assessment_events WHERE record_id=? ORDER BY id", (record_id,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def save_teacher_access(self, teacher_id: str, token_hash: str, item: dict) -> None:
        payload = json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO teacher_access(teacher_id,token_hash,payload) VALUES(?,?,?) ON CONFLICT(teacher_id) DO UPDATE SET token_hash=excluded.token_hash,payload=excluded.payload", (teacher_id, token_hash, payload))

    def teacher_access_by_hash(self, token_hash: str) -> dict | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT payload FROM teacher_access WHERE token_hash=?", (token_hash,)).fetchone()
        return json.loads(row[0]) if row else None
