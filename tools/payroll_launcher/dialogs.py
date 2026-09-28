"""Human-facing failure handling for the launcher.

A normal user must never see a Python traceback or a bare crash.  Every failure
path ends in a Chinese dialog with an actionable choice, and the technical
detail is written to a local report that the user can open on demand.

The dialog itself is the one genuinely platform-specific piece of user
experience: macOS drives ``osascript``, Windows uses the built-in message box.
Both routes return the same logical choice, so the recovery flows in
:mod:`.cli` stay identical.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import host
from .lifecycle import LaunchResult, log_tail
from .paths import LauncherConfig

DIALOG_TITLE = "工资核算助手"
RETRY = "retry"
RESTART = "restart"
DIAGNOSTICS = "diagnostics"
DISMISSED = "dismissed"

_CHOICE_NAMES = {"重试": RETRY, "重新启动": RESTART, "查看诊断": DIAGNOSTICS}


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _has_osascript() -> bool:
    return Path("/usr/bin/osascript").is_file()


def _failure_buttons(allow_restart: bool) -> list[str]:
    buttons = ["查看诊断"] if not allow_restart else ["查看诊断", "重新启动"]
    buttons.append("重试")
    return buttons


def _choose_via_osascript(message: str, buttons: list[str]) -> str:
    button_list = ", ".join(f'"{_escape(name)}"' for name in buttons)
    script = (
        f'display dialog "{_escape(message)}" '
        f"buttons {{{button_list}}} default button \"重试\" "
        f'with title "{DIALOG_TITLE}" with icon caution'
    )
    try:
        completed = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        print(f"[{DIALOG_TITLE}] {message}")
        return ""
    if completed.returncode != 0:
        return ""
    output = (completed.stdout or "").strip()
    return output.split(":", 1)[1].strip() if ":" in output else output


def choose_after_failure(message: str, allow_restart: bool) -> str:
    """Show the failure dialog.  Falls back to stderr when no GUI is available."""
    buttons = _failure_buttons(allow_restart)
    if _has_osascript():
        name = _choose_via_osascript(message, buttons)
    elif host.IS_WINDOWS:
        name = host.show_choice(message, buttons, default="重试", title=DIALOG_TITLE)
    else:
        name = ""
    if not name:
        print(f"[{DIALOG_TITLE}] {message}")
        return DISMISSED
    return _CHOICE_NAMES.get(name, DISMISSED)


def problem_report_path(cfg: LauncherConfig) -> Path:
    return cfg.state_dir / "last-problem.md"


def write_problem_report(cfg: LauncherConfig, result: LaunchResult) -> Path:
    """Write a local, plain-Chinese report.  Contains no payroll values."""
    cfg.state_dir.mkdir(parents=True, exist_ok=True)
    tail = result.log_tail or log_tail(cfg)
    lines = [
        "# 工资核算助手启动诊断",
        "",
        f"- 时间：{datetime.now(timezone.utc).astimezone().isoformat()}",
        f"- 结果：{result.state}",
        f"- 提示内容：{result.message}",
        f"- 页面地址：{result.url}",
        f"- 端口：{cfg.port}",
        f"- 正式数据目录：{cfg.data_dir}",
        f"- 数据库文件：{cfg.db_path}",
        f"- 程序目录：{cfg.repo_root}",
        f"- 程序：{cfg.python}",
        f"- 是否发布包：{'是' if cfg.frozen else '否（源码运行）'}",
        f"- 启动器状态目录：{cfg.state_dir}",
        "",
        "## 技术说明",
        "",
        result.diagnostics or "（无）",
        "",
        "## 诊断日志尾部",
        "",
        "```text",
        *(tail or ["（暂无日志）"]),
        "```",
        "",
        "## 下一步",
        "",
        "1. 如果提示端口被占用：关闭占用该端口的程序后，回到对话框点“重试”。",
        "2. 如果提示程序目录或界面资源缺失：请重新解压完整的程序压缩包，不要只复制单个 exe。",
        "3. 如果提示 Python 环境不完整（仅源码运行时可能出现）：在程序目录安装依赖后点“重试”。",
        "4. 如果服务无响应：点“重新启动”，启动器只会结束它自己启动的进程。",
        "5. 本文件只包含路径和技术信息，不包含任何工资或教师数据。",
        "",
    ]
    path = problem_report_path(cfg)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def open_path(path: Path) -> None:
    host.open_path(path)


def open_diagnostics(cfg: LauncherConfig) -> None:
    report = problem_report_path(cfg)
    if report.is_file():
        open_path(report)
        return
    if cfg.log_file.is_file():
        open_path(cfg.log_file)
        return
    open_path(cfg.state_dir if cfg.state_dir.is_dir() else cfg.data_dir)


def open_url(url: str) -> bool:
    """Open the local page, reporting failure to the caller for visible handling."""
    return host.open_url(url)
