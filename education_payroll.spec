# PyInstaller onedir build for the local Windows RC.
from pathlib import Path

project = Path(SPECPATH)
hiddenimports = ["payroll_ui", "payroll_ui.__main__", "payroll_ui.platform"]
a = Analysis(
    [str(project / "launcher.py")],
    pathex=[str(project)],
    datas=[(str(project / "payroll_ui" / "static"), "payroll_ui/static")],
    hiddenimports=hiddenimports,
    excludes=["tkinter.test"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Education Payroll",
    debug=False,
    console=True,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    argv_emulation=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Education Payroll",
)
