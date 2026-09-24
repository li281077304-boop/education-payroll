"""Regression coverage for the production local entry point.

These tests never signal a real process: ``stop_service`` and
``restart_service`` receive an injected killer, so the assertions describe
exactly which pid the launcher would act on.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

from payroll_launcher import cli, dialogs, lifecycle, paths
from payroll_launcher.lifecycle import (
    STATE_OTHER_DATA,
    STATE_PORT_TAKEN,
    STATE_REUSED,
    STATE_STARTED,
    ensure_running,
    read_pid_file,
    restart_service,
    stop_service,
    write_pid_file,
)
from payroll_launcher.paths import DEFAULT_PORT, HOST, LauncherConfig, resolve_config
from payroll_launcher.probe import ProbeKind, probe
from payroll_ui.health import HEALTH_CONTRACT, HEALTH_PATH, data_dir_fingerprint
from payroll_ui.server import PayrollHttpServer
from payroll_ui.service import PayrollService

REPO_ROOT = Path(__file__).parents[1]
STATIC = REPO_ROOT / "payroll_ui" / "static"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def launch_config(tmp_path: Path, port: int, data_dir: Path | None = None) -> LauncherConfig:
    return LauncherConfig(
        repo_root=REPO_ROOT,
        python=Path(sys.executable),
        host=HOST,
        port=port,
        data_dir=data_dir or (tmp_path / "app-data"),
    )


class _ServerFixture:
    """Run the real Payroll HTTP server on an ephemeral loopback port."""

    def __init__(self, data_dir: Path):
        self.service = PayrollService(data_dir)
        self.server = PayrollHttpServer(("127.0.0.1", 0), self.service, STATIC)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_ServerFixture":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def port(self) -> int:
        return int(self.server.server_port)


class _FakeHandler(BaseHTTPRequestHandler):
    payload = b'{"hello":"world"}'
    status = 200

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(self.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.payload)))
        self.end_headers()
        self.wfile.write(self.payload)

    def log_message(self, *_args: object) -> None:
        return


class _FakeServer:
    def __init__(self, payload: bytes = b'{"hello":"world"}', status: int = 200):
        handler = type("_Handler", (_FakeHandler,), {"payload": payload, "status": status})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "_FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])


# --------------------------------------------------------------------------- health


def test_health_endpoint_identifies_service_without_token_and_without_business_data(tmp_path):
    data_dir = tmp_path / "app-data"
    with _ServerFixture(data_dir) as fixture:
        body = json.loads(urlopen(f"http://127.0.0.1:{fixture.port}{HEALTH_PATH}", timeout=5).read())

    assert body["contract"] == HEALTH_CONTRACT
    assert body["app"] == "education-payroll"
    assert body["service"] == "payroll-ui"
    assert body["port"] == fixture.port
    assert body["data_dir_fingerprint"] == data_dir_fingerprint(data_dir)
    assert body["run_count"] == 0

    # The handshake must stay free of anything resembling payroll content.
    assert set(body) == {
        "contract", "app", "service", "pid", "port",
        "data_dir_fingerprint", "started_at", "run_count",
    }


def test_health_endpoint_reports_existing_runs_without_leaking_details(tmp_path):
    data_dir = tmp_path / "app-data"
    service = PayrollService(data_dir)
    service.store.save({"id": "run-1", "created_at": "2026-09-01T00:00:00+00:00", "period": "2026-08"})
    raw = json.dumps(service.store.get("run-1")).encode("utf-8")

    with _ServerFixture(data_dir) as fixture:
        body = json.loads(urlopen(f"http://127.0.0.1:{fixture.port}{HEALTH_PATH}", timeout=5).read())

    assert body["run_count"] == 1
    assert b"run-1" not in json.dumps(body).encode("utf-8")
    assert raw != b""


# --------------------------------------------------------------------------- probe


def test_probe_detects_absent_port(tmp_path):
    result = probe(HOST, free_port(), tmp_path / "app-data", timeout=0.4)
    assert result.kind is ProbeKind.ABSENT


def test_probe_recognises_our_service_on_our_data_dir(tmp_path):
    data_dir = tmp_path / "app-data"
    with _ServerFixture(data_dir) as fixture:
        result = probe(HOST, fixture.port, data_dir, timeout=2.0)
    assert result.kind is ProbeKind.OURS
    assert result.pid
    assert result.payload["data_dir_fingerprint"] == data_dir_fingerprint(data_dir)


def test_probe_flags_our_service_when_it_uses_another_data_dir(tmp_path):
    with _ServerFixture(tmp_path / "real") as fixture:
        result = probe(HOST, fixture.port, tmp_path / "other", timeout=2.0)
    assert result.kind is ProbeKind.OTHER_DATA


def test_probe_flags_foreign_json_and_plain_http(tmp_path):
    with _FakeServer(b'{"contract":"someone-else"}') as fake:
        assert probe(HOST, fake.port, tmp_path / "app-data", timeout=2.0).kind is ProbeKind.FOREIGN
    with _FakeServer(b"not json at all", status=200) as fake:
        assert probe(HOST, fake.port, tmp_path / "app-data", timeout=2.0).kind is ProbeKind.FOREIGN


# --------------------------------------------------------------------------- config


def test_config_pins_fixed_port_and_application_support_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.ENV_CONFIG, raising=False)
    monkeypatch.setenv(paths.ENV_REPO_ROOT, str(REPO_ROOT))
    monkeypatch.setenv(paths.ENV_PYTHON, sys.executable)
    cfg = resolve_config()

    assert cfg.port == DEFAULT_PORT
    assert cfg.data_dir == Path.home() / "Library" / "Application Support" / "EducationPayroll"
    assert cfg.db_path.name == "payroll-ui.sqlite3"
    assert cfg.state_dir.parent == cfg.data_dir
    assert "/tmp" not in str(cfg.data_dir)
    assert cfg.base_url == f"http://127.0.0.1:{DEFAULT_PORT}/"


def test_config_reads_an_explicit_file_and_rejects_a_missing_checkout(tmp_path):
    config_file = tmp_path / "launcher.json"
    config_file.write_text(json.dumps({
        "repo_root": str(REPO_ROOT), "python": sys.executable,
        "data_dir": str(tmp_path / "pinned-data"), "port": 8799,
    }), encoding="utf-8")
    cfg = resolve_config(config_file)
    assert cfg.port == 8799
    assert cfg.data_dir == tmp_path / "pinned-data"

    broken = tmp_path / "broken.json"
    broken.write_text(json.dumps({"repo_root": str(tmp_path / "nowhere")}), encoding="utf-8")
    with pytest.raises(paths.LauncherConfigError):
        resolve_config(broken)


# --------------------------------------------------------------------------- pid record


def test_pid_record_round_trip_and_clear(tmp_path):
    cfg = launch_config(tmp_path, 8760)
    write_pid_file(cfg, os.getpid(), {"health": {"app": "education-payroll"}})
    record = read_pid_file(cfg)
    assert record["pid"] == os.getpid()
    assert record["data_dir"] == str(cfg.data_dir)
    assert record["launcher_contract"] == "payroll-launcher/1"
    lifecycle.clear_pid_file(cfg)
    assert read_pid_file(cfg) is None


# --------------------------------------------------------------------------- reuse / port safety


def test_ensure_running_reuses_a_healthy_service_without_starting_another(monkeypatch, tmp_path):
    data_dir = tmp_path / "app-data"
    with _ServerFixture(data_dir) as fixture:
        cfg = launch_config(tmp_path, fixture.port, data_dir)
        calls: list[int] = []
        monkeypatch.setattr(lifecycle, "start_process", lambda _cfg: calls.append(1))
        result = ensure_running(cfg)

    assert result.ok and result.state == STATE_REUSED
    assert calls == []
    assert result.pid


def test_ensure_running_refuses_a_foreign_process_and_never_kills_it(monkeypatch, tmp_path):
    with _FakeServer(b'{"contract":"someone-else"}') as fake:
        cfg = launch_config(tmp_path, fake.port)
        started: list[int] = []
        monkeypatch.setattr(lifecycle, "start_process", lambda _cfg: started.append(1))
        result = ensure_running(cfg)

    assert not result.ok and result.state == STATE_PORT_TAKEN
    assert started == []
    assert str(fake.port) in result.message


def test_ensure_running_refuses_a_service_bound_to_another_data_dir(monkeypatch, tmp_path):
    with _ServerFixture(tmp_path / "elsewhere") as fixture:
        cfg = launch_config(tmp_path, fixture.port, tmp_path / "app-data")
        monkeypatch.setattr(lifecycle, "start_process", lambda _cfg: pytest.fail("不得启动第二个实例"))
        result = ensure_running(cfg)

    assert not result.ok and result.state == STATE_OTHER_DATA


def test_ensure_running_reports_an_unusable_python_without_starting(monkeypatch, tmp_path):
    cfg = launch_config(tmp_path, free_port())
    monkeypatch.setattr(lifecycle, "start_process", lambda _cfg: pytest.fail("不应在环境不可用时启动"))
    result = ensure_running(cfg, python_problem="Python 无法载入工资核算程序。")

    assert not result.ok and result.state == lifecycle.STATE_PYTHON_INVALID
    assert result.can_retry


# --------------------------------------------------------------------------- safe restart


def test_stop_service_sends_terminate_to_the_recorded_pid_only(monkeypatch, tmp_path):
    data_dir = tmp_path / "app-data"
    cfg = launch_config(tmp_path, free_port(), data_dir)
    write_pid_file(cfg, 4242)
    signals: list[tuple[int, int]] = []
    alive = {"value": True}

    def killer(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        alive["value"] = False

    monkeypatch.setattr(lifecycle, "probe", lambda *_a, **_k: lifecycle.ProbeResult(ProbeKind.ABSENT, "hung"))
    monkeypatch.setattr(lifecycle, "process_alive", lambda _pid: alive["value"])
    monkeypatch.setattr(lifecycle, "looks_like_payroll", lambda pid: pid == 4242)

    stopped, message = stop_service(cfg, killer=killer, waiter=lambda _s: None)

    assert stopped
    assert signals == [(4242, lifecycle.signal.SIGTERM)]
    assert read_pid_file(cfg) is None
    assert "已安全停止" in message


def test_stop_service_refuses_a_recycled_or_unrelated_pid(monkeypatch, tmp_path):
    cfg = launch_config(tmp_path, free_port())
    write_pid_file(cfg, 5150)
    signals: list[tuple[int, int]] = []

    monkeypatch.setattr(lifecycle, "probe", lambda *_a, **_k: lifecycle.ProbeResult(ProbeKind.ABSENT))
    monkeypatch.setattr(lifecycle, "process_alive", lambda _pid: True)
    monkeypatch.setattr(lifecycle, "looks_like_payroll", lambda _pid: False)

    stopped, message = stop_service(cfg, killer=lambda pid, sig: signals.append((pid, sig)),
                                   waiter=lambda _s: None)

    assert not stopped
    assert signals == []
    assert "误杀" in message


def test_stop_service_skips_when_health_pid_disagrees_with_the_record(monkeypatch, tmp_path):
    cfg = launch_config(tmp_path, free_port())
    write_pid_file(cfg, 6001)
    signals: list[tuple[int, int]] = []

    monkeypatch.setattr(lifecycle, "probe", lambda *_a, **_k: lifecycle.ProbeResult(
        ProbeKind.OURS, "other process", {"pid": 6002}))
    monkeypatch.setattr(lifecycle, "process_alive", lambda _pid: True)
    monkeypatch.setattr(lifecycle, "looks_like_payroll", lambda _pid: True)

    stopped, message = stop_service(cfg, killer=lambda pid, sig: signals.append((pid, sig)),
                                   waiter=lambda _s: None)

    assert not stopped
    assert signals == []
    assert "不一致" in message


def test_stop_service_does_nothing_without_our_own_record(monkeypatch, tmp_path):
    cfg = launch_config(tmp_path, free_port())
    monkeypatch.setattr(lifecycle, "process_alive", lambda _pid: True)
    stopped, message = stop_service(cfg, killer=lambda *_a: pytest.fail("不得结束无记录的进程"))
    assert not stopped
    assert "没有由本启动器启动的服务记录" in message


def test_restart_refuses_a_foreign_port_and_still_does_not_open(monkeypatch, tmp_path):
    with _FakeServer(b'{"contract":"someone-else"}') as fake:
        cfg = launch_config(tmp_path, fake.port)
        monkeypatch.setattr(lifecycle, "start_process", lambda _cfg: pytest.fail("不得在外部占用时启动"))
        result = restart_service(cfg, killer=lambda *_a: pytest.fail("不得结束无关进程"))

    assert not result.ok and result.state == STATE_PORT_TAKEN


def test_restart_reuses_a_service_it_did_not_start(tmp_path):
    data_dir = tmp_path / "app-data"
    with _ServerFixture(data_dir) as fixture:
        cfg = launch_config(tmp_path, fixture.port, data_dir)
        result = restart_service(cfg, killer=lambda *_a: pytest.fail("不得结束非启动器实例"))

    assert result.ok and result.state == STATE_REUSED
    assert "没有结束它" in result.message


# --------------------------------------------------------------------------- error experience


def test_problem_report_is_plain_chinese_and_free_of_payroll_values(tmp_path):
    cfg = launch_config(tmp_path, 8760)
    result = lifecycle.LaunchResult(
        ok=False, state=STATE_PORT_TAKEN,
        message="端口 8760 已被其它程序占用，启动器不会结束其它程序。",
        url=cfg.base_url, diagnostics="端口返回非工资服务响应", log_tail=["probe -> foreign"],
    )
    path = dialogs.write_problem_report(cfg, result)
    text = path.read_text(encoding="utf-8")

    assert str(cfg.data_dir) in text
    assert str(cfg.db_path) in text
    assert "端口 8760 已被其它程序占用" in text
    assert "Traceback" not in text
    # A diagnosis report must never become a second copy of payroll content.
    assert "¥" not in text
    assert "教师姓名" not in text
    assert "学生" not in text
    assert "端口被占用" in text or "重试" in text


def test_failure_dialog_offers_retry_and_diagnostics(monkeypatch, tmp_path):
    captured: dict[str, str] = {}

    class _Completed:
        returncode = 0
        stdout = "button returned:查看诊断"
        stderr = ""

    def fake_run(argv, **_kwargs):
        captured["script"] = argv[-1]
        return _Completed()

    monkeypatch.setattr(dialogs.subprocess, "run", fake_run)
    monkeypatch.setattr(dialogs, "_has_osascript", lambda: True)

    assert dialogs.choose_after_failure("启动失败", allow_restart=True) == dialogs.DIAGNOSTICS
    assert "重试" in captured["script"]
    assert "重新启动" in captured["script"]
    assert "查看诊断" in captured["script"]


# --------------------------------------------------------------------------- cli wiring


def test_cli_open_reuses_service_and_opens_browser_without_dialog(monkeypatch, tmp_path, capsys):
    data_dir = tmp_path / "app-data"
    opened: list[str] = []
    with _ServerFixture(data_dir) as fixture:
        config_file = tmp_path / "launcher.json"
        config_file.write_text(json.dumps({
            "repo_root": str(REPO_ROOT), "python": sys.executable,
            "data_dir": str(data_dir), "port": fixture.port,
        }), encoding="utf-8")
        monkeypatch.setattr(cli, "open_url", lambda url: opened.append(url))
        code = cli.main(["--config", str(config_file), "--no-dialog"])

    assert code == 0
    assert opened == [f"http://127.0.0.1:{fixture.port}/"]
    assert "已在运行" in capsys.readouterr().out


def test_cli_inventory_reads_production_database_read_only(tmp_path, monkeypatch):
    data_dir = tmp_path / "app-data"
    service = PayrollService(data_dir)
    service.store.save({"id": "run-aug", "created_at": "2026-09-17T06:24:37+00:00", "period": "2026-08"})
    cfg = launch_config(tmp_path, 8760, data_dir)

    snapshot = cli.inventory(cfg)
    assert snapshot["exists"] is True
    assert snapshot["run_count"] == 1
    assert snapshot["runs"][0]["period"] == "2026-08"

    # Read-only mode must not create anything when the database is missing.
    missing = cli.inventory(launch_config(tmp_path, 8760, tmp_path / "empty"))
    assert missing["exists"] is False
    assert not (tmp_path / "empty" / "payroll-ui.sqlite3").exists()


def test_cli_status_exposes_paths_and_probe_kind(tmp_path, monkeypatch):
    cfg = launch_config(tmp_path, free_port())
    payload = lifecycle.status(cfg)
    assert payload["probe"]["kind"] == ProbeKind.ABSENT.value
    assert payload["database"].endswith("payroll-ui.sqlite3")
    assert payload["launcher_record"] is None


# --------------------------------------------------------------------------- bundle builder


def test_build_app_script_produces_both_production_entry_points(tmp_path):
    output_dir = tmp_path / "dist"
    completed = subprocess.run(
        ["sh", str(REPO_ROOT / "macos" / "build_app.sh"), str(output_dir)],
        capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stderr

    for name, mode in (("工资核算助手", "open"), ("重启工资服务", "restart")):
        bundle = output_dir / f"{name}.app"
        shim = bundle / "Contents" / "MacOS" / "launcher"
        plist = (bundle / "Contents" / "Info.plist").read_text(encoding="utf-8")
        assert shim.is_file() and os.access(shim, os.X_OK)
        assert f"--mode {mode}" in shim.read_text(encoding="utf-8")
        assert "<key>LSUIElement</key>" in plist
        assert "<string>launcher</string>" in plist
        assert name in plist
        assert (bundle / "Contents" / "Resources" / "launcher.json").is_file()

    shim_text = (output_dir / "工资核算助手.app" / "Contents" / "MacOS" / "launcher").read_text(encoding="utf-8")
    assert str(REPO_ROOT) in shim_text, "启动器必须固化程序绝对路径"
    assert "$(pwd)" not in shim_text, "启动器不得依赖调用时的 shell cwd"
    assert "/tmp" not in shim_text


def test_app_transport_does_not_require_a_terminal_or_random_port():
    script = (REPO_ROOT / "macos" / "build_app.sh").read_text(encoding="utf-8")
    # The launcher is plain shell + Python + the user's browser: no framework
    # runtime and no package manager is invoked to build or run it.
    for forbidden in ("npx", "npm ", "yarn ", "cargo ", "tauri "):
        assert forbidden not in script, forbidden
    assert "--port 0" not in script
    # Development/UAT keeps working through the unchanged module entry point.
    main = (REPO_ROOT / "payroll_ui" / "__main__.py").read_text(encoding="utf-8")
    assert 'default=0' in main
    assert "default_data_dir()" in main
