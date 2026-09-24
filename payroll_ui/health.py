"""Service identity contract shared by the local UI server and its launcher.

The launcher must never guess whether the port it is about to use belongs to
the current Payroll service.  This module is the single source of truth for
that handshake.

It describes the running process only.  It contains no payroll data, no
business rule and no file contents.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path

# Bump only when the payload shape changes in an incompatible way.
HEALTH_CONTRACT = "payroll-ui/1"

APP_ID = "education-payroll"
SERVICE_ID = "payroll-ui"

HEALTH_PATH = "/api/health"


def data_dir_fingerprint(data_dir: Path | str) -> str:
    """Stable, non-reversible fingerprint of the resolved data directory.

    The launcher uses it to prove that the service already holding the fixed
    port is attached to the same production data directory, rather than to one
    of the throwaway UAT directories under /tmp.
    """
    resolved = str(Path(data_dir).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]


def health_payload(
    data_dir: Path | str,
    port: int,
    started_at: datetime | None = None,
    run_count: int | None = None,
) -> dict:
    """Describe this process.  Deliberately free of business data."""
    started = started_at or datetime.now(timezone.utc)
    payload = {
        "contract": HEALTH_CONTRACT,
        "app": APP_ID,
        "service": SERVICE_ID,
        "pid": os.getpid(),
        "port": int(port),
        "data_dir_fingerprint": data_dir_fingerprint(data_dir),
        "started_at": started.isoformat(),
    }
    if run_count is not None:
        payload["run_count"] = int(run_count)
    return payload
