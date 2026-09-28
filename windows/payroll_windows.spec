# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows release.

Three executables are produced from one entry script, all sharing a single
``_internal`` runtime folder:

* ``EducationPayroll``      -- 工资核算助手：启动/复用服务并打开浏览器
* ``RestartPayrollService`` -- 重启工资服务：只结束本启动器启动的服务
* ``PayrollCommandLine``    -- 工资核算助手-命令行：诊断用

The build script renames them to their Chinese display names.  That keeps
PyInstaller away from non-ASCII executable names during the build, while the
entry point still reads its own file name to decide what to do.

Two data sets must be shipped explicitly, otherwise the frozen UI answers 404
on its own assets or the core rules fail to load:

* ``payroll_ui/static`` -- the browser UI (index.html / app.js / app.css /
  teacher.html).  ``payroll_ui/__main__.py`` and ``paths.static_root()`` both
  resolve it relative to the module, so it must keep its package path.
* ``config`` -- ``payroll_core/config/core_rules.py`` resolves
  ``Path(__file__).parents[2] / "config" / "core_rules_2026.yaml"``, which
  inside a bundle is ``<_MEIPASS>/config/core_rules_2026.yaml``.
"""
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
REPO_ROOT = SPEC_DIR.parent

ENTRY = REPO_ROOT / "tools" / "payroll_launcher" / "frozen_entry.py"

DATAS = [
    (str(REPO_ROOT / "payroll_ui" / "static"), "payroll_ui/static"),
    (str(REPO_ROOT / "config"), "config"),
]

HIDDEN_IMPORTS = [
    # The launcher imports these lazily, so name them explicitly rather than
    # trusting the analyzer to walk every branch of every runtime mode.
    "payroll_launcher",
    "payroll_launcher.cli",
    "payroll_launcher.paths",
    "payroll_launcher.lifecycle",
    "payroll_launcher.probe",
    "payroll_launcher.dialogs",
    "payroll_launcher.host",
    "payroll_launcher.service_mode",
    "payroll_ui.server",
    "payroll_ui.service",
    "payroll_ui.health",
    "payroll_ui.storage",
    "payroll_ui.native_dialogs",
    "payroll_ui.submissions",
    "payroll_ui.business",
    "payroll_ui.business_inputs",
    "payroll_ui.core_flow",
    "payroll_ui.assessment_flow",
    "payroll_ui.base_salary_import",
    "payroll_ui.period_document",
    "payroll_ui.support_department",
    "payroll_core",
    "payroll_core.calculation",
    "payroll_core.config.core_rules",
    "payroll_core.config.loader",
    "payroll_core.excel.final_workbook_contract",
    "payroll_core.excel.inspect",
    "payroll_core.excel.payroll",
    "payroll_core.excel.standard_workbook",
    "payroll_core.excel.writeback",
    "openpyxl",
    "xlrd",
    "yaml",
    "ctypes.wintypes",
]

# Nothing below is reachable from the application code; excluding them keeps a
# long-lived internal tool small without risking a runtime ImportError.
EXCLUDES = [
    "tkinter",
    "pytest",
    "_pytest",
    "setuptools",
    "pip",
    "numpy",
    "pandas",
    "matplotlib",
    "PIL",
    "IPython",
]

analysis = Analysis(
    [str(ENTRY)],
    pathex=[str(REPO_ROOT), str(REPO_ROOT / "tools")],
    binaries=[],
    datas=DATAS,
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

EXE_OPTIONS = dict(
    exclude_binaries=True,
    upx=False,
    debug=False,
    strip=False,
    bootloader_ignore_signals=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)


def build_exe(name: str, console: bool) -> EXE:
    return EXE(
        pyz,
        analysis.scripts,
        [],
        name=name,
        console=console,
        icon=None,
        **EXE_OPTIONS,
    )


app = build_exe("EducationPayroll", console=False)
restart = build_exe("RestartPayrollService", console=False)
command_line = build_exe("PayrollCommandLine", console=True)

bundle = COLLECT(
    app,
    restart,
    command_line,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EducationPayroll",
)
