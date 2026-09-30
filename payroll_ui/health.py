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
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# Bump only when the payload shape changes in an incompatible way.
HEALTH_CONTRACT = "payroll-ui/1"

APP_ID = "education-payroll"
SERVICE_ID = "payroll-ui"

HEALTH_PATH = "/api/health"
RELEASE_VERSION_ENV = "PAYROLL_RELEASE_VERSION"
BUILD_SHA_ENV = "PAYROLL_BUILD_SHA"
BUILD_DIRTY_ENV = "PAYROLL_BUILD_DIRTY"


def data_dir_fingerprint(data_dir: Path | str) -> str:
    """Stable, non-reversible fingerprint of the resolved data directory.

    The launcher uses it to prove that the service already holding the fixed
    port is attached to the same production data directory, rather than to one
    of the throwaway UAT directories under /tmp.
    """
    resolved = str(Path(data_dir).expanduser().resolve())
    return hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]


def build_identity() -> dict[str, str | bool]:
    """Capture the release identity once when the service starts.

    Packaged launchers provide immutable build metadata. A source checkout
    falls back to its current Git commit and tracked-worktree state.
    """
    release_version = os.environ.get(RELEASE_VERSION_ENV, "Payroll-V1").strip() or "Payroll-V1"
    expected_build_sha = os.environ.get(BUILD_SHA_ENV, "").strip()
    dirty_value = os.environ.get(BUILD_DIRTY_ENV, "").strip().lower()
    packaged_dirty = dirty_value in {"1", "true", "yes"}
    source_workspace = os.environ.get("PAYROLL_LAUNCHER_REPO_ROOT", "").strip()
    root = Path(source_workspace).expanduser() if source_workspace else Path(__file__).resolve().parents[1]
    try:
        actual_sha = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root, check=True, capture_output=True, text=True, timeout=2,
        ).stdout.strip()
        actual_dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=root, check=True, capture_output=True, text=True, timeout=2,
        ).stdout.strip())
        # A Mac bundle launches its recorded external checkout. Never echo the
        # stamped SHA if that checkout has since moved or acquired local edits.
        # Frozen Windows builds have no .git metadata and use the embedded stamp.
        build_sha = actual_sha
        dirty = actual_dirty or (bool(expected_build_sha) and actual_sha != expected_build_sha)
    except (OSError, subprocess.SubprocessError):
        if source_workspace:
            # A Mac app is a launcher for an external checkout. If that checkout
            # loses its Git identity, its stamped SHA is not proof of the code
            # currently on disk; report unverifiable rather than echoing it.
            build_sha = "unknown"
            dirty = True
        else:
            # Frozen Windows builds have no .git directory; their build-info.json
            # is the immutable source identity for the bundled code.
            build_sha = expected_build_sha or "unknown"
            dirty = True if not expected_build_sha else packaged_dirty
    return {"release_version": release_version, "build_sha": build_sha, "build_dirty": dirty}


def health_payload(
    data_dir: Path | str,
    port: int,
    started_at: datetime | None = None,
    run_count: int | None = None,
    identity: dict | None = None,
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
    current_identity = identity or build_identity()
    payload.update({
        "release_version": str(current_identity.get("release_version") or "Payroll-V1"),
        "build_sha": str(current_identity.get("build_sha") or "unknown"),
        "build_dirty": bool(current_identity.get("build_dirty", False)),
    })
    if run_count is not None:
        payload["run_count"] = int(run_count)
    return payload
