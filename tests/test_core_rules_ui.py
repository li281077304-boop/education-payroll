"""Browser-side coverage for the configured payroll rule UI."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_core_rule_forms_and_configured_result_copy_render_in_real_javascript():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const app = {innerHTML:''};
const context = {
  document:{querySelector(selector){return selector === '#app' ? app : null;}},
  window:{confirm(){return true;},clearTimeout(){},setTimeout(){}},
  console,
};
vm.createContext(context);
vm.runInContext(source, context);

const seed = {
 schema_version:'payroll-core-rules/v1', rule_version_id:'rules-v1',
 effective_from:'2026-08', effective_to:'2026-09', source:'confirmed', lesson_hour_factor:'2',
 grade_coefficients:{'七年级':'0.9'}, excluded_grades:['领航伴学'],
 course_rules:[
  {id:'one_to_one',treatment:'ONE_TO_ONE',class_types:['1对1']},
  {id:'special_one_to_two',treatment:'SPECIAL_FIXED',class_types:['1对2'],coefficient:'1.2'},
  {id:'small_group',treatment:'SMALL_GROUP',class_types:['小班']},
 ],
 small_group_headcount_coefficients:{'2':'1.0','3':'1.2'},
 ae:{tiers:[{id:'zero_to_30',minimum:'0',maximum:'30',base:'0',minimum_exclusive:false}],star_bonuses:{'3':'5'}},
 af:{default_policy_candidate:{obligation_hours:'30',label:'待个人确认',source:'规则说明'}},
};
context.seed = seed;
const editor = vm.runInContext('coreRulesEditor(seed)', context);
for (const text of ['班型与计算方式','特殊班型固定系数','年级系数与明确排除','普通小班实到人数系数','AE 课时档位','星级加成','AF 默认政策候选','special_one_to_two','领航伴学']) assert(editor.includes(text), text);
for (const id of ['core-effective-from','core-course-editor','core-grade-editor','core-headcount-editor','core-tier-editor','core-star-editor']) assert(editor.includes(id), id);
assert(editor.includes('type="month"'));
assert(!editor.includes('<textarea'));
assert.equal(vm.runInContext('versionList([{id:"rate-v1"}])[0].id', context), 'rate-v1');
assert.equal(vm.runInContext('versionList({versions:[{id:"rate-v2"}]} )[0].id', context), 'rate-v2');

const policyRow = vm.runInContext('policyProfileEditorRow({teacher:"教师甲",employment_type:"PART_TIME",allow_no_teaching:true})', context);
for (const text of ['policy-employment','全职','兼职','policy-no-teaching','checked']) assert(policyRow.includes(text), text);
const rateRow = vm.runInContext('partTimeRateEditorRow({teacher:"兼职甲",grade_scope:"*",rate_per_session:123})', context);
for (const text of ['兼职甲','*','123']) assert(rateRow.includes(text), text);

vm.runInContext(`current={
 id:'run-1',calculation_engine:'CONFIGURED_V1',core_rule_version_id:'rules-v1',part_time_rate_version_id:'rate-v1',
 summary:{automatic_pass:false,automatic_coverage:80,scope_note:'AA/AC/AD 来自独立排课。'},field_status:[],
 core_calculation:{rows:[{teacher:'教师甲',fields:{
  AA:{value:'2',state:'DETERMINED',reason:'确定',evidence:[]},
  AC:{value:null,state:'NEEDS_INPUT',reason:'缺规则',evidence:[]},
  AD:{value:null,state:'NEEDS_INPUT',reason:'待输入',evidence:[]},
  AE:{value:'35',state:'ESTIMATED',reason:'tier-1',evidence:[{kind:'AE_TIER',rule_id:'tier-1'}]},
  AF:{value:null,state:'NEEDS_INPUT',reason:'待输入',evidence:[]},
  PART_TIME:{value:null,state:'NOT_APPLICABLE',reason:'不适用',evidence:[]}
 }}]}
}`, context);
const configured = vm.runInContext('overviewPage()', context);
assert(configured.includes('AA/AC/AD 来自独立排课。'));
assert(!configured.includes('AD 仍来自工资表目标自身'));
assert(configured.includes('兼职按节课时费'));
assert(!configured.includes('兼职 PART_TIME'));
assert(configured.includes('tier-1'));

vm.runInContext('current.calculation_engine="LEGACY"; current.summary.scope_note="不应显示"; current.core_calculation=null', context);
const legacy = vm.runInContext('overviewPage()', context);
assert(legacy.includes('AD 仍来自工资表目标自身'));
assert(!legacy.includes('不应显示'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_core_rule_ui_uses_supported_endpoints_and_month_periods():
    source = (Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js").read_text()
    assert 'api("/api/core-rules", { method: "POST"' in source
    assert 'api("/api/part-time-rates", { method: "POST"' in source
    assert "/core-rules`" in source and "/part-time-rates`" in source
    assert 'id="part-time-from" type="month"' in source
    assert 'id="part-time-to" type="month"' in source
    assert "payload.versions || []" not in source
