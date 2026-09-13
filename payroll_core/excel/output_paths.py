"""Collision-safe export paths and a sensible default output location.

A user should never be told "输出文件已存在" and never be asked to type an
absolute path. An existing file is preserved and the new one gets a free name.
"""
from __future__ import annotations

from pathlib import Path


def safe_output_path(target: str | Path) -> Path:
    """Return a path that does not collide with any existing file.

    工资表.xlsx → 工资表 (2).xlsx → 工资表 (3).xlsx …
    Gaps are filled safely: with (2) and (4) present, (3) is reused because it
    collides with nothing.
    """
    path = Path(target).expanduser()
    if not path.exists():
        return path
    suffix = path.suffix
    stem = path.name[: -len(suffix)] if suffix else path.name
    index = 2
    while True:
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def default_output_dir(filename: str | None = None) -> Path:
    """Preferred export folder, with a working fallback.

    Normal users get ``Desktop/工资导出``. When the Desktop is unavailable the
    home directory is used, and as a last resort ``/tmp``. The chosen location
    is always returned so the UI can tell the user where the file went.
    """
    home = Path.home()
    candidates = [home / "Desktop" / "工资导出", home / "工资导出", home]
    for base in candidates:
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".payroll-write-probe"
            probe.touch(exist_ok=True)
            probe.unlink(missing_ok=True)
            return base / filename if filename else base
        except OSError:
            continue
    fallback = Path("/tmp")
    return fallback / filename if filename else fallback


def describe_location(path: str | Path) -> str:
    """Human-readable location for the UI, without exposing raw internals."""
    path = Path(path).expanduser()
    home = Path.home()
    try:
        relative = path.relative_to(home)
        return f"~/ {relative.as_posix()}".replace("~/ ", "~/")
    except ValueError:
        return path.name
