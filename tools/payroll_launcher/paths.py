"""Resolve every path the launcher needs, independently of the shell cwd.

Resolution rules live here so the .app shim, the CLI and the tests all agree
on one answer.  Nothing in this module creates or moves data.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# A fixed loopback port.  The launcher is the only component allowed to choose
# a port for the production entry; UAT launches keep using random ports.
DEFAULT_PORT = 8760
HOST = "127.0.0.1"

APP_MARKER = "education-payroll"

ENV_CONFIG = "PAYROLL_LAUNCHER_CONFIG"
ENV_REPO_ROOT = "PAYROLL_LAUNCHER_REPO_ROOT"
ENV_PYTHON = "PAYROLL_LAUNCHER_PYTHON"


class LauncherConfigError(RuntimeError):
    """Raised when no safe configuration can be assembled."""


def default_data_dir() -> Path:
    """The single production data directory.

    This mirrors the UI's own default so the launcher can never silently move
    the database.  It is deliberately under Application Support: /tmp is wiped
    on reboot, and a fresh UAT directory would hide the real history.
    """
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EducationPayroll"
    return Path.home() / "Library" / "Application Support" / "EducationPayroll"


@dataclass(frozen=True)
class LauncherConfig:
    repo_root: Path
    python: Path
    host: str
    port: int
    data_dir: Path

    @property
    def state_dir(self) -> Path:
        """Launcher bookkeeping lives beside the data, never inside the DB."""
        return self.data_dir / "launcher"

    @property
    def pid_file(self) -> Path:
        return self.state_dir / "service.json"

    @property
    def log_file(self) -> Path:
        return self.state_dir / "diagnostics.log"

    @property
    def lock_file(self) -> Path:
        return self.state_dir / "launcher.lock"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "payroll-ui.sqlite3"


def _repo_root_from_source() -> Path:
    # tools/payroll_launcher/paths.py -> tools/payroll_launcher -> tools -> repo
    return Path(__file__).resolve().parents[2]


def _load_config_file(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LauncherConfigError(f"启动器配置文件无法读取：{path}") from exc


def resolve_config(explicit_config: Path | None = None) -> LauncherConfig:
    """Assemble a configuration without touching the data directory."""
    config_path = explicit_config
    if config_path is None:
        env_path = os.environ.get(ENV_CONFIG)
        config_path = Path(env_path) if env_path else None
    file_config = _load_config_file(config_path)

    repo_env = os.environ.get(ENV_REPO_ROOT)
    if repo_env:
        repo_root = Path(repo_env).expanduser()
    elif file_config.get("repo_root"):
        repo_root = Path(str(file_config["repo_root"])).expanduser()
    else:
        repo_root = _repo_root_from_source()
    repo_root = repo_root.resolve()
    if not (repo_root / "payroll_ui" / "server.py").is_file():
        raise LauncherConfigError(f"找不到 Payroll 程序目录：{repo_root}")

    python_env = os.environ.get(ENV_PYTHON)
    candidate = None
    for source in (python_env, file_config.get("python")):
        if source:
            candidate = Path(str(source)).expanduser()
            break
    if candidate is None:
        venv_python = repo_root / ".venv" / "bin" / "python"
        if venv_python.is_file():
            candidate = venv_python
        elif sys.executable:
            candidate = Path(sys.executable)
    if candidate is None or not candidate.is_file():
        raise LauncherConfigError("找不到可用的 Python 解释器。")

    data_dir = Path(str(file_config.get("data_dir") or default_data_dir())).expanduser()
    port = int(file_config.get("port") or DEFAULT_PORT)
    host = str(file_config.get("host") or HOST)
    return LauncherConfig(repo_root=repo_root, python=candidate, host=host, port=port, data_dir=data_dir)


def interpreter_problem(python: Path, repo_root: Path) -> str | None:
    """Return a human-readable reason if this interpreter cannot run the UI."""
    probe = "import payroll_ui, payroll_core; print('ok')"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root)
    try:
        completed = subprocess.run(
            [str(python), "-c", probe],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"无法执行 Python：{exc}"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        return detail[-1] if detail else "Python 无法载入工资核算程序。"
    return None
