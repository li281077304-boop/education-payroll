"""Loopback-only HTTP shell for the local payroll tool.

The browser is a view and input surface.  File parsing and every payroll
judgement remain in the Python core on this computer.
"""
from __future__ import annotations

import json
import mimetypes
import secrets
import subprocess
import tempfile
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from payroll_core.excel.inspect import inspect_workbook

from .service import PayrollService


class PayrollHttpServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], service: PayrollService, static_root: Path):
        super().__init__(address, PayrollHandler)
        self.service = service
        self.static_root = static_root
        self.token = secrets.token_urlsafe(24)


class PayrollHandler(SimpleHTTPRequestHandler):
    server: PayrollHttpServer

    def log_message(self, _format: str, *_args: object) -> None:
        return  # do not leak local paths or payroll values to stdout

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def _error(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self._json({"error": message}, status)

    def _payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("请求内容无法识别。") from exc

    def _authorized(self) -> bool:
        return self.headers.get("X-Payroll-Token") == self.server.token

    def _serve_static(self, relative: str) -> None:
        path = (self.server.static_root / relative).resolve()
        if self.server.static_root not in path.parents and path != self.server.static_root:
            self.send_error(HTTPStatus.NOT_FOUND); return
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND); return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            return self._serve_static("index.html")
        if parsed.path.startswith("/static/"):
            return self._serve_static(parsed.path.removeprefix("/static/"))
        if parsed.path == "/api/bootstrap":
            return self._json({"token": self.server.token})
        if not self._authorized():
            return self._error("本地会话已失效，请刷新页面。", HTTPStatus.FORBIDDEN)
        try:
            if parsed.path == "/api/runs":
                return self._json(self.server.service.list())
            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/export.csv"):
                run_id = parsed.path.split("/")[3]
                body = self.server.service.export_csv(run_id).encode("utf-8-sig")
                self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", f'attachment; filename="payroll_audit_{run_id}.csv"')
                self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
            if parsed.path.startswith("/api/runs/") and parsed.path.endswith("/evidence"):
                run_id = parsed.path.split("/")[3]
                issue = parse_qs(parsed.query).get("issue", [""])[0]
                return self._json(self.server.service.evidence(run_id, issue))
            if parsed.path.startswith("/api/runs/"):
                return self._json(self.server.service.get(parsed.path.split("/")[3]))
            return self._error("找不到该页面。", HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            return self._error(str(exc))

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            return self._error("本地会话已失效，请刷新页面。", HTTPStatus.FORBIDDEN)
        try:
            payload = self._payload(); path = urlparse(self.path).path
            if path == "/api/runs":
                return self._json(self.server.service.create(str(payload.get("period", ""))), HTTPStatus.CREATED)
            if path == "/api/pick":
                return self._json({"path": self._pick_excel()})
            if path == "/api/inspect":
                return self._json(self._inspect_path(str(payload.get("path", ""))))
            bits = path.strip("/").split("/")
            if len(bits) >= 4 and bits[:2] == ["api", "runs"]:
                run_id, action = bits[2], bits[3]
                if action == "files":
                    return self._json(self.server.service.import_file(run_id, str(payload.get("role", "")), str(payload.get("path", "")), payload.get("sha256")))
                if action == "check":
                    return self._json(self.server.service.check(run_id))
                if action == "decisions":
                    return self._json(self.server.service.decide(run_id, str(payload.get("issue_id", "")), str(payload.get("action", "")), str(payload.get("person", "")), str(payload.get("reason", ""))))
                if action == "management":
                    return self._json(self.server.service.save_management(run_id, payload.get("values", {}), str(payload.get("person", ""))))
            return self._error("找不到该操作。", HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            return self._error(str(exc))

    @staticmethod
    def _pick_excel() -> str | None:
        script = 'POSIX path of (choose file with prompt "选择 Excel 文件" of type {"org.openxmlformats.spreadsheetml.sheet", "com.microsoft.excel.xls", "com.microsoft.excel.xlsm"})'
        try:
            return subprocess.check_output(["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    @staticmethod
    def _inspect_path(raw: str) -> dict:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            raise ValueError("找不到刚才选择的文件。")
        result = inspect_workbook(path)
        if not result.records:
            return {"recognized": False, "sheets": [], "missing": [issue.message for issue in result.errors]}
        workbook = result.records[0]
        return {"recognized": not result.errors, "layout": workbook.fingerprint.layout, "sheets": [sheet.name for sheet in workbook.sheets], "missing": [issue.message for issue in result.errors], "warnings": [issue.message for issue in result.warnings]}
