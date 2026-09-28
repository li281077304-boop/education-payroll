"""Windows browser UAT for the end-user QUICK entry, using synthetic data.

``tests/test_payroll_v1_browser_uat.py`` drives Chromium through the Node
Playwright binding and hardcodes the macOS Chrome bundle path, so it cannot run
on Windows.  This is its Windows counterpart, and it is not a relaxed version
of it: it drives the same production ``app.js``, through the same real
``PayrollHttpServer``, over a real browser, with the same assertions about the
created payroll period.

Only synthetic, sanitized fixtures are used.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from threading import Thread

import pytest

from payroll_ui.server import PayrollHttpServer
from tests.test_quick_generate_api import _group, _schedule, _service

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows browser UAT")

REPO_ROOT = Path(__file__).parents[1]

# Chromium-based browsers that ship with, or are commonly installed on,
# Windows.  Edge is present on every supported Windows install, so this suite
# never needs to download a browser of its own.
_WINDOWS_BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
)


def _browser_executable() -> str | None:
    for candidate in _WINDOWS_BROWSERS:
        if Path(candidate).is_file():
            return candidate
    return None


@pytest.fixture(scope="module")
def browser():
    playwright_api = pytest.importorskip(
        "playwright.sync_api", reason="Python Playwright is needed for the live browser UAT",
    )
    executable = _browser_executable()
    if executable is None:
        pytest.skip("本机没有可用的 Chromium 浏览器（Edge / Chrome）")

    with playwright_api.sync_playwright() as playwright:
        instance = playwright.chromium.launch(
            headless=True, executable_path=executable,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            yield instance
        finally:
            instance.close()


def _serve(tmp_path: Path, monkeypatch, teachers: list[str]):
    service = _service(tmp_path, monkeypatch, teachers)
    server = PayrollHttpServer(("127.0.0.1", 0), service, REPO_ROOT / "payroll_ui" / "static")
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    return server, worker


def test_quick_entry_generates_august_payroll_in_a_real_browser(tmp_path, monkeypatch, browser):
    """A. 冷启动 + C. QUICK 真实路径（默认月份 → 手选 2026-08 → 上传 → 生成）。"""
    schedule = _schedule(tmp_path / "人工月08_排课表.csv", ["UAT教师甲"])
    group = _group(tmp_path / "数学组提交表.csv", ["UAT教师甲"])
    server, worker = _serve(tmp_path, monkeypatch, ["UAT教师甲"])
    try:
        page = browser.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        created: list[str] = []

        def remember_created_period(request) -> None:
            period = _created_period(request)
            if period:
                created.append(period)

        page.on("request", remember_created_period)

        page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")

        # ---- 首页：默认工资月份必须与产品规则一致
        page.wait_for_selector("#quick-period")
        default_period = page.evaluate("defaultPayrollPeriod()")
        assert page.input_value("#quick-period") == default_period

        # ---- 普通用户路径不得出现历史工资导入或星级选择
        home_text = page.inner_text("body")
        assert "导入历史工资" not in home_text
        assert "星级版本" not in home_text
        assert "极速生成工资表" in home_text

        page.fill("#quick-period", "2026-08")
        page.click("button:has-text('极速生成工资表')")
        page.wait_for_selector("#quick-files")

        quick_text = page.inner_text("body")
        assert "一键生成工资表" in quick_text
        # 学科组提交表是主要输入，与排课表并列出现
        assert "排课表" in quick_text
        assert "学科组提交表" in quick_text
        assert "导入历史工资" not in quick_text
        assert "星级版本" not in quick_text

        # ---- 创建请求的月份必须是用户选择的 2026-08
        assert created == ["2026-08"], f"创建核算的 period 不是 2026-08：{created}"

        page.set_input_files("#quick-files", [str(schedule), str(group)])
        page.wait_for_selector("text=学科组提交表：已识别 1 份", timeout=20_000)

        page.click("button:has-text('生成工资表')")
        page.wait_for_selector("h1:has-text('工资表已生成')", timeout=30_000)

        result_text = page.inner_text("body")
        assert "工资月份：2026-08" in result_text
        assert "人工月：2026-08-05 ～ 2026-08-05" in result_text
        assert not page_errors, f"页面出现 JavaScript 错误：{page_errors}"
        page.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=15)


def test_professional_view_offers_the_support_department_as_an_optional_supplement(
    tmp_path, monkeypatch, browser,
):
    """D. V1 已确认 UI：支持部是次级补充输入，不是必填项。"""
    schedule = _schedule(tmp_path / "人工月08_排课表.csv", ["UAT教师甲"])
    group = _group(tmp_path / "数学组提交表.csv", ["UAT教师甲"])
    server, worker = _serve(tmp_path, monkeypatch, ["UAT教师甲"])
    try:
        page = browser.new_page()
        page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="networkidle")
        page.wait_for_selector("#quick-period")
        page.fill("#quick-period", "2026-08")
        page.click("button:has-text('极速生成工资表')")
        page.wait_for_selector("#quick-files")
        page.set_input_files("#quick-files", [str(schedule), str(group)])
        page.wait_for_selector("text=学科组提交表：已识别 1 份", timeout=20_000)
        page.click("button:has-text('生成工资表')")
        page.wait_for_selector("h1:has-text('工资表已生成')", timeout=30_000)

        page.click("button:has-text('查看专业核算详情')")
        page.wait_for_selector("text=准备核算材料", timeout=20_000)
        text = page.inner_text("body")

        # 支持部资料以“补充资料”出现，并明确说明没有也可以继续
        assert "支持部" in text, "专业核算材料页应显示支持部资料入口"
        assert "没有也可以继续" in text, "支持部资料必须被标注为可选补充，而不是必填"
        page.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=15)


def _created_period(request) -> str:
    """Record the ``period`` of a create-run request, ignoring everything else."""
    if not request.url.endswith("/api/quick-runs") or request.method != "POST":
        return ""
    try:
        import json

        return str(json.loads(request.post_data or "{}").get("period", ""))
    except ValueError:
        return ""


def test_windows_browser_uat_can_always_find_a_browser():
    """The suite must never silently pass by skipping on a normal Windows box."""
    assert _browser_executable() is not None, (
        "本机没有 Edge / Chrome，Windows 浏览器 UAT 无法真实执行。"
        f"已探测：{list(_WINDOWS_BROWSERS)}"
    )


def test_the_browser_driver_is_available():
    shutil.which("node")  # recorded for the report; the Windows driver is Python-based
    import importlib.util

    assert importlib.util.find_spec("playwright") is not None
