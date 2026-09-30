"""Command line surface of the launcher.

Two entry points are intentional:

* PRODUCTION LOCAL APP - the .app bundles call ``open`` (default) and
  ``restart``.  These keep the real data directory and the fixed port.
* DEVELOPMENT / UAT - ``python -m payroll_ui --port 0 --data-dir /tmp/...``
  remains available for tests and never goes through this module.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from . import lifecycle
from .dialogs import (
    DIAGNOSTICS,
    RESTART,
    RETRY,
    choose_after_failure,
    open_diagnostics,
    open_url,
    write_problem_report,
)
from .lifecycle import ensure_running, log_line, restart_service, status, stop_service
from .paths import (
    DEFAULT_PORT,
    HOST,
    SERVICE_FLAG,
    LauncherConfig,
    LauncherConfigError,
    interpreter_problem,
    resolve_config,
    with_overrides,
)
from .probe import ProbeKind, probe

MAX_ATTEMPTS = 3

MODE_OPEN = "open"
MODE_RESTART = "restart"
STATE_BROWSER_OPEN_FAILED = "browser-open-failed"


def _python_problem_if_needed(cfg: LauncherConfig) -> str | None:
    """Only pay for the interpreter check when a start is actually possible."""
    if probe(cfg.host, cfg.port, cfg.data_dir, expected_build_sha=cfg.build_sha,
             expected_build_dirty=cfg.build_dirty if cfg.build_sha else None).kind is ProbeKind.OURS:
        return None
    try:
        return interpreter_problem(cfg.python, cfg.repo_root)
    except Exception as exc:  # pragma: no cover - defensive
        return f"无法验证 Python 环境：{exc}"


def _announce(cfg: LauncherConfig, result) -> None:
    log_line(cfg, f"{result.state}: {result.diagnostics or result.message}")
    print(result.message)


def _open_page(cfg: LauncherConfig, url: str, *, no_open: bool, no_dialog: bool) -> bool:
    """Open the browser or leave a durable, actionable failure before returning."""
    if no_open:
        return True
    for _attempt in range(MAX_ATTEMPTS):
        if open_url(url):
            return True
        result = lifecycle.LaunchResult(
            ok=False,
            state=STATE_BROWSER_OPEN_FAILED,
            message="工资服务已经启动，但系统未能自动打开浏览器。请重试或查看诊断信息。",
            url=url,
            diagnostics="macOS open 命令未能打开本地工资页面。",
            log_tail=lifecycle.log_tail(cfg),
        )
        lifecycle.log_line(cfg, f"fail {result.state}: {result.diagnostics}")
        write_problem_report(cfg, result)
        if no_dialog:
            print(f"{result.message}\n诊断文件：{cfg.state_dir / 'last-problem.md'}")
            return False
        choice = choose_after_failure(result.message, allow_restart=False)
        if choice == DIAGNOSTICS:
            open_diagnostics(cfg)
            choice = choose_after_failure(
                "诊断信息已打开。如需再次打开工资页面，请点击“重试”。",
                allow_restart=False,
            )
        if choice != RETRY:
            return False
    return False


def run_open(cfg: LauncherConfig, no_open: bool = False, no_dialog: bool = False) -> int:
    attempt = 0
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        result = ensure_running(cfg, python_problem=_python_problem_if_needed(cfg))
        if result.ok:
            _announce(cfg, result)
            return 0 if _open_page(cfg, result.url, no_open=no_open, no_dialog=no_dialog) else 1

        write_problem_report(cfg, result)
        log_line(cfg, f"fail {result.state}: {result.diagnostics}")
        if no_dialog:
            print(f"{result.message}\n诊断文件：{cfg.state_dir / 'last-problem.md'}")
            return 1

        choice = choose_after_failure(result.message, allow_restart=result.can_restart)
        if choice == RETRY:
            continue
        if choice == RESTART:
            restarted = restart_service(cfg, python_problem=_python_problem_if_needed(cfg))
            if restarted.ok:
                _announce(cfg, restarted)
                return 0 if _open_page(
                    cfg, restarted.url, no_open=no_open, no_dialog=no_dialog
                ) else 1
            write_problem_report(cfg, restarted)
            log_line(cfg, f"restart fail {restarted.state}: {restarted.diagnostics}")
            if choose_after_failure(restarted.message, allow_restart=False) == DIAGNOSTICS:
                open_diagnostics(cfg)
            return 1
        if choice == DIAGNOSTICS:
            open_diagnostics(cfg)
            if choose_after_failure(
                "诊断信息已打开。如果问题已经解决，可以点击“重试”重新启动。",
                allow_restart=False,
            ) == RETRY:
                continue
            return 1
        return 1
    return 1


def run_restart(cfg: LauncherConfig, no_open: bool = False, no_dialog: bool = False) -> int:
    result = restart_service(cfg, python_problem=_python_problem_if_needed(cfg))
    if result.ok:
        _announce(cfg, result)
        return 0 if _open_page(cfg, result.url, no_open=no_open, no_dialog=no_dialog) else 1
    write_problem_report(cfg, result)
    log_line(cfg, f"restart-mode fail {result.state}: {result.diagnostics}")
    if no_dialog:
        print(f"{result.message}\n诊断文件：{cfg.state_dir / 'last-problem.md'}")
        return 1
    if choose_after_failure(result.message, allow_restart=False) == DIAGNOSTICS:
        open_diagnostics(cfg)
    return 1


def run_stop(cfg: LauncherConfig) -> int:
    stopped, message = stop_service(cfg)
    print(message)
    return 0 if stopped else 1


def run_status(cfg: LauncherConfig) -> int:
    payload = status(cfg)
    payload["python_problem"] = interpreter_problem(cfg.python, cfg.repo_root)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def inventory(cfg: LauncherConfig) -> dict:
    """Read the production database read-only.  Never creates or writes."""
    if not cfg.db_path.is_file():
        return {"database": str(cfg.db_path), "exists": False, "runs": []}
    uri = f"file:{cfg.db_path}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        counts = {}
        for table in tables:
            counts[table] = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        runs = []
        for run_id, created_at, payload in connection.execute(
                "SELECT id, created_at, payload FROM runs ORDER BY created_at"):
            period = ""
            try:
                period = str(json.loads(payload).get("period") or "")
            except (ValueError, TypeError):
                pass
            runs.append({"id": run_id, "created_at": created_at, "period": period})
    finally:
        connection.close()
    return {
        "database": str(cfg.db_path),
        "exists": True,
        "size_bytes": cfg.db_path.stat().st_size,
        "table_counts": counts,
        "run_count": len(runs),
        "runs": runs,
    }


def run_inventory(cfg: LauncherConfig) -> int:
    print(json.dumps(inventory(cfg), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="payroll_launcher",
        description="工资核算助手正式本地入口（服务生命周期与数据目录由本启动器固定）。",
    )
    parser.add_argument("--mode", choices=[MODE_OPEN, MODE_RESTART], default=MODE_OPEN,
                        help="open：打开（必要时启动）；restart：安全重启后打开")
    parser.add_argument("--config", type=Path, default=None, help="启动器配置文件路径")
    parser.add_argument("--data-dir", type=Path, default=None, help="覆盖正式数据目录（仅用于诊断）")
    parser.add_argument("--port", type=int, default=None, help="覆盖固定端口（仅用于诊断）")
    parser.add_argument("--status", action="store_true", help="打印服务与目录状态后退出")
    parser.add_argument("--inventory", action="store_true", help="只读列出正式数据目录中的历史 Run")
    parser.add_argument("--stop", action="store_true", help="安全停止启动器启动的服务")
    parser.add_argument("--diagnostics", action="store_true", help="打开诊断信息")
    parser.add_argument("--print-config", action="store_true", help="打印解析后的配置")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--no-dialog", action="store_true", help="不弹窗，失败信息打印到标准输出")
    parser.add_argument(SERVICE_FLAG, action="store_true",
                        help=argparse.SUPPRESS)  # 内部：把本进程当作工资服务运行
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.service:
        # Internal: the launcher re-enters its own executable to serve the UI.
        from . import service_mode

        return service_mode.run_service(
            args.data_dir or paths.default_data_dir(),
            args.port if args.port is not None else DEFAULT_PORT,
        )
    try:
        cfg = resolve_config(args.config)
    except LauncherConfigError as exc:
        message = f"工资核算助手启动失败，请查看诊断信息。\n\n{exc}"
        if paths.is_frozen():
            fallback = LauncherConfig(
                repo_root=paths.program_root(),
                python=Path(sys.executable),
                host=HOST,
                port=DEFAULT_PORT,
                data_dir=args.data_dir or paths.default_data_dir(),
                frozen=True,
            )
        else:
            fallback = LauncherConfig(
                repo_root=Path(os.environ.get(paths.ENV_REPO_ROOT, Path.cwd())),
                python=Path(os.environ.get(paths.ENV_PYTHON, sys.executable)),
                host=HOST,
                port=DEFAULT_PORT,
                data_dir=args.data_dir or paths.default_data_dir(),
            )
        failure = lifecycle.LaunchResult(
            ok=False, state="config-invalid", message=message, url=fallback.base_url,
            diagnostics=str(exc), log_tail=lifecycle.log_tail(fallback),
        )
        try:
            write_problem_report(fallback, failure)
            lifecycle.log_line(fallback, f"fail {failure.state}: {exc}")
        except OSError:
            pass
        if args.no_dialog:
            print(f"{message}\n诊断文件：{fallback.state_dir / 'last-problem.md'}")
        else:
            choose_after_failure(message, allow_restart=False)
        return 1

    if args.data_dir or args.port:
        cfg = with_overrides(cfg, data_dir=args.data_dir, port=args.port)

    try:
        if args.print_config:
            print(json.dumps({
                "repo_root": str(cfg.repo_root), "python": str(cfg.python),
                "host": cfg.host, "port": cfg.port, "data_dir": str(cfg.data_dir),
                "state_dir": str(cfg.state_dir),
            }, ensure_ascii=False, indent=2))
            return 0
        if args.status:
            return run_status(cfg)
        if args.inventory:
            return run_inventory(cfg)
        if args.stop:
            return run_stop(cfg)
        if args.diagnostics:
            open_diagnostics(cfg)
            return 0
        if args.mode == MODE_RESTART:
            return run_restart(cfg, no_open=args.no_open, no_dialog=args.no_dialog)
        return run_open(cfg, no_open=args.no_open, no_dialog=args.no_dialog)
    except Exception as exc:  # Finder has no terminal; turn unexpected errors into a durable UI failure.
        message = "工资助手启动过程中遇到问题，请查看诊断信息后重试。"
        failure = lifecycle.LaunchResult(
            ok=False, state="unexpected-launch-error", message=message,
            url=cfg.base_url, diagnostics=f"{type(exc).__name__}: {exc}",
            log_tail=lifecycle.log_tail(cfg),
        )
        try:
            write_problem_report(cfg, failure)
            lifecycle.log_line(cfg, f"fail {failure.state}: {failure.diagnostics}")
        except OSError:
            pass
        if args.no_dialog:
            print(f"{message}\n诊断文件：{cfg.state_dir / 'last-problem.md'}")
        else:
            choose_after_failure(message, allow_restart=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
