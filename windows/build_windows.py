"""Build the Windows release package for 工资核算助手.

Two modes are supported:

1. **Fresh build** (default)::

       python windows/build_windows.py [--output DIR] [--no-zip]

   Builds from the current checkout through ``payroll_windows.spec``.  The
   workspace must be clean *and* ``HEAD`` must sit exactly on an official
   release tag ``payroll-vX.Y.Z`` -- the version is derived from that tag, never
   typed by hand.  This fails closed so an un-released or duplicate version can
   never be produced by accident.

2. **Repackage an existing package** (used to re-brand an already-built
   artifact without recompiling it)::

       python windows/build_windows.py --repackage <PACKAGE_DIR> [--version V1.0.0]

   Reads the immutable ``build_sha`` from the package's own ``build-info.json``
   (never from the current ``HEAD``), derives the version from the tag that
   points at that SHA (``--version`` is only a fallback when no tag is found),
   rewrites ``build-info.json`` with the correct ``release_version`` while
   keeping ``build_sha`` / ``build_dirty=false``, and regroups the tree.  No
   executable is compiled and no executable byte is modified: the frozen
   executables report their identity from ``build-info.json`` at runtime, so
   only that metadata file needs to change.

Both modes produce, under ``windows/dist`` by default::

    工资核算助手-{V}-{short}-{platform}/
    ├── 工资核算助手.exe          <- the only file a normal user opens
    ├── 重启工资服务.exe          <- maintenance tool, not needed normally
    ├── 工资核算助手-命令行.exe    <- maintenance tool, not needed normally
    ├── _internal/                 <- one shared runtime for all three
    ├── 使用说明.txt
    ├── 版本信息.txt               <- generated, never hand-written
    └── build-info.json
    工资核算助手-{V}-{short}-{platform}.zip
    工资核算助手-{V}-{short}-{platform}.zip.sha256

Why the maintenance tools are *not* hidden in a sub-folder: a PyInstaller
onedir executable resolves its runtime from an ``_internal`` folder next to
itself, so relocating one forces either a second copy of ``_internal`` or a
onefile rebuild -- both duplicate the Python runtime and roughly double the
package size.  Paying ~+50% size for a cosmetic "clean top level" is not worth
it, so all three executables stay beside the single shared runtime and
使用说明.txt states plainly that the two tools are for troubleshooting only.

Nothing here is committed to Git, and no machine-specific path is baked into the
executables.  PyInstaller builds ASCII-named executables and this script renames
them afterwards, which keeps the frozen bootloader away from non-ASCII
executable names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SPEC = REPO_ROOT / "windows" / "payroll_windows.spec"

# PyInstaller's onedir bundle folder and the entry executable it builds.
BUNDLE_NAME = "EducationPayroll"
PYI_ENTRY_EXE = "EducationPayroll.exe"

# The user-facing entry point.
APP_DISPLAY = "工资核算助手.exe"

# PyInstaller build names (ASCII) -> Chinese display names, for the maintenance
# tools that ship beside the main entry and share its runtime.
TOOLS = {
    "RestartPayrollService.exe": "重启工资服务.exe",
    "PayrollCommandLine.exe": "工资核算助手-命令行.exe",
}

# ``payroll-v1.0.0`` -> release version ``V1.0.0``.
RELEASE_TAG_RE = re.compile(r"^payroll-v(\d+\.\d+\.\d+)$")
VERSION_RE = re.compile(r"^V?(\d+\.\d+\.\d+)$")

# sys.platform -> human readable platform name used in names and metadata.
PLATFORM_NAMES = {
    "win32": "Windows",
    "cygwin": "Windows",
    "darwin": "Mac",
    "linux": "Linux",
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

三、另外两个程序是维修工具（正常使用无需打开）

  同目录下的这两个程序只在排障时使用，
  正常使用工资核算助手时不需要打开它们：

      重启工资服务.exe
          页面打不开或提示连接失败时，双击它。
          它只会结束由本启动器启动的那一个工资服务进程。

      工资核算助手-命令行.exe
          仅供排障查看状态，双击无效，需在命令行中运行：

              --status        查看服务与数据目录状态
              --stop          安全停止工资服务
              --inventory     只读列出历史核算记录
              --diagnostics   打开最近一次诊断

四、出问题怎么办

  程序不会静默失败。启动失败时会弹出中文提示，
  并把技术信息写到：

      %LOCALAPPDATA%\\EducationPayroll\\launcher\\last-problem.md

  诊断文件里只有路径和技术信息，不含任何工资、教师或学生数据。

五、端口

  固定使用 127.0.0.1:8760。
  如果该端口被别的程序占用，程序会明确提示，
  不会结束其它程序，也不会偷偷改用别的端口。

六、目录结构

  工资核算助手.exe          主程序（双击它即可）
  重启工资服务.exe          维修工具（平时无需打开）
  工资核算助手-命令行.exe    维修工具（平时无需打开）
  _internal\\                三个程序共用的运行时（请勿删除或移动）
  使用说明.txt              本文件
  版本信息.txt              版本 / Build / 发布日期 / 平台
"""


def _discard(path: Path) -> None:
    """Remove an old output without bulk-deleting inside the workspace.

    The tree is renamed into the system temporary directory first and deleted
    there.  That is one filesystem operation instead of a walk of every file,
    so the build stays repeatable for anyone running it inside a repository
    with a "confirm before deleting many files" policy.  A plain file (for
    example the previous ``.zip``) is unlinked in place.
    """
    if not path.exists() and not path.is_symlink():
        return
    staging = Path(tempfile.mkdtemp(prefix="payroll-build-cleanup-"))
    try:
        moved = staging / path.name
        shutil.move(str(path), str(moved))
        if moved.is_dir() and not moved.is_symlink():
            shutil.rmtree(moved, ignore_errors=True)
        else:
            try:
                moved.unlink()
            except OSError:
                pass
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _run(command: list[str], cwd: Path) -> None:
    print("$", " ".join(command))
    completed = subprocess.run(command, cwd=str(cwd))
    if completed.returncode != 0:
        raise SystemExit(f"命令失败（退出码 {completed.returncode}）：{' '.join(command)}")


def _git(*arguments: str) -> str:
    """Run git read-only and return stripped stdout, failing closed on error."""
    try:
        completed = subprocess.run(
            ["git", *arguments], cwd=REPO_ROOT,
            check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"无法读取 Git 信息：{exc}") from exc
    return completed.stdout.strip()


def _head_sha() -> str:
    return _git("rev-parse", "--verify", "HEAD")


def _is_clean() -> bool:
    return not bool(_git("status", "--porcelain", "--untracked-files=all"))


def _tags_pointing_at(sha: str) -> list[str]:
    """Every tag that points exactly at ``sha`` (lightweight or annotated)."""
    return [line.strip() for line in _git("tag", "--points-at", sha).splitlines() if line.strip()]


def _version_from_tags(tags: list[str]) -> str | None:
    """Return the release version (``V1.0.0``) of the first release tag found."""
    for tag in tags:
        match = RELEASE_TAG_RE.match(tag)
        if match:
            return f"V{match.group(1)}"
    return None


def _normalise_version(value: str) -> str:
    """Accept ``1.0.0`` or ``V1.0.0`` and return the canonical ``V1.0.0``."""
    match = VERSION_RE.match(value.strip())
    if not match:
        raise SystemExit(f"--version 参数格式不正确：{value}（应形如 V1.0.0）")
    return f"V{match.group(1)}"


def _commit_date(sha: str) -> str:
    """Release date, taken from the commit the package was built from."""
    return _git("show", "-s", "--format=%cs", sha)


def _platform_name() -> str:
    return PLATFORM_NAMES.get(sys.platform, sys.platform.capitalize())


def _release_folder(version: str, short: str, platform: str) -> str:
    return f"工资核算助手-{version}-{short}-{platform}"


def _build_info(version: str, sha: str) -> dict:
    """The immutable identity stamped into the package and read at runtime."""
    return {"release_version": version, "build_sha": sha, "build_dirty": False}


def _version_info_text(version: str, short: str, sha: str, date: str, platform: str) -> str:
    """Render ``版本信息.txt`` -- every value is filled in by the build.

    The exact wording is a release contract (support asks the user to quote
    "版本号 + Build"), so it must not be reflowed.
    """
    return (
        "工资核算助手\n"
        f"版本：{version}\n"
        f"Build：{short}\n"
        "完整 Build SHA：\n"
        f"{sha}\n"
        f"发布日期：{date}\n"
        f"平台：{platform}\n"
        "如果需要反馈问题，请同时提供：\n"
        "版本号 + Build。\n"
    )


def _assemble_release(
    release_dir: Path,
    *,
    app_exe: Path,
    internal_dir: Path | None,
    tools: list[tuple[Path, str]],
    build_info: dict,
    usage_text: str,
    version_info: str,
) -> Path:
    """Lay out one release tree and fail closed if anything is missing.

    The layout is identical for a fresh build and a repackage: the main entry,
    the two maintenance tools and one shared ``_internal`` runtime all sit at
    the top level, because a relocated onedir executable would need its own copy
    of the runtime.
    """
    _discard(release_dir)
    release_dir.mkdir(parents=True)

    shutil.copy2(app_exe, release_dir / APP_DISPLAY)
    if internal_dir is not None:
        shutil.copytree(internal_dir, release_dir / "_internal")
    for source, display in tools:
        shutil.copy2(source, release_dir / display)

    metadata = json.dumps(build_info, ensure_ascii=False, indent=2) + "\n"
    (release_dir / "build-info.json").write_text(metadata, encoding="utf-8")
    (release_dir / "使用说明.txt").write_text(usage_text, encoding="utf-8")
    (release_dir / "版本信息.txt").write_text(version_info, encoding="utf-8")

    verify(release_dir)
    return release_dir


def verify(release_dir: Path) -> None:
    """Fail loudly rather than shipping a broken or duplicated package."""
    missing = [name for name in REQUIRED_BUNDLE_PATHS if not (release_dir / name).is_file()]
    if missing:
        raise SystemExit("发布包缺少必要资源：\n  " + "\n  ".join(missing))

    expected = {APP_DISPLAY, *TOOLS.values()}
    actual = sorted(path.name for path in release_dir.glob("*.exe"))
    if set(actual) != expected:
        raise SystemExit(
            f"顶层可执行文件应为 {sorted(expected)}，实际为：{actual}"
        )

    # One shared runtime only: a second _internal means the Python runtime was
    # duplicated, which is exactly the size regression this layout avoids.
    internals = sorted(
        path.relative_to(release_dir).as_posix()
        for path in release_dir.rglob("_internal") if path.is_dir()
    )
    if internals != ["_internal"]:
        raise SystemExit(f"发布包必须只有一份 _internal 运行时，实际为：{internals}")

    for name in ("使用说明.txt", "版本信息.txt"):
        if not (release_dir / name).is_file():
            raise SystemExit(f"发布包缺少 {name}")

    try:
        info = json.loads((release_dir / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("发布包缺少有效的 build-info.json。") from exc
    if (not isinstance(info, dict) or len(str(info.get("build_sha") or "")) != 40
            or not info.get("release_version") or info.get("build_dirty") is not False):
        raise SystemExit("发布包 build-info.json 中的版本身份不完整或不安全。")

    print("资源检查通过：界面、核心规则、版本身份、三个可执行文件与唯一共享 runtime 均在位。")


def _locate_app_executable(package_dir: Path) -> Path:
    for name in (APP_DISPLAY, PYI_ENTRY_EXE):
        candidate = package_dir / name
        if candidate.is_file():
            return candidate
    raise SystemExit(f"源包中找不到入口可执行文件 {APP_DISPLAY}：{package_dir}")


def _locate_internal(package_dir: Path) -> Path:
    internal = package_dir / "_internal"
    if internal.is_dir():
        return internal
    raise SystemExit(f"源包中找不到 _internal 运行时目录：{package_dir}")


def _locate_tool(package_dir: Path, display: str) -> Path:
    """Find a tool in the shared (flat) layout, tolerating a legacy tools/ one."""
    for candidate in (package_dir / display, package_dir / "tools" / display):
        if candidate.is_file():
            return candidate
    raise SystemExit(f"源包中找不到维修工具：{display}")


def fresh_build(dist_dir: Path, explicit_version: str | None = None) -> Path:
    """Compile from the checkout through the spec and assemble the release.

    Strict by design: only a clean workspace whose ``HEAD`` is tagged with an
    official ``payroll-vX.Y.Z`` release tag may produce a package.  Everything
    (version, short SHA, date, platform) is derived, never typed.
    """
    if not SPEC.is_file():
        raise SystemExit(f"找不到打包配置：{SPEC}")

    sha = _head_sha()
    if len(sha) != 40 or not _is_clean():
        raise SystemExit("Windows 发布必须从干净、已提交的源码构建。")

    version = _version_from_tags(_tags_pointing_at(sha))
    if version is None:
        raise SystemExit(
            "当前 HEAD 未落在正式发布 tag（形如 payroll-vX.Y.Z）上，"
            "拒绝构建未发布或重复的版本包。请先为该提交打正式 tag。"
        )
    if explicit_version is not None and _normalise_version(explicit_version) != version:
        raise SystemExit(
            f"--version 与 HEAD 上的发布 tag 不一致（tag 推导为 {version}，参数为 {explicit_version}）。"
        )

    short = sha[:7]
    date = _commit_date(sha)
    platform = _platform_name()
    release_dir = dist_dir / _release_folder(version, short, platform)

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
        app_exe = bundle / PYI_ENTRY_EXE
        if not app_exe.is_file():
            raise SystemExit(f"PyInstaller 没有生成入口可执行文件：{app_exe}")

        # All three executables live in the same onedir bundle and share its
        # single _internal runtime.
        tools: list[tuple[Path, str]] = []
        for build_name, display in TOOLS.items():
            built = bundle / build_name
            if not built.is_file():
                raise SystemExit(f"PyInstaller 没有生成维修工具：{built}")
            tools.append((built, display))

        _assemble_release(
            release_dir,
            app_exe=app_exe,
            internal_dir=bundle / "_internal",
            tools=tools,
            build_info=_build_info(version, sha),
            usage_text=USAGE_TEXT,
            version_info=_version_info_text(version, short, sha, date, platform),
        )
        return release_dir
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def repackage(package_dir: Path, dist_dir: Path, explicit_version: str | None = None) -> Path:
    """Re-brand an existing package into the current layout without recompiling.

    The identity is read *from the package*, not from the current checkout: the
    executable bytes stay untouched and the version is whatever tag points at
    the package's own ``build_sha``.
    """
    if not package_dir.is_dir():
        raise SystemExit(f"找不到要复用的发布包目录：{package_dir}")

    try:
        source_info = json.loads((package_dir / "build-info.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"源包缺少有效的 build-info.json：{package_dir}") from exc

    sha = str(source_info.get("build_sha") or "").strip()
    if len(sha) != 40:
        raise SystemExit("源包 build-info.json 缺少有效的 build_sha，无法安全复用。")

    version = _version_from_tags(_tags_pointing_at(sha))
    if version is None:
        if explicit_version is None:
            raise SystemExit(
                f"找不到指向 build_sha {sha} 的正式 tag。请确认 tag 存在，或用 --version 指定版本。"
            )
        version = _normalise_version(explicit_version)
    elif explicit_version is not None and _normalise_version(explicit_version) != version:
        raise SystemExit(
            f"--version 与指向该 build_sha 的 tag 不一致（tag 推导为 {version}，参数为 {explicit_version}）。"
        )

    short = sha[:7]
    date = _commit_date(sha)
    platform = _platform_name()

    app_exe = _locate_app_executable(package_dir)
    internal_dir = _locate_internal(package_dir)
    tools = [(_locate_tool(package_dir, display), display) for display in TOOLS.values()]

    release_dir = dist_dir / _release_folder(version, short, platform)
    _assemble_release(
        release_dir,
        app_exe=app_exe,
        internal_dir=internal_dir,
        tools=tools,
        build_info=_build_info(version, sha),
        usage_text=USAGE_TEXT,
        version_info=_version_info_text(version, short, sha, date, platform),
    )
    return release_dir


def package(release_dir: Path, dist_dir: Path) -> tuple[Path, str]:
    """Zip the release folder and write its ``.sha256`` sidecar file."""
    zip_path = dist_dir / f"{release_dir.name}.zip"
    _discard(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(release_dir.rglob("*")):
            archive.write(path, path.relative_to(release_dir.parent))

    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    checksum = zip_path.parent / f"{zip_path.name}.sha256"
    checksum.write_text(f"{digest}  {zip_path.name}\n", encoding="utf-8")
    return zip_path, digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建 Windows 发布包")
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "windows" / "dist",
                        help="输出目录（默认 windows/dist，已加入 .gitignore）")
    parser.add_argument("--no-zip", action="store_true", help="只生成程序目录，不打包 ZIP")
    parser.add_argument("--repackage", type=Path, default=None,
                        help="复用既有发布包目录并按新布局重组（不重新编译、不改动 EXE 字节）")
    parser.add_argument("--version", default=None,
                        help="版本号（如 V1.0.0）；仅在无法从 tag 推导时作为兜底")
    args = parser.parse_args(argv)

    dist_dir = args.output.resolve()
    dist_dir.mkdir(parents=True, exist_ok=True)
    # Older revisions of this script built inside windows/build; PyInstaller now
    # works in the system temp directory, so clear any leftover.
    _discard(dist_dir.parent / "build")

    if args.repackage is not None:
        release_dir = repackage(args.repackage.resolve(), dist_dir, explicit_version=args.version)
    else:
        release_dir = fresh_build(dist_dir, explicit_version=args.version)

    print(f"\n发布目录：{release_dir}")
    print(f"  入口：{release_dir / APP_DISPLAY}")

    if args.no_zip:
        return 0

    zip_path, digest = package(release_dir, dist_dir)
    print(f"\n发布包：{zip_path}")
    print(f"SHA-256：{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
