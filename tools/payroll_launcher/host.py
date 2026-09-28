"""Operating-system primitives used by the Payroll launcher.

The launcher's decisions -- reuse, start, refuse, stop -- are identical on
every platform.  Only a handful of primitives differ, so they live here and
no other launcher module needs an ``os.name`` branch.

Everything in this file is deliberately side-effect free unless the function
name says otherwise, and nothing here knows about payroll rules or data.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# ---------------------------------------------------------------------------
# Windows constants (kept local so the module imports on every platform)
# ---------------------------------------------------------------------------

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_SYNCHRONIZE = 0x00100000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259

_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_FAILED = 0xFFFFFFFF

_IDYES = 6
_IDNO = 7

_MB_YESNOCANCEL = 0x00000003
_MB_ICONWARNING = 0x00000030
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000


def _kernel32():
    """Load kernel32 once, with exact signatures for 64-bit handles."""
    cached = getattr(_kernel32, "_library", None)
    if cached is not None:
        return cached
    import ctypes  # imported here so this module stays importable everywhere

    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    library.OpenProcess.restype = ctypes.c_void_p
    library.CloseHandle.argtypes = [ctypes.c_void_p]
    library.CloseHandle.restype = ctypes.c_int
    library.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    library.GetExitCodeProcess.restype = ctypes.c_int
    library.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)
    ]
    library.QueryFullProcessImageNameW.restype = ctypes.c_int
    library.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    library.CreateMutexW.restype = ctypes.c_void_p
    library.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    library.WaitForSingleObject.restype = ctypes.c_ulong
    library.ReleaseMutex.argtypes = [ctypes.c_void_p]
    library.ReleaseMutex.restype = ctypes.c_int
    _kernel32._library = library
    return library


# ---------------------------------------------------------------------------
# Launch serialisation
# ---------------------------------------------------------------------------


def acquire_launcher_lock(lock_file: Path):
    """Block until this process owns the launcher critical section.

    Returns an opaque token to hand back to :func:`release_launcher_lock`.

    POSIX uses an advisory ``flock`` on a file inside the launcher state
    directory.  Windows uses a named mutex instead: it is released by the
    kernel even if the launcher is killed mid-flight, so a crashed run can
    never leave a stale lock behind and a second double-click always proceeds
    once the first one is gone.
    """
    if IS_WINDOWS:
        import ctypes

        kernel32 = _kernel32()
        name = "Local\\EducationPayrollLauncher-" + hashlib.sha256(
            str(lock_file).lower().encode("utf-8")
        ).hexdigest()[:32]
        handle = kernel32.CreateMutexW(None, False, name)
        if not handle:
            raise OSError(f"无法创建启动器互斥体（错误 {ctypes.get_last_error()}）")
        result = int(kernel32.WaitForSingleObject(handle, _WAIT_FAILED))
        if result not in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
            kernel32.CloseHandle(handle)
            raise OSError("无法获取启动器互斥体。")
        return ("windows-mutex", handle)

    import fcntl

    lock_file.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_file.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:
        handle.close()
        raise
    return ("posix-flock", handle)


def release_launcher_lock(token) -> None:
    if not token:
        return
    kind, handle = token
    if kind == "windows-mutex":
        kernel32 = _kernel32()
        try:
            kernel32.ReleaseMutex(handle)
        finally:
            kernel32.CloseHandle(handle)
        return
    try:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


# ---------------------------------------------------------------------------
# Process identity
# ---------------------------------------------------------------------------


def process_alive(pid: int) -> bool:
    """Return True only when ``pid`` is a live process.

    ``os.kill(pid, 0)`` is the obvious probe, but on Windows it does not mean
    "probe": any signal other than the two console events is forwarded to
    ``TerminateProcess``.  Probing with signal 0 would therefore kill the
    service the launcher is trying to inspect, so Windows uses the documented
    ``OpenProcess`` / ``GetExitCodeProcess`` pair instead.
    """
    if pid <= 0:
        return False
    if IS_WINDOWS:
        return _windows_process_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_process_alive(pid: int) -> bool:
    import ctypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION | _SYNCHRONIZE, False, int(pid))
    if not handle:
        # A live process owned by another account refuses the handle.  Treating
        # that as "dead" would let the launcher start a duplicate service.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_command(pid: int) -> str:
    """Best-effort description of what ``pid`` is running.

    POSIX returns the full command line.  Windows can only read the executable
    path without extra privileges, so callers must treat a result that looks
    like a bare interpreter path as "weaker evidence".
    """
    if pid <= 0:
        return ""
    if IS_WINDOWS:
        return _windows_process_image(pid)
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def _windows_process_image(pid: int) -> str:
    import ctypes

    kernel32 = _kernel32()
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return ""
    try:
        size = ctypes.c_ulong(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        kernel32.CloseHandle(handle)


def terminate(pid: int, force: bool = False) -> None:
    """Terminate ``pid``.  Callers must have proven the identity first.

    ``force`` is accepted for signature parity with the POSIX signal ladder;
    Windows has a single ``TerminateProcess`` primitive.
    """
    if IS_WINDOWS:
        import ctypes

        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
        if not handle:
            raise OSError(f"无法结束进程 {pid}（错误 {ctypes.get_last_error()}）")
        try:
            if not kernel32.TerminateProcess(handle, 1):
                raise OSError(f"无法结束进程 {pid}（错误 {ctypes.get_last_error()}）")
        finally:
            kernel32.CloseHandle(handle)
        return
    os.kill(pid, 9 if force else 15)


# ---------------------------------------------------------------------------
# Desktop integration
# ---------------------------------------------------------------------------


def open_url(url: str) -> bool:
    """Open ``url`` in the system default browser."""
    if IS_WINDOWS:
        try:
            return bool(webbrowser.open(url, new=2, autoraise=True))
        except (OSError, webbrowser.Error):
            return False
    try:
        completed = subprocess.run(["/usr/bin/open", url], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0


def open_path(path: Path) -> None:
    """Reveal ``path`` with the desktop's default handler."""
    if IS_WINDOWS:
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
        except OSError:
            print(f"诊断文件位置：{path}")
        return
    try:
        subprocess.run(["/usr/bin/open", str(path)], capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        print(f"诊断文件位置：{path}")


def show_choice(message: str, labels: list[str], default: str, title: str) -> str:
    """Ask the user to pick one of ``labels``.  Returns "" when unavailable.

    Windows uses the built-in message box, which cannot carry custom button
    captions, so the mapping between buttons and actions is spelled out in the
    message body.  The technical detail always reaches ``last-problem.md``
    regardless of which button is pressed.
    """
    if not IS_WINDOWS:
        return ""
    import ctypes

    mapping = _windows_button_mapping(labels)
    if not mapping:
        return ""
    body = message + "\n\n" + "    ".join(f"【{name}】{action}" for name, action in mapping["legend"])
    flags = _MB_YESNOCANCEL | _MB_ICONWARNING | _MB_SETFOREGROUND | _MB_TOPMOST
    try:
        result = ctypes.windll.user32.MessageBoxW(None, body, title, flags)
    except OSError:
        return ""
    return mapping["labels"].get(int(result), "")


def _windows_button_mapping(labels: list[str]) -> dict:
    """Map the three Windows message-box answers onto our logical labels."""
    legend: list[tuple[str, str]] = []
    resolved: dict[int, str] = {}
    for slot, index in ((_IDYES, 0), (_IDNO, 1)):
        if len(labels) > index:
            legend.append(("是" if slot == _IDYES else "否", labels[index]))
            resolved[slot] = labels[index]
    if not resolved:
        return {}
    return {"legend": legend + [("取消", "关闭")], "labels": resolved}


def has_native_dialog() -> bool:
    """Whether a desktop dialog can be shown at all."""
    if IS_WINDOWS:
        return True
    return Path("/usr/bin/osascript").is_file()


def launcher_identity() -> dict:
    """Facts about this process, used only for diagnostics."""
    return {
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "platform": sys.platform,
    }
