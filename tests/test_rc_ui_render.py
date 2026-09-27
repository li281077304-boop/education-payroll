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


def test_generate_flow_exposes_payroll_preview_and_safe_export_action():
    """The normal generate flow must visibly connect calculation to export."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;}}, window:{}, console};
vm.createContext(context);
vm.runInContext(source, context);
vm.runInContext(`current={period:'2026-08',mode:'GENERATE',summary:{core_calculation_complete:true},generated_payroll:{status:'NEEDS_CONFIRMATION',rows:[{teacher:'教师甲',fields:{
 AA:{value:20,state:'DETERMINED'},AC:{value:2.4,state:'DETERMINED'},AD:{value:22.4,state:'DETERMINED'},
 AE:{value:40,state:'DETERMINED'},AF:{value:0,state:'DETERMINED'},PART_TIME:{value:null,state:'NOT_APPLICABLE'}
},final_fields:{AK:{value:9.5,state:'DETERMINED'},AV:{value:84.5,state:'DETERMINED'}}}]}}`, context);
const html = vm.runInContext('payrollPreviewPage()', context);
for (const text of ['工资预览','教师甲','AA','AC','AD','AE','AF','AK','AV','兼职按节课时费','星级','导出工资表']) assert(html.includes(text), text);
assert(html.includes('9.5') && html.includes('84.5'));
assert(!html.includes('undefined'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_issue_center_puts_user_actions_above_collapsed_audit_details():
    """Teacher-level issue groups remain available, but are not top-level tasks."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;}}, window:{}, console};
vm.createContext(context);
vm.runInContext(source, context);
vm.runInContext(`current={
  user_actions:[{id:'action-af',title:'确认 AF 默认政策',teacher_count:2,teachers:['教师甲','教师乙'],group_ids:['g1','g2']}],
  issue_groups:[
    {id:'g1',teacher:'教师甲',title:'AF 政策需要确认',severity_rank:1,severity_label:'重要',fields:['AF'],expected:30,actual:null,difference:null},
    {id:'g2',teacher:'教师乙',title:'AF 政策需要确认',severity_rank:1,severity_label:'重要',fields:['AF'],expected:30,actual:null,difference:null},
    {id:'audit-only',teacher:'教师丙',title:'来源审计记录',severity_rank:3,severity_label:'提示',fields:['rating'],expected:2,actual:2,difference:0}
  ], issues:[{id:'f1'},{id:'f2'},{id:'f3'}]
}`, context);
const html = vm.runInContext('issuesPage()', context);
assert(html.includes('class="user-action"'));
assert(html.includes('确认 AF 默认政策：2 位教师'));
assert(html.includes('class="audit-details"'));
assert(html.includes('查看审计明细'));
const firstDetails = html.indexOf('<details');
const firstIssueTable = html.indexOf('<table class="table issues">');
assert(firstDetails >= 0 && firstIssueTable > firstDetails, 'issue table must be inside a collapsed details section');
assert(html.indexOf('audit-only') >= 0 || html.includes('来源审计记录'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_historical_reconciliation_page_shows_real_field_totals_and_categories():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;}}, window:{}, console};
vm.createContext(context); vm.runInContext(source, context);
const html = vm.runInContext(`historicalReconciliationPage({
 period_start:'2026-06-29', period_end:'2026-08-02', teachers_compared:30, difference_teachers:2, unexplained:0,
 field_stats:{AA:{matches:27,comparable:27},AC:{matches:25,comparable:27},AD:{matches:25,comparable:27},AE:{matches:27,comparable:27},AF:{matches:24,comparable:30}},
 rows:[{teacher:'任勇',difference_category:'PERSONAL_EXCEPTION',fields:{AF:{historical:5491,current:4381.17,diff:-1110,difference_category:'PERSONAL_EXCEPTION',evidence:[{historical_formula:'=AD7*AE7',historical_obligation_hours:0,current_obligation_hours:30}]}}},
 {teacher:'刘文剑',difference_category:'COURSE_CONTRIBUTION',fields:{AC:{historical:240.31,current:239.11,diff:-1.2,difference_category:'COURSE_CONTRIBUTION',evidence:[{course_contribution_count:101}]}}}]
})`, context);
for (const text of ['历史工资对账','27/27','25/27','24/30','已分类差异：2 人','任勇','PERSONAL_EXCEPTION','刘文剑','COURSE_CONTRIBUTION','历史公式：=AD7*AE7','逐课证据 101 条']) assert(html.includes(text), text);
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_todo_summary_counts_material_confirmation_without_issue_groups_and_uses_saved_decisions():
    """The flow header counts actionable material cards, not audit rows alone."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;},querySelectorAll(){return []; }}, window:{}, console};
vm.createContext(context);
vm.runInContext(source, context);
vm.runInContext(`current={
 id:'run-pending', mode:'GENERATE', issue_groups:[], user_actions:[], business_decisions:[], decisions:[],
 support_department_pending_preview:{status:'PENDING_CONFIRMATION'},
 historical_salary_reference_pending_preview:{status:'PENDING_CONFIRMATION',source_sha256:'history-v1'},
 support_source:{bound:false}, period_authority:{}, employment:{salary_basis_counts:{SOURCE_UNKNOWN:0},teachers:[]}
}; renewalMaterialPreview=null;`, context);
let summary = vm.runInContext('currentTodoSummary()', context);
assert(summary.pending >= 2, JSON.stringify(summary));
assert.equal(vm.runInContext('current.issue_groups.length', context), 0);
vm.runInContext(`current={
 id:'run-decisions', mode:'AUDIT', issue_groups:[
  {id:'done-1',decision:{status:'ACTIVE',action:'ACCEPTED_EXCEPTION'}},
  {id:'defer-1',decision:{status:'ACTIVE',action:'DEFERRED'}}
 ], user_actions:[], business_decisions:[
  {group_id:'done-1',status:'ACTIVE',action:'ACCEPTED_EXCEPTION'},
  {group_id:'defer-1',status:'ACTIVE',action:'DEFERRED'}
 ], decisions:[], files:{}, support_source:{bound:false}, period_authority:{}, employment:{salary_basis_counts:{SOURCE_UNKNOWN:0},teachers:[]}
};`, context);
summary = vm.runInContext('currentTodoSummary()', context);
    assert.deepEqual(JSON.parse(JSON.stringify(summary)), {pending:0,processed:1,deferred:1});
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_todo_summary_salary_basis_states_and_same_hash_group_candidates_are_exclusive():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;},querySelectorAll(){return []; }}, window:{}, console};
vm.createContext(context); vm.runInContext(source, context);
const common = {id:'run-summary',mode:'AUDIT',period:'2026-08',issue_groups:[],user_actions:[],business_decisions:[],decisions:[],
  files:{},period_authority:{is_fallback:false},period_check:{},support_source:{bound:false},
  employment:{salary_basis_counts:{SOURCE_UNKNOWN:1},teachers:[{teacher:'教师甲',teacher_id:'t1',salary_basis:'SOURCE_UNKNOWN'}]}};
context.common = common;
vm.runInContext('current=common', context);
let summary = vm.runInContext('currentTodoSummary()', context);
assert.deepEqual(JSON.parse(JSON.stringify(summary)), {pending:1,processed:0,deferred:0});
vm.runInContext(`current.employment.salary_basis_counts.SOURCE_UNKNOWN=0;
current.employment.teachers=[{teacher:'教师甲',teacher_id:'t1',salary_basis:'HOURLY_SUBMISSION_ONLY',salary_basis_source:'USER_CONFIRMED_SALARY_BASIS'}]`, context);
summary = vm.runInContext('currentTodoSummary()', context);
assert.deepEqual(JSON.parse(JSON.stringify(summary)), {pending:0,processed:1,deferred:0});
vm.runInContext(`current.employment.salary_basis_counts.SOURCE_UNKNOWN=1;
current.employment.teachers=[{teacher:'教师甲',teacher_id:'t1',salary_basis:'SOURCE_UNKNOWN'}];
current.base_salary_deferred=true`, context);
summary = vm.runInContext('currentTodoSummary()', context);
assert.deepEqual(JSON.parse(JSON.stringify(summary)), {pending:0,processed:0,deferred:1});
vm.runInContext(`current.base_salary_deferred=false;
 current.employment.salary_basis_counts.SOURCE_UNKNOWN=0; current.employment.teachers=[];
 current.pending_subject_group_imports={
 a:{candidate_id:'candidate-a',role:'math',recognized_group:'数学组',source_sha256:'same-hash'},
 b:{candidate_id:'candidate-b',role:'math',recognized_group:'语文组',source_sha256:'same-hash'}
}; current.subject_group_materials=[]; current.subject_group_pending_history=[]`, context);
summary = vm.runInContext('currentTodoSummary()', context);
assert.equal(summary.pending, 2, JSON.stringify(summary));
vm.runInContext(`delete current.pending_subject_group_imports.a;
current.subject_group_materials=[{candidate_id:'candidate-a',recognized_role:'math',recognized_group:'数学组',source_sha256:'same-hash',status:'CONFIRMED'}]`, context);
summary = vm.runInContext('currentTodoSummary()', context);
assert.deepEqual(JSON.parse(JSON.stringify(summary)), {pending:1,processed:1,deferred:0});
vm.runInContext(`delete current.pending_subject_group_imports.b;
current.subject_group_pending_history=[{candidate_id:'candidate-b',role:'math',recognized_group:'语文组',source_sha256:'same-hash',event:'CANCELLED'}]`, context);
summary = vm.runInContext('currentTodoSummary()', context);
assert.deepEqual(JSON.parse(JSON.stringify(summary)), {pending:0,processed:1,deferred:1});
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_pending_group_preview_uses_the_selected_candidate_not_the_first_role_match():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const fullSource = fs.readFileSync(process.argv[1], 'utf8');
const start = fullSource.indexOf('async function previewExistingSubjectGroup');
const end = fullSource.indexOf('async function confirmSubjectGroup', start);
const source = fullSource.slice(start, end);
const context = {document:{querySelector(){return null;},querySelectorAll(){return []; }}, window:{}, console};
vm.createContext(context); vm.runInContext(source, context);
vm.runInContext(`current={id:'run-1',operator_role:'SUBJECT_LEADER',selected_groups:['数学组','语文组'],selected_group:'',
 files:{math:{path:'/source-A.csv',recognized_group:'数学组'}},pending_subject_group_imports:{
  'candidate-a':{candidate_id:'candidate-a',role:'math',recognized_group:'数学组',source_path:'/source-A.csv',source_sha256:'sha-a'},
  'candidate-b':{candidate_id:'candidate-b',role:'math',recognized_group:'语文组',source_path:'/source-B.csv',source_sha256:'sha-b'}
 }};
 selectedRunGroups=(run)=>run.selected_groups;
 escapeHtml=(value)=>String(value||'');
 sent=null; shown=null;
 api=async(_path,options)=>{sent=JSON.parse(options.body);return {run:current}};
 renderRun=()=>{}; showMessage=(message)=>{shown=message};`, context);
(async()=>{
 await vm.runInContext("previewExistingSubjectGroup('math','candidate-b')", context);
 const sent = vm.runInContext('sent', context);
 if (!sent) throw new Error(`preview request not sent: ${vm.runInContext('shown', context)}`);
 assert.equal(sent.path,'/source-B.csv');
 assert.equal(sent.selected_group,'语文组');
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
