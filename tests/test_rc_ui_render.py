"""Check that the real detail renderer consumes the backend's grouped payload."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_grouped_detail_renders_both_fields_and_reachable_decision_form():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const node = {innerHTML:'', scrollIntoView(){}};
const context = {document:{querySelector(){return node;}}, window:{}, console};
vm.createContext(context);
vm.runInContext(source, context);
assert(vm.runInContext("reconfirmationBanner({business_decisions:[{status:'NEEDS_RECONFIRMATION'}]})",context).includes('1 条人工决定需要重新确认'));
assert.equal(vm.runInContext("reconfirmationBanner({business_decisions:[{status:'ACTIVE'}]})",context),'');
vm.runInContext(`current = {id:'run-1', authority_context:{
 schedule:{name:'fake_schedule.xlsx'},
 rating:{name:'rating-v1',source:'synthetic',effective_period:'2025-10 ～ 2026-09'},
 policy:{name:'policy-v1',source:'synthetic',effective_period:'2025-10 ～ 2026-09'},
 rules:{name:'rules-v1',source:'synthetic',effective_period:'2025-10 起持续维护'}
}}`, context);
const authority = vm.runInContext("authoritySummary()",context);
for (const text of ['当前核对依据','排课权威源','星级权威版本','教师政策版本','工资规则版本','查看、修正或改用版本']) assert(authority.includes(text), text);
const payload = {
 issue: {id:'biz-test',teacher:'教师甲',title:'档位与课时费依据',fields:['AE','AF'],fingerprint:'test-v1'},
 field_records: [
  {field:'rate',field_label:'AE',expected:42,actual:32,difference:-10,status_label:'差异'},
  {field:'af_policy',field_label:'AF',expected:1680,actual:1280,difference:-400,status_label:'差异'}
 ],
 sections: [
  {title:'共同输入',items:[{'AD':70,'权威星级':4}]},
  {title:'AE 规则链',items:[{'星级加成':10}]},
  {title:'AF 规则链',items:[{'义务课时':30}]},
  {title:'独立性边界',items:[{'AD':'仍来自工资表自身'}]}
 ],
 ac_calculation: {
  system_total: 2.16,
  records: [{
   '日期':'2026-08-01','班级':'测试班','课程':'数学','班型':'小班','年级':'七年级',
   '原始时长/课次':'2小时','折算规则':'年级系数 1 × 实到系数 1 × 班型系数 1 × 2 = 2',
   '本条折算值':2,'来源文件':'fake_schedule.xlsx','来源工作表':'排课','来源位置':'A2'
  }]
 },
 evidence:[{'来源文件':'fake_schedule.xlsx','来源位置':'A2','班型':'小班'}]
};
context.payload = payload;
vm.runInContext("current={id:'test-run'}; api=async()=>payload; showMessage=(m)=>{throw Error(m)};",context);
(async()=>{
 await vm.runInContext("evidence('biz-test')", context);
 const html=node.innerHTML;
 for (const text of ['共同输入','AE 规则链','AF 规则链','1680','1280','仍来自工资表自身','保存处理意见','系统排课计算','系统 AC 合计 = Σ 每条折算值 = 2.16','本条折算值']) assert(html.includes(text), text);
 assert(html.indexOf('保存处理意见') < html.indexOf('fake_schedule.xlsx'));
 assert(!html.includes('[object Object]'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
