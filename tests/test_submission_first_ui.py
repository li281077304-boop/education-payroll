"""Renderer contract tests for the simplified monthly payroll flow."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_submission_first_ui_hides_legacy_monthly_concepts_and_keeps_af_card():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const view = {innerHTML:''};
const context = {document:{querySelector(){return view;},querySelectorAll(){return [];}},window:{},console};
vm.createContext(context); vm.runInContext(source, context);
vm.runInContext(`current={id:'run-new',monthly_flow_version:'SUBMISSION_FIRST_V1',mode:'GENERATE',operator_role:'DOS',period:'2026-08',
 processing_scope:{scope_count:2,teachers:[{display_name:'教师甲'},{display_name:'教师乙'}]},
 subject_group_materials:[], support_source:{bound:false}, support_department_pending_preview:null,
 materials:[],health:{warnings:[],missing:[],readiness:100},
 authority_context:{rating:{version_id:'rating-v1'}}, af_policy_confirmation:null,
 files:{schedule:{name:'schedule.csv'}}, issue_groups:[],user_actions:[],issues:[],field_records:[],
 period_authority:{},period_check:{},employment:{teachers:[{teacher:'教师甲',salary_basis:'SOURCE_UNKNOWN'}],salary_basis_counts:{SOURCE_UNKNOWN:1}},
 historical_salary_reference_snapshots:[{source_name:'legacy-history.xlsx'}],historical_salary_reference_snapshot:{source_name:'legacy-history.xlsx'},
 historical_salary_reference_pending_preview:{status:'PENDING_CONFIRMATION'},base_salary_input_snapshot:null,
 currentTodoSummary:null}; tab='issues';`, context);
const staff = vm.runInContext('teacherScopePage()', context);
assert(staff.includes('本次教师名单'));
assert(!staff.includes('长期归属科组'));
assert(!staff.includes('工资基础'));
const materials = vm.runInContext('materialsPage()', context);
assert(materials.includes('学科组提交表'));
assert(materials.includes('支持部权威工资资料（可选）'));
assert(!materials.includes('历史工资参考'));
assert(!materials.includes('请选择这份资料所属科组'));
const summary = vm.runInContext('currentTodoSummary()', context);
assert.equal(summary.pending, 1); // AF rule only; no history/salary/employment todo.
assert.equal(summary.processed, 0);
assert.equal(summary.deferred, 0);
const authority = vm.runInContext('authoritySummary()', context);
assert(authority.includes('教师星级：已自动应用'));
const af = vm.runInContext('afPolicyBlock()', context);
for (const text of ['本月义务课时规则','普通教师：30 小时','教师甲','教师乙','af-teacher-search','max-height:178px','确认本月规则']) assert(af.includes(text), text);
assert(!af.includes('salary_basis'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_submission_first_generate_hides_source_formula_advisories():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const view = {innerHTML:''};
const context = {document:{querySelector(){return view;},querySelectorAll(){return [];}},window:{},console};
vm.createContext(context); vm.runInContext(source, context);
vm.runInContext(`current={id:'run-new',monthly_flow_version:'SUBMISSION_FIRST_V1',mode:'GENERATE',period:'2026-08',
 source_formula_advisories:[{sheet:'Sheet1',cell:'AF7',status:'FORMULA_MISSING'}],
 generated_payroll:{status:'NEEDS_CONFIRMATION',rows:[]},core_calculation:{rows:[]},
 period_display:{label:'2026-08',start:'2026-08-03',end:'2026-08-30'},files:{},summary:{}}; tab='payroll';`, context);
vm.runInContext('renderTab()', context);
assert(!view.innerHTML.includes('FORMULA_MISSING'));
assert(!view.innerHTML.includes('来源工资表公式异常'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_submission_first_next_step_runs_preview_and_enters_payroll():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;},querySelectorAll(){return []; }},window:{},console};
vm.createContext(context); vm.runInContext(source, context);
vm.runInContext(`current={id:'run-next',monthly_flow_version:'SUBMISSION_FIRST_V1',mode:'GENERATE',files:{schedule:{}},issue_groups:[],
 period_check:{},generated_payroll:null,core_calculation:null}; tab='issues';
 let posted=''; api=async(path)=>{posted=path;return {id:'run-next',monthly_flow_version:'SUBMISSION_FIRST_V1',mode:'GENERATE',issue_groups:[],generated_payroll:{rows:[{teacher:'教师甲'}]}};};
 periodNeedsDecision=()=>false; markBusy=()=>()=>{}; renderRun=()=>{}; showMessage=(message)=>{lastMessage=message;};`, context);
(async()=>{
 await vm.runInContext(`continueFlow('payroll')`,context);
 assert.equal(vm.runInContext('posted',context),'/api/runs/run-next/preview');
 assert.equal(vm.runInContext('tab',context),'payroll');
 assert(vm.runInContext('lastMessage',context).includes('工资预览已更新'));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_submission_first_renewal_preview_explains_missing_rows_as_zero_not_exception():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;},querySelectorAll(){return []; }},window:{},console};
vm.createContext(context); vm.runInContext(source, context);
vm.runInContext(`current={id:'run-renewal',monthly_flow_version:'SUBMISSION_FIRST_V1',period:'2026-08',af_policy_confirmation:{confirmed_by:'UAT'}};
 tab='issues'; renewalMaterialPreview={run_id:'run-renewal',period:'2026-08',source_name:'renewal.csv',source_rows:1,matched:[],no_renewal_row:[{teacher:'教师甲'}],identity_unmatched:[],outside_roster:[],source_conflicts:[],match_counts:{matched:0,no_renewal_row:1,identity_unmatched:0,outside_roster:0},can_confirm:true};`, context);
const html = vm.runInContext('renewalPreviewMarkup()', context);
assert(html.includes('无续费记录（按 0 计入）'));
assert(html.includes('AH / AI / AJ 按 0 进入本月工资'));
assert(!html.includes('不会自动填 0'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_submission_first_payroll_preview_hides_part_time_but_legacy_keeps_it():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    script = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8').split('(async () => {')[0];
const context = {document:{querySelector(){return null;},querySelectorAll(){return []; }},window:{},console};
vm.createContext(context); vm.runInContext(source, context);
vm.runInContext(`const row={teacher:'教师甲',status:'NEEDS_CONFIRMATION',blockers:[],fields:{
 AA:{value:1,state:'DETERMINED'},AC:{value:0,state:'DETERMINED'},AD:{value:1,state:'DETERMINED'},
 AE:{value:40,state:'DETERMINED'},AF:{value:0,state:'DETERMINED'},PART_TIME:{value:null,state:'NEEDS_INPUT',reason:'兼职按节课时费'}},
 final_fields:{M:{value:null,state:'BLOCKED_BY_INPUT'},AH:{value:0,state:'DETERMINED'},AI:{value:0,state:'DETERMINED'},
 AJ:{value:0,state:'DETERMINED'},AK:{value:0,state:'DETERMINED'},AV:{value:null,state:'MISSING_SOURCE'}}};
 current={id:'run-preview',period:'2026-08',period_label:'2026-08',mode:'GENERATE',generated_payroll:{status:'NEEDS_CONFIRMATION',rows:[row]},
 period_authority:{},period_check:{},authority_context:{rating:{}},summary:{}}; tab='payroll';`, context);
vm.runInContext(`current.monthly_flow_version='SUBMISSION_FIRST_V1'`, context);
const simple = vm.runInContext('payrollPreviewPage()', context);
assert(!simple.includes('兼职按节课时费'));
assert(!simple.includes('PART_TIME'));
vm.runInContext(`delete current.monthly_flow_version`, context);
const legacy = vm.runInContext('payrollPreviewPage()', context);
assert(legacy.includes('兼职按节课时费'));
'''
    app = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"
    result = subprocess.run([node, "-e", script, str(app)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
