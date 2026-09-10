let token = null;
let current = null;
let homeRuns = [];
let tab = "materials";
let filters = { field: "all", state: "all", decision: "all", teacher: "" };
let detailBasisToken = null;

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
  $("#app").innerHTML = `<div class="shell"><header class="top"><div><div class="brand">工资核算助手</div><div class="muted small">文件只在本机读取，不修改原工资表</div></div><div><button class="quiet" onclick="businessInputsPage()">业务填报</button>${current ? '<button class="quiet" onclick="writebackPage()">批注回填</button>' : ""}${historyButton ? '<button class="quiet" onclick="home()">核算历史</button>' : ""}<a class="quiet" href="/teacher">教师填报</a></div></header>${content}</div>`;
}

async function home() {
  try {
    homeRuns = await api("/api/runs");
    current = null;
    const today = new Date();
    const defaultPeriod = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
    shell(`<section class="hero card"><div><p class="eyebrow">开始核算</p><h1>新建工资核算</h1><p class="muted">选择月份后，导入排课数据和本次提交表；如有基准最终工资表，系统以它作为工资结果依据。</p></div><div class="create-box"><label for="period">核算月份</label><input id="period" type="month" value="${defaultPeriod}" onchange="duplicateHint()"><p id="duplicate-hint" class="small muted"></p><button onclick="createRun()">创建并导入材料</button><button class="secondary full" onclick="authorityDashboard()">基础资料与规则</button></div></section><section class="card"><div class="section-head"><div><p class="eyebrow">历史记录</p><h2>最近核算</h2></div><span class="muted">${homeRuns.length} 条</span></div>${historyList()}</section>`, false);
    duplicateHint();
  } catch (error) { showMessage(error.message); }
}

async function authorityDashboard(runId = null, focus = "") {
  try {
    const catalog = await api("/api/authorities");
    const section = (title, versions, kind, click) => `<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>${title}</h2><p class="muted">版本会保留来源、生效期与被哪些核算记录使用；修正时请创建新版本，不要删除旧版本。</p></div><button class="secondary" onclick="${click}">查看与修正</button></div>${versions.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>状态</th><th>来源</th><th>已用于</th></tr></thead><tbody>${versions.map(v => `<tr><td>${escapeHtml(v.source_version || v.id)}</td><td>${escapeHtml(v.effective_from)} ～ ${escapeHtml(v.effective_to)}</td><td>${escapeHtml(v.status || "ACTIVE")}</td><td>${escapeHtml(v.source)}</td><td>${v.used_by_runs?.length || 0} 个 Run</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">尚未保存版本。</p>'}</section>`;
    const rebind = runId ? `<section class="card"><h2>让当前核算改用修正版</h2><p class="muted">这是明确的人工操作。切换后会要求重新全盘核对，相关人工意见会变为“需重新确认”。</p>${authorityRebindControl("rating", catalog.ratings, runId)}${authorityRebindControl("policy", catalog.policies, runId)}</section>` : "";
    const rules = catalog.rules.map(r => `<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.effective_from)} ～ ${escapeHtml(r.effective_to)}</td><td>${escapeHtml(r.source_version)}</td><td>${escapeHtml(r.source)}</td></tr>`).join("");
    shell(`<div class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>核对依据</h1><p class="muted">修正基础资料会新建版本；历史版本和已使用记录都不会被覆盖。</p></div><button class="secondary" onclick="${runId ? `openRun('${runId}')` : "home()"}">返回</button></div>${rebind}${section("教师星级", catalog.ratings, "rating", `ratingDashboard('${runId || ""}')`)}${section("教师工资政策", catalog.policies, "policy", `policyDashboard('${runId || ""}')`)}<section class="card"><div class="section-head"><div><p class="eyebrow">工资规则</p><h2>现行档位金额规则</h2><p class="muted">本版只读展示当前代码化的规则来源，不在这里修改业务规则。</p></div></div><div class="table-wrap"><table class="table"><thead><tr><th>规则</th><th>生效期</th><th>版本</th><th>来源</th></tr></thead><tbody>${rules}</tbody></table></div></section>`, false);
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
    const rows = versions.flatMap((version) => version.profiles.map((profile) => `<tr><td>${escapeHtml(profile.teacher)}</td><td>${escapeHtml(profile.role)}</td><td>${profile.rating_override || profile.rating || "待确认"} 星</td><td>${profile.obligation_hours_deduction_enabled ? `${profile.obligation_hours} 小时，扣除` : "不扣除"}</td><td>${escapeHtml(profile.special_approval || "无")}</td><td>${escapeHtml(version.effective_from)} ～ ${escapeHtml(version.effective_to)}</td><td>${escapeHtml(version.status || "ACTIVE")}</td><td><button class="quiet" onclick="policyDashboard('${returnRunId}', '${version.id}')">创建修正版</button></td></tr>`));
    const list = correction ? correction.profiles.map(x => `${x.teacher}，${x.role}，${x.rating || ""}，${x.rating_override || ""}，${x.obligation_hours || 0}，${x.obligation_hours_deduction_enabled ? "是" : "否"}，${x.special_approval || ""}`).join("\n") : "";
    shell(`<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h1>教师工资政策档案</h1><p class="muted">身份、星级和义务课时待遇分别保存。相同身份可以有不同的有效政策。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>身份</th><th>星级</th><th>义务课时</th><th>特殊审批</th><th>生效期</th><th>状态</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="8" class="muted">尚未保存工资政策档案。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建政策修正版" : "保存政策版本"}</h2><p class="muted">每行填写：教师，身份，基础星级，特批星级，义务小时，是否扣除，特殊审批。特批星级留空即可。修正版不会覆盖旧版本。</p><input id="policy-supersedes" type="hidden" value="${escapeHtml(correction?.id || "")}"><div class="decision-form"><label>生效开始<input id="policy-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="policy-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label class="wide">数据来源<input id="policy-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：年度工资政策确认"></label><label class="wide">政策档案<textarea id="policy-list" placeholder="教师甲，TRMT，4，4，30，是，保留四星待遇">${escapeHtml(list)}</textarea></label></div><div class="action-bar"><span class="muted small">保存不会修改工资表，也不会自动改变历史 Run。</span><button onclick="savePolicies('${returnRunId}')">保存政策版本</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

async function savePolicies(returnRunId = "") {
  try {
    const profiles = $("#policy-list").value.split(/\n+/).filter(Boolean).map((line) => { const values = line.split(/[，,]/).map((item) => item.trim()); const [teacher, role, rating, fourth, fifth, sixth, seventh] = values; const modern = values.length >= 7; return { teacher, role, rating: Number(rating) || null, rating_override: modern ? (Number(fourth) || null) : null, obligation_hours: Number(modern ? fifth : fourth) || 0, obligation_hours_deduction_enabled: ["是", "true", "1"].includes(String(modern ? sixth : fifth).toLowerCase()), special_approval: (modern ? seventh : sixth) || "" }; });
    await api("/api/policies", { method: "POST", body: JSON.stringify({ effective_from: $("#policy-from").value, effective_to: $("#policy-to").value, source: $("#policy-source").value, profiles, supersedes_version_id: $("#policy-supersedes").value || null }) });
    showMessage("工资政策版本已保存。若要用于当前核算，请在“当前核对依据”中主动切换。", "success"); await policyDashboard(returnRunId);
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
    current = await api("/api/runs", { method: "POST", body: JSON.stringify({ period: $("#period").value }) });
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
  return `<details class="authority-summary"><summary>当前核对依据</summary><div class="facts">${fact("schedule", "排课权威源")}${fact("rating", "星级权威版本")}${fact("policy", "教师政策版本")}${fact("rules", "工资规则版本")}</div><div class="action-bar"><span class="muted small">发现基础资料录入错误时，请创建修正版；旧版本与历史 Run 会继续保留。</span><button class="secondary" onclick="authorityDashboard('${current.id}')">查看、修正或改用版本</button></div></details>`;
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
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 1 步</p><h2>准备核算材料</h2><p class="muted">排课数据和提交表齐全即可开始。导入基准最终工资表后，系统会用它核验本次提交教师。</p></div><strong class="readiness">${current.health.readiness}%</strong></div><div class="material-grid">${current.materials.map(materialCard).join("")}</div>${warnings.length ? `<div class="warning-list"><strong>材料提示</strong>${warnings.map((warning) => `<p>⚠ ${escapeHtml(warning)}</p>`).join("")}</div>` : ""}<div class="action-bar"><div>${current.health.missing.length ? `<strong>还缺：</strong>${current.health.missing.map(escapeHtml).join("、")}` : "必需材料已准备，可以开始核对。"}</div><div><button class="secondary" onclick="refreshRun()">重新检查材料</button><button ${current.health.ready ? "" : "disabled"} onclick="recheck()">开始核对</button></div></div></section>`;
}

function materialCard(material) {
  const copy = roleCopy[material.role];
  const file = material.file;
  const stateClass = material.state === "失效" ? "bad" : file ? "ok" : material.required ? "warn" : "muted";
  const stateText = material.state === "失效" ? "● 已变化，需重新选择" : file ? "✓ 已识别" : material.required ? "○ 必需材料" : "可稍后补充";
  const risk = file ? [file.missing_cache ? `${file.missing_cache} 个公式结果不可读取` : "", file.external_references ? `${file.external_references} 处依赖其他文件` : ""].filter(Boolean) : [];
  return `<article class="material-card ${material.state === "失效" ? "stale" : ""}"><div class="material-top"><strong>${escapeHtml(copy[0])}</strong><span class="${stateClass}">${stateText}</span></div><p class="small muted">${escapeHtml(copy[2])}</p>${file ? `<div class="file-name">${escapeHtml(file.name)}</div><div class="facts"><span>${file.records} 条记录</span><span>${file.teachers} 名教师</span></div>${risk.length ? `<p class="small warn">⚠ ${risk.join("；")}</p>` : ""}<details><summary>查看文件信息</summary><p class="small muted">工作表：${file.sheets.map(escapeHtml).join("、")}<br>文件标识：${file.sha256.slice(0, 10)}</p></details>` : '<div class="empty compact">尚未选择文件</div>'}<button class="secondary full" onclick="choose('${material.role}')">${escapeHtml(copy[1])}</button></article>`;
}

function overviewPage() {
  const summary = current.summary || {};
  const headline = summary.automatic_pass ? "排课项目核对完成" : "排课项目仍有问题";
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">核对结果</p><h2>${headline}</h2><p class="muted">整份工资仍包含需要上游数据或人工确认的项目。</p></div><button class="secondary" onclick="downloadReport()">导出核对报告</button></div><div class="metric-grid"><div class="metric"><span>排课项目完成度</span><strong>${summary.automatic_coverage ?? 0}%</strong><small>${summary.automatic_completed ?? 0} / ${summary.automatic_required ?? 0} 项</small></div><div class="metric"><span>未说明的差异</span><strong>${summary.unexplained ?? 0}</strong><small>必须处理</small></div><div class="metric"><span>需要人工确认</span><strong>${summary.manual_review ?? 0}</strong><small>不能自动判断</small></div></div><h3>每个项目实际检查到哪一步</h3><div class="table-wrap"><table class="table scope"><thead><tr><th>项目</th><th>读取工资表</th><th>可靠原始依据</th><th>重新计算</th><th>与工资表比较</th><th>当前结论</th></tr></thead><tbody>${current.field_status.map(fieldRow).join("")}</tbody></table></div><div class="banner info"><strong>检查范围说明</strong><span>星级、档位和课时费政策会按已有资料核对；AD 仍来自工资表目标自身，尚未形成独立闭环。</span></div><div class="action-bar"><div>${summary.automatic_pass ? "AA、AC 没有待处理项。" : "请先处理异常中心中的问题。"}</div><div><button class="secondary" onclick="setTab('issues')">查看待处理问题</button><button onclick="recheck()">重新核对全部材料</button></div></div></section>`;
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
    const activeAction = decision?.action || "DEFERRED";
    $("#issue-detail").innerHTML = `<article class="detail-panel"><div class="section-head"><div><p class="eyebrow">问题详情</p><h3>${escapeHtml(group.title)}</h3><p class="muted">${escapeHtml(group.teacher)}</p></div><button class="quiet" aria-label="关闭问题详情" onclick="$('#issue-detail').innerHTML=''">关闭</button></div>${groupFacts(group)}${decision ? `<div class="decision-saved"><strong>${escapeHtml(group.decision_label || "已记录处理意见")}</strong><p>状态：${escapeHtml(decisionStatusLabel(decision.status))} · ${escapeHtml(decision.person)} · ${escapeHtml(decision.reason)}</p></div>` : ""}<section class="action-first" aria-labelledby="decision-heading"><h4 id="decision-heading">记录处理意见</h4><p class="muted small">默认是“暂时保留”，不会把问题认定为已确认。</p><div class="decision-form"><label for="decision">处理方式<select id="decision"><option value="DEFERRED" ${activeAction === "DEFERRED" ? "selected" : ""}>暂时保留，稍后处理</option><option value="CONFIRMED_ERROR" ${activeAction === "CONFIRMED_ERROR" ? "selected" : ""}>确认工资表需要修改</option><option value="ACCEPTED_EXCEPTION" ${activeAction === "ACCEPTED_EXCEPTION" ? "selected" : ""}>确认属于接受的特殊情况</option></select></label><label for="person">确认人<input id="person" value="${escapeHtml(decision?.person || "")}" placeholder="填写姓名"></label><label class="wide" for="reason">判断说明<textarea id="reason" placeholder="说明判断依据（必填）">${escapeHtml(decision?.reason || "")}</textarea></label></div><div class="action-bar"><span class="muted small">保存不会修改原 Excel，也不会直接让整份工资通过。</span><span><button class="secondary" onclick="evidence('${id}')">重新查看证据</button><button onclick="decide('${id}')">保存处理意见</button></span></div></section>${affectedFacts(result.field_records || [])}${sections.map(evidenceSection).join("")}${acCalculationEvidence(acCalculation)}${courseEvidence(courses, result.note, acCalculation)}${boundaryNote(result.boundary)}</article>`;
    $("#issue-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showMessage(error.message); }
}

function groupFacts(group) {
  return `<div class="comparison"><div><span>系统值</span><strong>${escapeHtml(group.expected ?? "无法计算")}</strong></div><div><span>工资表值</span><strong>${escapeHtml(group.actual ?? "未读取")}</strong></div><div><span>差异</span><strong>${escapeHtml(group.difference ?? "—")}</strong></div></div><p>${escapeHtml(group.reason || "请结合以下字段事实和来源证据判断。")}</p>`;
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
    if (!inspected.recognized) throw new Error(`无法识别这张表。检测到的工作表：${inspected.sheets.join("、") || "无"}。${inspected.missing.join("；")}`);
    current = await api(`/api/runs/${current.id}/files`, { method: "POST", body: JSON.stringify({ role, path: picked.path }) });
    showMessage(`已将文件识别为“${roleCopy[role][0]}”。`, "success");
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
  const reviewer = window.prompt("审核人：", "");
  if (!reviewer) return;
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
    const rows = candidates.map(item => `<tr><td>${escapeHtml(item.comment_type)}</td><td>${escapeHtml(item.sheet)}!${escapeHtml(item.cell)}</td><td>${escapeHtml(item.status)}</td><td>${escapeHtml(item.content)}</td><td>${item.status === "PROPOSED" ? `<button class="quiet" onclick="approveCandidate('${item.id}')">预览并确认</button>` : ""}</td></tr>`).join("");
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
  const reviewer = window.prompt("确认人：", ""); if (!reviewer) return;
  const strategy = window.prompt("已有批注处理方式：APPEND、KEEP_EXISTING 或 REPLACE_CONFIRMED", "APPEND"); if (!strategy) return;
  try { const result = await api(`/api/runs/${current.id}/comment-candidates/approve`, {method: "POST", body: JSON.stringify({candidate_id: id, reviewer, strategy})}); window.alert(`预览完成。\n原批注：${result.before_comment || "无"}\n新批注：${result.after_comment}`); await writebackPage(); }
  catch (error) { showMessage(error.message); }
}

async function writebackApproved(source, ids) {
  const output = $("#write-output").value;
  const reviewer = $("#write-person").value;
  try { const result = await api(`/api/runs/${current.id}/writeback`, {method: "POST", body: JSON.stringify({source_workbook: source, candidate_ids: ids.split(","), output_path: output, reviewer})}); showMessage(`已输出新文件：${result.output_path}`, "success"); await writebackPage(); }
  catch (error) { showMessage(error.message); }
}
