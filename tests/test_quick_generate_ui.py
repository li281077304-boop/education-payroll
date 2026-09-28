"""Production UI contracts for the quick generation shell."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


APP = Path(__file__).parents[1] / "payroll_ui" / "static" / "app.js"


def _node(script: str) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is needed to exercise the production UI renderer")
    result = subprocess.run([node, "-e", script, str(APP)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_home_offers_quick_primary_and_existing_professional_create() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`let page=''; api=async()=>[]; shell=(html)=>{page=html}; duplicateHint=()=>{};`,context);
(async()=>{
 await vm.runInContext('home()',context);
 const page=vm.runInContext('page',context);
 assert(page.includes('onclick="startQuickGenerate()"'));
 assert(page.includes('极速生成工资表'));
 assert(page.includes('onclick="showProfessionalCreate()"'));
 assert(page.includes('id="professional-create" class="card hidden"'));
 assert(page.includes('onclick="createRun()"'));
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_quick_page_is_small_and_hides_payroll_internals() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`current={id:'quick-1',ui_mode:'QUICK',monthly_flow_version:'SUBMISSION_FIRST_V1',period:'2026-08',files:{},quick_materials:[{kind:'schedule'},{kind:'subject_group'}],subject_group_materials:[]};quickState={stage:'upload',uploaded:[],result:null,problem:null};`,context);
const page=vm.runInContext('quickRunPage()',context);
for(const text of ['一键生成工资表','quick-files','multiple','quick-drop-zone','排课表：已识别','学科组提交表：已识别 1 份','生成工资表'])assert(page.includes(text),text);
for(const text of ['教师归属','待处理问题','field_records','issue_groups','authority','source hash','FORMULA_MISSING','PART_TIME','salary_basis','用工性质','工资基础','重新核算'])assert(!page.includes(text),text);
''')


def test_success_and_failure_keep_same_run_when_entering_professional_mode() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`current={id:'same-run',ui_mode:'QUICK',monthly_flow_version:'SUBMISSION_FIRST_V1',period:'2026-08',period_start:'2026-08-03',period_end:'2026-08-30'};quickState={stage:'success',uploaded:[],problem:null,result:{teacher_count:15,period:'2026-08',download_url:'/api/quick-runs/same-run/download'}};`,context);
let page=vm.runInContext('quickRunPage()',context);
for(const text of ['工资表已生成','教师：15 人','打开工资表','查看专业核算详情'])assert(page.includes(text),text);
vm.runInContext(`quickState.stage='problem';quickState.problem={issues:[{user_message:'张三的岗位津贴数据不一致'}]};`,context);
page=vm.runInContext('quickRunPage()',context);
assert(page.includes('张三的岗位津贴数据不一致'));
assert(page.includes('进入专业模式处理'));
vm.runInContext(`quickState.problem={admin_configuration:true,issues:[{user_message:'星级配置需要管理员修正'}]};`,context);
page=vm.runInContext('quickRunPage()',context);
assert(page.includes('请联系管理员'));
assert(!page.includes('进入专业模式处理'));
vm.runInContext(`let posted='';api=async(path)=>{posted=path;return {run:{id:'same-run',ui_mode:'PROFESSIONAL',monthly_flow_version:'SUBMISSION_FIRST_V1'}}};renderRun=()=>{};showMessage=()=>{};`,context);
(async()=>{
 await vm.runInContext('quickOpenProfessional()',context);
 assert.equal(vm.runInContext('posted',context),'/api/quick-runs/same-run/professional');
 assert.equal(vm.runInContext('current.id',context),'same-run');
 assert.equal(vm.runInContext('current.ui_mode',context),'PROFESSIONAL');
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_quick_success_opens_token_protected_workbook_download() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
let request=null,clicked=false;
const context={document:{querySelector(){return null},addEventListener(){},createElement(){return {click(){clicked=true}}}},window:{setTimeout(){}},URL:{createObjectURL(){return 'blob:workbook'},revokeObjectURL(){}},console,fetch:async(url,options)=>{request={url,options};return {ok:true,blob:async()=>({})}}};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`token='local-token';current={id:'same-run',period:'2026-08'};quickState={stage:'success',result:{period:'2026-08',download_url:'/api/quick-runs/same-run/download'}};`,context);
(async()=>{
 await vm.runInContext('openQuickWorkbook()',context);
 assert.equal(request.url,'/api/quick-runs/same-run/download');
 assert.equal(request.options.headers['X-Payroll-Token'],'local-token');
 assert(clicked);
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_quick_upload_and_generate_use_one_run_and_keep_blockers_visible() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console,btoa:(value)=>Buffer.from(value,'binary').toString('base64')};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`current={id:'same-run',ui_mode:'QUICK',monthly_flow_version:'SUBMISSION_FIRST_V1',files:{},subject_group_materials:[]};quickState={stage:'upload',uploaded:[],problem:null,result:null};let calls=[],bodies=[];renderRun=()=>{};showMessage=()=>{};bytesToBase64=()=>'';api=async(path,options)=>{calls.push(path);bodies.push(options?.body||'');if(path==='/api/upload'){const name=JSON.parse(options.body).name;return {path:'/uploads/'+name};}if(path.endsWith('/materials'))return {ok:true,materials:[{detected_kind:'subject_group'},{detected_kind:'schedule'}],run:{id:'same-run',ui_mode:'QUICK',monthly_flow_version:'SUBMISSION_FIRST_V1',files:{schedule:{name:'schedule.xlsx'}},subject_group_materials:[{source_name:'group.xlsx'}]}};if(path.endsWith('/generate'))return {ok:false,run_id:'same-run',issues:[{user_message:'教师甲的资料有冲突'}]};throw Error(path);};`,context);
(async()=>{
 const file={name:'group.xlsx',arrayBuffer:async()=>new Uint8Array([1,2,3]).buffer};
 const schedule={name:'schedule.xlsx',arrayBuffer:async()=>new Uint8Array([4,5,6]).buffer};
 await vm.runInContext('uploadQuickFiles',context)([file,schedule]);
 assert.equal(vm.runInContext('quickState.stage',context),'upload',JSON.stringify(vm.runInContext('quickState.problem',context)));
 assert.equal(vm.runInContext('quickState.uploaded[0].kind',context),'subject_group');
 assert.equal(vm.runInContext('quickState.uploaded[1].kind',context),'schedule');
 assert.deepEqual(JSON.parse(vm.runInContext('bodies[2]',context)).paths,['/uploads/group.xlsx','/uploads/schedule.xlsx']);
 await vm.runInContext('quickGenerate()',context);
 assert.equal(vm.runInContext('quickState.stage',context),'problem');
 assert.equal(vm.runInContext('current.id',context),'same-run');
 assert.equal(vm.runInContext('quickRunPage()',context).includes('教师甲的资料有冲突'),true);
 assert.deepEqual([...vm.runInContext('calls',context)],['/api/upload','/api/upload','/api/quick-runs/same-run/materials','/api/quick-runs/same-run/generate']);
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_reopening_finished_quick_run_restores_success_without_new_run() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`let calls=[];api=async(path)=>{calls.push(path);return {id:'saved-run',ui_mode:'QUICK',monthly_flow_version:'SUBMISSION_FIRST_V1',period:'2026-08',period_start:'2026-08-03',period_end:'2026-08-30',generated_payroll:{path:'/local/workbook.xlsx',rows:[{teacher:'教师甲'}]}}};renderRun=()=>{};showMessage=()=>{};`,context);
(async()=>{
 await vm.runInContext("openRun('saved-run')",context);
 assert.equal(vm.runInContext('quickState.stage',context),'success');
 assert.equal(vm.runInContext('quickState.result.teacher_count',context),1);
 assert.equal(vm.runInContext('current.id',context),'saved-run');
 assert.deepEqual([...vm.runInContext('calls',context)],['/api/runs/saved-run']);
assert(vm.runInContext('quickRunPage()',context).includes('工资表已生成'));
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_professional_handoff_lists_original_unclassified_upload_without_reupload():
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`current={id:'same-run',ui_mode:'PROFESSIONAL',monthly_flow_version:'SUBMISSION_FIRST_V1',
 quick_materials:[{kind:'PROFESSIONAL_REQUIRED',name:'uploaded-extra.csv',path:'/uploads/original.csv',sha256:'digest',transfer_reason:'原文件已保留'}],
 files:{},subject_group_materials:[]};`,context);
const html=vm.runInContext('quickStagedProfessionalMaterials()',context);
assert(html.includes('uploaded-extra.csv'));
assert(html.includes('原文件仍保存在本次核算中'));
assert(html.includes('importQuickStagedProfessional'));
''')
