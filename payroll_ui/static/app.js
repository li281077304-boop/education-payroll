let token = null;
let current = null;
let homeRuns = [];
let tab = "materials";
let filters = { field: "all", state: "all", decision: "all", teacher: "" };
let evidenceResolutionCourses = [];
let evidenceIssueId = "";
let detailBasisToken = null;
let partTimeRateRows = [];
let policyProfileRows = [];
let coreRuleEditingBase = {};

const coreStateLabels = {
  DETERMINED: "已确定",
  ESTIMATED: "估算",
  NEEDS_INPUT: "缺资料",
  NOT_APPLICABLE: "不适用",
};

const roleCopy = {
  schedule: ["原始排课数据", "选择原始排课表", "用于重新计算一对一和班课"],
  math: ["数学组提交表（任选）", "选择数学组提交表", "确定本次需要核验的教师"],
  science: ["理化组提交表（任选）", "选择理化组提交表", "确定本次需要核验的教师"],
  baseline: ["基准最终工资表（可选）", "选择基准最终工资表", "作为实际工资值和公式核验的依据"],
  check: ["最终工资核对表（可选）", "选择最终核对表", "仅作辅助查看，不作为排课依据"],
};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
const fmtDate = (value) => value ? new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

function versionList(payload) {
  return Array.isArray(payload) ? payload : (payload?.versions || []);
}

function splitNames(value) {
  return String(value || "").split(/[，,、；;]+/).map((item) => item.trim()).filter(Boolean);
}

function option(value, selectedValue, label) {
  return `<option value="${escapeHtml(value)}" ${value === selectedValue ? "selected" : ""}>${escapeHtml(label)}</option>`;
}

function coreVersionRows(versions, returnRunId = "") {
  return (versions || []).map((version) => {
    const rules = version.rules || {};
    const summary = `${rules.course_rules?.length || 0} 条班型 · ${Object.keys(rules.grade_coefficients || {}).length} 个年级 · ${rules.ae?.tiers?.length || 0} 档 AD`;
    const audit = [version.actor || "—", version.created_at ? fmtDate(version.created_at) : "—", version.sha256 ? `sha ${String(version.sha256).slice(0, 10)}` : ""].filter(Boolean).join(" · ");
    return `<tr><td>${escapeHtml(version.id)}</td><td>${escapeHtml(version.effective_from || "—")} ～ ${escapeHtml(version.effective_to || "持续")}</td><td>${escapeHtml(version.source || "—")}</td><td>${escapeHtml(summary)}</td><td>${escapeHtml(audit)}</td><td><button class="quiet" onclick="coreRulesDashboard('${escapeHtml(returnRunId)}', '${escapeHtml(version.id)}')">复制为新版本</button></td></tr>`;
  }).join("");
}

function applicableVersions(versions, runId) {
  const period = current?.id === runId ? current.period : "";
  return period ? versions.filter((version) => version.effective_from <= period && period <= version.effective_to) : versions;
}

function coreBindingControls(runId, versions, rateVersions) {
  if (!runId) return "";
  const coreVersions = applicableVersions(versions || [], runId);
  const partTimeVersions = applicableVersions(rateVersions || [], runId);
  const coreOptions = coreVersions.map((version) => option(version.id, current?.core_rule_version_id, `${version.id} · ${version.effective_from}～${version.effective_to} · ${version.source || "无来源"}`)).join("");
  const rateOptions = partTimeVersions.map((version) => option(version.id, current?.part_time_rate_version_id, `${version.id} · ${version.effective_from}～${version.effective_to} · ${version.source || "无来源"}`)).join("");
  const corePlaceholder = coreVersions.length > 1 && !current?.core_rule_version_id ? '<option value="" selected>同月多个版本，请先选择</option>' : "";
  const ratePlaceholder = partTimeVersions.length > 1 && !current?.part_time_rate_version_id ? '<option value="" selected>同月多个版本，请先选择</option>' : "";
  const coreReady = coreOptions && !(coreVersions.length > 1 && !current?.core_rule_version_id);
  const rateReady = rateOptions && !(partTimeVersions.length > 1 && !current?.part_time_rate_version_id);
  return `<section class="card rebind-card"><h2>当前核算显式绑定版本</h2><p class="muted">只列出适用于 ${escapeHtml(current?.period || "当前月份")} 的版本。同一月份有多个版本时不会默认替你选；绑定后系统立即重新核算，并保留原版本历史。</p><div class="binding-grid"><label>核心规则版本<select id="core-version-bind">${corePlaceholder}${coreOptions || '<option value="">当前月份没有可用版本</option>'}</select></label><button class="secondary" ${coreReady ? "" : "disabled"} onclick="bindCoreRules('${escapeHtml(runId)}')">绑定并重新核算</button><label>兼职单价版本<select id="part-time-version-bind">${ratePlaceholder}${rateOptions || '<option value="">当前月份没有可用版本</option>'}</select></label><button class="secondary" ${rateReady ? "" : "disabled"} onclick="bindPartTimeRates('${escapeHtml(runId)}')">绑定并重新核算</button></div></section>`;
}

function coreCourseRuleRow(rule = {}) {
  // 只有特殊班型可配置：一对一与普通小班固定在 Core，不出现在这里。
  const coefficients = Object.entries(rule.coefficients || {}).map(([count, value]) => `${count}=${value}`).join("、");
  return `<tr><td><input class="core-course-id" value="${escapeHtml(rule.id || "")}" placeholder="例如 special_one_to_two"></td><td><select class="core-course-treatment">${option("SPECIAL", rule.treatment, "特殊班型（按实到人数配置）")}</select></td><td><input class="core-course-types" value="${escapeHtml((rule.class_types || []).join("、"))}" placeholder="多个名称用顿号分隔"></td><td><input class="core-course-coefficients" value="${escapeHtml(coefficients)}" placeholder="实到人数=系数，例如 1=0.8、2=1.2"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function coreGradeRuleRow(name = "", coefficient = "", excluded = false) {
  return `<tr><td><input class="core-grade-name" value="${escapeHtml(name)}" placeholder="年级名称"></td><td><select class="core-grade-kind">${option("COEFFICIENT", excluded ? "EXCLUDED" : "COEFFICIENT", "参与计算")}${option("EXCLUDED", excluded ? "EXCLUDED" : "COEFFICIENT", "明确排除")}</select></td><td><input class="core-grade-coefficient" type="number" step="0.01" min="0" value="${escapeHtml(coefficient)}" placeholder="排除时留空"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function coreHeadcountRow(count = "", coefficient = "") {
  return `<tr><td><input class="core-headcount-count" type="number" step="1" min="1" value="${escapeHtml(count)}"></td><td><input class="core-headcount-coefficient" type="number" step="0.01" min="0" value="${escapeHtml(coefficient)}"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function coreTierRow(tier = {}) {
  return `<tr><td><input class="core-tier-id" value="${escapeHtml(tier.id || "")}" placeholder="档位名称"></td><td><input class="core-tier-min" type="number" step="0.01" min="0" value="${escapeHtml(tier.minimum ?? "")}"></td><td><label class="inline-check"><input class="core-tier-exclusive" type="checkbox" ${tier.minimum_exclusive ? "checked" : ""}>不含下限</label></td><td><input class="core-tier-max" type="number" step="0.01" min="0" value="${escapeHtml(tier.maximum ?? "")}" placeholder="最高档留空"></td><td><input class="core-tier-base" type="number" step="0.01" min="0" value="${escapeHtml(tier.base ?? "")}"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function coreStarRow(star = "", bonus = "") {
  return `<tr><td><input class="core-star-level" type="number" step="1" min="1" max="6" value="${escapeHtml(star)}"></td><td><input class="core-star-bonus" type="number" step="0.01" min="0" value="${escapeHtml(bonus)}"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function coreRulesEditor(rules) {
  const grades = Object.entries(rules.grade_coefficients || {}).map(([name, value]) => coreGradeRuleRow(name, value, false)).join("") + (rules.excluded_grades || []).map((name) => coreGradeRuleRow(name, "", true)).join("");
  const headcounts = Object.entries(rules.small_group_headcount_coefficients || {}).map(([count, value]) => coreHeadcountRow(count, value)).join("");
  const stars = Object.entries(rules.ae?.star_bonuses || {}).map(([star, value]) => coreStarRow(star, value)).join("");
  const candidate = rules.af?.default_policy_candidate;
  return `<div class="decision-form core-meta"><label>生效开始<input id="core-effective-from" type="month" value="${escapeHtml(rules.effective_from || "")}"></label><label>生效结束<input id="core-effective-to" type="month" value="${escapeHtml(rules.effective_to || "")}"></label><label>每节小时系数<input id="core-hour-factor" type="number" step="0.01" min="0" value="${escapeHtml(rules.lesson_hour_factor ?? "")}"></label></div>
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>特殊班型</h3><p class="muted small">特殊 1 对 2/1 对 3 必须按“班型 + 实到人数”配置；不能填一个固定单一系数。普通小班另按主核实到人数规则计算。</p></div><button type="button" class="quiet" onclick="addCoreCourseRule()">新增班型规则</button></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>规则标识</th><th>计算方式</th><th>班型名称</th><th>实到人数=系数</th><th></th></tr></thead><tbody id="core-course-editor">${(rules.course_rules || []).map(coreCourseRuleRow).join("")}</tbody></table></div></section>
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>年级系数与明确排除</h3><p class="muted small">没有配置且未明确排除的年级会显示“缺资料”。</p></div><button type="button" class="quiet" onclick="addCoreGradeRule()">新增年级</button></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>年级</th><th>处理方式</th><th>系数</th><th></th></tr></thead><tbody id="core-grade-editor">${grades}</tbody></table></div></section>
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>普通小班实到人数系数（固定，不可配置）</h3><p class="muted small">普通小班与一对一属于主核稳定规则，固定在 Core：普通小班按实到人数 1人0.8 / 2人1.0 / 3人1.2 …，一对一走独立 AA 逻辑。这里只读展示，不放进规则包。</p></div></div></section>
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>AE 课时档位（按 AD 小时数）</h3><p class="muted small">AD 档位驱动 AE 课时单价；边界连续且每个小时数只能命中一个档位，最高档上限留空。</p></div><button type="button" class="quiet" onclick="addCoreTierRule()">新增档位</button></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>档位</th><th>下限</th><th>边界</th><th>上限</th><th>基础金额</th><th></th></tr></thead><tbody id="core-tier-editor">${(rules.ae?.tiers || []).map(coreTierRow).join("")}</tbody></table></div></section>
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>星级加成</h3><p class="muted small">这是星级对应的金额加成；教师本人星级仍由独立星级资料确定。</p></div><button type="button" class="quiet" onclick="addCoreStarRule()">新增星级</button></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>星级</th><th>加成金额</th><th></th></tr></thead><tbody id="core-star-editor">${stars}</tbody></table></div></section>
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>AF 默认政策候选</h3><p class="muted small">仅在缺少个人有效期政策时作为“估算”；不会标成已确定。</p></div><label class="inline-check"><input id="core-af-default-enabled" type="checkbox" ${candidate ? "checked" : ""}>启用候选</label></div><div class="decision-form"><label>义务课时<input id="core-af-obligation" type="number" step="0.01" min="0" value="${escapeHtml(candidate?.obligation_hours ?? "")}"></label><label>候选名称<input id="core-af-label" value="${escapeHtml(candidate?.label || "")}"></label><label class="wide">候选来源<input id="core-af-source" value="${escapeHtml(candidate?.source || "")}"></label></div></section>`;
}

async function api(url, options = {}) {
  const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", "X-Payroll-Token": token, ...options.headers } });
  const type = response.headers.get("content-type") || "";
  const payload = type.includes("json") ? await response.json() : await response.text();
  if (!response.ok) throw new Error(payload.error || "操作未完成，请稍后重试。");
  return payload;
}

function showMessage(message, kind = "error") {
  let node = $("#message");
  if (!node) {
    document.body.insertAdjacentHTML("beforeend", '<div id="message" class="message"></div>');
    node = $("#message");
  }
  node.className = `message ${kind}`;
  node.textContent = message;
  node.hidden = false;
  window.clearTimeout(showMessage.timer);
  showMessage.timer = window.setTimeout(() => { node.hidden = true; }, 5200);
}

function statusBadge(run) {
  const kind = run.status === "STALE" ? "bad" : run.status === "FILES_READY" ? "info" : run.status === "DRAFT" ? "muted" : "warn";
  const icon = run.status === "STALE" ? "●" : run.status === "FILES_READY" ? "i" : run.status === "DRAFT" ? "○" : "⚠";
  return `<span class="status ${kind}">${icon} ${escapeHtml(run.status_label)}</span>`;
}

function shell(content, historyButton = true) {
  $("#app").innerHTML = `<div class="shell"><header class="top"><div><div class="brand">工资核算助手</div><div class="muted small">文件只在本机读取，不修改原工资表</div></div><div><button class="quiet" onclick="businessInputsPage()">业务填报</button>${current ? '<button class="quiet" onclick="writebackPage()">批注回填</button>' : ""}${historyButton ? '<button class="quiet" onclick="home()">核算历史</button>' : ""}<button class="quiet" onclick="payrollSheetsPage()">工资表汇总</button><button class="quiet" onclick="assessmentsPage()">岗位考核</button><a class="quiet" href="/teacher">教师填报</a></div></header>${content}</div>`;
}

async function home() {
  try {
    homeRuns = await api("/api/runs");
    current = null;
    const today = new Date();
    const defaultPeriod = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
    shell(`<section class="hero card"><div><p class="eyebrow">开始核算</p><h1>新建工资核算</h1><p class="muted">选择月份后，导入排课数据和本次提交表；如有基准最终工资表，系统以它作为工资结果依据。</p></div><div class="create-box"><label for="period">核算月份</label><input id="period" type="month" value="${defaultPeriod}" onchange="duplicateHint()"><label for="mode">这次要做什么</label><select id="mode"><option value="AUDIT">我要核对一份工资表（老师/组长已经做好了）</option><option value="GENERATE">直接帮我生成工资表（没有现成工资表）</option></select><p id="duplicate-hint" class="small muted"></p><button onclick="createRun()">创建并导入材料</button><button class="secondary full" onclick="authorityDashboard()">基础资料与规则</button></div></section><section class="card"><div class="section-head"><div><p class="eyebrow">历史记录</p><h2>最近核算</h2></div><span class="muted">${homeRuns.length} 条</span></div>${historyList()}</section>`, false);
    duplicateHint();
  } catch (error) { showMessage(error.message); }
}

async function authorityDashboard(runId = null, focus = "") {
  try {
    const catalog = await api("/api/authorities");
    const section = (title, versions, kind, click) => `<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>${title}</h2><p class="muted">版本会保留来源、生效期与被哪些核算记录使用；修正时请创建新版本，不要删除旧版本。</p></div><button class="secondary" onclick="${click}">查看与修正</button></div>${versions.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>状态</th><th>来源</th><th>已用于</th></tr></thead><tbody>${versions.map(v => `<tr><td>${escapeHtml(v.source_version || v.id)}</td><td>${escapeHtml(v.effective_from)} ～ ${escapeHtml(v.effective_to)}</td><td>${escapeHtml(v.status || "ACTIVE")}</td><td>${escapeHtml(v.source)}</td><td>${v.used_by_runs?.length || 0} 个 Run</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">尚未保存版本。</p>'}</section>`;
    const rebind = runId ? `<section class="card"><h2>让当前核算改用修正版</h2><p class="muted">这是明确的人工操作。切换后会要求重新全盘核对，相关人工意见会变为“需重新确认”。</p>${authorityRebindControl("rating", catalog.ratings, runId)}${authorityRebindControl("policy", catalog.policies, runId)}</section>` : "";
    const rules = catalog.rules.map(r => `<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.effective_from)} ～ ${escapeHtml(r.effective_to)}</td><td>${escapeHtml(r.source_version)}</td><td>${escapeHtml(r.source)}</td></tr>`).join("");
    shell(`<div class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>核对依据</h1><p class="muted">修正基础资料会新建版本；历史版本和已使用记录都不会被覆盖。</p></div><button class="secondary" onclick="${runId ? `openRun('${runId}')` : "home()"}">返回</button></div>${rebind}<section class="card core-entry-card"><div class="section-head"><div><p class="eyebrow">核心规则链</p><h2>核心规则配置（7 类）</h2><p class="muted">班型、人数、年级、AD、星级加成、个人政策和兼职单价统一从版本化资料读取；同一月份有多个版本时必须由你显式选择。</p></div><button onclick="coreRulesDashboard('${runId || ""}')">打开核心规则面板</button></div></section>${section("教师星级", catalog.ratings, "rating", `ratingDashboard('${runId || ""}')`)}${section("教师工资政策", catalog.policies, "policy", `policyDashboard('${runId || ""}')`)}<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>班型折算规则（旧入口）</h2><p class="muted">保留现有入口，历史版本继续可查；新的核心规则链请从上方七类面板维护。</p></div><button class="secondary" onclick="classTypeRulesPage('${runId || ""}')">查看与配置</button></div></section><section class="card"><div class="section-head"><div><p class="eyebrow">历史兼容</p><h2>历史兼容规则（只读）</h2><p class="muted">仅供旧核算记录继续解释原结果；配置化核算请以上方“核心规则配置”为准。</p></div></div><div class="table-wrap"><table class="table"><thead><tr><th>规则</th><th>生效期</th><th>版本</th><th>来源</th></tr></thead><tbody>${rules}</tbody></table></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

async function coreRulesDashboard(returnRunId = "", correctionId = "") {
  try {
    const [core, ratePayload] = await Promise.all([api("/api/core-rules"), api("/api/part-time-rates")]);
    const versions = core.versions || [];
    const correction = versions.find((version) => version.id === correctionId);
    const selectedRules = correction?.rules || core.seed || {};
    coreRuleEditingBase = JSON.parse(JSON.stringify(selectedRules));
    const rateVersions = versionList(ratePayload);
    const sourceDefault = correction?.source || "";
    const actorDefault = correction?.actor || "";
    const bind = coreBindingControls(returnRunId, versions, rateVersions);
    shell(`<section class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>核心规则面板（7 类）</h1><p class="muted">按真实字段逐项编辑；保存会创建不可变的新版本，不会覆盖历史 Run。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></section>${bind}<section class="card"><div class="section-head"><div><h2>已有核心规则版本</h2><p class="muted">点击“复制为新版本”后，在下方表格中修改。</p></div><span class="muted">${versions.length} 个版本</span></div><div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>来源</th><th>内容</th><th>审计信息</th><th></th></tr></thead><tbody>${coreVersionRows(versions, returnRunId) || '<tr><td colspan="6" class="muted">尚未保存核心规则版本。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建核心规则修正版" : "创建核心规则版本"}</h2><p class="muted">${correction ? `当前复制自 ${escapeHtml(correction.id)}；保存后旧版本仍保留。` : "请直接填写表格，不需要接触配置文件或代码。"}</p><div class="decision-form"><label>来源说明<input id="core-source" value="${escapeHtml(sourceDefault)}" placeholder="例如：2026 秋季规则确认"></label><label>操作人<input id="core-actor" value="${escapeHtml(actorDefault)}" placeholder="填写姓名"></label></div>${coreRulesEditor(selectedRules)}<div class="action-bar"><span class="muted small">保存只创建新版本；要用于某个 Run，需在上方显式绑定。</span><button onclick="saveCoreRules('${returnRunId}')">保存新核心规则版本</button></div></section><section class="core-rule-block core-rule-readonly"><div class="core-rule-block-head"><div><h3>个人政策</h3><p class="muted small">复用已有政策字段表单，明确填写 FULL_TIME/PART_TIME 和允许无课。</p></div><button class="secondary" onclick="policyDashboard('${returnRunId}')">管理个人政策</button></div><p class="core-rule-summary">个人政策单独版本化，保存时不会混入核心规则版本。</p></section><section class="core-rule-block core-rule-readonly"><div class="core-rule-block-head"><div><h3>兼职课次单价</h3><p class="muted small">复用独立单价版本，按教师 + 年级范围匹配，缺单价显示“缺资料”。</p></div><button class="secondary" onclick="partTimeRatesDashboard('${returnRunId}')">管理兼职单价</button></div><p class="core-rule-summary">兼职单价单独版本化，保存时不会混入核心规则版本。</p></section>`, false);
  } catch (error) { showMessage(error.message); }
}

function addCoreCourseRule() { $("#core-course-editor")?.insertAdjacentHTML("beforeend", coreCourseRuleRow()); }
function addCoreGradeRule() { $("#core-grade-editor")?.insertAdjacentHTML("beforeend", coreGradeRuleRow()); }
function addCoreHeadcountRule() { $("#core-headcount-editor")?.insertAdjacentHTML("beforeend", coreHeadcountRow()); }
function addCoreTierRule() { $("#core-tier-editor")?.insertAdjacentHTML("beforeend", coreTierRow()); }
function addCoreStarRule() { $("#core-star-editor")?.insertAdjacentHTML("beforeend", coreStarRow()); }

function editorRows(selector) { return [...document.querySelectorAll(`${selector} tr`)]; }
function inputValue(row, selector) { return row.querySelector(selector)?.value.trim() || ""; }

function collectCoreRules() {
  const rules = JSON.parse(JSON.stringify(coreRuleEditingBase || {}));
  const grade_coefficients = {};
  const excluded_grades = [];
  editorRows("#core-grade-editor").forEach((row) => {
    const name = inputValue(row, ".core-grade-name");
    if (!name) return;
    if (inputValue(row, ".core-grade-kind") === "EXCLUDED") excluded_grades.push(name);
    else grade_coefficients[name] = inputValue(row, ".core-grade-coefficient");
  });
  const course_rules = editorRows("#core-course-editor").map((row) => {
    const coefficients = {};
    (inputValue(row, ".core-course-coefficients") || "").split(/[、,;；\s]+/).forEach((pair) => {
      const parts = pair.split("=");
      if (parts.length === 2 && parts[0].trim() && parts[1].trim()) coefficients[parts[0].trim()] = parts[1].trim();
    });
    return { id: inputValue(row, ".core-course-id"), treatment: "SPECIAL", class_types: splitNames(inputValue(row, ".core-course-types")), coefficients };
  }).filter((rule) => rule.id || rule.class_types.length);
  const tiers = editorRows("#core-tier-editor").map((row) => ({
    id: inputValue(row, ".core-tier-id"),
    minimum: inputValue(row, ".core-tier-min"),
    maximum: inputValue(row, ".core-tier-max") || null,
    minimum_exclusive: Boolean(row.querySelector(".core-tier-exclusive")?.checked),
    base: inputValue(row, ".core-tier-base"),
  })).filter((tier) => tier.id);
  const star_bonuses = {};
  editorRows("#core-star-editor").forEach((row) => {
    const star = inputValue(row, ".core-star-level");
    if (star) star_bonuses[star] = inputValue(row, ".core-star-bonus");
  });
  const candidate = $("#core-af-default-enabled")?.checked ? {
    obligation_hours: $("#core-af-obligation")?.value.trim() || "",
    label: $("#core-af-label")?.value.trim() || "",
    source: $("#core-af-source")?.value.trim() || "",
  } : null;
  rules.schema_version = coreRuleEditingBase.schema_version || "payroll-core-rules/v1";
  rules.rule_version_id = coreRuleEditingBase.rule_version_id || "ui-new-version";
  rules.effective_from = $("#core-effective-from")?.value || rules.effective_from || "";
  rules.effective_to = $("#core-effective-to")?.value || rules.effective_to || "";
  rules.source = $("#core-source")?.value.trim() || rules.source || "";
  rules.lesson_hour_factor = $("#core-hour-factor")?.value.trim() || rules.lesson_hour_factor || "";
  rules.grade_coefficients = grade_coefficients;
  rules.excluded_grades = excluded_grades;
  rules.course_rules = course_rules;
  rules.small_group_headcount_coefficients = small_group_headcount_coefficients;
  rules.ae = { ...(rules.ae || {}), tiers, star_bonuses };
  rules.af = { ...(rules.af || {}) };
  if (candidate) rules.af.default_policy_candidate = candidate;
  else delete rules.af.default_policy_candidate;
  return rules;
}

async function saveCoreRules(returnRunId = "") {
  try {
    const rules = collectCoreRules();
    const payload = { rules, source: $("#core-source")?.value.trim() || "", actor: $("#core-actor")?.value.trim() || "" };
    if (!payload.source || !payload.actor) throw new Error("请填写规则来源和操作人。");
    const saved = await api("/api/core-rules", { method: "POST", body: JSON.stringify(payload) });
    const savedId = versionList(saved)[0]?.id;
    showMessage(`核心规则已保存为新版本${savedId ? `：${savedId}` : ""}。历史 Run 不会自动改变。`, "success");
    await coreRulesDashboard(returnRunId);
  } catch (error) { showMessage(error.message); }
}

async function bindCoreRules(runId) {
  const versionId = $("#core-version-bind")?.value;
  if (!versionId) return showMessage("请选择核心规则版本。");
  if (!window.confirm("确认将此核心规则版本绑定到当前 Run，并重新核算吗？历史结果不会被静默改写。")) return;
  try {
    const result = await api(`/api/runs/${runId}/core-rules`, { method: "POST", body: JSON.stringify({ version_id: versionId }) });
    current = result.run || result;
    if (!current.id) current = await api(`/api/runs/${runId}`);
    tab = ["REVIEW_REQUIRED", "PASS"].includes(current.status) ? "overview" : "materials";
    renderRun();
    showMessage(`已显式绑定核心规则版本 ${versionId}，并完成重新核算。`, "success");
  } catch (error) { showMessage(error.message); }
}

async function bindPartTimeRates(runId) {
  const versionId = $("#part-time-version-bind")?.value;
  if (!versionId) return showMessage("请选择兼职单价版本。");
  if (!window.confirm("确认将此兼职单价版本绑定到当前 Run，并重新核算吗？历史结果不会被静默改写。")) return;
  try {
    const result = await api(`/api/runs/${runId}/part-time-rates`, { method: "POST", body: JSON.stringify({ version_id: versionId }) });
    current = result.run || result;
    if (!current.id) current = await api(`/api/runs/${runId}`);
    tab = ["REVIEW_REQUIRED", "PASS"].includes(current.status) ? "overview" : "materials";
    renderRun();
    showMessage(`已显式绑定兼职单价版本 ${versionId}，并完成重新核算。`, "success");
  } catch (error) { showMessage(error.message); }
}

function authorityRebindControl(kind, versions, runId) {
  const applicable = versions.filter(v => v.status === "ACTIVE" && v.effective_from <= current?.period && current?.period <= v.effective_to);
  const label = kind === "rating" ? "星级版本" : "工资政策版本";
  return `<div class="action-bar"><label>${label}<select id="rebind-${kind}">${applicable.map(v => `<option value="${escapeHtml(v.id)}">${escapeHtml(v.source_version || v.id)} · ${escapeHtml(v.source)}</option>`).join("") || '<option value="">没有适用版本</option>'}</select></label><button class="secondary" ${applicable.length ? "" : "disabled"} onclick="rebindAuthority('${runId}', '${kind}')">改用选中修正版并重新核对</button></div>`;
}

async function rebindAuthority(runId, kind) {
  try { current = await api(`/api/runs/${runId}/authority`, { method: "POST", body: JSON.stringify({ kind, version_id: $(`#rebind-${kind}`).value }) }); tab = "materials"; renderRun(); showMessage("当前核算已改用新版本；请重新全盘核对。", "success"); }
  catch (error) { showMessage(error.message); }
}

async function ratingDashboard(returnRunId = "", correctionId = "") {
  try {
    const versions = await api("/api/ratings");
    const correction = versions.find(v => v.id === correctionId);
    const rows = versions.flatMap((version) => version.ratings.map((rating) => `<tr><td>${escapeHtml(rating.teacher)}</td><td>${rating.rating} 星</td><td>${escapeHtml(version.effective_from)} ～ ${escapeHtml(version.effective_to)}</td><td>${escapeHtml(version.source)}</td><td>${escapeHtml(version.status || "ACTIVE")}</td><td><button class="quiet" onclick="ratingDashboard('${returnRunId}', '${version.id}')">创建修正版</button></td></tr>`));
    const latest = versions[0];
    const list = correction ? correction.ratings.map(x => `${x.teacher}，${x.rating}，${x.role || "教师"}，${x.allow_blank_payroll_rating ? "是" : "否"}`).join("\n") : "";
    shell(`<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h1>教师星级</h1><p class="muted">工资核算按月份绑定当时生效的星级版本，不会用新年度名单覆盖历史月份。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></div><div class="banner info"><strong>当前最新版本：${latest ? `${escapeHtml(latest.effective_from)} ～ ${escapeHtml(latest.effective_to)}` : "尚未导入"}</strong><span>${latest ? `下一次更新时间：${escapeHtml(String(Number(latest.effective_to.slice(0, 4)) + 1))}-10` : "请先导入年度星级名单。"}</span></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>星级</th><th>生效期</th><th>数据来源</th><th>状态</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="6" class="muted">尚未保存星级名单。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建星级修正版" : "导入新的星级版本"}</h2><p class="muted">${correction ? "原版本会保留并标记为 SUPERSEDED；请在下面修正后保存新版本。" : "每行填写：教师姓名，星级，岗位，工资表是否允许不显示星级。"}</p><input id="rating-supersedes" type="hidden" value="${escapeHtml(correction?.id || "")}"><div class="decision-form"><label>生效开始<input id="rating-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="rating-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label>数据来源<input id="rating-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：2025年度星级评定"></label><label>版本名称<input id="rating-version" value="${escapeHtml(correction ? `${correction.source_version} corrected` : "")}" placeholder="例如：2025-10 v2"></label><label class="wide">名单<textarea id="rating-list" placeholder="张三，4，教师，否">${escapeHtml(list)}</textarea></label></div><div class="action-bar"><span class="muted small">保存不会修改工资表，也不会自动改变历史 Run。</span><button onclick="saveRatings('${returnRunId}')">保存星级版本</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

async function saveRatings(returnRunId = "") {
  try {
    const ratings = $("#rating-list").value.split(/\n+/).filter(Boolean).map((line) => { const [teacher, rating, role, blankAllowed] = line.split(/[，,]/).map((item) => item.trim()); return { teacher, rating: Number(rating), role: role || "教师", allow_blank_payroll_rating: ["是", "true", "1"].includes(String(blankAllowed).toLowerCase()) }; });
    await api("/api/ratings", { method: "POST", body: JSON.stringify({ effective_from: $("#rating-from").value, effective_to: $("#rating-to").value, source: $("#rating-source").value, source_version: $("#rating-version").value, ratings, supersedes_version_id: $("#rating-supersedes").value || null }) });
    showMessage("星级版本已保存。若要用于当前核算，请在“当前核对依据”中主动切换。", "success"); await ratingDashboard(returnRunId);
  } catch (error) { showMessage(error.message); }
}

async function policyDashboard(returnRunId = "", correctionId = "") {
  try {
    const versions = await api("/api/policies");
    const correction = versions.find(v => v.id === correctionId);
    const rows = versions.flatMap((version) => version.profiles.map((profile) => `<tr><td>${escapeHtml(profile.teacher)}</td><td>${escapeHtml(profile.role)}</td><td>${escapeHtml(profile.employment_type || "FULL_TIME")}</td><td>${profile.allow_no_teaching ? "是" : "否"}</td><td>${profile.rating_override || profile.rating || "待确认"} 星</td><td>${profile.obligation_hours_deduction_enabled ? `${profile.obligation_hours} 小时，扣除` : "不扣除"}</td><td>${escapeHtml(profile.special_approval || "无")}</td><td>${escapeHtml(version.effective_from)} ～ ${escapeHtml(version.effective_to)}</td><td>${escapeHtml(version.status || "ACTIVE")}</td><td><button class="quiet" onclick="policyDashboard('${returnRunId}', '${version.id}')">创建修正版</button></td></tr>`));
    policyProfileRows = correction?.profiles ? JSON.parse(JSON.stringify(correction.profiles)) : [{}];
    shell(`<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h1>教师工资政策档案</h1><p class="muted">逐人明确全职/兼职、个人义务课时和是否允许管理岗当月无课；不会根据岗位文字自动猜测。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>身份</th><th>用工类型</th><th>允许无课</th><th>星级</th><th>义务课时</th><th>特殊审批</th><th>生效期</th><th>状态</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="10" class="muted">尚未保存工资政策档案。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建政策修正版" : "保存政策版本"}</h2><p class="muted">每位教师一行。允许无课必须显式勾选；旧档案未填写时仍按“全职 / 不允许”显示。</p><input id="policy-supersedes" type="hidden" value="${escapeHtml(correction?.id || "")}"><div class="decision-form"><label>生效开始<input id="policy-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="policy-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label class="wide">数据来源<input id="policy-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：年度工资政策确认"></label></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>教师</th><th>身份</th><th>用工类型</th><th>允许无课</th><th>基础星级</th><th>特批星级</th><th>义务小时</th><th>扣除义务小时</th><th>特殊审批</th><th></th></tr></thead><tbody id="policy-profile-editor">${policyProfileRows.map(policyProfileEditorRow).join("")}</tbody></table></div><div class="action-bar"><button type="button" class="secondary" onclick="addPolicyProfileRow()">新增教师</button><span class="muted small">保存不会修改工资表，也不会自动改变历史 Run。</span><button onclick="savePolicies('${returnRunId}')">保存政策版本</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

function policyProfileEditorRow(profile = {}) {
  const employment = profile.employment_type || "FULL_TIME";
  return `<tr><td><input class="policy-teacher" value="${escapeHtml(profile.teacher || "")}" placeholder="教师姓名"></td><td><input class="policy-role" value="${escapeHtml(profile.role || "")}" placeholder="例如 教师/管理岗"></td><td><select class="policy-employment">${option("FULL_TIME", employment, "全职")}${option("PART_TIME", employment, "兼职")}</select></td><td><label class="inline-check"><input class="policy-no-teaching" type="checkbox" ${profile.allow_no_teaching ? "checked" : ""}>允许</label></td><td><input class="policy-rating" type="number" min="1" max="6" step="1" value="${escapeHtml(profile.rating ?? "")}"></td><td><input class="policy-rating-override" type="number" min="1" max="6" step="1" value="${escapeHtml(profile.rating_override ?? "")}" placeholder="可空"></td><td><input class="policy-obligation" type="number" min="0" step="0.01" value="${escapeHtml(profile.obligation_hours ?? 0)}"></td><td><label class="inline-check"><input class="policy-deduct" type="checkbox" ${profile.obligation_hours_deduction_enabled ? "checked" : ""}>扣除</label></td><td><input class="policy-approval" value="${escapeHtml(profile.special_approval || "")}" placeholder="可空"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function addPolicyProfileRow() { $("#policy-profile-editor")?.insertAdjacentHTML("beforeend", policyProfileEditorRow()); }

function collectPolicyProfiles() {
  return editorRows("#policy-profile-editor").map((row) => ({
    teacher: inputValue(row, ".policy-teacher"),
    role: inputValue(row, ".policy-role"),
    employment_type: inputValue(row, ".policy-employment") || "FULL_TIME",
    allow_no_teaching: Boolean(row.querySelector(".policy-no-teaching")?.checked),
    rating: inputValue(row, ".policy-rating") ? Number(inputValue(row, ".policy-rating")) : null,
    rating_override: inputValue(row, ".policy-rating-override") ? Number(inputValue(row, ".policy-rating-override")) : null,
    obligation_hours: Number(inputValue(row, ".policy-obligation") || 0),
    obligation_hours_deduction_enabled: Boolean(row.querySelector(".policy-deduct")?.checked),
    special_approval: inputValue(row, ".policy-approval"),
  })).filter((profile) => profile.teacher || profile.role);
}

async function savePolicies(returnRunId = "") {
  try {
    const profiles = collectPolicyProfiles();
    if (!profiles.length) throw new Error("请至少填写一位教师的政策。");
    await api("/api/policies", { method: "POST", body: JSON.stringify({ effective_from: $("#policy-from").value, effective_to: $("#policy-to").value, source: $("#policy-source").value, profiles, supersedes_version_id: $("#policy-supersedes").value || null }) });
    showMessage("工资政策版本已保存。若要用于当前核算，请在“当前核对依据”中主动切换。", "success"); await policyDashboard(returnRunId);
  } catch (error) { showMessage(error.message); }
}

async function partTimeRatesDashboard(returnRunId = "", correctionId = "") {
  try {
    const payload = await api("/api/part-time-rates");
    const versions = versionList(payload);
    const correction = versions.find((version) => version.id === correctionId);
    partTimeRateRows = correction?.profiles ? JSON.parse(JSON.stringify(correction.profiles)) : [{ teacher: "", grade_scope: "", rate_per_session: "" }];
    const rows = versions.flatMap((version) => (version.profiles || []).map((profile) => `<tr><td>${escapeHtml(profile.teacher)}</td><td>${escapeHtml(profile.grade_scope || "全部年级")}</td><td>${escapeHtml(profile.rate_per_session)}</td><td>${escapeHtml(version.effective_from || "—")} ～ ${escapeHtml(version.effective_to || "持续")}</td><td>${escapeHtml(version.source || "—")}</td><td>${escapeHtml(version.actor || "—")}</td><td><button class="quiet" onclick="partTimeRatesDashboard('${returnRunId}', '${escapeHtml(version.id)}')">创建修正版</button></td></tr>`));
    shell(`<section class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>兼职课次单价</h1><p class="muted">兼职不走 AA/AC/AD/AE/AF 全职链路；按教师、年级范围和每课次单价计算“兼职按节课时费”，缺单价时显示“缺资料”。</p></div><button class="secondary" onclick="coreRulesDashboard('${returnRunId}')">返回核心规则面板</button></section>${returnRunId ? `<section class="card rebind-card"><h2>当前核算的兼职版本</h2><p class="muted">需要切换时请返回核心规则面板并显式选择版本。</p></section>` : ""}<section class="card"><div class="section-head"><div><h2>已有单价版本</h2><p class="muted">旧版本保留；同一核算月份有多个版本时由你显式选择。</p></div><span class="muted">${versions.length} 个版本</span></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>年级范围</th><th>每课次单价</th><th>生效期</th><th>来源</th><th>操作人</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="7" class="muted">尚未保存兼职单价版本。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建兼职单价修正版" : "保存兼职单价版本"}</h2><p class="muted">${correction ? `当前复制自 ${escapeHtml(correction.id)}；保存会新建版本，不会覆盖旧版本。` : "每位教师和年级范围各填一行。"}</p><div class="decision-form"><label>生效开始<input id="part-time-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="part-time-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label>数据来源<input id="part-time-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：2026-09 兼职确认表"></label><label>操作人<input id="part-time-actor" value="${escapeHtml(correction?.actor || "")}" placeholder="填写姓名"></label></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>教师</th><th>年级范围</th><th>每课次单价</th><th></th></tr></thead><tbody id="part-time-rate-editor">${partTimeRateRows.map(partTimeRateEditorRow).join("")}</tbody></table></div><div class="action-bar"><button type="button" class="secondary" onclick="addPartTimeRateRow()">新增一行</button><span class="muted small">保存不会修改工资表，也不会自动改变历史 Run。</span><button onclick="savePartTimeRates('${returnRunId}')">保存兼职单价版本</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

function partTimeRateEditorRow(profile = {}) {
  return `<tr><td><input class="part-time-teacher" value="${escapeHtml(profile.teacher || "")}" placeholder="教师姓名"></td><td><input class="part-time-grade" value="${escapeHtml(profile.grade_scope || "*")}" placeholder="例如 七年级；全部年级填 *"></td><td><input class="part-time-rate" type="number" min="0" step="0.01" value="${escapeHtml(profile.rate_per_session ?? "")}" placeholder="元/课次"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function addPartTimeRateRow() {
  $("#part-time-rate-editor")?.insertAdjacentHTML("beforeend", partTimeRateEditorRow());
}

function collectPartTimeProfiles() {
  return [...document.querySelectorAll("#part-time-rate-editor tr")].map((row) => {
    const teacher = inputValue(row, ".part-time-teacher");
    const grade_scope = inputValue(row, ".part-time-grade");
    const rateText = inputValue(row, ".part-time-rate");
    if (!teacher && !grade_scope && !rateText) return null;
    if (!teacher || !grade_scope || rateText === "") throw new Error("兼职单价每行都要填写教师、年级范围和单价。");
    return { teacher, grade_scope, rate_per_session: Number(rateText) };
  }).filter(Boolean);
}

async function savePartTimeRates(returnRunId = "") {
  try {
    const profiles = collectPartTimeProfiles();
    const payload = { profiles, source: $("#part-time-source")?.value.trim() || "", effective_from: $("#part-time-from")?.value || "", effective_to: $("#part-time-to")?.value || "", actor: $("#part-time-actor")?.value.trim() || "" };
    if (!profiles.length || !payload.source || !payload.effective_from || !payload.effective_to || !payload.actor) throw new Error("请填写兼职单价、来源、生效月份和操作人。");
    const saved = await api("/api/part-time-rates", { method: "POST", body: JSON.stringify(payload) });
    const savedId = versionList(saved)[0]?.id;
    showMessage(`兼职单价已保存为新版本${savedId ? `：${savedId}` : ""}。历史 Run 不会自动改变。`, "success");
    await partTimeRatesDashboard(returnRunId);
  } catch (error) { showMessage(error.message); }
}

function historyList() {
  if (!homeRuns.length) return '<div class="empty">还没有核算记录。创建后，即使关闭程序也可以从这里继续。</div>';
  return `<div class="history-list">${homeRuns.map((run) => {
    const summary = run.summary || {};
    const groupCount = (run.issue_groups || []).length;
    const fieldCount = run.issues?.length || summary.unexplained || summary.manual_review || 0;
    const next = run.status === "STALE" ? "重新选择变化的材料" : run.status === "DRAFT" ? "继续导入材料" : run.status === "FILES_READY" ? "开始核对" : (summary.unexplained || summary.manual_review) ? "处理核对问题" : "查看核对结果";
    return `<article class="history-row"><div><strong>${escapeHtml(run.period)}</strong><div class="small muted">编号 ${escapeHtml(run.id)} · 更新于 ${fmtDate(run.updated_at || run.created_at)}</div></div><div>${statusBadge(run)}<div class="small muted">材料 ${run.health.readiness}% · 待处理 ${groupCount} 个问题${fieldCount ? `（字段核查 ${fieldCount} 项）` : ""}</div></div><button class="secondary" onclick="openRun('${run.id}')">${next}</button></article>`;
  }).join("")}</div>`;
}

function duplicateHint() {
  const input = $("#period");
  const hint = $("#duplicate-hint");
  if (!input || !hint) return;
  const count = homeRuns.filter((run) => run.period === input.value).length;
  hint.textContent = count ? `该月份已有 ${count} 条记录，新记录会单独保存。` : "";
}

async function createRun() {
  try {
    const mode = $("#mode") ? $("#mode").value : "AUDIT";
    current = await api("/api/runs", { method: "POST", body: JSON.stringify({ period: $("#period").value, mode }) });
    tab = "materials";
    renderRun();
  } catch (error) { showMessage(error.message); }
}

async function openRun(id) {
  try {
    current = await api(`/api/runs/${id}`);
    tab = current.status === "STALE" || current.status === "DRAFT" || current.status === "FILES_READY" ? "materials" : (current.issue_groups || []).length ? "issues" : "overview";
    renderRun();
  } catch (error) { showMessage(error.message); }
}

function runSteps() {
  const checked = ["REVIEW_REQUIRED", "PASS"].includes(current.status);
  return `<div class="steps"><span class="done">1 创建记录</span><span class="${current.health.readiness === 100 ? "done" : ""}">2 准备材料</span><span class="${checked ? "done" : ""}">3 查看结果</span><span class="${current.decisions?.length ? "done" : ""}">4 处理问题</span></div>`;
}

function navigation() {
  const checked = ["REVIEW_REQUIRED", "PASS"].includes(current.status);
  const groupCount = (current.issue_groups || []).length;
  const items = [["materials", "材料准备", true], ["overview", "核对结果", checked], ["issues", `待处理问题${groupCount ? ` (${groupCount})` : ""}`, checked], ["management", "管理岗位确认", true]];
  return `<nav class="tabs">${items.map(([id, label, enabled]) => `<button class="${tab === id ? "active" : ""}" ${enabled ? `onclick="setTab('${id}')"` : "disabled"}>${label}</button>`).join("")}</nav>`;
}

function reconfirmationBanner(run) {
  const count = (run.business_decisions || []).filter(d => d.status === "NEEDS_RECONFIRMATION").length;
  return count ? `<div class="banner error"><strong>${count} 条人工决定需要重新确认</strong><span>依据已变化，原意见仅保留为历史记录，不再自动生效。更新材料并重新核对后，请重新判断。</span></div>` : "";
}

function renderRun() {
  const stale = reconfirmationBanner(current) + (current.status === "STALE" ? '<div class="banner error"><strong>原始文件已发生变化</strong><span>请重新选择标记为“已变化”的材料，再重新核对。旧结果不会继续显示为有效。</span></div>' : "");
  const lastError = current.last_error ? `<div class="banner error"><strong>上次核对未完成</strong><span>${escapeHtml(current.last_error)}</span></div>` : "";
  shell(`<div class="run-title"><div><p class="eyebrow">${escapeHtml(current.period)}</p><h1>工资核对</h1><div class="small muted">记录编号 ${escapeHtml(current.id)}</div></div>${statusBadge(current)}</div>${runSteps()}${stale}${lastError}${authoritySummary()}${navigation()}<section id="view"></section>`);
  renderTab();
}

function authoritySummary() {
  const context = current.authority_context || {};
  const fact = (key, title) => {
    const item = context[key] || {};
    const detail = [item.source, item.effective_period, item.name && item.name !== "尚未绑定" ? `版本：${item.name}` : ""].filter(Boolean).join(" · ");
    return `<div><strong>${title}</strong><span>${escapeHtml(detail || item.name || "尚未绑定")}</span></div>`;
  };
  const extra = context.core_rules || context.part_time_rates ? `${context.core_rules ? fact("core_rules", "核心规则版本") : ""}${context.part_time_rates ? fact("part_time_rates", "兼职单价版本") : ""}` : "";
  const legacyRuleLabel = current.calculation_engine === "CONFIGURED_V1" ? "历史兼容规则" : "工资规则版本";
  return `<details class="authority-summary"><summary>当前核对依据</summary><div class="facts">${fact("schedule", "排课权威源")}${fact("rating", "星级权威版本")}${fact("policy", "教师政策版本")}${fact("rules", legacyRuleLabel)}${extra}</div><div class="action-bar"><span class="muted small">发现基础资料录入错误时，请创建修正版；旧版本与历史 Run 会继续保留。</span><button class="secondary" onclick="authorityDashboard('${current.id}')">查看、修正或改用版本</button></div></details>`;
}

function setTab(next) { tab = next; renderRun(); }
function renderTab() {
  const view = $("#view");
  if (tab === "materials") view.innerHTML = materialsPage();
  if (tab === "overview") view.innerHTML = overviewPage();
  if (tab === "issues") view.innerHTML = issuesPage();
  if (tab === "management") view.innerHTML = managementPage();
}

function materialsPage() {
  const warnings = [...new Set(current.health.warnings || [])];
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 1 步</p><h2>准备核算材料</h2><p class="muted">排课数据和提交表齐全即可开始。导入基准最终工资表后，系统会用它核验本次提交教师。</p></div><strong class="readiness">${current.health.readiness}%</strong></div><div class="material-grid">${current.materials.map(materialCard).join("")}</div>${warnings.length ? `<div class="warning-list"><strong>材料提示</strong>${warnings.map((warning) => `<p>⚠ ${escapeHtml(warning)}</p>`).join("")}</div>` : ""}<div class="action-bar"><div>${current.health.missing.length ? `<strong>还缺：</strong>${current.health.missing.map(escapeHtml).join("、")}` : (current.mode === "GENERATE" ? "排课数据已准备，可以直接生成工资表（缺基础资料时只会生成草稿）。" : "必需材料已准备，可以开始核对。")}</div><div><button class="secondary" onclick="refreshRun()">重新检查材料</button>${current.mode === "GENERATE" ? `<button ${current.health.ready ? "" : "disabled"} onclick="generatePayroll()">生成标准工资表</button>` : `<button ${current.health.ready ? "" : "disabled"} onclick="recheck()">开始核对</button>`}</div></div></section>`;
}

function materialCard(material) {
  const copy = roleCopy[material.role];
  const file = material.file;
  const stateClass = material.state === "失效" ? "bad" : file ? "ok" : material.required ? "warn" : "muted";
  const stateText = material.state === "失效" ? "● 已变化，需重新选择" : file ? "✓ 已识别" : material.required ? "○ 必需材料" : "可稍后补充";
  const risk = file ? [file.missing_cache ? `${file.missing_cache} 个公式结果不可读取` : "", file.external_references ? `${file.external_references} 处依赖其他文件` : ""].filter(Boolean) : [];
  return `<article class="material-card ${material.state === "失效" ? "stale" : ""}"><div class="material-top"><strong>${escapeHtml(copy[0])}</strong><span class="${stateClass}">${stateText}</span></div><p class="small muted">${escapeHtml(copy[2])}</p>${file ? `<div class="file-name">${escapeHtml(file.name)}</div><div class="facts"><span>${file.records} 条记录</span><span>${file.teachers} 名教师</span></div>${risk.length ? `<p class="small warn">⚠ ${risk.join("；")}</p>` : ""}<details><summary>查看文件信息</summary><p class="small muted">工作表：${file.sheets.map(escapeHtml).join("、")}<br>文件标识：${file.sha256.slice(0, 10)}</p></details>` : '<div class="empty compact">尚未选择文件</div>'}<button class="secondary full" onclick="choose('${material.role}')">${escapeHtml(copy[1])}</button></article>`;
}

function coreCalculationCell(field) {
  if (!field || typeof field !== "object") return `<div class="core-result-cell"><strong>${escapeHtml(field ?? "—")}</strong></div>`;
  const state = String(field.state || "NEEDS_INPUT").toUpperCase();
  const label = coreStateLabels[state] || escapeHtml(field.state || "缺资料");
  const className = state === "DETERMINED" ? "determined" : state === "ESTIMATED" ? "estimated" : state === "NOT_APPLICABLE" ? "not-applicable" : "needs-input";
  const evidence = Array.isArray(field.evidence) && field.evidence.length ? `<details><summary>依据</summary><div class="small muted">${field.evidence.map((item) => escapeHtml(typeof item === "object" ? Object.values(item).join(" · ") : item)).join("<br>")}</div></details>` : "";
  return `<div class="core-result-cell ${className}"><strong>${escapeHtml(field.value ?? "—")}</strong><span>${label}</span><small>${escapeHtml(field.reason || "")}</small>${evidence}</div>`;
}

function coreCalculationSection() {
  const calculation = current.core_calculation;
  const rows = calculation?.rows || [];
  if (!rows.length) return "";
  const fieldKey = (row, key) => row.fields?.[key] || row.fields?.[key.toLowerCase()] || row[key] || null;
  const rendered = rows.map((row) => `<tr><td><strong>${escapeHtml(row.teacher || row.teacher_id || "—")}</strong></td><td>${coreCalculationCell(fieldKey(row, "AA"))}</td><td>${coreCalculationCell(fieldKey(row, "AC"))}</td><td>${coreCalculationCell(fieldKey(row, "AD"))}</td><td>${coreCalculationCell(fieldKey(row, "AE"))}</td><td>${coreCalculationCell(fieldKey(row, "AF"))}</td><td>${coreCalculationCell(fieldKey(row, "PART_TIME"))}</td></tr>`).join("");
  const versionNote = [current.core_rule_version_id ? `核心规则 ${current.core_rule_version_id}` : "", current.part_time_rate_version_id ? `兼职单价 ${current.part_time_rate_version_id}` : ""].filter(Boolean).join(" · ");
  return `<section class="card core-calculation-card"><div class="section-head"><div><p class="eyebrow">核心计算结果</p><h2>每位教师的核心字段</h2><p class="muted">状态为“估算”“缺资料”或“不适用”的项目不会冒充全薪通过。${escapeHtml(versionNote)}</p></div></div><div class="table-wrap"><table class="table core-calculation-table"><thead><tr><th>教师</th><th>AA</th><th>AC</th><th>AD</th><th>AE</th><th>AF</th><th>兼职按节课时费</th></tr></thead><tbody>${rendered}</tbody></table></div></section>`;
}

function overviewPage() {
  const summary = current.summary || {};
  const headline = summary.automatic_pass ? "排课项目核对完成" : "排课项目仍有问题";
  const scopeNote = current.calculation_engine === "CONFIGURED_V1" ? (summary.scope_note || "配置化核心结果按当前 Run 绑定版本计算。") : "星级、档位和课时费政策会按已有资料核对；AD 仍来自工资表目标自身，尚未形成独立闭环。";
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">核对结果</p><h2>${headline}</h2><p class="muted">整份工资仍包含需要上游数据或人工确认的项目。</p></div><button class="secondary" onclick="downloadReport()">导出核对报告</button></div><div class="metric-grid"><div class="metric"><span>排课项目完成度</span><strong>${summary.automatic_coverage ?? 0}%</strong><small>${summary.automatic_completed ?? 0} / ${summary.automatic_required ?? 0} 项</small></div><div class="metric"><span>未说明的差异</span><strong>${summary.unexplained ?? 0}</strong><small>必须处理</small></div><div class="metric"><span>需要人工确认</span><strong>${summary.manual_review ?? 0}</strong><small>不能自动判断</small></div></div><h3>每个项目实际检查到哪一步</h3><div class="table-wrap"><table class="table scope"><thead><tr><th>项目</th><th>读取工资表</th><th>可靠原始依据</th><th>重新计算</th><th>与工资表比较</th><th>当前结论</th></tr></thead><tbody>${current.field_status.map(fieldRow).join("")}</tbody></table></div><div class="banner info"><strong>检查范围说明</strong><span>${escapeHtml(scopeNote)}</span></div><div class="action-bar"><div>${summary.automatic_pass ? "AA、AC 没有待处理项。" : "请先处理异常中心中的问题。"}</div><div><button class="secondary" onclick="setTab('issues')">查看待处理问题</button><button onclick="recheck()">重新核对全部材料</button></div></div></section>${coreCalculationSection()}`;
}

function fieldRow(field) {
  const mark = (value) => value ? '<span class="check">✓</span>' : '<span class="dash">—</span>';
  return `<tr><td><strong>${escapeHtml(field.label)}</strong></td><td>${mark(field.read)}</td><td>${mark(field.authority)}</td><td>${mark(field.computed)}</td><td>${mark(field.compared)}</td><td><span class="field-state">${escapeHtml(field.state)}</span><div class="small muted">${escapeHtml(field.note)}</div></td></tr>`;
}

function issuesPage() {
  const groups = current.issue_groups || [];
  const rows = groups.filter((group) => !filters.teacher || String(group.teacher || "").includes(filters.teacher.trim()));
  const fieldCount = current.issues?.length || groups.reduce((total, group) => total + (group.count || group.field_records?.length || 0), 0);
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">异常中心</p><h2>待处理问题</h2><p class="muted">同一原因的字段核查会合并为一个业务问题。</p></div><button onclick="recheck()">重新核对全部材料</button></div><div class="filters"><label for="filter-teacher">教师<input id="filter-teacher" placeholder="输入教师姓名" value="${escapeHtml(filters.teacher)}" oninput="updateFilters()"></label></div><div class="result-count">显示 ${rows.length} 个业务问题（字段核查记录 ${fieldCount} 项）</div>${rows.length ? `<div class="table-wrap"><table class="table issues"><thead><tr><th>程度</th><th>问题</th><th>教师</th><th>影响字段</th><th>系统值</th><th>工资表值</th><th>差异</th><th><span class="sr-only">操作</span></th></tr></thead><tbody>${rows.map(issueRow).join("")}</tbody></table></div>` : '<div class="empty">当前筛选条件下没有问题。</div>'}<div id="issue-detail"></div></section>`;
}

function issueRow(group) {
  const severity = group.severity_rank <= 1 ? "bad" : group.severity_rank === 2 ? "warn" : "ok";
  return `<tr><td><span class="${severity}">${escapeHtml(group.severity_label)}</span></td><td>${escapeHtml(group.title)}<div class="small muted">${escapeHtml(group.decision_label || "待处理")}</div></td><td>${escapeHtml(group.teacher)}</td><td>${escapeHtml((group.fields || []).join("、"))}</td><td>${escapeHtml(group.expected ?? "—")}</td><td>${escapeHtml(group.actual ?? "—")}</td><td>${escapeHtml(group.difference ?? "—")}</td><td><button class="quiet" aria-label="查看 ${escapeHtml(group.teacher)}：${escapeHtml(group.title)} 的明细" onclick="evidence('${group.id}')">查看明细</button></td></tr>`;
}

function updateFilters() {
  filters.teacher = $("#filter-teacher")?.value || "";
  const scroll = window.scrollY;
  renderTab();
  window.scrollTo(0, scroll);
}

async function evidence(id) {
  try {
    const result = await api(`/api/runs/${current.id}/evidence?issue=${id}`);
    const group = result.issue || {};
    detailBasisToken = group.fingerprint || null;
    const decision = group.decision;
    const sections = result.sections || [];
    const courses = result.evidence || [];
    const acCalculation = result.ac_calculation;
    const resolutionCourses = result.resolution_courses || [];
    evidenceResolutionCourses = resolutionCourses;
    evidenceIssueId = id;
    const activeAction = decision?.action || "DEFERRED";
    $("#issue-detail").innerHTML = `<article class="detail-panel"><div class="section-head"><div><p class="eyebrow">问题详情</p><h3>${escapeHtml(group.title)}</h3><p class="muted">${escapeHtml(group.teacher)}</p></div><button class="quiet" aria-label="关闭问题详情" onclick="$('#issue-detail').innerHTML=''">关闭</button></div>${groupFacts(group)}${decision ? `<div class="decision-saved"><strong>${escapeHtml(group.decision_label || "已记录处理意见")}</strong><p>状态：${escapeHtml(decisionStatusLabel(decision.status))} · ${escapeHtml(decision.person)} · ${escapeHtml(decision.reason)}</p></div>` : ""}<section class="action-first" aria-labelledby="decision-heading"><h4 id="decision-heading">记录处理意见</h4><p class="muted small">默认是“暂时保留”，不会把问题认定为已确认。</p><div class="decision-form"><label for="decision">处理方式<select id="decision"><option value="DEFERRED" ${activeAction === "DEFERRED" ? "selected" : ""}>暂时保留，稍后处理</option><option value="CONFIRMED_ERROR" ${activeAction === "CONFIRMED_ERROR" ? "selected" : ""}>确认工资表需要修改</option><option value="ACCEPTED_EXCEPTION" ${activeAction === "ACCEPTED_EXCEPTION" ? "selected" : ""}>确认属于接受的特殊情况</option></select></label><label for="person">确认人<input id="person" value="${escapeHtml(decision?.person || "")}" placeholder="填写姓名"></label><label class="wide" for="reason">判断说明<textarea id="reason" placeholder="说明判断依据（必填）">${escapeHtml(decision?.reason || "")}</textarea></label></div><div class="action-bar"><span class="muted small">保存不会修改原 Excel，也不会直接让整份工资通过。</span><span><button class="secondary" onclick="evidence('${id}')">重新查看证据</button><button onclick="decide('${id}')">保存处理意见</button></span></div></section>${affectedFacts(result.field_records || [])}${sections.map(evidenceSection).join("")}${acCalculationEvidence(acCalculation)}${courseEvidence(courses, result.note, acCalculation)}${boundaryNote(result.boundary)}</article>`;
    $("#issue-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showMessage(error.message); }
}

function resolutionControls(issueId, courses) {
  if (!courses.length) return "";
  const options = courses.map(course => `<option value="${escapeHtml(course.id)}">${escapeHtml(course.label || course.id)}</option>`).join("");
  return `<section class="action-first"><h4>结构化处理班课差异</h4><p class="muted small">选择具体课程后保存。上游事实修正保留原始排课；特殊核算口径只作用于本次工资核算。</p><div class="decision-form"><label>课程<select id="resolution-course">${options}</select></label><label>处理方式<select id="resolution-kind"><option value="SOURCE_DATA_CORRECTION">修正上游事实</option><option value="APPROVED_PAYROLL_OVERRIDE">特殊核算口径</option></select></label><label>确认人<input id="resolution-person" placeholder="填写姓名"></label><label class="wide">处理内容<textarea id="resolution-values" placeholder='上游事实修正：{"field":"grade","corrected_value":"高二","reason_code":"GRADE_ROLLOVER_NOT_UPDATED","reason":"8月升年级未同步"}&#10;特殊口径：{"approved_treatment":"按批准口径","approved_contribution":1.2,"reason":"已批准"}'></textarea></label></div><div class="action-bar"><button onclick="createResolution('${issueId}')">保存并重新核对</button></div></section>`;
}

async function createResolution(issueId) {
  try {
    const values = JSON.parse($("#resolution-values").value || "{}");
    current = await api(`/api/runs/${current.id}/resolutions`, { method: "POST", body: JSON.stringify({ issue_id: issueId, kind: $("#resolution-kind").value, course_record_id: $("#resolution-course").value, values, confirmed_by: $("#resolution-person").value, fingerprint: detailBasisToken }) });
    renderRun(); showMessage("已保存结构化处理并重新核对。", "success");
  } catch (error) { showMessage(error.message); }
}

function groupFacts(group) {
  return `<div class="comparison"><div><span>系统值</span><strong>${escapeHtml(group.expected ?? "无法计算")}</strong></div><div><span>工资表值</span><strong>${escapeHtml(group.actual ?? "未读取")}</strong></div><div><span>差异</span><strong>${escapeHtml(group.difference ?? "—")}</strong></div></div><p>${escapeHtml(group.reason || "请结合以下字段事实和来源证据判断。")}</p>${resolutionControls(evidenceIssueId, evidenceResolutionCourses)}`;
}

function decisionStatusLabel(status) {
  return { ACTIVE: "当前有效", NEEDS_RECONFIRMATION: "依据已变化，需重新确认" }[status] || "已记录";
}

function affectedFacts(records = []) {
  if (!records.length) return "";
  return `<h4>受影响字段事实</h4><div class="table-wrap"><table class="table"><thead><tr><th>字段</th><th>系统值</th><th>工资表值</th><th>差异</th><th>结论</th></tr></thead><tbody>${records.map((item) => `<tr><td>${escapeHtml(item.field_label || item.field || "—")}</td><td>${escapeHtml(item.expected ?? "—")}</td><td>${escapeHtml(item.actual ?? "—")}</td><td>${escapeHtml(item.difference ?? "—")}</td><td>${escapeHtml(item.status_label || item.reason || "—")}</td></tr>`).join("")}</tbody></table></div>`;
}

function evidenceSection(section) {
  return `<section class="evidence-section"><h4>${escapeHtml(section.title)}</h4>${section.items?.length ? `<div class="evidence-list">${section.items.map(evidenceCard).join("")}</div>` : '<p class="muted">暂无来源记录。</p>'}</section>`;
}

function acCalculationEvidence(calculation) {
  if (!calculation) return "";
  const lessons = calculation.records || [];
  return `<section class="evidence-section"><h4>系统排课计算</h4><p><strong>系统 AC 合计 = Σ 每条折算值 = ${escapeHtml(calculation.system_total)}</strong></p><p class="small muted">以下仅列入满足既有班课折算规则的课程；批注与工资表值不参与该合计。</p>${lessons.length ? `<details open><summary>查看 ${lessons.length} 条参与计算的课程</summary><div class="table-wrap"><table class="table"><thead><tr><th>日期</th><th>班级</th><th>课程</th><th>班型</th><th>年级</th><th>原始时长/课次</th><th>折算规则</th><th>本条折算值</th><th>来源</th></tr></thead><tbody>${lessons.map((row) => `<tr><td>${escapeHtml(row["日期"])}</td><td>${escapeHtml(row["班级"])}</td><td>${escapeHtml(row["课程"])}</td><td>${escapeHtml(row["班型"])}</td><td>${escapeHtml(row["年级"])}</td><td>${escapeHtml(row["原始时长/课次"])}</td><td>${escapeHtml(row["折算规则"])}</td><td><strong>${escapeHtml(row["本条折算值"])}</strong></td><td>${escapeHtml(row["来源文件"])}<br><span class="small muted">${escapeHtml(row["来源工作表"])} · ${escapeHtml(row["来源位置"])}</span></td></tr>`).join("")}</tbody></table></div></details>` : '<p class="muted">没有可按现有规则计算的班课记录。</p>'}</section>`;
}

function courseEvidence(courses, note, acCalculation) {
  if (acCalculation) return "";
  const lessons = courses.filter((item) => (item["来源"] || item.source) !== "工资表");
  if (!lessons.length) return `<p class="muted">${escapeHtml(note || "当前没有可展开的逐课来源。")}</p>`;
  const provenance = lessons[0];
  return `<section class="evidence-section"><h4>AC 课程来源（${lessons.length} 条）</h4><p class="small muted">来源概览：${escapeHtml(provenance["来源文件"] || provenance.source_file || "原始排课")} · ${escapeHtml(provenance["来源工作表"] || provenance.sheet || "工作表")}</p><details><summary>展开 ${lessons.length} 条课程明细</summary><div class="evidence-list">${lessons.map(evidenceCard).join("")}</div></details></section>`;
}

function boundaryNote(boundary) {
  if (!boundary) return "";
  if (typeof boundary === "string") return `<div class="banner info"><strong>核对边界</strong><span>${escapeHtml(boundary)}</span></div>`;
  return `<div class="banner info"><strong>核对边界</strong><span>课程来源、工资表目标和独立权威依据分别展示；工资表自身不作为独立依据。</span></div>`;
}

function evidenceCard(item) {
  return `<div class="evidence-card">${Object.entries(item).map(([key, value]) => `<div><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>`;
}

function managementPage() {
  const values = Object.fromEntries((current.management || []).map((item) => [item.field, item.value]));
  const person = current.management?.[0]?.confirmed_by || "";
  const fields = ["平均课时", "续推人次", "退费人次", "管理考核说明"];
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">人工确认</p><h2>管理岗位考核</h2><p class="muted">系统只提供可靠事实；当前没有可靠自动数据的项目由负责人填写最终确认值。</p></div></div><div class="table-wrap"><table class="table management"><thead><tr><th>项目</th><th>系统参考值</th><th>人工最终确认值</th></tr></thead><tbody>${fields.map((field) => `<tr><td>${field}</td><td class="muted">暂无可靠自动数据</td><td><input id="m-${field}" value="${escapeHtml(values[field] || "")}" placeholder="填写确认值或说明"></td></tr>`).join("")}</tbody></table></div><label class="person-field">确认人<input id="m-person" value="${escapeHtml(person)}" placeholder="填写姓名"></label><div class="action-bar"><span class="muted small">这里不会自动推荐数值，也不会修改工资表。</span><button onclick="saveManagement()">保存人工确认</button></div></section>`;
}

async function choose(role) {
  try {
    const picked = await api("/api/pick", { method: "POST", body: "{}" });
    if (!picked.path) return;
    const inspected = await api("/api/inspect", { method: "POST", body: JSON.stringify(picked) });
    if (role === "schedule") {
      // Known layout imports straight away; anything else opens field recognition
      // instead of refusing the file.
      let preview = null;
      try { preview = await api(`/api/import-mapping?path=${encodeURIComponent(picked.path)}&role=schedule&period=${encodeURIComponent(current.period)}`); }
      catch (error) { preview = null; }
      if (preview && preview.status !== "KNOWN_LAYOUT" && preview.status !== "MAPPED") {
        return mappingPage(picked.path, role, preview);
      }
      if (preview && preview.status === "MAPPED" && preview.profile_id) {
        showMessage("已按之前确认过的格式识别字段。", "success");
      }
    }
    if (!inspected.recognized && role !== "schedule") throw new Error(`无法识别这张表。检测到的工作表：${inspected.sheets.join("、") || "无"}。${inspected.missing.join("；")}`);
    current = await api(`/api/runs/${current.id}/files`, { method: "POST", body: JSON.stringify({ role, path: picked.path }) });
    showMessage(`已将文件识别为“${roleCopy[role][0]}”。`, "success");
    renderRun();
  } catch (error) { showMessage(error.message); }
}

// 字段识别：业务需要哪些字段由业务模块声明，这里只回答“哪一列对应它”
function mappingPage(path, role, preview) {
  const options = (selected) => [`<option value="">（不使用）</option>`]
    .concat(preview.columns.map((item) => `<option value="${item.column}" ${Number(selected) === item.column ? "selected" : ""}>${escapeHtml(item.header)}</option>`)).join("");
  const pickOf = (item) => {
    if (item.header) return `已识别为 Excel 列：“${escapeHtml(item.header)}”`;
    if (item.candidates.length) return `发现 ${item.candidates.length} 个候选：${item.candidates.map(escapeHtml).join("、")}，请选择`;
    return "未自动确认，请手工选择";
  };
  const rows = preview.fields.map((item) => {
    const mark = item.header ? "✓" : (item.candidates.length ? "⚠" : "✕");
    const preselected = item.column ?? "";
    return `<tr><td>${mark} ${escapeHtml(item.label)}${item.required ? "" : '<span class="muted small">（可选）</span>'}</td><td class="muted small">${pickOf(item)}</td><td><select id="map-${item.field}">${options(preselected)}</select></td></tr>`;
  }).join("");
  shell(`<section class="section-head"><div><p class="eyebrow">字段识别</p><h1>这份表里，哪一列代表什么？</h1><p class="muted">系统不按固定列号读取，只按业务字段读取。确认一次后会记住这个格式，下个月同结构自动复用。</p></div><button class="secondary" onclick="renderRun()">返回核对</button></section><section class="card">${preview.message ? `<p class="small">${escapeHtml(preview.message)}</p>` : ""}<div class="table-wrap"><table class="table"><thead><tr><th>业务字段</th><th>识别情况</th><th>请指定 Excel 列</th></tr></thead><tbody>${rows}</tbody></table></div><p class="muted small">检测到的列：${preview.detected_columns.map(escapeHtml).join("、") || "无"}</p><div class="decision-form"><label>把这次确认的格式存下来<input id="map-profile-name" placeholder="例如 二校英语组排课格式"></label><label>确认人<input id="map-actor" placeholder="填写姓名"></label></div><div class="action-bar"><span class="muted small">已确认的格式下次自动复用；列有变化时会要求重新确认。</span><button onclick="applyMapping('${escapeHtml(path)}','${role}')">按此映射导入</button></div></section>`, false);
}

async function applyMapping(path, role) {
  const mapping = {};
  document.querySelectorAll("select[id^='map-']").forEach((node) => {
    if (node.value) mapping[node.id.replace("map-", "")] = Number(node.value);
  });
  const profileName = $("#map-profile-name")?.value || "";
  const actor = $("#map-actor")?.value || "";
  try {
    current = await api(`/api/runs/${current.id}/files`, { method: "POST", body: JSON.stringify({ role, path, mapping: { mapping, sheet: "", header_row: 0 }, profile_name: profileName, profile_actor: actor }) });
    showMessage(profileName ? "已导入，并记住这个格式。" : "已按你的映射导入。", "success");
    renderRun();
  } catch (error) { showMessage(error.message); }
}

async function refreshRun() {
  try { current = await api(`/api/runs/${current.id}`); showMessage("材料状态已更新。", "success"); renderRun(); }
  catch (error) { showMessage(error.message); }
}

async function recheck() {
  try { current = await api(`/api/runs/${current.id}/check`, { method: "POST", body: "{}" }); tab = (current.issue_groups || []).length ? "issues" : "overview"; renderRun(); showMessage("已重新核对全部材料。", "success"); }
  catch (error) { await refreshAfterError(error); }
}

async function refreshAfterError(error) {
  try { current = await api(`/api/runs/${current.id}`); renderRun(); } catch (_) { /* retain current screen */ }
  showMessage(error.message);
}

async function decide(id) {
  try {
    current = await api(`/api/runs/${current.id}/decisions`, { method: "POST", body: JSON.stringify({ issue_id: id, action: $("#decision").value, person: $("#person").value, reason: $("#reason").value, fingerprint: detailBasisToken }) });
    renderRun(); showMessage("处理意见已保存。请重新核对全部材料，使确认结果生效。", "success");
  } catch (error) { showMessage(error.message); }
}

async function saveManagement() {
  try {
    const values = {};
    ["平均课时", "续推人次", "退费人次", "管理考核说明"].forEach((field) => { values[field] = $(`#m-${field}`).value; });
    current = await api(`/api/runs/${current.id}/management`, { method: "POST", body: JSON.stringify({ values, person: $("#m-person").value }) });
    renderRun(); showMessage("人工确认已保存。", "success");
  } catch (error) { showMessage(error.message); }
}

async function downloadReport() {
  try {
    const response = await fetch(`/api/runs/${current.id}/export.csv`, { headers: { "X-Payroll-Token": token } });
    if (!response.ok) { const payload = await response.json(); throw new Error(payload.error || "报告导出未完成。"); }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `工资核对报告_${current.period}.csv`; anchor.click(); URL.revokeObjectURL(url);
  } catch (error) { showMessage(error.message); }
}

(async () => {
  token = (await (await fetch("/api/bootstrap")).json()).token;
  await home();
})().catch((error) => { $("#app").textContent = `无法启动：${error.message}`; });

async function businessInputsPage() {
  try {
    const inputs = await api("/api/business-inputs");
    const rows = inputs.map((item) => `<tr><td>${escapeHtml(item.period)}</td><td>${escapeHtml(item.teacher_id)}</td><td>${escapeHtml(inputTypeLabel(item.input_type))}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.payload?.item_type || item.payload?.note || "最终业务结果")}</td><td><button class="quiet" onclick="reviewInput('${item.id}')">审核</button>${current && item.status === "APPROVED" && item.period === current.period ? `<button class="quiet" onclick="bindBusinessInput('${item.id}')">绑定当前核对</button>` : ""}</td></tr>`).join("");
    shell(`<section class="section-head"><div><p class="eyebrow">业务填报</p><h1>待审核业务输入</h1><p class="muted">教师提交和上游最终结果都先审核；不会直接改工资或排课。</p></div><button class="secondary" onclick="home()">返回工作台</button></section><section class="card"><h2>导入上游最终结果</h2><div class="decision-form"><label>月份<input id="input-period" type="month"></label><label>类别<select id="input-kind"><option value="RENEWAL_RESULT">续费最终结果</option><option value="REFUND_RESULT">退费最终结果</option></select></label><label>文件路径<input id="input-path" placeholder="选择后的本机文件路径"></label><label>导入人<input id="input-person" placeholder="填写姓名"></label></div><div class="action-bar"><span class="muted small">系统只归档上游最终结果，不猜奖励或责任规则。</span><button onclick="importBusinessResult()">导入待审核</button></div></section><section class="card"><h2>创建教师访问码</h2><div class="decision-form"><label>教师标识<input id="teacher-id" placeholder="例如 教师甲"></label><label>显示名称<input id="teacher-name" placeholder="可选"></label></div><div class="action-bar"><span class="muted small">访问码只显示一次，请通过安全方式单独发送给教师。</span><button onclick="createTeacherAccess()">生成访问码</button></div><p id="teacher-token" class="muted"></p></section><section class="card"><div class="section-head"><div><h2>全部业务输入</h2><p class="muted">批准后可在对应月度核对中绑定；尚未配置续费奖励规则时只显示“资料已就绪”。</p></div><span class="muted">${inputs.length} 条</span></div><div class="table-wrap"><table class="table"><thead><tr><th>月份</th><th>教师</th><th>类别</th><th>状态</th><th>内容</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="6" class="muted">暂无业务输入。</td></tr>'}</tbody></table></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

function inputTypeLabel(value) {
  return { TEACHER_SUBMISSION: "教师填报", RENEWAL_RESULT: "续费最终结果", REFUND_RESULT: "退费最终结果" }[value] || value;
}

async function importBusinessResult() {
  try {
    await api("/api/business-inputs/import", { method: "POST", body: JSON.stringify({ input_type: $("#input-kind").value, period: $("#input-period").value, path: $("#input-path").value, submitted_by: $("#input-person").value }) });
    showMessage("已导入为待审核业务结果。", "success"); await businessInputsPage();
  } catch (error) { showMessage(error.message); }
}

async function createTeacherAccess() {
  try {
    const result = await api("/api/teacher-access", { method: "POST", body: JSON.stringify({ teacher_id: $("#teacher-id").value, display_name: $("#teacher-name").value }) });
    $("#teacher-token").textContent = `教师访问码（仅显示一次）：${result.access_token}`;
  } catch (error) { showMessage(error.message); }
}

async function reviewInput(id) {
  const items = await api("/api/business-inputs");
  const item = items.find(value => value.id === id);
  if (!item) { showMessage("找不到这条业务输入。", "error"); return; }
  const reviewer = window.prompt("审核人：", "");
  if (!reviewer) return;
  if (["SUBMITTED", "REQUEST_MORE_INFO"].includes(item.status)) {
    try { await api(`/api/business-inputs/${id}/review`, { method: "POST", body: JSON.stringify({ action: "START_REVIEW", reviewer, note: "开始审核" }) }); showMessage("已进入审核，可再次打开后给出结论。", "success"); await businessInputsPage(); }
    catch (error) { showMessage(error.message, "error"); }
    return;
  }
  const action = window.prompt("输入 APPROVE、REJECT 或 REQUEST_MORE_INFO：", "APPROVE");
  if (!action) return;
  const note = window.prompt("审核说明（可选）：", "") || "";
  try { await api(`/api/business-inputs/${id}/review`, { method: "POST", body: JSON.stringify({ action, reviewer, note }) }); showMessage("审核结果已保存。", "success"); await businessInputsPage(); }
  catch (error) { showMessage(error.message); }
}

async function bindBusinessInput(id) {
  if (!current) { showMessage("请先打开需要绑定的月度工资核对。 "); return; }
  try { current = await api(`/api/runs/${current.id}/business-inputs`, {method: "POST", body: JSON.stringify({input_id: id})}); showMessage("业务输入已绑定当前核对，请重新核对。", "success"); renderRun(); }
  catch (error) { showMessage(error.message); }
}

async function writebackPage() {
  if (!current) { showMessage("请先打开月度工资核对。 "); return; }
  try {
    const [inputs, candidates] = await Promise.all([api(`/api/business-inputs?period=${encodeURIComponent(current.period)}&status=APPROVED`), api(`/api/comment-candidates?run_id=${encodeURIComponent(current.id)}`)]);
    const refunds = inputs.filter(item => item.input_type === "REFUND_RESULT");
  const rows = candidates.map(item => `<tr><td>${escapeHtml(item.comment_type)}</td><td>${escapeHtml(item.sheet)}!${escapeHtml(item.cell)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.content)}</td><td>${["PROPOSED", "PREVIEWED"].includes(item.status) ? `<button class="quiet" onclick="approveCandidate('${item.id}')">预览并确认</button>` : ""}</td></tr>`).join("");
    const approved = candidates.filter(item => item.status === "APPROVED");
    const source = approved[0]?.source_workbook || "";
    shell(`<section class="section-head"><div><p class="eyebrow">批注回填</p><h1>预览后输出新工资表</h1><p class="muted">原 Excel 永远不覆盖。只有已确认来源与已确认候选才能写回新文件。</p></div><button class="secondary" onclick="openRun('${current.id}')">返回核对</button></section><section class="card"><h2>生成退费批注候选</h2><div class="decision-form"><label>已审核退费结果<select id="refund-input">${refunds.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.teacher_id)} · 第${escapeHtml(item.source_row)}行</option>`).join("") || '<option value="">暂无已审核退费结果</option>'}</select></label><label>目标工资表<select id="comment-role">${Object.keys(current.files || {}).filter(key => ["math", "science", "baseline"].includes(key)).map(key => `<option value="${key}">${escapeHtml(roleCopy[key][0])}</option>`).join("")}</select></label><label>工作表<input id="comment-sheet" placeholder="例如 工资表"></label><label>目标单元格<input id="comment-cell" placeholder="例如 AC23"></label></div><div class="action-bar"><span class="muted small">目标位置由管理员确认；不会猜测该写入哪个工资单元格。</span><button ${refunds.length ? "" : "disabled"} onclick="createRefundCandidate()">生成候选</button></div></section><section class="card"><h2>批注候选</h2><div class="table-wrap"><table class="table"><thead><tr><th>类型</th><th>位置</th><th>状态</th><th>建议内容</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">暂无候选。</td></tr>'}</tbody></table></div></section>${approved.length ? `<section class="card"><h2>确认输出新文件</h2><p class="muted">将写入 ${approved.length} 条已预览确认的批注。原工资表不会修改。</p><div class="decision-form"><label>输出文件路径<input id="write-output" placeholder="例如 /桌面/数学组9月工资_系统回填.xlsx"></label><label>回填确认人<input id="write-person" placeholder="填写姓名"></label></div><div class="action-bar"><span class="muted small">本次只处理同一原工资表的已确认候选。</span><button onclick="writebackApproved('${escapeHtml(source)}', '${approved.map(item => item.id).join(',')}')">输出新 Excel</button></div></section>` : ""}`, false);
  } catch (error) { showMessage(error.message); }
}

async function createRefundCandidate() {
  try { await api(`/api/runs/${current.id}/comment-candidates/refund`, {method: "POST", body: JSON.stringify({input_id: $("#refund-input").value, target_role: $("#comment-role").value, sheet: $("#comment-sheet").value, cell: $("#comment-cell").value})}); showMessage("已生成批注候选，请预览后确认。", "success"); await writebackPage(); }
  catch (error) { showMessage(error.message); }
}

async function approveCandidate(id) {
  const strategy = window.prompt("已有批注处理方式：APPEND、KEEP_EXISTING 或 REPLACE_CONFIRMED", "APPEND"); if (!strategy) return;
  try { const preview = await api(`/api/runs/${current.id}/comment-candidates/preview`, {method: "POST", body: JSON.stringify({candidate_id: id, strategy})}); if (!window.confirm(`请确认最终批注：\n\n原批注：${preview.before_comment || "无"}\n\n新批注：${preview.after_comment}`)) { await writebackPage(); return; } const reviewer = window.prompt("确认人：", ""); if (!reviewer) return; await api(`/api/runs/${current.id}/comment-candidates/approve`, {method: "POST", body: JSON.stringify({candidate_id: id, reviewer, preview_token: preview.preview_token})}); showMessage("批注已确认，可以输出新工资表。", "success"); await writebackPage(); }
  catch (error) { showMessage(error.message); }
}

async function writebackApproved(source, ids) {
  const output = $("#write-output").value;
  const reviewer = $("#write-person").value;
  try { const result = await api(`/api/runs/${current.id}/writeback`, {method: "POST", body: JSON.stringify({source_workbook: source, candidate_ids: ids.split(","), output_path: output, reviewer})}); showMessage(`已输出新文件：${result.output_path}`, "success"); await writebackPage(); }
  catch (error) { showMessage(error.message); }
}

// ---------------------------------------------------------------------------
// 教师个人工资表：标准化 -> 合并 -> 标准工资表（与岗位考核完全分开）
let sheetPaths = [];

async function payrollSheetsPage() {
  try {
    const batches = await api("/api/payroll-submissions");
    const rows = batches.map((batch) => `<tr><td>${escapeHtml(batch.period)}</td><td>${escapeHtml(batch.status)}</td><td>${(batch.files || []).length}</td><td>${escapeHtml(batch.output_workbook || "—")}</td><td><button class="quiet" onclick="previewBatch('${batch.id}')">看合并预览</button></td></tr>`).join("");
    shell(`<section class="section-head"><div><p class="eyebrow">教师个人工资表</p><h1>多表合并成标准工资表</h1><p class="muted">单个老师的表、多个老师的表、已汇总的总表，都先转成标准内部数据，再生成统一工资表。系统不复制粘贴单元格。</p></div></section><section class="card"><h2>待上传</h2><p class="muted small">可反复点击添加；格式有歧义时系统会停下来让你确认，确认过的格式下次自动复用。</p><div class="action-bar"><button class="secondary" onclick="addSheetPath()">添加工资表</button><span class="muted small">已添加 ${sheetPaths.length} 份</span><button ${sheetPaths.length ? "" : "disabled"} onclick="importSheets()">导入并合并</button></div></section><section class="card"><h2>批次</h2><div class="table-wrap"><table class="table"><thead><tr><th>月份</th><th>状态</th><th>文件数</th><th>标准工资表</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">暂无批次。</td></tr>'}</tbody></table></div></section>`, true);
  } catch (error) { showMessage(error.message); }
}

async function addSheetPath() {
  try { const picked = await api("/api/pick"); if (picked.path) { sheetPaths.push(picked.path); await payrollSheetsPage(); } }
  catch (error) { showMessage(error.message); }
}

async function importSheets() {
  const period = window.prompt("这些工资表属于哪个月份？", new Date().toISOString().slice(0, 7));
  if (!period) return;
  try { const batch = await api("/api/payroll-submissions", {method: "POST", body: JSON.stringify({paths: sheetPaths, period, submitted_by: "管理员"})}); sheetPaths = []; showMessage(batch.pending_layouts.length ? "有工资表格式需要你先确认列含义。" : "已导入，请看合并预览。", batch.pending_layouts.length ? "error" : "success"); await previewBatch(batch.id); }
  catch (error) { showMessage(error.message); }
}

async function previewBatch(id) {
  try {
    const preview = await api(`/api/payroll-submissions/${id}/merge-preview`);
    const findings = preview.findings.map((item) => `<tr><td>${escapeHtml(item.code)}</td><td>${escapeHtml(item.severity)}</td><td>${escapeHtml(item.teacher_id)}</td><td>${escapeHtml(item.message)}</td></tr>`).join("");
    const teachers = Object.keys(preview.merged).map((name) => `<tr><td>${escapeHtml(name)}</td><td>${preview.merged[name].one_to_one ?? "—"}</td><td>${preview.merged[name].class_value ?? "—"}</td></tr>`).join("");
    shell(`<section class="section-head"><div><p class="eyebrow">合并预览</p><h1>确认后再进入核对</h1><p class="muted">${escapeHtml(preview.period)} · ${Object.keys(preview.merged).length} 位教师</p></div><button class="secondary" onclick="payrollSheetsPage()">返回</button></section><section class="card"><h2>检查结果</h2><div class="table-wrap"><table class="table"><thead><tr><th>类型</th><th>级别</th><th>教师</th><th>说明</th></tr></thead><tbody>${findings || '<tr><td colspan="4" class="muted">没有发现问题。</td></tr>'}</tbody></table></div></section><section class="card"><h2>标准工资总表</h2><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>一对一折算</th><th>班课折算</th></tr></thead><tbody>${teachers}</tbody></table></div><div class="decision-form"><label>输出文件路径<input id="merge-output" placeholder="例如 /桌面/9月标准工资表.xlsx"></label><label>确认人<input id="merge-person" placeholder="填写姓名"></label></div><div class="action-bar"><span class="muted small">输出由内部模型生成，不会覆盖已有文件。</span><button ${preview.has_errors ? "disabled" : ""} onclick="confirmMerge('${id}')">生成标准工资表</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

async function confirmMerge(id) {
  try { const result = await api(`/api/payroll-submissions/${id}/merge`, {method: "POST", body: JSON.stringify({output_path: $("#merge-output").value, reviewer: $("#merge-person").value})}); showMessage(`已生成标准工资表：${result.output_workbook}`, "success"); await payrollSheetsPage(); }
  catch (error) { showMessage(error.message); }
}

// ---------------------------------------------------------------------------
// 岗位考核：只有组长上传，客观项按已确认口径算，主观项必须人工确认
async function assessmentsPage() {
  try {
    const period = new Date().toISOString().slice(0, 7);
    const [records, findings, results] = await Promise.all([api(`/api/assessments?period=${period}`), api(`/api/assessment-findings?period=${period}`), api(`/api/assessment-results?period=${period}`)]);
    const recordRows = records.map((item) => `<tr><td>${escapeHtml(item.teacher_id)}</td><td>${escapeHtml(item.status)}</td><td>${item.objective_score}</td><td>${(item.pending_subjective || []).length}</td><td><button class="quiet" onclick="confirmAssessment('${item.id}')">确认</button></td></tr>`).join("");
    const findingRows = findings.map((item) => `<tr><td>${escapeHtml(item.code)}</td><td>${escapeHtml(item.teacher_id)}</td><td>${escapeHtml(item.message)}</td></tr>`).join("");
    const resultRows = results.map((item) => `<tr><td>${escapeHtml(item.teacher_id)}</td><td>${item.final_score}</td><td>${escapeHtml(item.amount_status === "RULE_NOT_CONFIGURED" ? "金额规则未配置" : String(item.final_amount))}</td><td>${escapeHtml(item.reviewer)}</td></tr>`).join("");
    shell(`<section class="section-head"><div><p class="eyebrow">岗位考核（组长）</p><h1>${escapeHtml(period)} 岗位考核表</h1><p class="muted">考核表只由组长上传。客观项按已确认口径自动计算；主观项必须人工确认，系统不替管理者评分。金额规则未配置时不会猜金额。</p></div><button onclick="importAssessment()">上传考核表</button></section><section class="card"><h2>自动检查</h2><div class="table-wrap"><table class="table"><thead><tr><th>类型</th><th>组长</th><th>说明</th></tr></thead><tbody>${findingRows || '<tr><td colspan="3" class="muted">没有发现问题。</td></tr>'}</tbody></table></div></section><section class="card"><h2>已上传</h2><div class="table-wrap"><table class="table"><thead><tr><th>组长</th><th>状态</th><th>客观得分</th><th>待人工确认主观项</th><th></th></tr></thead><tbody>${recordRows || '<tr><td colspan="5" class="muted">暂无考核表。</td></tr>'}</tbody></table></div></section><section class="card"><h2>MANAGEMENT_ASSESSMENT_RESULT</h2><div class="table-wrap"><table class="table"><thead><tr><th>组长</th><th>最终得分</th><th>最终金额</th><th>确认人</th></tr></thead><tbody>${resultRows || '<tr><td colspan="4" class="muted">暂无正式结果。</td></tr>'}</tbody></table></div></section>`, true);
  } catch (error) { showMessage(error.message); }
}

async function importAssessment() {
  try {
    const picked = await api("/api/pick");
    if (!picked.path) return;
    const period = window.prompt("考核表属于哪个月份？", new Date().toISOString().slice(0, 7));
    if (!period) return;
    const leader = window.prompt("这是哪位组长的考核表？", "");
    if (!leader) return;
    await api("/api/assessments", {method: "POST", body: JSON.stringify({path: picked.path, period, leader_id: leader, submitted_by: leader})});
    showMessage("已上传并完成自动检查。", "success"); await assessmentsPage();
  } catch (error) { showMessage(error.message); }
}

async function confirmAssessment(id) {
  const reviewer = window.prompt("确认人：", "");
  if (!reviewer) return;
  try {
    const record = (await api(`/api/assessments?period=`)).find((item) => item.id === id);
    const answers = {};
    for (const key of (record?.pending_subjective || [])) {
      const value = window.prompt(`主观项 ${key} 的评分（必须由你填写，系统不会代替评分）：`, "");
      if (value === null) return;
      answers[key] = Number(value);
    }
    const result = await api(`/api/assessments/${id}/confirm`, {method: "POST", body: JSON.stringify({reviewer, subjective_confirmations: answers})});
    showMessage(result.status === "FINAL" ? `最终得分 ${result.final_score}；金额状态 ${result.amount_status}` : "仍有主观项待人工确认。", result.status === "FINAL" ? "success" : "error");
    await assessmentsPage();
  } catch (error) { showMessage(error.message); }
}

// ---------------------------------------------------------------------------
// 历史班型规则：仅用于解释旧 Run；新 Run 统一由“核心规则面板”绑定规则包。
async function classTypeRulesPage(runId = "") {
  try {
    const versions = await api("/api/class-type-rules");
    const summarize = (rules) => Object.entries(rules?.special_class_coefficients || {}).map(([name, table]) => `${name}（${Object.entries(table || {}).map(([count, value]) => `${count}人=${value}`).join("、")}）`).join("；") || "—";
    const rows = versions.map((item) => `<tr><td>${escapeHtml(item.id)}</td><td>${escapeHtml(item.effective_from)} ～ ${escapeHtml(item.effective_to)}</td><td>${escapeHtml(item.status || "ACTIVE")}</td><td>${escapeHtml(summarize(item.rules))}</td><td>${escapeHtml(item.source || "")}</td></tr>`).join("");
    shell(`<div class="section-head"><div><p class="eyebrow">历史兼容</p><h1>历史班型规则</h1><p class="muted">这里只读展示旧 Run 的规则快照。新核算请进入“核心规则面板”，它是唯一可编辑、唯一用于新 Run 的规则入口。</p></div><button class="secondary" onclick="authorityDashboard('${runId}')">返回基础资料</button></div><section class="card"><h2>历史版本</h2><div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>状态</th><th>特殊班型（班型 × 实到人数）</th><th>来源</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">暂无历史版本。</td></tr>'}</tbody></table></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

// ---------------------------------------------------------------------------
// 生成模式：同一套 Core 结果直接渲染成标准工资表（不复制任何提交表）
async function generatePayroll() {
  const output = window.prompt("标准工资表输出路径（不会覆盖已有文件）：", "");
  if (!output) return;
  try {
    const result = await api(`/api/runs/${current.id}/generate`, { method: "POST", body: JSON.stringify({ output_path: output }) });
    const blockers = [...new Set(result.blockers || [])];
    showMessage(result.status === "FINAL" ? `已生成标准工资表：${result.path}` : `已生成草稿，仍有待确认项：${blockers.join("、")}`, result.status === "FINAL" ? "success" : "error");
    await openRun(current.id);
  } catch (error) { showMessage(error.message); }
}
