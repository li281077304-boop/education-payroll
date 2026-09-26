"""界面收口：人工月卡片、工资预览依据、以及 defer 按钮的真实跳转。

这些断言跑的是生产 app.js 本身（Node + vm + 假 fetch），不是复制一份逻辑：
- 人工月只是自然月兜底时，界面必须说清楚，并给出设置入口；
- 有人工月时必须显示周期与来源，且不再提"自然月月末"；
- 课表越界时必须给出越界提示；
- 「暂不录入」点一次就要真的走完核算并进入工资预览（或进入异常处理）。

Node 不可用时跳过，与仓库既有 UI 测试保持一致。
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
const app = process.argv[2];
const script = process.argv[3];
const source = fs.readFileSync(app, 'utf8')
  .replace(/\(async \(\) => \{[\s\S]*?\}\)\(\)\.catch\([^\n]*\);\n/, '');
const genericNode = {
  value: '', innerHTML: '', textContent: '', hidden: false, disabled: false, isConnected: false,
  focus() {}, scrollIntoView() {}, insertAdjacentHTML() {}, addEventListener() {},
  querySelector() { return genericNode; }, querySelectorAll() { return []; },
  classList: {add() {}, remove() {}},
};
const person = {value: '核算负责人', focus() {}, isConnected: false};
const nodes = {'#defer-base-confirmed-by': person, '#base-salary-confirmed-by': person};
const fetchCalls = [];
const messages = [];
const context = {
  document: {
    querySelector(sel) { return nodes[sel] || genericNode; },
    querySelectorAll() { return []; },
    body: genericNode, activeElement: null,
    insertAdjacentHTML() {},
  },
  window: {location: {href: 'http://127.0.0.1:8760/'}, setTimeout() { return 0; }, clearTimeout() {}},
  console, URL, assert, fetchCalls, messages, __result: '',
  fetch: async (url, options) => {
    fetchCalls.push({url: String(url), body: options && options.body});
    return {ok: true, headers: {get: () => 'application/json'}, json: async () => JSON.parse(process.env.FAKE_PAYLOAD || '{}')};
  },
};
vm.createContext(context);
vm.runInContext(source, context);
vm.runInContext(`
  var __result_rendered = 0;
  renderRun = function () { __result_rendered += 1; };
  showMessage = function (message, kind) { messages.push([String(message), kind || 'error']); };
  refreshAfterError = function (error) { messages.push([String((error && error.message) || error), 'refresh']); };
`, context);
(async () => {
  const value = vm.runInContext(script, context);
  if (value && typeof value.then === 'function') await value;
  if (typeof context.__result === 'string') process.stdout.write(context.__result);
})().catch((error) => { console.error((error && error.stack) || String(error)); process.exit(1); });
"""

INLINE_AUTHORITY = {
    "payroll_period": "2026-08", "period_start": "2026-08-01", "period_end": "2026-08-30",
    "boundary_source": "MANUAL_PERIOD_RECORD", "source_label": "人工月资料",
    "is_fallback": False, "confirmed_by": "核算负责人", "revision": 1, "authority_id": "a1",
}
FALLBACK_AUTHORITY = {
    "payroll_period": "2026-08", "period_start": "2026-08-01", "period_end": "2026-08-31",
    "boundary_source": "LEGACY_CALENDAR_DEFAULT", "source_label": "自然月兜底（尚无人工月资料）",
    "is_fallback": True, "confirmed_by": "系统兜底", "revision": 1, "authority_id": "",
}
PREVIEW_ROW = {
    "teacher": "教师甲", "status": "NEEDS_CONFIRMATION", "star": 4,
    "fields": {"AE": {"value": 42, "state": "DETERMINED", "reason": "档位 42"}},
    "final_fields": {
        "M": {"value": None, "state": "BLOCKED_BY_INPUT", "reason": "缺少 G～L"},
        "AV": {"value": None, "state": "HUMAN_REQUIRED", "reason": "M 未确定"},
        "AH": {"value": 5, "state": "DETERMINED", "reason": "已确认续费"},
    },
    "blockers": [],
}


def _run_ui(tmp_path, script: str, payload: dict | None = None) -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    harness = tmp_path / "ui-harness.cjs"
    harness.write_text(_HARNESS, encoding="utf-8")
    import os
    env = dict(os.environ)
    env["FAKE_PAYLOAD"] = json.dumps(payload or {}, ensure_ascii=False)
    completed = subprocess.run([node, str(harness), str(APP_JS), script],
                               capture_output=True, text=True, env=env)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


def _current_expr(authority: dict, extra: str = "") -> str:
    return f"current = {{period: '2026-08', period_authority: {json.dumps(authority, ensure_ascii=False)}{extra}}};"


def test_the_materials_page_says_when_the_natural_month_is_only_a_fallback(tmp_path):
    card = _run_ui(tmp_path, _current_expr(FALLBACK_AUTHORITY) + " __result = periodAuthorityCard();")
    assert "暂按自然月兜底" in card
    assert "materials-authority-start" in card, "兜底时必须给出设置人工月的入口"
    assert "2026-08-01" in card and "2026-08-31" in card


def test_the_materials_page_shows_the_authority_and_drops_the_natural_month_wording(tmp_path):
    card = _run_ui(tmp_path, _current_expr(INLINE_AUTHORITY) + " __result = periodAuthorityCard();")
    assert "2026-08-01" in card and "2026-08-30" in card
    assert "人工月资料" in card
    assert "确认人：核算负责人" in card
    assert "暂按自然月兜底" not in card


def test_the_materials_page_flags_lessons_outside_the_authority(tmp_path):
    extra = ", period_check: {outside_authority: true, outside_authority_dates: ['2026-08-31']}"
    card = _run_ui(tmp_path, _current_expr(INLINE_AUTHORITY, extra) + " __result = periodAuthorityCard();")
    assert "人工周期之外的日期" in card
    assert "2026-08-31" in card


def test_the_preview_shows_the_period_and_star_authority_evidence(tmp_path):
    current = {
        "id": "run-1", "period": "2026-08", "period_label": "2026-08", "mode": "GENERATE",
        "period_authority": INLINE_AUTHORITY, "period_check": {},
        "generated_payroll": {"status": "NEEDS_CONFIRMATION", "blockers": [], "rows": [PREVIEW_ROW]},
        "authority_context": {"rating": {
            "name": "2026春星级-确认版", "version_id": "rating-2026-1", "source": "校区星级名单",
            "effective_period": "2026-01 ～ 2026-12",
        }},
        "summary": {},
    }
    page = _run_ui(tmp_path, f"current = {json.dumps(current, ensure_ascii=False)}; __result = payrollPreviewPage();")
    assert "本期使用的依据" in page, "工资预览必须能看见本期依据"
    assert "2026-08-01 ～ 2026-08-30" in page
    assert "人工月资料" in page
    assert "rating-2026-1" in page, "星级版本要可见"
    assert "2026-01 ～ 2026-12" in page, "星级生效期要可见"
    assert "校区星级名单" in page, "星级来源要可见"
    # 主表仍然保持精简：M/AA/AC/AD/AE/AF/AV 七个快速核对字段。
    for label in ("M 基本工资", "AA", "AC", "AD", "AE 课时单价", "AF", "AV 总工资"):
        assert label in page


def test_defer_enters_the_payroll_preview_in_a_single_click(tmp_path):
    payload = {
        "id": "run-1", "status": "REVIEW_REQUIRED",
        "defer_outcome": {"status": "PREVIEW_READY", "message": "已按暂不录入完成核算并生成工资预览。",
                          "blockers": [], "base_salary_state": "MISSING_SOURCE"},
    }
    script = """
(async () => {
  current = {id: 'run-1', af_policy_confirmation: {}};
  await deferBaseSalaryQuick();
  assert.strictEqual(tab, 'payroll', '无阻塞时必须直接进入工资预览');
  assert.strictEqual(fetchCalls.length, 1, '一次点击只应发一个业务流程请求');
  assert.ok(fetchCalls[0].url.endsWith('/base-salary-defer'), fetchCalls[0].url);
  assert.ok(messages.some(([text, kind]) => kind === 'success' && text.includes('工资预览')), JSON.stringify(messages));
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script, payload).strip() == "ok"


def test_defer_enters_the_exception_flow_when_something_still_blocks(tmp_path):
    payload = {
        "id": "run-1", "status": "REVIEW_REQUIRED",
        "defer_outcome": {"status": "NEEDS_ATTENTION", "message": "核算已完成，但还有其它阻塞需要处理。",
                          "blockers": ["PERIOD_OUTSIDE_AUTHORITY"], "base_salary_state": "MISSING_SOURCE"},
    }
    script = """
(async () => {
  current = {id: 'run-1', af_policy_confirmation: {}};
  await deferBaseSalaryQuick();
  assert.strictEqual(tab, 'issues', '有阻塞时必须进入异常处理，而不是假装预览已就绪');
  assert.ok(messages.some(([text]) => text.includes('阻塞')), JSON.stringify(messages));
  __result = 'ok';
})();
"""
    assert _run_ui(tmp_path, script, payload).strip() == "ok"


def test_the_daily_flow_keeps_engineering_configuration_in_advanced_settings():
    source = APP_JS.read_text(encoding="utf-8")
    for anchor in ("company-template-card", "period-authority-card", "base-salary-card", "rating-source-card"):
        assert f'id="{anchor}"' in source, anchor
    assert "advanced-settings" in source, "工程配置应折叠在高级设置里"
    start = source.index("advanced-settings")
    assert "工程配置" in source[start:start + 300], "折叠区要说明这是低频工程配置"


# --------------------------------------------------------- 人工月权威资料（界面）

_DOCUMENT_AUTHORITY = {
    "payroll_period": "2026-08", "period_start": "2026-08-03", "period_end": "2026-08-30",
    "boundary_source": "MANUAL_PERIOD_DOCUMENT", "source_label": "人工月资料（制度文件导入）",
    "is_fallback": False, "confirmed_by": "核算负责人", "revision": 1, "authority_id": "a-doc",
    "status": "ACTIVE",
    "source": {"source_type": "DOCUMENT", "source_file": "杰牛集团规章制度知识库.md",
               "source_section": "2. 2026 年人工月排期表", "source_row": 62,
               "imported_at": "2026-09-26T08:00:00+00:00", "source_hash": "abcdef1234567890"},
}


def _dashboard(run_period="2026-08", authorities=None, run_authority=None):
    authorities = [_DOCUMENT_AUTHORITY] if authorities is None else authorities
    run_authority = _DOCUMENT_AUTHORITY if run_authority is None else run_authority
    return (
        f"current = {{period: '{run_period}', period_authority: {json.dumps(run_authority, ensure_ascii=False)}}};"
        f" __result = periodAuthorityDashboardCard('run-1', {json.dumps(authorities, ensure_ascii=False)});"
    )


def test_the_manual_month_card_shows_the_imported_document_and_its_detail_table(tmp_path):
    card = _run_ui(tmp_path, _dashboard())

    assert "已导入 2026 年人工月：1 条" in card
    assert "《杰牛集团规章制度知识库》" in card
    assert "导入人工月资料" in card
    assert "查看明细" in card
    for header in ("工资月份", "人工周期", "来源", "状态"):
        assert f">{header}<" in card, header
    assert "当前核算使用" in card
    assert "2. 2026 年人工月排期表" in card, "明细里要能看到资料章节"


def test_the_manual_month_card_says_when_the_current_month_has_no_document(tmp_path):
    card = _run_ui(tmp_path, _dashboard(run_period="2026-10", authorities=[_DOCUMENT_AUTHORITY], run_authority={}))

    assert "当前月份 2026-10 没有人工月资料" in card
    assert "导入人工月资料" in card
    assert "手工设置 2026-10 的人工月" in card


def test_a_hand_written_authority_is_never_shown_as_the_imported_document(tmp_path):
    hand = {
        "payroll_period": "2026-08", "period_start": "2026-08-01", "period_end": "2026-08-30",
        "boundary_source": "USER_CONFIRMED", "source_label": "人工确认（本机手填）",
        "is_fallback": False, "confirmed_by": "核算负责人", "revision": 1, "authority_id": "a-hand",
        "status": "ACTIVE", "source": {},
    }
    card = _run_ui(tmp_path, _dashboard(authorities=[hand], run_authority=hand))

    assert "人工确认（本机手填）" in card
    assert "制度文件导入" not in card
    assert "本机手工设置" in card, "没有资料文件时要说清来源是本机手工设置"


def test_the_import_preview_lists_every_recognised_month_with_its_mapping_rule(tmp_path):
    preview = {
        "source": {"source_file": "杰牛集团规章制度知识库.md", "sha256": "abc", "source_type": "DOCUMENT",
                   "path": "/tmp/知识库.md"},
        "title": "杰牛集团 / 仁杰教育 — 规章制度知识库", "year": 2026, "can_import": True, "problems": [],
        "rows": [
            {"label": "7", "weeks": "5 周", "period_start": "2026-06-29", "period_end": "2026-08-02",
             "payroll_period": "2026-07", "action": "NEW", "mapping_rule": "按周期内天数最多的月份归属工资月份"},
            {"label": "8", "weeks": "4 周", "period_start": "2026-08-03", "period_end": "2026-08-30",
             "payroll_period": "2026-08", "action": "UPDATE", "mapping_rule": "按周期内天数最多的月份归属工资月份"},
        ],
    }
    page = _run_ui(tmp_path, f"current = {{id: 'run-1', af_policy_confirmation: {{}}}}; periodDocumentPreview = {json.dumps(preview, ensure_ascii=False)}; __result = periodDocumentPreviewMarkup();")

    assert "识别结果预览" in page
    assert "识别到 2 条" in page
    assert "2026-08-03" in page and "2026-08-30" in page
    assert "按周期内天数最多的月份归属工资月份" in page
    assert "确认导入这 2 条人工月" in page
    assert "period-document-confirmed-by" in page


def test_the_import_preview_blocks_a_document_that_cannot_be_read(tmp_path):
    preview = {
        "source": {"source_file": "知识库.md", "sha256": "abc", "source_type": "DOCUMENT", "path": "/tmp/知识库.md"},
        "title": "知识库", "year": 2026, "can_import": False,
        "problems": ["第 58 行（人工月 8）：无法识别日期范围，请使用如 8.03 — 8.30 的写法。"],
        "rows": [{"label": "8", "weeks": "4 周", "period_start": "", "period_end": "",
                  "payroll_period": "", "action": "NEW", "mapping_rule": ""}],
    }
    page = _run_ui(tmp_path, f"current = {{id: 'run-1', af_policy_confirmation: {{}}}}; periodDocumentPreview = {json.dumps(preview, ensure_ascii=False)}; __result = periodDocumentPreviewMarkup();")

    assert "需要先修正资料" in page
    assert "无法识别日期范围" in page
    assert "资料需要修正后才能导入" in page, "不能导入时按钮要说清原因"
