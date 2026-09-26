"""关键异步动作的按钮反馈 + 缺失模板时的跳转。

2026-09-26 UAT 观察：点击后没有可见反馈不可接受；「生成工资表」在缺少公司模板时
必须直接带用户去设置模板，并在设置成功后回到原来的工资预览继续。

这些断言跑的是生产 app.js（Node + vm + 可控 fetch/定时器），覆盖的是 api() 里那套
统一的按钮忙碌机制，因此对所有按钮同时成立：
- 点击后立即 disabled + 明确的"正在处理"文字；
- 成功/失败都有反馈；
- 请求未结束前不会恢复按钮（防重复提交）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parents[1]
APP_JS = REPO_ROOT / "payroll_ui" / "static" / "app.js"

_HARNESS = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[2], 'utf8')
  .replace(/\(async \(\) => \{[\s\S]*?\}\)\(\)\.catch\([^\n]*\);\n/, '');
const script = process.argv[3];
const genericNode = {
  value: '', innerHTML: '', textContent: '', hidden: false, disabled: false, isConnected: true,
  focus() {}, scrollIntoView() {}, insertAdjacentHTML() {}, addEventListener() {},
  querySelector() { return genericNode; }, querySelectorAll() { return []; },
  classList: {add() {}, remove() {}},
};
const nodes = {'#message': genericNode, '#app': genericNode};
const pending = [];
const timers = [];
const calls = [];
const messages = [];
const context = {
  document: {
    querySelector(sel) { return nodes[sel] || genericNode; },
    querySelectorAll() { return []; },
    body: genericNode, activeElement: null, insertAdjacentHTML() {},
    createElement() { return Object.assign({}, genericNode); },
  },
  window: {
    location: {href: 'http://127.0.0.1:8760/'},
    setTimeout(fn) { timers.push(fn); return timers.length; },
    clearTimeout() {},
  },
  console, URL, assert, calls, messages, pending, timers, __result: '',
  fetch: (url, options) => {
    calls.push({url: String(url), body: options && options.body});
    return new Promise((resolve, reject) => {
      pending.push((spec) => {
        const spec0 = spec || {};
        if (spec0.networkError) return reject(new Error(spec0.networkError));
        if (spec0.status && spec0.status >= 400) {
          return resolve({ok: false, status: spec0.status, headers: {get: () => 'application/json'},
                          json: async () => ({error: spec0.error || '失败'})});
        }
        return resolve({ok: true, status: 200, headers: {get: () => 'application/json'},
                        json: async () => (spec0.payload === undefined ? {} : spec0.payload)});
      });
    });
  },
};
vm.createContext(context);
vm.runInContext(source, context);
vm.runInContext(`
  var __flushed = 0;
  __flush = function () { const queued = timers.splice(0); queued.forEach(function (fn) { fn(); __flushed += 1; }); };
  renderRun = function () {};
  openRun = async function () {};
  showMessage = function (message, kind) { messages.push([String(message), kind || 'error']); };
  refreshAfterError = function (error) { messages.push([String((error && error.message) || error), 'refresh']); };
`, context);
(async () => {
  const value = vm.runInContext(script, context);
  if (value && typeof value.then === 'function') await value;
  if (typeof context.__result === 'string') process.stdout.write(context.__result);
})().catch((error) => { console.error((error && error.stack) || String(error)); process.exit(1); });
"""


def _run_ui(tmp_path, script: str) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    harness = tmp_path / "button-harness.cjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    completed = subprocess.run([node, str(harness), str(APP_JS), script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


_BUTTON_SETUP = """
button = {textContent: '自动核算', disabled: false, isConnected: true, focus() {}};
lastClickedActionButton = button;
"""


def test_a_clicked_button_is_disabled_with_a_busy_label_until_the_request_finishes(tmp_path):
    script = _BUTTON_SETUP + """
(async () => {
  const call = api('/api/runs/run-1/check', {method: 'POST', body: '{}'});
  assert.strictEqual(button.disabled, true, '请求进行中必须禁用按钮');
  assert.strictEqual(button.textContent, '正在重新核对…', button.textContent);
  pending.shift()({payload: {ok: true}});
  await call;
  __flush();
  assert.strictEqual(button.disabled, false, '请求结束后必须恢复按钮');
  assert.strictEqual(button.textContent, '自动核算');
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script).strip() == "ok"


def test_a_second_click_cannot_re_enable_the_button_early(tmp_path):
    script = _BUTTON_SETUP + """
(async () => {
  const first = api('/api/runs/run-1/check', {method: 'POST', body: '{}'});
  const second = api('/api/runs/run-1/check', {method: 'POST', body: '{}'});
  assert.strictEqual(button.disabled, true);
  pending.shift()({});
  await first;
  __flush();
  assert.strictEqual(button.disabled, true, '还有请求在飞就不能恢复按钮，避免重复提交');
  pending.shift()({});
  await second;
  __flush();
  assert.strictEqual(button.disabled, false);
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script).strip() == "ok"


def test_the_defer_button_says_what_it_is_actually_doing(tmp_path):
    script = _BUTTON_SETUP + """
(async () => {
  const call = api('/api/runs/run-1/base-salary-defer', {method: 'POST', body: '{}'});
  assert.strictEqual(button.textContent, '正在保存并核算…', button.textContent);
  pending.shift()({payload: {id: 'run-1', defer_outcome: {status: 'NEEDS_ATTENTION'}}});
  await call;
  __flush();
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script).strip() == "ok"
    source = APP_JS.read_text(encoding="utf-8")
    assert "暂不录入，先生成工资预览" in source, "按钮文字必须与实际动作一致"
    assert "暂不录入，先生成工资表" not in source


def test_a_failed_request_surfaces_an_actionable_message(tmp_path):
    script = _BUTTON_SETUP + """
(async () => {
  const call = api('/api/runs/run-1/check', {method: 'POST', body: '{}'});
  pending.shift()({status: 400, error: '排课周期不完整，请补齐后再生成最终工资表。'});
  let message = '';
  try { await call; } catch (error) { message = error.message; }
  assert.ok(message.includes('排课周期不完整'), message);
  __flush();
  assert.strictEqual(button.disabled, false, '失败后也要恢复按钮，让用户能重试');
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script).strip() == "ok"


def test_every_key_async_action_maps_to_a_named_busy_label(tmp_path):
    """接口路径 → 处理中文字必须成对存在，不能有按钮落到空白反馈."""
    script = _BUTTON_SETUP + """
(async () => {
  const cases = [
    ['/api/runs/run-1/check', '正在重新核对…'],
    ['/api/runs/run-1/preview', '正在核算…'],
    ['/api/runs/run-1/generate', '正在生成工资表…'],
    ['/api/runs/run-1/base-salary', '正在保存…'],
    ['/api/runs/run-1/period-window', '正在保存周期…'],
    ['/api/runs/run-1/renewal-confirm', '正在处理…'],
  ];
  for (const [path, expected] of cases) {
    button = {textContent: '按钮', disabled: false, isConnected: true, focus() {}};
    lastClickedActionButton = button;
    const call = api(path, {method: 'POST', body: '{}'});
    assert.strictEqual(button.disabled, true, path);
    assert.strictEqual(button.textContent, expected, path + ' → ' + button.textContent);
    pending.shift()({});
    await call;
    __flush();
  }
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script).strip() == "ok"


def test_missing_company_template_sends_the_user_to_the_template_setting_and_back(tmp_path):
    script = """
(async () => {
  const visited = [];
  authorityDashboard = async function (runId, focus) { visited.push([runId, focus]); };
  current = {id: 'run-1', period: '2026-08', mode: 'GENERATE'};
  const call = exportPayroll();
  assert.strictEqual(pending.length, 1, '第一个请求应当是导出路径建议');
  pending.shift()({payload: {path: '/tmp/工资表-2026-08.xlsx'}});
  for (let i = 0; i < 20 && pending.length === 0; i += 1) await null;
  assert.strictEqual(pending.length, 1, '第二个请求应当是最终生成');
  pending.shift()({status: 400, error: '尚未设置公司工资模板，请先在基础资料中选择公司工资模板。'});
  await call;
  assert.deepStrictEqual(visited, [['run-1', 'template']], JSON.stringify(visited));
  assert.ok(messages.some(([text]) => text.includes('公司工资模板')), JSON.stringify(messages));
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script).strip() == "ok"
    source = APP_JS.read_text(encoding="utf-8")
    # 模板保存成功后回到原来的工资预览，而不是让用户自己找回去。
    assert 'if (returnRunId) {' in source and "template" in source
