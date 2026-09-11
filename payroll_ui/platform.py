"""Native desktop adapters used by the local UI."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_FILETYPES = [("Excel 工作簿", "*.xls *.xlsx *.xlsm"), ("所有文件", "*.*")]


def pick_excel_files(*, multiple: bool = False) -> list[str]:
    """Return Excel files explicitly selected with the native picker."""
    if sys.platform == "darwin":
        picker = (
            'choose file with prompt "选择 Excel 文件" of type '
            '{"org.openxmlformats.spreadsheetml.sheet", "com.microsoft.excel.xls", '
            '"com.microsoft.excel.xlsm"}'
            f'{" with multiple selections allowed" if multiple else ""}'
        )
        script = f'POSIX paths of ({picker})' if multiple else f'POSIX path of ({picker})'
        try:
            selected = subprocess.check_output(
                ["osascript", "-e", script], text=True, stderr=subprocess.DEVNULL
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            return []
        return [value.strip() for value in selected.splitlines() if value.strip()]

    if sys.platform == "win32":
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                selected = filedialog.askopenfilenames(
                    title="选择 Excel 文件", filetypes=_FILETYPES
                ) if multiple else filedialog.askopenfilename(
                    title="选择 Excel 文件", filetypes=_FILETYPES
                )
            finally:
                root.destroy()
            values = selected if isinstance(selected, (tuple, list)) else (selected,)
            return [str(Path(value).resolve()) for value in values if value]
        except Exception:
            return []

    return []
