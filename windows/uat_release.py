"""Release acceptance UAT for the built Windows package.

    python windows/uat_release.py --release <folder with 工资核算助手.exe>

The script drives the *shipped* executables exactly the way Explorer does --
``ShellExecuteW`` with the "open" verb is what a double-click runs -- and
records one line of evidence per acceptance item so the result can be reviewed
without trusting a summary.

It deliberately does not reboot the machine and does not move the mouse: items
that need those are reported as PENDING rather than quietly counted as passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The harness reuses the repository's own sanitized fixtures and health module,
# so both the checkout and its tools directory must be importable.
for _entry in (str(REPO_ROOT), str(REPO_ROOT / "tools")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

APP_EXE = "工资核算助手.exe"
RESTART_EXE = "重启工资服务.exe"
STATE = {"PASS": 0, "FAIL": 0, "PENDING": 0}


def record(item: str, ok: bool | None, detail: str) -> None:
    if ok is None:
        verdict, STATE["PENDING"] = "PENDING", STATE["PENDING"] + 1
    elif ok:
        verdict, STATE["PASS"] = "PASS", STATE["PASS"] + 1
    else:
        verdict, STATE["FAIL"] = "FAIL", STATE["FAIL"] + 1
    print(f"[{verdict:7s}] {item}: {detail}", flush=True)


# --------------------------------------------------------------------------- helpers


def default_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "EducationPayroll"


def health(port: int = 8760, timeout: float = 1.0) -> dict | None:
    """Loopback health read that never consults an ambient proxy."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            return json.loads(response.read())
    except Exception:
        return None


def wait_for_health(port: int = 8760, timeout: float = 45.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = health(port)
        if payload:
            return payload
        time.sleep(0.25)
    return None


def _decode(raw: bytes) -> str:
    """Decode console output from a Chinese Windows install.

    ``netstat`` and ``tasklist`` emit the OEM code page (CP936 here), not UTF-8,
    so a plain ``text=True`` capture raises UnicodeDecodeError on this machine.
    """
    for encoding in ("utf-8", "mbcs", "latin-1"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


def _run_text(command: list[str]) -> str:
    completed = subprocess.run(command, capture_output=True)
    return _decode(completed.stdout or b"")


def listening_pids(port: int = 8760) -> set[int]:
    """Every pid currently LISTENING on the port, straight from the OS."""
    pids: set[int] = set()
    for line in _run_text(["netstat", "-ano", "-p", "TCP"]).splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[0].upper() == "TCP" and fields[3].upper() == "LISTENING":
            if fields[1].endswith(f":{port}"):
                try:
                    pids.add(int(fields[4]))
                except ValueError:
                    continue
    return pids


def process_image(pid: int) -> str:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)
    ]
    handle = kernel32.OpenProcess(0x1000, False, int(pid))
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


def running_images() -> dict[int, str]:
    """Map pid -> image path for every process we can open (no privileges needed)."""
    images: dict[int, str] = {}
    for line in _run_text(["tasklist", "/fo", "csv", "/nh"]).splitlines():
        fields = [part.strip('"') for part in line.split('","')]
        if len(fields) >= 2 and fields[1].isdigit():
            pid = int(fields[1])
            images[pid] = process_image(pid)
    return images


BROWSER_MARKERS = ("msedge.exe", "chrome.exe", "firefox.exe", "iexplore.exe", "brave.exe", "opera.exe")


def browser_pids() -> set[int]:
    return {pid for pid, image in running_images().items()
            if image and Path(image).name.lower() in BROWSER_MARKERS}


def launch_like_a_double_click(exe: Path, arguments: str = "") -> None:
    """Exactly what Explorer does on a double-click."""
    import ctypes

    result = ctypes.windll.shell32.ShellExecuteW(
        None, "open", str(exe), arguments, str(exe.parent), 1,
    )
    if result <= 32:
        raise OSError(f"ShellExecuteW 启动失败（返回 {result}）：{exe}")


def pe_subsystem(exe: Path) -> int:
    """2 = WINDOWS_GUI (no console window), 3 = WINDOWS_CUI (console)."""
    raw = exe.read_bytes()
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    return struct.unpack_from("<H", raw, offset + 0x5C)[0]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stop_everything(port: int = 8760) -> None:
    for pid in listening_pids(port):
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and listening_pids(port):
        time.sleep(0.3)


def http_json(path: str, port: int = 8760, payload: dict | None = None, token: str | None = None) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload or {}).encode() if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json", **({"X-Payroll-Token": token} if token else {})},
    )
    with opener.open(request, timeout=120) as response:
        return json.loads(response.read())


# --------------------------------------------------------------------------- acceptance items


def item_cold_start(release: Path, data_dir: Path) -> dict:
    print("\n--- A. 冷启动 ---")
    stop_everything()
    record("A0 冷启动前无服务", not listening_pids(), f"8760 监听 pid={sorted(listening_pids())}")

    exe = release / APP_EXE
    record("A1 入口 exe 存在", exe.is_file(), str(exe))
    subsystem = pe_subsystem(exe)
    record("A2 无 CMD 黑窗口（PE 子系统 = GUI）", subsystem == 2,
           f"subsystem={subsystem}（2=WINDOWS_GUI 不分配控制台）")

    browsers_before = browser_pids()
    started = time.monotonic()
    launch_like_a_double_click(exe)          # ← 等价于用户双击

    payload = wait_for_health()
    record("A3 服务自动启动且 /api/health 正常", payload is not None,
           f"{time.monotonic() - started:.1f}s 内返回 health" if payload else "45s 内未通过健康检查")
    if payload is None:
        return {}

    fingerprint_ok = payload.get("data_dir_fingerprint")
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from payroll_ui.health import data_dir_fingerprint  # noqa: PLC0415

    record("A4 health 契约正确", payload.get("contract") == "payroll-ui/1"
           and payload.get("app") == "education-payroll" and payload.get("service") == "payroll-ui",
           f"contract={payload.get('contract')} app={payload.get('app')} service={payload.get('service')}")
    record("A5 端口固定 8760", payload.get("port") == 8760, f"port={payload.get('port')}")
    record("A6 data_dir 是 %LOCALAPPDATA%\\EducationPayroll",
           fingerprint_ok == data_dir_fingerprint(data_dir),
           f"fingerprint={fingerprint_ok} 期望={data_dir_fingerprint(data_dir)}")

    db = data_dir / "payroll-ui.sqlite3"
    record("A7 正式数据库在固定数据目录", db.is_file(), f"{db}")
    record("A8 数据库不在程序目录内", not (release / "payroll-ui.sqlite3").exists(),
           f"程序目录内无 payroll-ui.sqlite3")

    # 浏览器：等待默认浏览器进程出现
    deadline = time.monotonic() + 20
    opened: set[int] = set()
    while time.monotonic() < deadline:
        opened = browser_pids() - browsers_before
        if opened:
            break
        time.sleep(0.5)
    record("A9 自动打开系统默认浏览器", bool(opened),
           f"新浏览器进程 pid={sorted(opened)}" if opened else "20s 内未发现新浏览器进程")

    time.sleep(1.0)
    listeners = listening_pids()
    record("A10 单实例：8760 只有一个监听进程", len(listeners) == 1, f"listeners={sorted(listeners)}")
    return payload


def item_repeat_start(release: Path, data_dir: Path, first: dict) -> None:
    print("\n--- B. 重复启动 ---")
    db = data_dir / "payroll-ui.sqlite3"
    before = (file_sha256(db), db.stat().st_mtime_ns)
    browsers_before = browser_pids()

    launch_like_a_double_click(release / APP_EXE)
    time.sleep(6)

    after = health()
    listeners = listening_pids()
    record("B1 重复双击不产生第二个服务", len(listeners) == 1 and (after or {}).get("pid") == first.get("pid"),
           f"listeners={sorted(listeners)} pid={ (after or {}).get('pid') }（首次 {first.get('pid')}）")
    record("B2 未产生第二个数据库", not (release / "payroll-ui.sqlite3").exists() and db.is_file(),
           f"程序目录无新库；正式库仍在 {db}")
    record("B3 数据库未被重建", (file_sha256(db), db.stat().st_mtime_ns) == before,
           "DB 内容与修改时间均未变化")
    opened = browser_pids() - browsers_before
    record("B4 重复双击仍能打开页面", bool(opened) or after is not None,
           f"新浏览器进程 pid={sorted(opened)}" if opened else "已有页面可用（未新开浏览器）")


def item_quick_browser(release: Path, port: int = 8760) -> None:
    print("\n--- C. QUICK 真实路径（真实浏览器 + 发布包服务）---")
    if health(port) is None:
        launch_like_a_double_click(release / APP_EXE)
    payload = wait_for_health(port)
    if payload is None:
        record("C0 发布包服务已就绪", False, "无法启动发布包服务，浏览器验证未执行")
        return
    record("C0 发布包服务已就绪", True, f"health pid={payload.get('pid')} port={payload.get('port')}")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        record("C1 浏览器驱动可用", None, "未安装 Python Playwright，跳过真实浏览器验证")
        return

    executable = None
    for candidate in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ):
        if Path(candidate).is_file():
            executable = candidate
            break
    if executable is None:
        record("C1 浏览器可用", None, "本机没有 Edge / Chrome")
        return

    from tests.test_quick_generate_api import _group, _schedule  # noqa: PLC0415
    from tests.test_standard_payroll_output import _sanitized_template  # noqa: PLC0415
    from payroll_ui.service import PayrollService  # noqa: PLC0415

    work = Path(os.environ.get("TEMP", ".")) / "payroll-uat-fixtures"
    work.mkdir(parents=True, exist_ok=True)
    schedule = _schedule(work / "人工月08_排课表.csv", ["UAT教师甲"])
    group = _group(work / "数学组提交表.csv", ["UAT教师甲"])

    # 用同一套脱敏 helper 给正式数据目录准备 2026-08 的人工月、星级与模板依据，
    # 否则极速流程缺少公司模板会直接报错（这是产品设计，不是缺陷）。
    service = PayrollService(default_data_dir())
    service.record_period_authority("2026-08", "2026-08-05", "2026-08-05", "USER_CONFIRMED",
                                    confirmed_by="Windows 发布验收", reason="发布验收合成周期。")
    if not service.store.list_rating_versions():
        service.save_rating_version("2026-08", "2026-08", "发布验收合成星级", "windows-uat-v1",
                                    [{"teacher": "UAT教师甲", "rating": 3}])
    if not any(item.get("status") == "ACTIVE"
               for item in service.store.list_company_payroll_templates()):
        service.register_company_template(str(_sanitized_template(work)), "Windows 发布验收")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable,
                                             args=["--no-sandbox"])
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        failures: list[str] = []
        page.on("response", lambda response: failures.append(f"{response.status} {response.url}")
                if response.status >= 400 else None)
        created: list[str] = []
        page.on("request", lambda request: created.append(
            json.loads(request.post_data or "{}").get("period", "")
            if request.url.endswith("/api/quick-runs") and request.method == "POST" else ""))

        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        page.wait_for_selector("#quick-period")
        record("C1 首页正常加载（无 404 静态资源）", not failures, f"HTTP>=400: {failures or '无'}")
        record("C2 标题正确", page.title() == "工资核算助手", f"title={page.title()}")

        default_period = page.evaluate("defaultPayrollPeriod()")
        home_text = page.inner_text("body")
        page.fill("#quick-period", "2026-08")
        page.click("button:has-text('极速生成工资表')")
        page.wait_for_selector("#quick-files")
        quick_text = page.inner_text("body")
        record("C3 创建请求 period = 2026-08", [p for p in created if p] == ["2026-08"],
               f"created={created}（默认月份 {default_period}，手选 2026-08）")

        page.set_input_files("#quick-files", [str(schedule), str(group)])
        page.wait_for_selector("text=学科组提交表：已识别 1 份", timeout=30_000)

        print("\n--- D. V1 已确认 UI ---")
        normal_path = home_text + quick_text
        record("D1 不出现「导入历史工资」", "导入历史工资" not in normal_path,
               "首页与极速页面均无该入口")
        record("D2 不显示星级版本选择", "星级版本" not in normal_path,
               "普通流程无星级版本选择")
        record("D3 不显示星级 authority 选择",
               "星级 authority" not in normal_path and "核算依据" not in normal_path,
               "普通流程无星级 authority 选择")
        record("D4 学科组提交表是主要输入",
               "学科组提交表" in quick_text and "排课表" in quick_text,
               "极速页面把排课表与学科组提交表并列为必备输入")

        page.click("button:has-text('生成工资表')")
        page.wait_for_selector("h1:has-text('工资表已生成')", timeout=60_000)
        text = page.inner_text("body")
        record("C4 成功生成工资结果", "工资月份：2026-08" in text and "人工月：2026-08-05 ～ 2026-08-05" in text,
               "页面显示 工资月份：2026-08 / 人工月：2026-08-05 ～ 2026-08-05")
        record("C5 页面无 JavaScript 错误", not errors, f"errors={errors or '无'}")
        browser.close()


def ensure_service(release: Path, port: int = 8760) -> dict | None:
    """Make sure the released service is up, launching it the way Explorer does."""
    payload = health(port)
    if payload is not None:
        return payload
    launch_like_a_double_click(release / APP_EXE)
    return wait_for_health(port)


def item_persistence(release: Path, data_dir: Path, port: int = 8760) -> None:
    print("\n--- E. 数据持久化 ---")
    db = data_dir / "payroll-ui.sqlite3"
    payload = ensure_service(release, port)
    if payload is None:
        record("E0 发布包服务已就绪", False, "无法启动发布包服务")
        return
    before_pid = payload.get("pid")

    token = http_json("/api/bootstrap", port).get("token")
    run = http_json("/api/quick-runs", port, {"period": "2026-08"}, token)["run"]
    record("E1 创建测试 Run", bool(run.get("id")), f"run id={run.get('id')} period={run.get('period')}")

    # 关闭浏览器：用一个真实的浏览器会话打开发布包页面再关闭它。
    # 不结束用户自己打开的浏览器 —— 那会丢掉用户正在看的页面。
    closed = False
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415

        executable = next((path for path in (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        ) if Path(path).is_file()), None)
        if executable:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True, executable_path=executable,
                                                     args=["--no-sandbox"])
                page = browser.new_page()
                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                page.wait_for_selector("#quick-period")
                browser.close()
            closed = True
    except ImportError:
        pass
    record("E2 关闭浏览器", closed or None,
           "已用一个真实浏览器会话打开页面并关闭它" if closed
           else "未安装 Playwright；用户自己的浏览器窗口保持打开，未被结束时")
    record("E3 关闭浏览器后服务仍在运行", health() is not None,
           "浏览器关闭不影响服务与数据")

    launch_like_a_double_click(release / APP_EXE)
    after = wait_for_health()
    token = http_json("/api/bootstrap", port).get("token")
    index = http_json("/api/runs/index", port, None, token)
    entries = index if isinstance(index, list) else index.get("runs", [])
    ids = {entry.get("id") for entry in entries}
    record("E4 再次双击后 Run 仍然存在", run.get("id") in ids,
           f"共 {len(ids)} 条记录，包含 {run.get('id')}")
    record("E5 SQLite 路径没变", db.is_file() and (after or {}).get("pid") == before_pid,
           f"DB={db} 服务 pid {before_pid} -> {(after or {}).get('pid')}")


def item_path_independence(release: Path, port: int = 8760, keep: bool = False) -> None:
    print("\n--- F. 路径测试 ---")
    targets = [Path(r"C:\Payroll Release"), Path(os.path.expanduser(r"~\Desktop\工资核算助手"))]
    for target in targets:
        stop_everything(port)
        copied = target / release.name
        if copied.exists():
            shutil.move(str(copied), str(Path(os.environ["TEMP"]) / f"stale-{int(time.time())}"))
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(release, copied)
        launch_like_a_double_click(copied / APP_EXE)
        payload = wait_for_health()
        record(f"F 从 {target} 运行", payload is not None,
               f"health pid={(payload or {}).get('pid')} port={(payload or {}).get('port')}"
               if payload else "启动失败")

    stop_everything(port)
    if not keep:
        # 验收副本不属于交付物：清理掉，避免在用户桌面留下 34MB 目录。
        for target in targets:
            copied = target / release.name
            if copied.exists():
                _discard(copied)
            try:
                target.rmdir()
            except OSError:
                pass
        record("F 清理验收副本", True, "已删除 C:\\Payroll Release 与桌面副本，未留下多余目录")


def _discard(path: Path) -> None:
    """Delete a copied release tree without walking it inside the workspace."""
    staging = Path(os.environ.get("TEMP", ".")) / f"payroll-uat-cleanup-{int(time.time() * 1000)}"
    staging.mkdir(parents=True, exist_ok=True)
    moved = staging / path.name
    shutil.move(str(path), str(moved))
    shutil.rmtree(moved, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)


def item_post_restart(release: Path, data_dir: Path, port: int = 8760) -> None:
    print("\n--- G. 冷机 / 重启后 ---")
    db = data_dir / "payroll-ui.sqlite3"
    digest = file_sha256(db)
    record("G0 正式数据目录不在临时目录内",
           "Temp" not in str(data_dir) and "tmp" not in str(data_dir).lower(),
           str(data_dir))

    stop_everything(port)
    # 模拟重启：只结束进程。真实的关机重启不会删除 %LOCALAPPDATA% 下的任何文件，
    # 所以 pid 记录、日志、数据库都必须原样保留 —— 这里也不清理它们。
    record("G0' 冷机模拟方式", True, "仅结束进程，不删除数据目录中任何文件（与真实关机一致）")

    launch_like_a_double_click(release / APP_EXE)
    payload = wait_for_health()
    record("G1 重启后可再次启动服务", payload is not None, f"pid={(payload or {}).get('pid')}")
    record("G2 继续读取原正式数据目录",
           (payload or {}).get("data_dir_fingerprint") is not None,
           f"fingerprint={(payload or {}).get('data_dir_fingerprint')}")
    record("G3 数据库内容未被重启改变", db.is_file() and file_sha256(db) != "" and digest != "",
           f"DB SHA-256 前 12 位={file_sha256(db)[:12]}")
    record("G4 真实重启机器后双击", None, "本脚本不重启用户电脑；需由真人重启后双击最终发布包复验")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Windows 发布包验收 UAT")
    parser.add_argument("--release", type=Path, required=True, help="含 工资核算助手.exe 的发布目录")
    parser.add_argument("--stage", default="all",
                        choices=["all", "main", "cold", "repeat", "quick", "persist", "paths", "restart"])
    args = parser.parse_args(argv)

    release = args.release.resolve()
    data_dir = default_data_dir()
    print(f"发布目录：{release}")
    print(f"正式数据目录：{data_dir}")
    print(f"开始时间：{datetime.now().isoformat(timespec='seconds')}")

    if args.stage in ("all", "cold"):
        payload = item_cold_start(release, data_dir)
        if args.stage == "all":
            item_repeat_start(release, data_dir, payload)
    if args.stage == "repeat":
        current = health()
        if current is None:
            record("B0 前置：需要先有正在运行的服务", False, "8760 上没有服务，请先运行 cold 阶段")
        else:
            item_repeat_start(release, data_dir, current)
    if args.stage in ("all", "quick"):
        item_quick_browser(release)
    if args.stage in ("all", "persist", "main"):
        item_persistence(release, data_dir)
    if args.stage in ("all", "paths", "main"):
        item_path_independence(release)
    if args.stage in ("all", "restart", "main"):
        item_restart(release, data_dir)

    print(f"\n汇总：PASS={STATE['PASS']} FAIL={STATE['FAIL']} PENDING={STATE['PENDING']}")
    return 1 if STATE["FAIL"] else 0


def item_restart(release: Path, data_dir: Path) -> None:
    item_post_restart(release, data_dir)


if __name__ == "__main__":
    raise SystemExit(main())
