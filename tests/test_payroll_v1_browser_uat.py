"""Live browser UAT for the end-user quick payroll entry, using private test data."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from threading import Thread

import pytest

from payroll_ui.server import PayrollHttpServer
from tests.test_quick_generate_api import _group, _schedule, _service


def test_browser_quick_entry_selects_august_uploads_materials_and_generates(tmp_path, monkeypatch):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed for the live browser UAT")
    preflight = subprocess.run(
        [node, "-e", "const fs=require('fs');process.exit(fs.existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')?0:2)"],
        capture_output=True, text=True,
    )
    if preflight.returncode:
        pytest.skip("Playwright Chromium is not installed in this environment")

    service = _service(tmp_path, monkeypatch, ["UAT教师甲"])
    schedule = _schedule(tmp_path / "人工月08_排课表.csv", ["UAT教师甲"])
    group = _group(tmp_path / "数学组提交表.csv", ["UAT教师甲"])
    server = PayrollHttpServer(("127.0.0.1", 0), service, Path(__file__).parents[1] / "payroll_ui" / "static")
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        script = r'''
const {chromium}=require('playwright'), assert=require('assert');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',args:['--no-sandbox','--disable-dev-shm-usage']});
  try {
    const page=await browser.newPage();
    const pageErrors=[];page.on('pageerror',error=>pageErrors.push(error.message));
    await page.goto(process.argv[1],{waitUntil:'networkidle'});
    await page.locator('#quick-period').waitFor();
    assert(await page.getByRole('button',{name:'极速生成工资表'}).isVisible());
    assert.equal(await page.locator('#quick-period').inputValue(),await page.evaluate(()=>defaultPayrollPeriod()));
    await page.locator('#quick-period').fill('2026-08');
    let createdPeriod='';
    page.on('request',request=>{
      if(request.url().endsWith('/api/quick-runs')&&request.method()==='POST')createdPeriod=JSON.parse(request.postData()).period;
    });
    await page.getByRole('button',{name:'极速生成工资表'}).click();
    await page.locator('#quick-files').waitFor();
    assert.equal(createdPeriod,'2026-08');
    assert(await page.getByRole('heading',{name:'一键生成工资表'}).isVisible());
    await page.locator('#quick-files').setInputFiles(process.argv.slice(2));
    await page.getByText('学科组提交表：已识别 1 份').waitFor({timeout:20000});
    await page.getByRole('button',{name:'生成工资表'}).click();
    await page.getByRole('heading',{name:'工资表已生成'}).waitFor({timeout:30000});
    const resultText=await page.locator('body').innerText();
    assert(resultText.includes('工资月份：2026-08'));
    assert(resultText.includes('人工月：2026-08-05 ～ 2026-08-05'));
    assert.deepEqual(pageErrors,[]);
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run(
            [node, "-e", script, f"http://127.0.0.1:{server.server_port}/", str(schedule), str(group)],
            capture_output=True, text=True, timeout=90,
        )
        assert result.returncode == 0, result.stderr
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
