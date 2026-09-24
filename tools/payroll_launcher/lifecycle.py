"""Start, reuse and safely stop the production Payroll service.

Safety rules enforced here:

* a foreign process on the port is reported, never killed;
* a restart only ever signals the process recorded in our own pid file, and
  only after its command line and health payload agree with that record;
* the launcher never chooses a data directory other than the configured one,
  so it cannot silently fork the real database.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .paths import LauncherConfig
from .probe import ProbeKind, ProbeResult, probe

START_TIMEOUT_SECONDS = 45.0
POLL_INTERVAL_SECONDS = 0.3
TERMINATE_GRACE_SECONDS = 10.0
MAX_LOG_BYTES = 2 * 1024 * 1024

STATE_REUSED = "reused"
STATE_STARTED = "started"
STATE_PORT_TAKEN = "port-taken"
STATE_OTHER_DATA = "other-data"
STATE_START_FAILED = "start-failed"
STATE_PYTHON_INVALID = "python-invalid"
STATE_CONFIG_INVALID = "config-invalid"


@dataclass
class LaunchResult:
    ok: bool
    state: str
    message: str
    url: str
    pid: int | None = None
    diagnostics: str = ""
    log_tail: list[str] = field(default_factory=list)

    @property
    def can_retry(self) -> bool:
        return self.state in {STATE_START_FAILED, STATE_PYTHON_INVALID}

    @property
    def can_restart(self) -> bool:
        return self.state in {STATE_START_FAILED, STATE_OTHER_DATA}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_line(cfg: LauncherConfig, message: str) -> None:
    """Append one launcher diagnostic line.  Never raises."""
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        log = cfg.log_file
        if log.is_file() and log.stat().st_size > MAX_LOG_BYTES:
            rotated = log.with_suffix(".log.1")
            log.replace(rotated)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"[{_now()}] {message}\n")
    except OSError:
        pass


def read_pid_file(cfg: LauncherConfig) -> dict | None:
    try:
        record = json.loads(cfg.pid_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return record if isinstance(record, dict) else None


def write_pid_file(cfg: LauncherConfig, pid: int, detail: dict | None = None) -> None:
    try:
        cfg.state_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "launcher_contract": "payroll-launcher/1",
            "pid": int(pid),
            "port": cfg.port,
            "host": cfg.host,
            "data_dir": str(cfg.data_dir),
            "repo_root": str(cfg.repo_root),
            "python": str(cfg.python),
            "started_at": _now(),
        }
        if detail:
            record["service"] = detail
        cfg.pid_file.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        log_line(cfg, f"WARN 无法写入启动器记录：{exc}")


def clear_pid_file(cfg: LauncherConfig) -> None:
    try:
        cfg.pid_file.unlink(missing_ok=True)
    except OSError as exc:
        log_line(cfg, f"WARN 无法清理启动器记录：{exc}")


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def process_command(pid: int) -> str:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def looks_like_payroll(pid: int) -> bool:
    """Guard against acting on a recycled pid."""
    return "payroll_ui" in process_command(pid)


def log_tail(cfg: LauncherConfig, lines: int = 25) -> list[str]:
    try:
        content = cfg.log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def _service_log(cfg: LauncherConfig) -> Path:
    return cfg.state_dir / "service-output.log"


def start_process(cfg: LauncherConfig) -> subprocess.Popen:
    """Spawn the UI detached from this process, with no terminal attached."""
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cfg.repo_root)
    env["PYTHONUNBUFFERED"] = "1"
    # Keep proxy settings from interfering with a loopback connection.
    for key in ("NO_PROXY", "no_proxy"):
        existing = env.get(key, "")
        env[key] = ",".join(part for part in (existing, "127.0.0.1,localhost") if part)
    handle = _service_log(cfg).open("ab")
    try:
        return subprocess.Popen(
            [
                str(cfg.python), "-u", "-m", "payroll_ui",
                "--data-dir", str(cfg.data_dir),
                "--port", str(cfg.port),
                "--no-browser",
            ],
            cwd=str(cfg.repo_root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    finally:
        handle.close()


def wait_for_health(cfg: LauncherConfig, process: subprocess.Popen | None = None,
                    timeout: float = START_TIMEOUT_SECONDS) -> ProbeResult:
    deadline = time.monotonic() + timeout
    last = ProbeResult(ProbeKind.ABSENT, "尚未监听")
    while time.monotonic() < deadline:
        last = probe(cfg.host, cfg.port, cfg.data_dir)
        if last.kind is ProbeKind.OURS:
            return last
        if last.kind in {ProbeKind.OTHER_DATA, ProbeKind.FOREIGN}:
            return last
        if process is not None and process.poll() is not None:
            return last
        time.sleep(POLL_INTERVAL_SECONDS)
    return last


class LauncherLock:
    """Serialise double-clicks so two launches cannot start two services."""

    def __init__(self, cfg: LauncherConfig):
        self.cfg = cfg
        self._handle = None

    def __enter__(self) -> "LauncherLock":
        self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
        self._handle = self.cfg.lock_file.open("a+")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


def ensure_running(cfg: LauncherConfig, python_problem: str | None = None) -> LaunchResult:
    """Reuse a healthy service, otherwise start exactly one."""
    with LauncherLock(cfg):
        existing = probe(cfg.host, cfg.port, cfg.data_dir)
        log_line(cfg, f"probe {cfg.host}:{cfg.port} -> {existing.kind.value} ({existing.detail})")

        if existing.kind is ProbeKind.OURS:
            write_pid_file(cfg, existing.pid or 0, {"reused": True, "health": existing.payload})
            return LaunchResult(
                ok=True, state=STATE_REUSED,
                message="工资核算服务已在运行，正在打开页面。",
                url=cfg.base_url, pid=existing.pid,
                diagnostics="复用已有服务，未启动第二个进程。",
            )
        if existing.kind is ProbeKind.OTHER_DATA:
            return LaunchResult(
                ok=False, state=STATE_OTHER_DATA,
                message="工资核算服务正在运行，但它使用的是另一个数据目录。为避免混用真实数据，启动器没有接管它。",
                url=cfg.base_url, pid=existing.pid,
                diagnostics=f"端口 {cfg.port} 上是本服务，但数据目录指纹不匹配：{existing.payload}",
                log_tail=log_tail(cfg),
            )
        if existing.kind is ProbeKind.FOREIGN:
            return LaunchResult(
                ok=False, state=STATE_PORT_TAKEN,
                message=f"端口 {cfg.port} 已被其它程序占用，启动器不会结束其它程序。请关闭占用该端口的程序后重试。",
                url=cfg.base_url,
                diagnostics=f"端口 {cfg.port} 返回非工资服务响应：{existing.detail}",
                log_tail=log_tail(cfg),
            )

        stale = read_pid_file(cfg)
        if stale and not process_alive(int(stale.get("pid") or 0)):
            clear_pid_file(cfg)

        if python_problem:
            return LaunchResult(
                ok=False, state=STATE_PYTHON_INVALID,
                message="工资核算服务无法启动：本机 Python 环境不完整。",
                url=cfg.base_url, diagnostics=python_problem, log_tail=log_tail(cfg),
            )

        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        log_line(cfg, f"start {cfg.python} -m payroll_ui --data-dir {cfg.data_dir} --port {cfg.port}")
        try:
            process = start_process(cfg)
        except OSError as exc:
            log_line(cfg, f"ERROR 启动失败：{exc}")
            return LaunchResult(
                ok=False, state=STATE_START_FAILED,
                message="工资核算服务启动失败，请查看诊断信息。",
                url=cfg.base_url, diagnostics=str(exc), log_tail=log_tail(cfg),
            )

        healthy = wait_for_health(cfg, process)
        if healthy.kind is ProbeKind.OURS:
            write_pid_file(cfg, healthy.pid or process.pid, {"health": healthy.payload})
            log_line(cfg, f"ready pid={healthy.pid or process.pid}")
            return LaunchResult(
                ok=True, state=STATE_STARTED,
                message="工资核算服务已启动，正在打开页面。",
                url=cfg.base_url, pid=healthy.pid or process.pid,
                diagnostics=f"已启动新服务：{cfg.base_url}",
            )

        code = process.poll()
        detail = f"健康检查未通过（{healthy.detail}），进程退出码={code}"
        log_line(cfg, f"ERROR {detail}")
        if code is None:
            try:
                process.terminate()
            except OSError:
                pass
        return LaunchResult(
            ok=False, state=STATE_START_FAILED,
            message="工资核算服务启动失败，请查看诊断信息。",
            url=cfg.base_url, diagnostics=detail, log_tail=log_tail(cfg),
        )


def stop_service(cfg: LauncherConfig, killer=os.kill, waiter=time.sleep) -> tuple[bool, str]:
    """Stop only the process this launcher owns.  Never guesses."""
    record = read_pid_file(cfg)
    if not record:
        return False, "没有由本启动器启动的服务记录，已跳过停止操作。"

    pid = int(record.get("pid") or 0)
    if str(record.get("data_dir") or "") != str(cfg.data_dir):
        return False, "启动器记录的数据目录与当前不一致，为避免误杀已跳过。"

    status = probe(cfg.host, cfg.port, cfg.data_dir)
    if status.kind in {ProbeKind.FOREIGN, ProbeKind.OTHER_DATA}:
        return False, "端口上的服务不是本启动器管理的实例，已跳过停止操作。"
    if status.kind is ProbeKind.OURS and status.pid is not None and status.pid != pid:
        return False, "启动器记录与实际服务进程不一致，为避免误杀已跳过。"

    if not process_alive(pid):
        clear_pid_file(cfg)
        return True, "服务已经停止。"
    if not looks_like_payroll(pid):
        return False, "记录的进程身份不是工资核算服务，为避免误杀已跳过。"

    try:
        killer(pid, signal.SIGTERM)
    except OSError as exc:
        return False, f"无法结束工资服务进程：{exc}"

    deadline = time.monotonic() + TERMINATE_GRACE_SECONDS
    while time.monotonic() < deadline:
        if not process_alive(pid):
            clear_pid_file(cfg)
            log_line(cfg, f"stopped pid={pid}")
            return True, "工资服务已安全停止。"
        waiter(0.25)

    try:
        killer(pid, signal.SIGKILL)
    except OSError as exc:
        return False, f"工资服务未能停止：{exc}"
    clear_pid_file(cfg)
    log_line(cfg, f"killed pid={pid}")
    return True, "工资服务已安全停止。"


def restart_service(cfg: LauncherConfig, python_problem: str | None = None,
                    killer=os.kill, waiter=time.sleep) -> LaunchResult:
    """Safe restart followed by a normal open."""
    with LauncherLock(cfg):
        stopped, message = stop_service(cfg, killer=killer, waiter=waiter)
        log_line(cfg, f"restart stop -> {stopped} ({message})")
        if not stopped:
            current = probe(cfg.host, cfg.port, cfg.data_dir)
            if current.kind is ProbeKind.OURS:
                return LaunchResult(
                    ok=True, state=STATE_REUSED,
                    message="当前服务不是启动器启动的，没有结束它；已直接复用正在运行的服务。",
                    url=cfg.base_url, pid=current.pid,
                    diagnostics=message,
                )
            return LaunchResult(
                ok=False, state=STATE_PORT_TAKEN,
                message="无法重启：端口上的程序不是本启动器管理的工资服务，启动器不会结束其它程序。",
                url=cfg.base_url, diagnostics=message, log_tail=log_tail(cfg),
            )
    return ensure_running(cfg, python_problem=python_problem)


def status(cfg: LauncherConfig) -> dict:
    record = read_pid_file(cfg)
    current = probe(cfg.host, cfg.port, cfg.data_dir)
    owns = None
    if record and record.get("pid"):
        owns = {
            "recorded_pid": int(record["pid"]),
            "recorded_pid_alive": process_alive(int(record["pid"])),
            "recorded_pid_is_payroll": looks_like_payroll(int(record["pid"])),
        }
    return {
        "url": cfg.base_url,
        "host": cfg.host,
        "port": cfg.port,
        "data_dir": str(cfg.data_dir),
        "database": str(cfg.db_path),
        "database_exists": cfg.db_path.is_file(),
        "repo_root": str(cfg.repo_root),
        "python": str(cfg.python),
        "state_dir": str(cfg.state_dir),
        "diagnostics_log": str(cfg.log_file),
        "probe": {"kind": current.kind.value, "detail": current.detail, "health": current.payload},
        "launcher_record": owns,
    }
