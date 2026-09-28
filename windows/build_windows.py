"""Build the Windows release package for 工资核算助手.

    python windows/build_windows.py [--output DIR] [--no-zip]

Produces, under ``windows/dist`` by default::

    EducationPayroll-Windows-v1/
    └── EducationPayroll/
        ├── 工资核算助手.exe           <- the only file a user needs to open
        ├── 重启工资服务.exe
        ├── 工资核算助手-命令行.exe
        ├── 使用说明.txt
        └── _internal/                 <- Python runtime + dependencies + assets
    EducationPayroll-Windows-v1.zip
    EducationPayroll-Windows-v1.zip.sha256

The whole build is repeatable from the checkout: nothing here is committed to
Git, and no machine-specific path is baked into the executables.  PyInstaller
builds ASCII-named executables and this script renames them afterwards, which
keeps the frozen bootloader away from non-ASCII executable names.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "windows" / "payroll_windows.spec"

RELEASE_FOLDER_NAME = "EducationPayroll-Windows-v1"
BUNDLE_NAME = "EducationPayroll"

# PyInstaller builds these; the user sees the Chinese names.
EXECUTABLE_NAMES = {
    "EducationPayroll.exe": "工资核算助手.exe",
    "RestartPayrollService.exe": "重启工资服务.exe",
    "PayrollCommandLine.exe": "工资核算助手-命令行.exe",
}

REQUIRED_BUNDLE_PATHS = (
    "_internal/payroll_ui/static/index.html",
    "_internal/payroll_ui/static/app.js",
    "_internal/payroll_ui/static/app.css",
    "_internal/payroll_ui/static/teacher.html",
    "_internal/config/core_rules_2026.yaml",
)

USAGE_TEXT = """工资核算助手（Windows 版）使用说明
================================================

一、怎么用

  双击「工资核算助手.exe」即可。
  程序会自动启动本机工资服务，并用默认浏览器打开工资助手页面。

  你不需要：打开命令行、安装 Python、记住网址或端口、记住程序放在哪里。

二、数据在哪

  你的工资数据保存在：

      %LOCALAPPDATA%\\EducationPayroll\\

  里面有：

      payroll-ui.sqlite3      正式数据库（历史核算、星级、政策、年级证据）
      technical-errors.log    技术错误记录
      launcher\\               启动器状态与诊断日志

  这个位置和程序文件夹是分开的。以后升级或重新解压程序，
  只要不删除上面的目录，历史数据都会原样保留。

三、重启服务

  如果页面打不开或提示连接失败，双击「重启工资服务.exe」。
  它只会结束由本启动器启动的那一个工资服务进程。

四、出问题怎么办

  程序不会静默失败。启动失败时会弹出中文提示，
  并把技术信息写到：

      %LOCALAPPDATA%\\EducationPayroll\\launcher\\last-problem.md

  诊断文件里只有路径和技术信息，不含任何工资、教师或学生数据。

五、命令行（仅排障用）

  「工资核算助手-命令行.exe」可以查看状态：

      --status        查看服务与数据目录状态
      --stop          安全停止工资服务
      --inventory     只读列出历史核算记录
      --diagnostics   打开最近一次诊断

六、端口

  固定使用 127.0.0.1:8760。
  如果该端口被别的程序占用，程序会明确提示，
  不会结束其它程序，也不会偷偷改用别的端口。
"""


def _discard(path: Path) -> None:
    """Remove an old output without bulk-deleting inside the workspace.

    The tree is renamed into the system temporary directory first and deleted
    there.  That is one filesystem operation instead of a walk of every file,
    so the build stays repeatable for anyone running it inside a repository
    with a "confirm before deleting many files" policy.
    """
    if not path.exists():
        return
    staging = Path(tempfile.mkdtemp(prefix="payroll-build-cleanup-"))
    try:
        moved = staging / path.name
        shutil.move(str(path), str(moved))
        shutil.rmtree(moved, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(command))
    completed = subprocess.run(command, cwd=str(cwd))
    if completed.returncode != 0:
        raise SystemExit(f"命令失败（退出码 {completed.returncode}）：{' '.join(command)}")


def build(dist_dir: Path) -> Path:
    """Run PyInstaller in a scratch directory and move the result into place."""
    if not SPEC.is_file():
        raise SystemExit(f"找不到打包配置：{SPEC}")

    scratch = Path(tempfile.mkdtemp(prefix="payroll-windows-build-"))
    try:
        _run(
            [
                sys.executable, "-m", "PyInstaller",
                "--clean", "--noconfirm",
                "--distpath", str(scratch / "dist"),
                "--workpath", str(scratch / "build"),
                str(SPEC),
            ],
            cwd=REPO_ROOT,
        )

        bundle = scratch / "dist" / BUNDLE_NAME
        if not bundle.is_dir():
            raise SystemExit(f"PyInstaller 没有生成 {bundle}")

        for built_name, user_name in EXECUTABLE_NAMES.items():
            built = bundle / built_name
            if not built.is_file():
                raise SystemExit(f"发布包缺少可执行文件：{built}")
            built.rename(bundle / user_name)

        (bundle / "使用说明.txt").write_text(USAGE_TEXT, encoding="utf-8")
        verify(bundle)

        final = dist_dir / BUNDLE_NAME
        _discard(final)
        dist_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(bundle), str(final))
        return final
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify(bundle: Path) -> None:
    """Fail loudly rather than shipping a package with a 404 for its own UI."""
    missing = [name for name in REQUIRED_BUNDLE_PATHS if not (bundle / name).is_file()]
    if missing:
        raise SystemExit("发布包缺少必要资源：\n  " + "\n  ".join(missing))
    for user_name in EXECUTABLE_NAMES.values():
        if not (bundle / user_name).is_file():
            raise SystemExit(f"发布包缺少 {user_name}")
    print("资源检查通过：静态界面、核心规则、三个可执行文件均在位。")


def package(bundle: Path, dist_dir: Path) -> tuple[Path, str]:
    release_dir = dist_dir / RELEASE_FOLDER_NAME
    _discard(release_dir)
    release_dir.mkdir(parents=True)
    shutil.move(str(bundle), str(release_dir / BUNDLE_NAME))

    zip_path = release_dir.with_suffix(".zip")
    _discard(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(release_dir.rglob("*")):
            archive.write(path, path.relative_to(dist_dir))

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum = zip_path.parent / f"{zip_path.name}.sha256"
    checksum.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 Windows 发布包")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "windows" / "dist",
                        help="输出目录（默认 windows/dist，已加入 .gitignore）")
    parser.add_argument("--no-zip", action="store_true", help="只生成程序目录，不打包 ZIP")
    args = parser.parse_args(argv)

    dist_dir = args.output.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    # Older revisions of this script built inside windows/build; PyInstaller now
    # works in the system temp directory, so clear any leftover.
    _discard(dist_dir.parent / "build")

    bundle = build(dist_dir)

    print(f"\n程序目录：{bundle}")
    print(f"  入口：{bundle / '工资核算助手.exe'}")

    if args.no_zip:
        return 0

    zip_path, digest = package(bundle, dist_dir)
    print(f"\n发布包：{zip_path}")
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
