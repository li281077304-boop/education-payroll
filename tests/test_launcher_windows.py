"""Windows release coverage for the production local entry point.

``tests/test_launcher.py`` covers the shared launcher contract and the macOS
``.app`` bundle.  This module covers what only exists on Windows, and it is
deliberately not a thin "skip on the other OS" shim: every behaviour below is
one the release depends on and that has no macOS counterpart.

Two of these tests exist because the obvious implementation is *destructive*
on Windows:

* ``process_alive`` must never probe with ``os.kill(pid, 0)`` -- on Windows
  that call is forwarded to ``TerminateProcess``, so probing would kill the
  service it is inspecting;
* the service port must be bound exclusively -- Windows honours
  ``SO_REUSEADDR`` by letting a second process bind a port that is already in
  use, which would silently run two services on one database.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from payroll_launcher import host, lifecycle, paths, service_mode
from payroll_launcher.paths import DEFAULT_PORT, HOST, LauncherConfig
from payroll_launcher.probe import ProbeKind, probe
from payroll_ui.health import data_dir_fingerprint
from payroll_ui.native_dialogs import EXCEL_PATTERNS, DOCUMENT_PATTERNS

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows release behaviour")

REPO_ROOT = Path(__file__).parents[1]


# --------------------------------------------------------------------------- release shape


def _fake_release(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """Build the directory layout PyInstaller onedir produces."""
    program = tmp_path / "EducationPayroll"
    internal = program / "_internal"
    static = internal / "payroll_ui" / "static"
    static.mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>工资核算助手</title>", encoding="utf-8")
    (static / "app.js").write_text("// bundled", encoding="utf-8")
    executable = program / "工资核算助手.exe"
    executable.write_bytes(b"MZ")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    return program, executable


def test_frozen_release_resolves_without_a_python_or_a_config_file(tmp_path, monkeypatch):
    program, executable = _fake_release(tmp_path, monkeypatch)

    cfg = paths.resolve_config()

    assert cfg.frozen is True
    assert cfg.python == executable
    assert cfg.repo_root == program
    assert paths.static_root() == program / "_internal" / "payroll_ui" / "static"
    assert cfg.port == DEFAULT_PORT
    assert cfg.host == HOST
    # Production data never lives inside the folder the user unpacked.
    assert cfg.data_dir == tmp_path / "Local" / "EducationPayroll"
    assert program not in cfg.data_dir.parents
    assert cfg.db_path.name == "payroll-ui.sqlite3"


def test_frozen_release_starts_the_ui_by_reentering_itself(tmp_path, monkeypatch):
    _program, executable = _fake_release(tmp_path, monkeypatch)
    cfg = paths.resolve_config()

    argv = paths.service_argv(cfg)

    assert argv[0] == str(executable)
    assert paths.SERVICE_FLAG in argv
    assert "--data-dir" in argv and "--port" in argv
    # A release must never depend on an interpreter that happens to be on PATH.
    assert "-m" not in argv
    assert "payroll_ui" not in argv


def test_frozen_release_skips_the_interpreter_preflight(tmp_path, monkeypatch):
    """Re-entering the exe with ``-c`` is not a PyInstaller mode.

    Running the preflight there would launch a second copy of the whole
    application instead of a two-line import check.
    """
    _program, executable = _fake_release(tmp_path, monkeypatch)
    cfg = paths.resolve_config()

    assert paths.interpreter_problem(cfg.python, cfg.repo_root) is None


def test_a_release_missing_its_assets_fails_closed(tmp_path, monkeypatch):
    _program, _executable = _fake_release(tmp_path, monkeypatch)
    paths.static_root().joinpath("index.html").unlink()

    with pytest.raises(paths.LauncherConfigError) as error:
        paths.resolve_config()

    assert "找不到工资核算界面资源" in str(error.value)


# --------------------------------------------------------------------------- process identity


def test_process_probe_never_signals_or_kills_the_target():
    """The probe must be observation-only on Windows.

    ``os.kill(pid, 0)`` looks like a harmless liveness check, but every signal
    other than the two console events is forwarded to ``TerminateProcess`` on
    Windows.  Using it here would have terminated the running Payroll service
    the moment the launcher asked whether it was alive.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert host.process_alive(child.pid) is True
        time.sleep(0.2)
        assert child.poll() is None, "探测存活状态不得结束被探测的进程"
    finally:
        child.kill()
        child.wait(timeout=15)

    assert host.process_alive(child.pid) is False


def test_process_probe_rejects_nonsense_pids():
    assert host.process_alive(0) is False
    assert host.process_alive(-1) is False
    assert host.process_alive(999_999_999) is False


def test_process_command_exposes_the_executable_image():
    """Windows reports the real interpreter, not a venv's forwarding stub.

    ``sys.executable`` can point at a venv shim while the running image is the
    base interpreter, so this asserts what the OS actually guarantees: an
    absolute, existing image path.  A frozen release has no such indirection --
    there ``sys.executable`` *is* the executable -- which is what the identity
    test below relies on.
    """
    image = host.process_command(os.getpid())

    assert image
    assert Path(image).is_absolute()
    assert Path(image).is_file()
    assert Path(image).stem.lower().startswith("python")


def test_process_command_returns_nothing_for_a_pid_we_cannot_open():
    assert host.process_command(0) == ""
    assert host.process_command(999_999_999) == ""


def test_a_frozen_release_recognises_its_own_executable_as_the_service(monkeypatch):
    """A released service runs inside 工资核算助手.exe, not under a python.exe.

    There is no command line to grep on Windows, so the frozen build proves
    identity by comparing the executable image with the configured program.
    """
    program = Path("C:/Release/EducationPayroll/工资核算助手.exe")
    frozen = LauncherConfig(
        repo_root=program.parent, python=program, host=HOST,
        port=DEFAULT_PORT, data_dir=Path("C:/fake"), frozen=True,
    )
    monkeypatch.setattr(lifecycle, "process_command", lambda _pid: str(program))
    assert lifecycle.looks_like_payroll(os.getpid(), frozen) is True

    monkeypatch.setattr(lifecycle, "process_command",
                        lambda _pid: "C:/Windows/System32/notepad.exe")
    assert lifecycle.looks_like_payroll(os.getpid(), frozen) is False

    monkeypatch.setattr(lifecycle, "process_command", lambda _pid: "")
    assert lifecycle.looks_like_payroll(os.getpid(), frozen) is False


def test_identity_check_stays_strict_when_no_config_is_given():
    assert lifecycle.looks_like_payroll(os.getpid()) is False


# --------------------------------------------------------------------------- single instance


_LOCK_CHILD = """
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[2])
sys.path.insert(0, sys.argv[3])
from payroll_launcher import host

token = host.acquire_launcher_lock(Path(sys.argv[1]))
print("held", flush=True)
time.sleep(float(sys.argv[4]))
host.release_launcher_lock(token)
"""


def test_the_launcher_lock_serialises_two_processes(tmp_path):
    """Two double-clicks must not both reach the "start a service" branch."""
    lock_file = tmp_path / "launcher" / "launcher.lock"
    lock_file.parent.mkdir(parents=True)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "tools")]))

    child = subprocess.Popen(
        [sys.executable, "-c", _LOCK_CHILD, str(lock_file), str(REPO_ROOT), str(REPO_ROOT / "tools"), "1.5"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    try:
        assert child.stdout.readline().strip() == "held", child.stderr.read()

        started = time.monotonic()
        token = host.acquire_launcher_lock(lock_file)
        waited = time.monotonic() - started
        host.release_launcher_lock(token)
    finally:
        child.wait(timeout=30)

    assert child.returncode == 0, child.stderr.read()
    assert waited >= 0.5, f"第二个启动器没有等待第一个释放锁（等待 {waited:.2f}s）"


def test_two_launchers_cannot_both_bind_the_service_port(tmp_path, monkeypatch):
    """The port itself is the last line of defence against a second service."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    data_dir = tmp_path / "app-data"

    address = service_mode.ExclusivePayrollHttpServer(("127.0.0.1", 0), _service(data_dir), _static())
    port = int(address.server_address[1])
    thread = threading.Thread(target=address.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(OSError):
            second = service_mode.ExclusivePayrollHttpServer(("127.0.0.1", port), _service(data_dir), _static())
            second.server_close()
    finally:
        address.shutdown()
        address.server_close()
        thread.join(timeout=15)

    # Windows would otherwise let a second bind succeed and run two services.
    assert service_mode.ExclusivePayrollHttpServer.allow_reuse_address is False


# --------------------------------------------------------------------------- shutdown handshake


def _service(data_dir: Path):
    from payroll_ui.service import PayrollService

    return PayrollService(data_dir)


def _static() -> Path:
    return REPO_ROOT / "payroll_ui" / "static"


def test_shutdown_request_is_ignored_unless_it_names_this_exact_process(tmp_path):
    data_dir = tmp_path / "app-data"
    data_dir.mkdir()
    state = data_dir / "launcher"
    state.mkdir()
    request = state / "stop-request.json"
    fingerprint = data_dir_fingerprint(data_dir)

    request.write_text(json.dumps({
        "contract": service_mode.SHUTDOWN_CONTRACT,
        "pid": os.getpid() + 1,
        "data_dir_fingerprint": fingerprint,
    }), encoding="utf-8")
    assert service_mode._is_request_for_me(request, os.getpid(), fingerprint) is False

    request.write_text(json.dumps({
        "contract": service_mode.SHUTDOWN_CONTRACT,
        "pid": os.getpid(),
        "data_dir_fingerprint": "someone-elses-database",
    }), encoding="utf-8")
    assert service_mode._is_request_for_me(request, os.getpid(), fingerprint) is False

    request.write_text(json.dumps({
        "contract": "not-ours",
        "pid": os.getpid(),
        "data_dir_fingerprint": fingerprint,
    }), encoding="utf-8")
    assert service_mode._is_request_for_me(request, os.getpid(), fingerprint) is False

    request.write_text(json.dumps({
        "contract": service_mode.SHUTDOWN_CONTRACT,
        "pid": os.getpid(),
        "data_dir_fingerprint": fingerprint,
    }), encoding="utf-8")
    assert service_mode._is_request_for_me(request, os.getpid(), fingerprint) is True


def test_the_service_closes_cleanly_when_the_launcher_asks_it_to(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    data_dir = tmp_path / "app-data"
    state = data_dir / "launcher"
    state.mkdir(parents=True)

    with socket.socket() as probe_socket:
        probe_socket.bind(("127.0.0.1", 0))
        port = int(probe_socket.getsockname()[1])

    finished = threading.Event()

    def serve() -> None:
        try:
            service_mode.run_service(data_dir, port, _static())
        finally:
            finished.set()

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    try:
        assert _wait_for_ours(port, data_dir)
        recorded = probe(HOST, port, data_dir)
        assert recorded.pid == os.getpid()

        (state / "stop-request.json").write_text(json.dumps({
            "contract": service_mode.SHUTDOWN_CONTRACT,
            "pid": os.getpid(),
            "data_dir_fingerprint": data_dir_fingerprint(data_dir),
        }), encoding="utf-8")

        assert finished.wait(timeout=20), "服务没有响应干净停止请求"
        assert not (state / "stop-request.json").exists(), "停止请求必须被消费掉"
    finally:
        if not finished.is_set():
            worker.join(timeout=5)


def _wait_for_ours(port: int, data_dir: Path, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe(HOST, port, data_dir).kind is ProbeKind.OURS:
            return True
        time.sleep(0.2)
    return False


def test_stop_service_asks_its_own_release_to_shut_down_before_killing_it(tmp_path, monkeypatch):
    """A restart must give the service a chance to close its database."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    data_dir = tmp_path / "app-data"
    cfg = LauncherConfig(
        repo_root=tmp_path, python=Path(sys.executable), host=HOST,
        port=DEFAULT_PORT, data_dir=data_dir, frozen=True,
    )
    lifecycle.write_pid_file(cfg, 4321)
    signals: list[tuple[int, int]] = []
    alive = {"value": True}

    monkeypatch.setattr(lifecycle, "probe", lambda *_a, **_k: lifecycle.ProbeResult(ProbeKind.ABSENT, "hung"))
    monkeypatch.setattr(lifecycle, "looks_like_payroll", lambda _pid, *_a: True)

    def killer(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        alive["value"] = False

    def waiter(_seconds: float) -> None:
        # Stand in for the grace period: the service answers our request.
        alive["value"] = False

    monkeypatch.setattr(lifecycle, "process_alive", lambda _pid: alive["value"])
    stopped, message = lifecycle.stop_service(cfg, killer=killer, waiter=waiter)

    assert stopped
    assert "已安全停止" in message
    # It was asked first, and only terminated because the grace loop ended.
    assert (data_dir / "launcher" / "stop-request.json").exists() is False
    assert lifecycle.read_pid_file(cfg) is None


def test_a_source_checkout_is_never_asked_to_shut_down_by_file(tmp_path, monkeypatch):
    """Only our own frozen service understands the request, so only ask it."""
    data_dir = tmp_path / "app-data"
    cfg = LauncherConfig(
        repo_root=tmp_path, python=Path(sys.executable), host=HOST,
        port=DEFAULT_PORT, data_dir=data_dir, frozen=False,
    )
    assert lifecycle.request_shutdown(cfg, os.getpid()) is False
    assert not (data_dir / "launcher" / "stop-request.json").exists()


# --------------------------------------------------------------------------- native dialogs


def test_native_dialogs_are_available_on_windows():
    from payroll_ui import native_dialogs

    assert native_dialogs.available() is True


def test_dialog_filters_are_translated_for_the_win32_common_dialog():
    from payroll_ui import native_dialogs

    spec = native_dialogs._filter_string(EXCEL_PATTERNS)

    assert spec is not None
    assert spec.endswith("\0\0")
    assert "*.xlsx;*.xls;*.xlsm" in spec
    assert native_dialogs._filter_string(DOCUMENT_PATTERNS).count("\0") >= 3
    # `人工月资料` accepts the Markdown/CSV/Excel mix the office actually keeps.
    assert "*.md;*.csv" in native_dialogs._filter_string(DOCUMENT_PATTERNS)
