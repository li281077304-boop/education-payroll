"""Entry point of the released Windows executable.

The release ships three names built from this same script; which one the user
double-clicked decides the default action:

===========================  =========================================
``工资核算助手.exe``          启动/复用本地工资服务并打开默认浏览器
``重启工资服务.exe``          安全重启（只结束本启动器启动的服务）后打开
``工资核算助手-命令行.exe``    诊断用：打印服务与目录状态
===========================  =========================================

``--service`` is internal.  The launcher uses it to re-enter its own
executable as the Payroll HTTP service, which is what makes the release
independent of any Python installed on the user's machine.

This module is the PyInstaller entry script, so PyInstaller executes it as
``__main__`` with no package context.  Relative imports would therefore fail
at startup, and the imports below are deliberately absolute.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from payroll_launcher import cli
from payroll_launcher.paths import SERVICE_FLAG, default_data_dir


def _windowed_default_arguments() -> list[str]:
    """Pick a default action from the executable's own name."""
    name = Path(sys.executable).stem
    if "重启" in name:
        return ["--mode", "restart"]
    if "命令行" in name or "诊断" in name:
        return ["--status"]
    return ["--mode", "open"]


def _ensure_output_streams() -> None:
    """A windowed build has no console, so ``print`` must not crash.

    Support engineers still need the launcher's own output, so it is appended
    to a log beside the other diagnostics instead of being discarded.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is not None:
            continue
        stream = None
        try:
            launcher_dir = default_data_dir() / "launcher"
            launcher_dir.mkdir(parents=True, exist_ok=True)
            stream = (launcher_dir / "launcher-output.log").open("a", encoding="utf-8", buffering=1)
        except OSError:
            try:
                stream = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
            except OSError:
                return
        setattr(sys, name, stream)


def _parse_service_arguments(argv: list[str]) -> tuple[Path, int]:
    """Read the two options the launcher passes to its own service."""
    data_dir = default_data_dir()
    port = 0
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--data-dir" and index + 1 < len(argv):
            data_dir = Path(argv[index + 1])
            index += 2
            continue
        if token == "--port" and index + 1 < len(argv):
            port = int(argv[index + 1])
            index += 2
            continue
        index += 1
    return data_dir, port


def main(argv: list[str] | None = None) -> int:
    _ensure_output_streams()
    arguments = list(sys.argv[1:] if argv is None else argv)

    if SERVICE_FLAG in arguments:
        from payroll_launcher import service_mode

        data_dir, port = _parse_service_arguments(arguments)
        return service_mode.run_service(data_dir, port)

    if not arguments:
        arguments = _windowed_default_arguments()
    return cli.main(arguments)


if __name__ == "__main__":
    sys.exit(main())
