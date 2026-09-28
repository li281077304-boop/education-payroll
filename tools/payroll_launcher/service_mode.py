"""Run the Payroll HTTP service inside the launcher's own process.

A frozen release has no separate interpreter to launch, so the launcher
re-enters its own executable with ``--service`` and the UI runs here.  Two
behaviours exist only on this path:

* an **exclusive loopback bind**, because Windows honours ``SO_REUSEADDR`` by
  letting a second process bind a port that is already in use -- without this,
  a stray second start could quietly serve the same database twice;
* a **shutdown watchdog**, so the launcher can ask this process to close its
  database and exit cleanly before it ever resorts to terminating it.

Neither behaviour changes a payroll rule; they only decide whether this
process is the one allowed to serve the user's data.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from payroll_ui.health import data_dir_fingerprint
from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService

SHUTDOWN_CONTRACT = "payroll-shutdown/1"
WATCHDOG_INTERVAL_SECONDS = 0.25


class ExclusivePayrollHttpServer(PayrollHttpServer):
    """A Payroll server that refuses to share its port.

    ``HTTPServer`` normally sets ``SO_REUSEADDR``.  On Windows that option lets
    several processes bind the *same* address, so it would be possible for two
    copies of the tool to answer on 8760 and operate on one database at the
    same time.  Asking for an exclusive bind turns that into a clean startup
    failure instead.
    """

    allow_reuse_address = os.name != "nt"


def _stop_request_path(data_dir: Path) -> Path:
    return data_dir / "launcher" / "stop-request.json"


def _is_request_for_me(request_file: Path, pid: int, fingerprint: str) -> bool:
    try:
        record = json.loads(request_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(record, dict):
        return False
    if record.get("contract") != SHUTDOWN_CONTRACT:
        return False
    try:
        requested_pid = int(record.get("pid"))
    except (TypeError, ValueError):
        return False
    return requested_pid == pid and record.get("data_dir_fingerprint") == fingerprint


def _watch_shutdown(server: PayrollHttpServer, data_dir: Path, finished: threading.Event) -> None:
    """Close the server as soon as the launcher asks this exact process to."""
    request_file = _stop_request_path(data_dir)
    fingerprint = data_dir_fingerprint(data_dir)
    pid = os.getpid()
    while not finished.is_set():
        if _is_request_for_me(request_file, pid, fingerprint):
            try:
                request_file.unlink(missing_ok=True)
            except OSError:
                pass
            server.shutdown()
            return
        finished.wait(WATCHDOG_INTERVAL_SECONDS)


def run_service(data_dir: Path, port: int, static_root: Path | None = None) -> int:
    """Serve the payroll UI on loopback until the process is asked to stop."""
    from . import paths

    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    assets = Path(static_root) if static_root is not None else paths.static_root()

    server = ExclusivePayrollHttpServer(("127.0.0.1", int(port)), PayrollService(root), assets)
    finished = threading.Event()
    watchdog = threading.Thread(
        target=_watch_shutdown, args=(server, root, finished),
        name="payroll-shutdown-watchdog", daemon=True,
    )
    watchdog.start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        finished.set()
        server.server_close()
    return 0
