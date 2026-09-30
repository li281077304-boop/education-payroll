# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows release.

Three executables are produced from one entry script:

* ``EducationPayroll``      -- 工资核算助手：启动/复用服务并打开浏览器
* ``RestartPayrollService`` -- 重启工资服务：只结束本启动器启动的服务
* ``PayrollCommandLine``    -- 工资核算助手-命令行：诊断用

Two deployment shapes are used on purpose:

* the **main entry** is an *onedir* build: a folder with ``EducationPayroll.exe``
  plus a shared ``_internal`` runtime.  It is the only thing a normal user opens,
  so keeping the runtime in ``_internal`` keeps startup fast and the exe small.
* the two **maintenance tools** are *onefile* builds.  They are copied into the
  ``tools/`` sub-folder of the release, where a PyInstaller onedir executable
  would fail: such an executable resolves ``sys._MEIPASS`` to an ``_internal``
  folder *next to itself*, which would not exist once it is moved out of the
  main folder.  A onefile build unpacks its own runtime into a temporary folder
  at every launch, so it runs from any location -- exactly what ``tools/`` needs.

The build script renames the executables to their Chinese display names and
assembles the final release tree::

    dist/EducationPayroll/           <- onedir bundle (main app)
        EducationPayroll.exe
        _internal/
    dist/RestartPayrollService.exe   <- onefile maintenance tool
    dist/PayrollCommandLine.exe      <- onefile maintenance tool

Renaming after the build keeps PyInstaller away from non-ASCII executable
names during the build, while the entry point still reads its own file name to
decide what to do.

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

COMMON_EXE_OPTIONS = dict(
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

# The main entry point: an onedir build so the runtime is shared instead of
# re-extracted on every launch.
app = EXE(
    pyz,
    analysis.scripts,
    [],
    name="EducationPayroll",
    console=False,
    icon=None,
    exclude_binaries=True,
    **COMMON_EXE_OPTIONS,
)

bundle = COLLECT(
    app,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="EducationPayroll",
)


def maintenance_tool(name: str, console: bool) -> EXE:
    """Build one self-contained (onefile) maintenance executable.

    Onefile embeds the interpreter, the bundled modules and the data files in a
    single exe, so the result can live in ``tools/`` and still run.
    """
    return EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name=name,
        console=console,
        icon=None,
        exclude_binaries=False,
        **COMMON_EXE_OPTIONS,
    )


restart = maintenance_tool("RestartPayrollService", console=False)
command_line = maintenance_tool("PayrollCommandLine", console=True)
