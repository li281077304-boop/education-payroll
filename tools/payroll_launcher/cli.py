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
import sqlite3
import sys
from pathlib import Path

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
from .paths import LauncherConfig, LauncherConfigError, interpreter_problem, resolve_config
from .probe import ProbeKind, probe

MAX_ATTEMPTS = 3

MODE_OPEN = "open"
MODE_RESTART = "restart"


def _python_problem_if_needed(cfg: LauncherConfig) -> str | None:
    """Only pay for the interpreter check when a start is actually possible."""
    if probe(cfg.host, cfg.port, cfg.data_dir).kind is ProbeKind.OURS:
        return None
    try:
        return interpreter_problem(cfg.python, cfg.repo_root)
    except Exception as exc:  # pragma: no cover - defensive
        return f"无法验证 Python 环境：{exc}"


def _announce(cfg: LauncherConfig, result) -> None:
    log_line(cfg, f"{result.state}: {result.diagnostics or result.message}")
    print(result.message)


def run_open(cfg: LauncherConfig, no_open: bool = False, no_dialog: bool = False) -> int:
    attempt = 0
    while attempt < MAX_ATTEMPTS:
        attempt += 1
        result = ensure_running(cfg, python_problem=_python_problem_if_needed(cfg))
        if result.ok:
            _announce(cfg, result)
            if not no_open:
                open_url(result.url)
            return 0

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
                if not no_open:
                    open_url(restarted.url)
                return 0
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
        if not no_open:
            open_url(result.url)
        return 0
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = resolve_config(args.config)
    except LauncherConfigError as exc:
        message = f"工资核算助手启动失败，请查看诊断信息。\n\n{exc}"
        if args.no_dialog:
            print(message)
        else:
            choose_after_failure(message, allow_restart=False)
        return 1

    if args.data_dir or args.port:
        cfg = LauncherConfig(
            repo_root=cfg.repo_root,
            python=cfg.python,
            host=cfg.host,
            port=args.port or cfg.port,
            data_dir=args.data_dir or cfg.data_dir,
        )

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


if __name__ == "__main__":
    sys.exit(main())
