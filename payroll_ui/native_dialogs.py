"""Native file and folder pickers for the local UI.

Most material enters the tool through the browser's own file input, which works
the same everywhere.  A few older buttons still ask the desktop for an absolute
path instead, and those need a platform dialog.

Each platform uses the dialog that already exists on the machine -- osascript
on macOS, the Win32 common dialogs on Windows -- so the release gains no GUI
toolkit, no extra runtime and no new dependency.  Every function returns
``None`` when the user cancels or when no dialog is available, which is exactly
what the existing macOS code already did.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

# Filters are described once and translated per platform.  macOS wants uniform
# type identifiers while Windows wants filename globs.
EXCEL_UTIS = (
    "org.openxmlformats.spreadsheetml.sheet",
    "com.microsoft.excel.xls",
    "com.microsoft.excel.xlsm",
)
EXCEL_PATTERNS = (("Excel 工作簿", "*.xlsx;*.xls;*.xlsm"), ("所有文件", "*.*"))
DOCUMENT_PATTERNS = (("人工月资料", "*.md;*.csv;*.xlsx;*.xls"), ("所有文件", "*.*"))


def available() -> bool:
    """Whether a desktop dialog can be shown on this machine."""
    if os.name == "nt":
        return True
    return Path("/usr/bin/osascript").is_file()


def pick_file(title: str, patterns: tuple[tuple[str, str], ...] = (),
              macos_utis: tuple[str, ...] = ()) -> str | None:
    if os.name == "nt":
        return _windows_pick_file(title, patterns)
    return _macos_pick_file(title, macos_utis)


def pick_folder(title: str) -> str | None:
    if os.name == "nt":
        return _windows_pick_folder(title)
    return _macos_pick_folder(title)


# ---------------------------------------------------------------------------
# macOS
# ---------------------------------------------------------------------------


def _macos_script(kind: str, title: str, utis: tuple[str, ...]) -> str:
    if kind == "folder":
        return f'POSIX path of (choose folder with prompt "{title}")'
    if utis:
        type_list = ", ".join(f'"{uti}"' for uti in utis)
        return f'POSIX path of (choose file with prompt "{title}" of type {{{type_list}}})'
    return f'POSIX path of (choose file with prompt "{title}")'


def _macos_run(script: str) -> str | None:
    try:
        return subprocess.check_output(
            ["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _macos_pick_file(title: str, utis: tuple[str, ...]) -> str | None:
    return _macos_run(_macos_script("file", title, utis))


def _macos_pick_folder(title: str) -> str | None:
    return _macos_run(_macos_script("folder", title, ()))


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

_OFN_READONLY = 0x00000001
_OFN_NOCHANGEDIR = 0x00000008
_OFN_PATHMUSTEXIST = 0x00000800
_OFN_FILEMUSTEXIST = 0x00001000
_OFN_EXPLORER = 0x00080000

_BIF_RETURNONLYFSDIRS = 0x0001
_BIF_NEWDIALOGSTYLE = 0x0040


def _windows_types():
    """Build the ctypes structures once, on first use."""
    import ctypes
    from ctypes import wintypes

    class OPENFILENAME(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("hInstance", wintypes.HINSTANCE),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", wintypes.LPARAM),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    class BROWSEINFO(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszDisplayName", wintypes.LPWSTR),
            ("lpszTitle", wintypes.LPCWSTR),
            ("ulFlags", wintypes.UINT),
            ("lpfn", ctypes.c_void_p),
            ("lParam", wintypes.LPARAM),
            ("iImage", ctypes.c_int),
        ]

    return OPENFILENAME, BROWSEINFO


def _filter_string(patterns: tuple[tuple[str, str], ...]) -> str | None:
    if not patterns:
        return None
    # The Win32 filter is a double-NUL terminated list of label/pattern pairs.
    return "\0".join(f"{label}\0{pattern}" for label, pattern in patterns) + "\0\0"


def _windows_pick_file(title: str, patterns: tuple[tuple[str, str], ...]) -> str | None:
    import ctypes
    from ctypes import wintypes

    OPENFILENAME, _ = _windows_types()
    comdlg32 = ctypes.WinDLL("comdlg32", use_last_error=True)
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(OPENFILENAME)]
    comdlg32.GetOpenFileNameW.restype = wintypes.BOOL

    buffer = ctypes.create_unicode_buffer(32768)
    spec = OPENFILENAME()
    spec.lStructSize = ctypes.sizeof(OPENFILENAME)
    spec.hwndOwner = None
    spec.lpstrFilter = _filter_string(patterns)
    spec.nFilterIndex = 1 if patterns else 0
    spec.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    spec.nMaxFile = len(buffer)
    spec.lpstrTitle = title
    spec.Flags = _OFN_EXPLORER | _OFN_FILEMUSTEXIST | _OFN_PATHMUSTEXIST | _OFN_NOCHANGEDIR | _OFN_READONLY

    try:
        if not comdlg32.GetOpenFileNameW(ctypes.byref(spec)):
            return None
    except OSError:
        return None
    return buffer.value or None


def _windows_pick_folder(title: str) -> str | None:
    import ctypes
    from ctypes import wintypes

    _, BROWSEINFO = _windows_types()
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFO)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL

    # The shell dialog lives in COM; initialising is harmless when it is
    # already done and keeps the call working from an HTTP worker thread.
    initialized = False
    try:
        initialized = ole32.CoInitialize(None) in (0, 1)  # S_OK, S_FALSE
    except OSError:
        initialized = False

    try:
        display = ctypes.create_unicode_buffer(260)
        info = BROWSEINFO()
        info.hwndOwner = None
        info.pidlRoot = None
        info.pszDisplayName = ctypes.cast(display, wintypes.LPWSTR)
        info.lpszTitle = title
        info.ulFlags = _BIF_RETURNONLYFSDIRS | _BIF_NEWDIALOGSTYLE
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return None
        try:
            path_buffer = ctypes.create_unicode_buffer(32768)
            if not shell32.SHGetPathFromIDListW(pidl, path_buffer):
                return None
            return path_buffer.value or None
        finally:
            try:
                ole32.CoTaskMemFree(pidl)
            except OSError:
                pass
    except OSError:
        return None
    finally:
        if initialized:
            try:
                ole32.CoUninitialize()
            except OSError:
                pass
