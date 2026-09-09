let token = null;
let current = null;
let homeRuns = [];
let tab = "materials";
let filters = { field: "all", state: "all", decision: "all", teacher: "" };

const roleCopy = {
  schedule: ["原始排课数据", "选择原始排课表", "用于重新计算一对一和班课"],
  math: ["数学组工资表", "选择数学组工资表", "读取数学组填报结果"],
  science: ["理化组工资表", "选择理化组工资表", "读取理化组填报结果"],
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
  $("#app").innerHTML = `<div class="shell"><header class="top"><div><div class="brand">工资核算助手</div><div class="muted small">文件只在本机读取，不修改原工资表</div></div>${historyButton ? '<button class="quiet" onclick="home()">核算历史</button>' : ""}</header>${content}</div>`;
}

async function home() {
  try {
    homeRuns = await api("/api/runs");
    current = null;
    const today = new Date();
    const defaultPeriod = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
    shell(`<section class="hero card"><div><p class="eyebrow">开始核算</p><h1>新建工资核算</h1><p class="muted">选择月份后，按提示依次导入三份必需材料。</p></div><div class="create-box"><label for="period">核算月份</label><input id="period" type="month" value="${defaultPeriod}" onchange="duplicateHint()"><p id="duplicate-hint" class="small muted"></p><button onclick="createRun()">创建并导入材料</button></div></section><section class="card"><div class="section-head"><div><p class="eyebrow">历史记录</p><h2>最近核算</h2></div><span class="muted">${homeRuns.length} 条</span></div>${historyList()}</section>`, false);
    duplicateHint();
  } catch (error) { showMessage(error.message); }
}

function historyList() {
  if (!homeRuns.length) return '<div class="empty">还没有核算记录。创建后，即使关闭程序也可以从这里继续。</div>';
  return `<div class="history-list">${homeRuns.map((run) => {
    const summary = run.summary || {};
    const next = run.status === "STALE" ? "重新选择变化的材料" : run.status === "DRAFT" ? "继续导入材料" : run.status === "FILES_READY" ? "开始核对" : (summary.unexplained || summary.manual_review) ? "处理核对问题" : "查看核对结果";
    return `<article class="history-row"><div><strong>${escapeHtml(run.period)}</strong><div class="small muted">编号 ${escapeHtml(run.id)} · 更新于 ${fmtDate(run.updated_at || run.created_at)}</div></div><div>${statusBadge(run)}<div class="small muted">材料 ${run.health.readiness}% · 待处理 ${(summary.unexplained || 0) + (summary.manual_review || 0)} 项</div></div><button class="secondary" onclick="openRun('${run.id}')">${next}</button></article>`;
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
    tab = current.status === "STALE" || current.status === "DRAFT" || current.status === "FILES_READY" ? "materials" : (current.summary?.unexplained || current.summary?.manual_review) ? "issues" : "overview";
    renderRun();
  } catch (error) { showMessage(error.message); }
}

function runSteps() {
  const checked = ["REVIEW_REQUIRED", "PASS"].includes(current.status);
  return `<div class="steps"><span class="done">1 创建记录</span><span class="${current.health.readiness === 100 ? "done" : ""}">2 准备材料</span><span class="${checked ? "done" : ""}">3 查看结果</span><span class="${current.decisions?.length ? "done" : ""}">4 处理问题</span></div>`;
}

function navigation() {
  const checked = ["REVIEW_REQUIRED", "PASS"].includes(current.status);
  const items = [["materials", "材料准备", true], ["overview", "核对结果", checked], ["issues", `待处理问题${current.issues?.length ? ` (${current.issues.length})` : ""}`, checked], ["management", "管理岗位确认", true]];
  return `<nav class="tabs">${items.map(([id, label, enabled]) => `<button class="${tab === id ? "active" : ""}" ${enabled ? `onclick="setTab('${id}')"` : "disabled"}>${label}</button>`).join("")}</nav>`;
}

function renderRun() {
  const stale = current.status === "STALE" ? '<div class="banner error"><strong>原始文件已发生变化</strong><span>请重新选择标记为“已变化”的材料，再重新核对。旧结果不会继续显示为有效。</span></div>' : "";
  const lastError = current.last_error ? `<div class="banner error"><strong>上次核对未完成</strong><span>${escapeHtml(current.last_error)}</span></div>` : "";
  shell(`<div class="run-title"><div><p class="eyebrow">${escapeHtml(current.period)}</p><h1>工资核对</h1><div class="small muted">记录编号 ${escapeHtml(current.id)}</div></div>${statusBadge(current)}</div>${runSteps()}${stale}${lastError}${navigation()}<section id="view"></section>`);
  renderTab();
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
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 1 步</p><h2>准备核算材料</h2><p class="muted">三份必需材料准备好后即可开始核对。</p></div><strong class="readiness">${current.health.readiness}%</strong></div><div class="material-grid">${current.materials.map(materialCard).join("")}</div>${warnings.length ? `<div class="warning-list"><strong>材料提示</strong>${warnings.map((warning) => `<p>⚠ ${escapeHtml(warning)}</p>`).join("")}</div>` : ""}<div class="action-bar"><div>${current.health.missing.length ? `<strong>还缺：</strong>${current.health.missing.map(escapeHtml).join("、")}` : "必需材料已准备，可以开始核对。"}</div><div><button class="secondary" onclick="refreshRun()">重新检查材料</button><button ${current.health.ready ? "" : "disabled"} onclick="recheck()">开始核对</button></div></div></section>`;
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
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">核对结果</p><h2>${headline}</h2><p class="muted">整份工资仍包含需要上游数据或人工确认的项目。</p></div><button class="secondary" onclick="downloadReport()">导出核对报告</button></div><div class="metric-grid"><div class="metric"><span>排课项目完成度</span><strong>${summary.automatic_coverage ?? 0}%</strong><small>${summary.automatic_completed ?? 0} / ${summary.automatic_required ?? 0} 项</small></div><div class="metric"><span>未说明的差异</span><strong>${summary.unexplained ?? 0}</strong><small>必须处理</small></div><div class="metric"><span>需要人工确认</span><strong>${summary.manual_review ?? 0}</strong><small>不能自动判断</small></div></div><h3>每个项目实际检查到哪一步</h3><div class="table-wrap"><table class="table scope"><thead><tr><th>项目</th><th>读取工资表</th><th>可靠原始依据</th><th>重新计算</th><th>与工资表比较</th><th>当前结论</th></tr></thead><tbody>${current.field_status.map(fieldRow).join("")}</tbody></table></div><div class="banner info"><strong>检查范围说明</strong><span>AA、AC 使用原始排课重新计算；AE、AF 只完成公式复算；AV 当前只读取工资表结果。</span></div><div class="action-bar"><div>${summary.automatic_pass ? "AA、AC 没有待处理项。" : "请先处理异常中心中的问题。"}</div><div><button class="secondary" onclick="setTab('issues')">查看待处理问题</button><button onclick="recheck()">重新核对全部材料</button></div></div></section>`;
}

function fieldRow(field) {
  const mark = (value) => value ? '<span class="check">✓</span>' : '<span class="dash">—</span>';
  return `<tr><td><strong>${escapeHtml(field.label)}</strong></td><td>${mark(field.read)}</td><td>${mark(field.authority)}</td><td>${mark(field.computed)}</td><td>${mark(field.compared)}</td><td><span class="field-state">${escapeHtml(field.state)}</span><div class="small muted">${escapeHtml(field.note)}</div></td></tr>`;
}

function issuesPage() {
  const rows = filteredIssues();
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">异常中心</p><h2>待处理问题</h2><p class="muted">严重问题排在前面。已记录的意见仍会保留，便于复查。</p></div><button onclick="recheck()">重新核对全部材料</button></div><div class="filters"><label>项目<select id="filter-field" onchange="updateFilters()"><option value="all">全部项目</option><option value="one_to_one">AA 一对一</option><option value="class_value">AC 班课</option><option value="ae">AE 课时单价</option><option value="af">AF 总课时费</option></select></label><label>问题状态<select id="filter-state" onchange="updateFilters()"><option value="all">全部状态</option><option value="blocking">需要处理</option><option value="confirmed">已确认</option></select></label><label>处理意见<select id="filter-decision" onchange="updateFilters()"><option value="all">全部</option><option value="none">尚未记录</option><option value="recorded">已记录意见</option></select></label><label>教师<input id="filter-teacher" placeholder="输入教师姓名" value="${escapeHtml(filters.teacher)}" oninput="updateFilters()"></label></div><div class="result-count">显示 ${rows.length} / ${current.issues.length} 项</div>${rows.length ? `<div class="table-wrap"><table class="table issues"><thead><tr><th>程度</th><th>项目</th><th>教师</th><th>排课计算值</th><th>工资表值</th><th>差异</th><th>状态</th><th>处理意见</th><th></th></tr></thead><tbody>${rows.map(issueRow).join("")}</tbody></table></div>` : '<div class="empty">当前筛选条件下没有问题。</div>'}<div id="issue-detail"></div></section>`;
}

function filteredIssues() {
  return (current.issues || []).filter((issue) => {
    if (filters.field !== "all" && issue.field !== filters.field) return false;
    if (filters.state === "blocking" && issue.status === "EXPLAINED_DIFFERENCE") return false;
    if (filters.state === "confirmed" && issue.status !== "EXPLAINED_DIFFERENCE") return false;
    if (filters.decision === "none" && issue.decision) return false;
    if (filters.decision === "recorded" && !issue.decision) return false;
    return !filters.teacher || issue.teacher.includes(filters.teacher.trim());
  });
}

function issueRow(issue) {
  const severity = issue.severity_rank <= 1 ? "bad" : issue.severity_rank === 2 ? "warn" : "ok";
  return `<tr><td><span class="${severity}">${escapeHtml(issue.severity_label)}</span></td><td>${escapeHtml(issue.field_label)}</td><td>${escapeHtml(issue.teacher)}</td><td>${issue.expected ?? "—"}</td><td>${issue.actual ?? "—"}</td><td>${issue.difference ?? "—"}</td><td>${escapeHtml(issue.status_label)}</td><td>${escapeHtml(issue.decision_label)}</td><td><button class="quiet" onclick="evidence('${issue.id}')">查看明细</button></td></tr>`;
}

function updateFilters() {
  filters = { field: $("#filter-field").value, state: $("#filter-state").value, decision: $("#filter-decision").value, teacher: $("#filter-teacher").value };
  const scroll = window.scrollY;
  renderTab();
  $("#filter-field").value = filters.field; $("#filter-state").value = filters.state; $("#filter-decision").value = filters.decision;
  window.scrollTo(0, scroll);
}

async function evidence(id) {
  try {
    const result = await api(`/api/runs/${current.id}/evidence?issue=${id}`);
    const issue = result.issue;
    const decision = issue.decision;
    $("#issue-detail").innerHTML = `<article class="detail-panel"><div class="section-head"><div><p class="eyebrow">问题详情</p><h3>${escapeHtml(issue.title)}</h3></div><button class="quiet" onclick="$('#issue-detail').innerHTML=''">关闭</button></div><div class="comparison"><div><span>排课重新计算</span><strong>${issue.expected ?? "无法计算"}</strong></div><div><span>工资表填报</span><strong>${issue.actual ?? "未读取"}</strong></div><div><span>差异</span><strong>${issue.difference ?? "—"}</strong></div></div><p>${escapeHtml(issue.reason)}</p><h4>来源记录</h4>${result.evidence.length ? `<div class="evidence-list">${result.evidence.map(evidenceCard).join("")}</div>` : `<p class="muted">${escapeHtml(result.note || "当前没有可展开的逐课来源。")}</p>`}${decision ? `<div class="decision-saved"><strong>已记录：${escapeHtml(issue.decision_label)}</strong><p>${escapeHtml(decision.reason)} · 确认人：${escapeHtml(decision.person)}</p></div>` : ""}<h4>记录处理意见</h4><div class="decision-form"><label>处理方式<select id="decision"><option value="special">确认属于特殊情况</option><option value="payroll_error">工资表需要修改</option><option value="defer">暂时保留，稍后处理</option><option value="confirm_source">原始依据需要核实</option></select></label><label>确认人<input id="person" value="${escapeHtml(decision?.person || "")}" placeholder="填写姓名"></label><label class="wide">说明<textarea id="reason" placeholder="说明判断依据（必填）">${escapeHtml(decision?.reason || "")}</textarea></label></div><div class="action-bar"><span class="muted small">保存意见不会修改原 Excel，也不会直接让整份工资通过。</span><button onclick="decide('${id}')">保存处理意见</button></div></article>`;
    $("#issue-detail").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showMessage(error.message); }
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
  try { current = await api(`/api/runs/${current.id}/check`, { method: "POST", body: "{}" }); tab = current.issues.length ? "issues" : "overview"; renderRun(); showMessage("已重新核对全部材料。", "success"); }
  catch (error) { await refreshAfterError(error); }
}

async function refreshAfterError(error) {
  try { current = await api(`/api/runs/${current.id}`); renderRun(); } catch (_) { /* retain current screen */ }
  showMessage(error.message);
}

async function decide(id) {
  try {
    current = await api(`/api/runs/${current.id}/decisions`, { method: "POST", body: JSON.stringify({ issue_id: id, action: $("#decision").value, person: $("#person").value, reason: $("#reason").value }) });
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
