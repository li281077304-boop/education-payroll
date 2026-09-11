# Windows onedir build for the local RC.
from pathlib import Path

project = Path(SPECPATH)
a = Analysis(
    [str(project / "launcher.py")],
    pathex=[str(project)],
    datas=[
        (str(project / "payroll_ui" / "static"), "payroll_ui/static"),
        # Core configuration is resolved relative to payroll_core at runtime.
        (str(project / "config" / "core_rules_2026.yaml"), "config"),
    ],
    hiddenimports=["payroll_ui", "payroll_ui.__main__", "payroll_ui.platform"],
    excludes=["tkinter.test"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Education Payroll", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="Education Payroll")
