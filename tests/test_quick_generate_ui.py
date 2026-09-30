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
 assert(page.includes('id="quick-period" type="month"'));
 assert(page.includes('工资月份'));
 assert(page.includes('value="'+vm.runInContext('defaultPayrollPeriod(new Date())',context)+'"'));
 assert(page.includes('极速生成工资表'));
 assert(page.includes('onclick="showProfessionalCreate()"'));
 assert(page.includes('id="professional-create" class="card hidden"'));
 assert(page.includes('onclick="createRun()"'));
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_quick_entry_posts_the_user_selected_period_without_changing_it_later() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
let body=null,postedPath='',rendered=false;
const context={document:{querySelector(selector){return selector==='#quick-period'?{value:'2026-08'}:null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`api=async(path,options)=>{postedPath=path;body=JSON.parse(options.body);return {run:{id:'quick-aug',period:body.period,ui_mode:'QUICK'}}};renderRun=()=>{rendered=true};showMessage=(message)=>{throw Error(message)};`,context);
(async()=>{
 await vm.runInContext('startQuickGenerate()',context);
 assert.equal(vm.runInContext('postedPath',context),'/api/quick-runs');
 assert.equal(vm.runInContext('body.period',context),'2026-08');
 assert.equal(vm.runInContext('current.period',context),'2026-08');
 assert.equal(vm.runInContext('rendered',context),true);
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_quick_entry_without_month_edit_keeps_default_period() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
let body=null;
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`api=async(_path,options)=>{body=JSON.parse(options.body);return {run:{id:'quick-default',period:body.period}}};renderRun=()=>{};showMessage=(message)=>{throw Error(message)};`,context);
(async()=>{
 await vm.runInContext('startQuickGenerate()',context);
 assert.equal(vm.runInContext('body.period',context),vm.runInContext('defaultPayrollPeriod()',context));
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
vm.runInContext(`quickState.stage='problem';quickState.problem={error_kind:'NEEDS_PROFESSIONAL_REVIEW',issues:[{user_message:'张三的岗位津贴数据不一致'}]};`,context);
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
 assert.deepEqual(JSON.parse(vm.runInContext('bodies[2]',context)).paths,[{name:'group.xlsx',path:'/uploads/group.xlsx'},{name:'schedule.xlsx',path:'/uploads/schedule.xlsx'}]);
 await vm.runInContext('quickGenerate()',context);
 assert.equal(vm.runInContext('quickState.stage',context),'problem');
 assert.equal(vm.runInContext('current.id',context),'same-run');
 assert.equal(vm.runInContext('quickRunPage()',context).includes('教师甲的资料有冲突'),true);
 assert.deepEqual([...vm.runInContext('calls',context)],['/api/upload','/api/upload','/api/quick-runs/same-run/materials','/api/quick-runs/same-run/generate']);
})().catch(error=>{console.error(error);process.exit(1)});
    ''')


def test_manual_mapping_confirmation_preserves_uploaded_identity_sheet_and_header_row() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
let page='';
const selects=[
 {id:'map-teacher',value:'1'},{id:'map-grade',value:'2'},{id:'map-subject',value:'3'},
 {id:'map-class_type',value:'4'},{id:'map-actual_student_count',value:'5'}
];
const document={querySelectorAll(){return selects;},querySelector(id){return id==='#map-profile-name'?{value:'脱敏格式'}:id==='#map-actor'?{value:'脱敏确认'}:null;},addEventListener(){}};
const context={document,window:{},console};vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`current={id:'run-map'};shell=(html)=>{page=html};showMessage=()=>{};renderRun=()=>{};api=async(path,options)=>{posted={path,body:JSON.parse(options.body)};return {id:'run-map'}};`,context);
(async()=>{
 const preview={source_sha256:'b'.repeat(64),sheet:'课程数据第二页',header_row:2,
  columns:[{column:1,header:'授课人'},{column:2,header:'所在学段'}],fields:[],detected_columns:[]};
 vm.runInContext(`mappingPage('/server/uploads/8f2a.xlsx','schedule',${JSON.stringify(preview)},'${'b'.repeat(64)}','原始课表.xlsx')`,context);
 const action=vm.runInContext('[...pendingImportMappings.keys()][0]',context);
 await vm.runInContext('applyPendingImportMapping',context)(action);
 const posted=vm.runInContext('posted',context);
 assert.equal(posted.path,'/api/runs/run-map/files');
 assert.equal(posted.body.path,'/server/uploads/8f2a.xlsx');
 assert.equal(posted.body.sha256,'b'.repeat(64));
 assert.equal(posted.body.name,'原始课表.xlsx');
 assert.equal(posted.body.mapping.sheet,'课程数据第二页');
 assert.equal(posted.body.mapping.header_row,2);
 assert.equal(posted.body.mapping.mapping.class_type,4);
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_quick_wrong_month_upload_shows_clear_schedule_mismatch_without_run_pollution() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[1],'utf8').split('(async () => {')[0];
const context={document:{querySelector(){return null},addEventListener(){}},window:{},console,btoa:()=>"c2FtcGxl"};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`current={id:'quick-september',period:'2026-09',ui_mode:'QUICK',monthly_flow_version:'SUBMISSION_FIRST_V1',files:{},quick_materials:[],subject_group_materials:[]};quickState={stage:'upload',uploaded:[],problem:null,result:null};let calls=[];renderRun=()=>{};showMessage=()=>{};bytesToBase64=()=>'';api=async(path)=>{calls.push(path);if(path==='/api/upload')return {path:'/uploads/server-copy.csv',sha256:'d'.repeat(64)};return {ok:false,run:{...current,quick_materials:[{kind:'SCHEDULE_PERIOD_MISMATCH',name:'八月排课表.csv',sha256:'${'d'.repeat(64)}'}]},materials:[{ok:false,error_kind:'SCHEDULE_PERIOD_MISMATCH',detected_kind:'schedule-period-mismatch',message:'这是一份排课表，但没有找到 2026-09 的排课记录。文件中的课程日期属于 2026-08。请检查工资月份或上传对应月份排课表。'}]}};`,context);
(async()=>{
 await vm.runInContext('uploadQuickFiles',context)([{name:'八月排课表.csv',arrayBuffer:async()=>new Uint8Array([1]).buffer}]);
 const problem=vm.runInContext('quickState.problem',context);
 assert.equal(problem.error_kind,'SCHEDULE_PERIOD_MISMATCH',JSON.stringify(problem));
 assert.ok(vm.runInContext('current.quick_materials[0].sha256',context));
 const page=vm.runInContext('quickRunPage()',context);
 assert.ok(page.includes('没有找到 2026-09 的排课记录'));
 assert.ok(page.includes('已上传的资料会保留'));
 assert.ok(!page.includes('生成工资表'));
 assert.deepEqual(vm.runInContext('calls',context),['/api/upload','/api/quick-runs/quick-september/materials']);
})().catch(error=>{console.error(error);process.exit(1)});
''')


def test_clicking_material_drop_zone_uses_browser_upload_input_not_native_path_picker() -> None:
    _node(r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const whole=fs.readFileSync(process.argv[1],'utf8');
const source=whole.slice(whole.indexOf('function bindMaterialDropZones()'),whole.indexOf('function bytesToBase64'));
const roles=['schedule','subject_group','renewal','refund','support','package'];
const zones=roles.map(role=>{const handlers={};return {dataset:{dropRole:role},style:{},handlers,
  addEventListener(name,fn){handlers[name]=fn},setAttribute(){}}});
const clicks={};
const document={
  addEventListener(){},
  querySelectorAll(selector){return selector==='[data-drop-role]'?zones:[]},
  querySelector(selector){
    const support=selector==='#support-material-file';
    const role=support?'support':(selector.match(/data-material-file-input="([^"]+)"/)||[])[1];
    if(!role)return null;
    return {click(){clicks[role]=(clicks[role]||0)+1}};
  }
};
const context={document,window:{},console};
vm.createContext(context);vm.runInContext(source,context);
vm.runInContext(`let nativePickerCalls=0;choose=()=>{nativePickerCalls++};browseMaterialFiles=(role)=>{const input=document.querySelector('[data-material-file-input="'+role+'"]');input?.click()};`,context);
vm.runInContext('bindMaterialDropZones()',context);
for(const zone of zones)zone.handlers.click();
assert.equal(vm.runInContext('nativePickerCalls',context),0,'material card clicks must not send the browser back to an OS path picker');
for(const role of ['schedule','subject_group','renewal','refund','support'])assert.equal(clicks[role],1,role);
assert.equal(clicks.package,undefined,'the package zone stays drag/paste only; its separate folder button is the fallback');
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
