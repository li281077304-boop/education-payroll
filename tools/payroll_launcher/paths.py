"""Resolve every path the launcher needs, independently of the shell cwd.

Resolution rules live here so the macOS ``.app`` shim, the Windows release
folder, the CLI and the tests all agree on one answer.  Nothing in this module
creates or moves data.

Two deployment shapes are supported:

* **source checkout** -- the launcher runs from ``tools/payroll_launcher`` and
  starts the UI with the checkout's own interpreter;
* **frozen release** -- the launcher *is* the released executable and starts
  the UI by re-entering itself, so no system Python is involved.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path

# A fixed loopback port.  The launcher is the only component allowed to choose
# a port for the production entry; UAT launches keep using random ports.
DEFAULT_PORT = 8760
HOST = "127.0.0.1"

APP_MARKER = "education-payroll"

ENV_CONFIG = "PAYROLL_LAUNCHER_CONFIG"
ENV_REPO_ROOT = "PAYROLL_LAUNCHER_REPO_ROOT"
ENV_PYTHON = "PAYROLL_LAUNCHER_PYTHON"

SERVICE_FLAG = "--service"


class LauncherConfigError(RuntimeError):
    """Raised when no safe configuration can be assembled."""


def default_data_dir() -> Path:
    """The single production data directory.

    This mirrors the UI's own default so the launcher can never silently move
    the database.  It is deliberately outside the program folder: ``/tmp`` is
    wiped on reboot, a Downloads or Desktop copy gets deleted by hand, and a
    fresh UAT directory would hide the real history.  Replacing the program
    folder must never touch this location.
    """
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EducationPayroll"
    return Path.home() / "Library" / "Application Support" / "EducationPayroll"


def is_frozen() -> bool:
    """True when running from a PyInstaller release build."""
    return bool(getattr(sys, "frozen", False))


def bundled_root() -> Path:
    """Where a frozen build keeps its bundled modules and data files."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return _repo_root_from_source()


def program_root() -> Path:
    """The folder the user sees as "the program".

    For a frozen release this is the folder holding the executable, which is
    exactly what the user unpacked from the ZIP; data never lives here.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _repo_root_from_source()


def static_root() -> Path:
    """Absolute location of the UI's static assets in either deployment."""
    if is_frozen():
        return bundled_root() / "payroll_ui" / "static"
    return Path(__file__).resolve().parents[2] / "payroll_ui" / "static"


@dataclass(frozen=True)
class LauncherConfig:
    repo_root: Path
    python: Path
    host: str
    port: int
    data_dir: Path
    # ``python`` holds the released executable in a frozen build; this flag
    # records which of the two shapes we are running so ``service_argv`` and
    # the interpreter preflight do not have to guess.
    frozen: bool = False

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
    def stop_request_file(self) -> Path:
        """Where the launcher asks its own service to shut down cleanly."""
        return self.state_dir / "stop-request.json"

    @property
    def service_log_file(self) -> Path:
        return self.state_dir / "service-output.log"

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


def _resolve_config_path(explicit_config: Path | None) -> Path | None:
    if explicit_config is not None:
        return explicit_config
    env_path = os.environ.get(ENV_CONFIG)
    return Path(env_path) if env_path else None


def _frozen_config(file_config: dict) -> LauncherConfig:
    """Configuration of a released build.

    A frozen release carries its own runtime, so neither an interpreter nor a
    config file has to be found on the machine.  Ambient environment variables
    are deliberately ignored here: the release must behave the same no matter
    which shell (or which working directory) started it.
    """
    program = program_root()
    assets = static_root()
    if not (assets / "index.html").is_file():
        raise LauncherConfigError(f"找不到工资核算界面资源：{assets}")

    executable = Path(sys.executable).resolve()
    if not executable.is_file():
        raise LauncherConfigError(f"找不到工资核算程序：{executable}")

    data_dir = Path(str(file_config.get("data_dir") or default_data_dir())).expanduser()
    return LauncherConfig(
        repo_root=program,
        python=executable,
        host=str(file_config.get("host") or HOST),
        port=int(file_config.get("port") or DEFAULT_PORT),
        data_dir=data_dir,
        frozen=True,
    )


def resolve_config(explicit_config: Path | None = None) -> LauncherConfig:
    """Assemble a configuration without touching the data directory."""
    file_config = _load_config_file(_resolve_config_path(explicit_config))

    if is_frozen():
        return _frozen_config(file_config)

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


def with_overrides(cfg: LauncherConfig, *, data_dir: Path | None = None, port: int | None = None) -> LauncherConfig:
    """Diagnostic-only override that always preserves the deployment shape."""
    return replace(cfg, data_dir=data_dir or cfg.data_dir, port=port or cfg.port)


def service_argv(cfg: LauncherConfig) -> list[str]:
    """The exact command that starts the Payroll HTTP service.

    A frozen release re-enters its own executable, which is what makes the
    package independent of any Python installed on the user's machine.
    """
    if cfg.frozen:
        return [
            str(cfg.python),
            SERVICE_FLAG,
            "--data-dir", str(cfg.data_dir),
            "--port", str(cfg.port),
        ]
    return [
        str(cfg.python), "-u", "-m", "payroll_ui",
        "--data-dir", str(cfg.data_dir),
        "--port", str(cfg.port),
        "--no-browser",
    ]


def interpreter_problem(python: Path, repo_root: Path) -> str | None:
    """Return a human-readable reason if this interpreter cannot run the UI.

    A frozen release is its own interpreter, so there is nothing to preflight:
    re-entering the executable with ``-c`` is not a supported PyInstaller mode
    and would launch a second copy of the application instead.
    """
    if is_frozen():
        if not static_root().is_dir():
            return "发布包缺少界面资源，请重新解压完整的程序目录。"
        return None
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
