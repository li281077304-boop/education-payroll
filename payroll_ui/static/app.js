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
let baseSalaryImportPreview = null;
let supportImportPreview = null;
let supportImportPath = "";
let supportImportName = "";
let baseSalaryImportPath = "";
let baseSalaryImportName = "";
let pendingHistoryReferenceFile = null;
let pendingHistoryReferenceGroup = "";
let renewalMaterialPreview = null;
const materialBusy = new Set();

const coreStateLabels = {
  DETERMINED: "已确定",
  ESTIMATED: "估算",
  NEEDS_INPUT: "缺资料",
  NOT_APPLICABLE: "不适用",
};

const roleCopy = {
  schedule: ["原始排课数据", "选择原始排课表", "用于重新计算一对一和班课"],
  subject_group: ["学科组提交表", "选择学科组提交表", "请先选择本文件所属科组；每份资料分别确认"],
  math: ["学科组提交表", "选择学科组提交表", "确定本次需要核验的教师"],
  science: ["学科组提交表", "选择学科组提交表", "确定本次需要核验的教师"],
  renewal: ["续费表", "选择续费表", "识别当前月份续费课时；确认后进入工资"],
  refund: ["退费表", "选择退费表", "读取上游已确认的退费结果"],
  baseline: ["工资结果参考表", "选择工资结果参考表", "仅作辅助核对"],
  check: ["历史核对辅助表", "选择历史核对辅助表", "仅作辅助查看"],
};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>\"]/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char]);
const payrollGroups = ["数学组", "理化组", "语文组", "英语组", "其它"];
function checkedGroups(containerId) {
  return [...document.querySelectorAll(`#${containerId} input[type="checkbox"]:checked`)].map((item) => item.value);
}
function selectedRunGroups(run = current) {
  if (run?.operator_role !== "SUBJECT_LEADER") return [];
  const groups = Array.isArray(run.selected_groups) ? run.selected_groups.filter(Boolean) : [];
  return groups.length ? [...new Set(groups)] : run.selected_group ? [run.selected_group] : [];
}
function runGroupsLabel(run = current, fallback = "") {
  return selectedRunGroups(run).join("、") || fallback;
}
function runNeedsRecalculation(run = current) {
  return Boolean(run?.recalculation_required || run?.role_scope_recalculation_required);
}
function subjectGroupCandidateKey(item, fallback = "") {
  if (item?.candidate_id) return String(item.candidate_id);
  return `${item?.role || item?.recognized_role || "legacy"}|${item?.recognized_group || ""}|${item?.source_sha256 || item?.sha256 || fallback}`;
}
const fmtDate = (value) => value ? new Date(value).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
let lastClickedActionButton = null;
const busyButtons = new WeakMap();
if (typeof document.addEventListener === "function") {
  document.addEventListener("click", (event) => {
    lastClickedActionButton = event.target?.closest?.("button:not(:disabled)") || null;
  }, true);
}

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
  <section class="core-rule-block"><div class="core-rule-block-head"><div><h3>AF（总课时费）默认政策候选</h3><p class="muted small">仅在缺少个人有效期政策时作为“估算”；不会标成已确定。</p></div><label class="inline-check"><input id="core-af-default-enabled" type="checkbox" ${candidate ? "checked" : ""}>启用候选</label></div><div class="decision-form"><label>义务课时<input id="core-af-obligation" type="number" step="0.01" min="0" value="${escapeHtml(candidate?.obligation_hours ?? "")}"></label><label>候选名称<input id="core-af-label" value="${escapeHtml(candidate?.label || "")}"></label><label class="wide">候选来源<input id="core-af-source" value="${escapeHtml(candidate?.source || "")}"></label></div></section>`;
}

async function api(url, options = {}) {
  const button = lastClickedActionButton?.isConnected ? lastClickedActionButton : null;
  let busy = button ? busyButtons.get(button) : null;
  if (button) {
    if (busy?.releaseTimer) window.clearTimeout(busy.releaseTimer);
    if (!busy) {
      const path = new URL(url, window.location.href).pathname;
      const labels = [
        ["/check", "正在重新核对…"], ["/preview", "正在核算…"], ["/generate", "正在生成工资表…"],
        ["/base-salary-defer", "正在保存暂不录入状态…"], ["/base-salary", "正在保存…"], ["/period-window", "正在保存周期…"], ["/period-authority", "正在同步人工月…"], ["/period-document/import", "正在导入人工月…"], ["/af-policy", "正在保存…"],
        ["/support", "正在导入支持部工资资料…"], ["/support-preview", "正在识别支持部资料…"], ["/support-remove", "正在从本次核算移除…"], ["/staff-batch", "正在批量确认人员资料…"], ["/base-salary-reference/use", "正在确认本月参考值…"], ["/employment", "正在保存用工性质…"], ["/part-time-pay-decision", "正在保存兼职工资方式…"],
        ["/company-template", "正在保存模板…"], ["/decisions", "正在保存…"],
      ];
      const label = labels.find(([suffix]) => path.endsWith(suffix))?.[1] || "正在处理…";
      busy = { originalText: button.textContent, originalDisabled: button.disabled, requests: 0, releaseTimer: null };
      busyButtons.set(button, busy);
      button.disabled = true;
      button.textContent = label;
    }
    busy.requests += 1;
  }
  try {
    const response = await fetch(url, { ...options, headers: { "Content-Type": "application/json", "X-Payroll-Token": token, ...options.headers } });
    const type = response.headers.get("content-type") || "";
    const payload = type.includes("json") ? await response.json() : await response.text();
    if (!response.ok) throw new Error(payload.error || "操作未完成，请稍后重试。");
    return payload;
  } finally {
    if (button && busy) {
      busy.requests = Math.max(0, busy.requests - 1);
      if (busy.requests === 0) {
        busy.releaseTimer = window.setTimeout(() => {
          if (button.isConnected && busyButtons.get(button) === busy) {
            button.disabled = busy.originalDisabled;
            button.textContent = busy.originalText;
          }
          busyButtons.delete(button);
          busy.releaseTimer = null;
        }, 120);
      }
    }
  }
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
  $("#app").innerHTML = `<div class="shell"><header class="top"><div><div class="brand">工资核算助手</div><div class="muted small">文件只在本机读取，不修改原工资表</div></div><div><button class="quiet" onclick="home()">工作台</button></div></header>${content}</div>`;
}

async function home() {
  try {
    // Use the cheap persisted index here.  Opening a selected Run still uses
    // the authoritative full render, but the home page must keep history
    // reachable without parsing every workbook in the archive.
    homeRuns = await api("/api/runs/index");
    current = null;
    baseSalaryImportPreview = null;
    renewalMaterialPreview = null;
    const today = new Date();
    const defaultPeriod = defaultPayrollPeriod(today);
    shell(`<section class="hero card"><div><p class="eyebrow">开始核算</p><h1>新建工资核算</h1><p class="muted">先选择你本次承担的范围。DOS 负责全教学部；学科组长只处理确认属于本组的人。</p></div><div class="create-box"><label for="operator-role">本次使用身份</label><select id="operator-role" required onchange="toggleLeaderGroupChoice()"><option value="" selected>请选择角色</option><option value="DOS">DOS / 教学管理者（全教学部）</option><option value="SUBJECT_LEADER">学科组长（仅负责科组）</option></select><div id="selected-group-wrap" class="hidden"><strong>负责科组（可多选）</strong><div id="selected-group" class="checkbox-list" style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px">${payrollGroups.map((group) => `<label style="display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid #dfe3e8;border-radius:7px;background:#fff;font-weight:500"><input type="checkbox" value="${group}" data-run-group style="width:auto;margin:0"> ${group}</label>`).join("")}</div></div><label for="period">工资月份</label><input id="period" type="month" value="${defaultPeriod}" onchange="duplicateHint()"><details class="advanced-period"><summary>需要时调整排课核算周期</summary><label for="period-start">核算周期开始</label><input id="period-start" type="date"><label for="period-end">核算周期结束</label><input id="period-end" type="date"><p class="small muted">普通核算不需要填写；留空时使用该工资月份的人工月 authority。</p></details><label for="mode">这次要做什么</label><select id="mode"><option value="AUDIT">核对一份已有工资表</option><option value="GENERATE">生成工资表</option></select><p id="duplicate-hint" class="small muted"></p><button onclick="createRun()">创建核算</button><button class="secondary full" onclick="authorityDashboard()">基础资料与规则</button></div></section><section class="card history-section"><div class="section-head"><div><p class="eyebrow">继续已有核算</p><h2>历史核算</h2><p class="muted">选择某个月份继续查看材料、核对结果或工资预览；打开时才读取该记录的完整证据。</p></div><span class="muted">${homeRuns.length} 条记录</span></div>${historyList()}</section>`, false);
    duplicateHint();
  } catch (error) { showMessage(error.message); }
}

async function authorityDashboard(runId = null, focus = "") {
  try {
    const [catalog, companyTemplates, periodPayload] = await Promise.all([api("/api/authorities"), api("/api/company-template"), api("/api/period-authorities")]);
    const section = (title, versions, kind, click) => `<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>${title}</h2><p class="muted">版本会保留来源、生效期与被哪些核算记录使用；修正时请创建新版本，不要删除旧版本。</p></div><button class="secondary" onclick="${click}">查看与修正</button></div>${versions.length ? `<div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>状态</th><th>来源</th><th>已用于</th></tr></thead><tbody>${versions.map(v => `<tr><td>${escapeHtml(v.source_version || v.id)}</td><td>${escapeHtml(v.effective_from)} ～ ${escapeHtml(v.effective_to)}</td><td>${escapeHtml(v.status || "ACTIVE")}</td><td>${escapeHtml(v.source)}</td><td>${v.used_by_runs?.length || 0} 个核算</td></tr>`).join("")}</tbody></table></div>` : '<p class="muted">尚未保存版本。</p>'}</section>`;
    const rebind = runId ? `<section class="card"><h2>让当前核算改用修正版</h2><p class="muted">这是明确的人工操作。切换后会要求重新全盘核对，相关人工意见会变为“需重新确认”。</p>${authorityRebindControl("rating", catalog.ratings, runId)}${authorityRebindControl("policy", catalog.policies, runId)}</section>` : "";
    // 普通月度工资流程只需要这几块：公司工资模板 / 人工月 / 历史基本工资 /
    // 教师星级来源。星级加成金额、个人政策、7 类核心规则等属于低频工程配置，
    // 收进下方“高级设置”。
    const authorityList = periodPayload.authorities || [];
    const runPeriod = runId ? (current?.period || "") : "";
    const runAuthority = (runId && current?.period_authority) || {};
    periodAuthorityList = authorityList;
    const periodCard = periodAuthorityDashboardCard(runId, authorityList);
    const baseSalaryCount = Object.keys(current?.base_salary_inputs || {}).length;
    const baseSalaryState = current?.base_salary_input_snapshot ? `已带入 ${baseSalaryCount} 位教师` : current?.base_salary_deferred ? "已记录暂不录入（M 保持待补充）" : "尚未导入";
    const baseSalaryCard = `<section id="base-salary-card" class="card"><div class="section-head"><div><p class="eyebrow">生产输入</p><h2>历史基本工资</h2><p class="muted">用一张历史工资表批量带入 G～L，未匹配教师再单独补录；已保存的教师资料下个月自动复用。</p></div><span class="status ${current?.base_salary_input_snapshot ? "ok" : "warn"}">${escapeHtml(baseSalaryState)}</span></div>${runId ? `<div class="action-bar"><button class="secondary" onclick="openBaseSalaryPage('${escapeHtml(runId)}')">去导入或补录</button></div>` : '<p class="muted small">打开一个工资核算记录后，可在这里导入或补录基本工资。</p>'}</section>`;
    const starAuthorityRef = current?.authority_context?.rating || {};
    const ratingSourceCard = `<section id="rating-source-card" class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>教师星级来源</h2><p class="muted">星级来自独立资料的版本与生效期，不由 AE 档位金额反推；这里只查看来源，不改星级值和加成算法。</p></div><button class="secondary" onclick="ratingDashboard('${runId || ""}')">查看与修正</button></div><div class="facts"><div><span>当前核算使用</span><strong>${escapeHtml(starAuthorityRef.name || "尚未绑定")}</strong></div><div><span>版本</span><strong>${escapeHtml(starAuthorityRef.version_id || "—")}</strong></div><div><span>生效期</span><strong>${escapeHtml(starAuthorityRef.effective_period || "—")}</strong></div><div><span>来源</span><strong>${escapeHtml(starAuthorityRef.source || "—")}</strong></div></div></section>`;
    const rules = catalog.rules.map(r => `<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.effective_from)} ～ ${escapeHtml(r.effective_to)}</td><td>${escapeHtml(r.source_version)}</td><td>${escapeHtml(r.source)}</td></tr>`).join("");
    const activeTemplate = companyTemplates.find((item) => item.status === "ACTIVE");
    const templateCard = `<section id="company-template-card" class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>公司工资模板</h2><p class="muted">设置一次后，新月份自动使用；系统保存结构副本，工资值仍来自当前核算。</p></div><span class="status ${activeTemplate ? "ok" : "warn"}">${activeTemplate ? "已设置" : "未设置"}</span></div><div class="facts"><div><span>当前模板</span><strong>${escapeHtml(activeTemplate?.name || "尚未设置")}</strong></div><div><span>设置时间</span><strong>${escapeHtml(activeTemplate?.created_at ? fmtDate(activeTemplate.created_at) : "—")}</strong></div></div><div class="action-bar"><button onclick="chooseCompanyTemplate('${escapeHtml(runId || "")}')">${activeTemplate ? "更换模板" : "选择公司工资模板"}</button>${runId ? `<button class="secondary" onclick="openRun('${escapeHtml(runId)}')">返回当前工资预览</button>` : ""}</div></section>`;
    shell(`<div class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>核对依据</h1><p class="muted">修正基础资料会新建版本；历史版本和已使用记录都不会被覆盖。</p></div><button class="secondary" onclick="${runId ? `openRun('${runId}')` : "home()"}">返回</button></div>${rebind}${templateCard}${periodCard}${baseSalaryCard}${ratingSourceCard}<details class="card advanced-settings"><summary>高级设置（管理员）：星级加成、个人政策与 7 类核心规则</summary><p class="muted small">以下属于低频工程配置，日常月度工资流程不需要改动。任何修改都会新建版本，不会覆盖历史核算记录。</p><section class="card core-entry-card"><div class="section-head"><div><p class="eyebrow">核心规则链</p><h2>核心规则配置（7 类）</h2><p class="muted">班型、人数、年级、AD、星级加成、个人政策和兼职单价统一从版本化资料读取；同一月份有多个版本时必须由你显式选择。</p></div><button onclick="coreRulesDashboard('${runId || ""}')">打开核心规则面板</button></div></section>${section("教师星级", catalog.ratings, "rating", `ratingDashboard('${runId || ""}')`)}${section("教师工资政策", catalog.policies, "policy", `policyDashboard('${runId || ""}')`)}<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>班型折算规则（旧入口）</h2><p class="muted">保留现有入口，历史版本继续可查；新的核心规则链请从上方七类面板维护。</p></div><button class="secondary" onclick="classTypeRulesPage('${runId || ""}')">查看与配置</button></div></section><section class="card"><div class="section-head"><div><p class="eyebrow">历史兼容</p><h2>历史兼容规则（只读）</h2><p class="muted">仅供旧核算记录继续解释原结果；配置化核算请以上方“核心规则配置”为准。</p></div></div><div class="table-wrap"><table class="table"><thead><tr><th>规则</th><th>生效期</th><th>版本</th><th>来源</th></tr></thead><tbody>${rules}</tbody></table></div></section></details>`, false);
    if (focus === "template") $("#company-template-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) { showMessage(error.message); }
}

async function chooseCompanyTemplate(returnRunId = "") {
  try {
    const picked = await api("/api/pick", { method: "POST", body: "{}" });
    if (!picked.path) return;
    await api("/api/company-template", { method: "POST", body: JSON.stringify({ path: picked.path, actor: "本机管理员" }) });
    showMessage("公司工资模板已保存；以后新月份会自动使用。", "success");
    if (returnRunId) {
      await openRun(returnRunId);
      tab = "payroll";
      renderRun();
      showMessage("模板已保存。现在可以在工资预览中继续生成。", "success");
    } else await authorityDashboard();
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
    shell(`<section class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>核心规则面板（7 类）</h1><p class="muted">按真实字段逐项编辑；保存会创建不可变的新版本，不会覆盖历史核算。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></section>${bind}<section class="card"><div class="section-head"><div><h2>已有核心规则版本</h2><p class="muted">点击“复制为新版本”后，在下方表格中修改。</p></div><span class="muted">${versions.length} 个版本</span></div><div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>来源</th><th>内容</th><th>审计信息</th><th></th></tr></thead><tbody>${coreVersionRows(versions, returnRunId) || '<tr><td colspan="6" class="muted">尚未保存核心规则版本。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建核心规则修正版" : "创建核心规则版本"}</h2><p class="muted">${correction ? `当前复制自 ${escapeHtml(correction.id)}；保存后旧版本仍保留。` : "请直接填写表格，不需要接触配置文件或代码。"}</p><div class="decision-form"><label>来源说明<input id="core-source" value="${escapeHtml(sourceDefault)}" placeholder="例如：2026 秋季规则确认"></label><label>操作人<input id="core-actor" value="${escapeHtml(actorDefault)}" placeholder="填写姓名"></label></div>${coreRulesEditor(selectedRules)}<div class="action-bar"><span class="muted small">保存只创建新版本；要用于某个核算，需在上方显式绑定。</span><button onclick="saveCoreRules('${returnRunId}')">保存新核心规则版本</button></div></section><section class="core-rule-block core-rule-readonly"><div class="core-rule-block-head"><div><h3>个人政策</h3><p class="muted small">复用已有政策字段表单，明确填写 FULL_TIME/PART_TIME 和允许无课。</p></div><button class="secondary" onclick="policyDashboard('${returnRunId}')">管理个人政策</button></div><p class="core-rule-summary">个人政策单独版本化，保存时不会混入核心规则版本。</p></section><section class="core-rule-block core-rule-readonly"><div class="core-rule-block-head"><div><h3>兼职课次单价</h3><p class="muted small">复用独立单价版本，按教师 + 年级范围匹配，缺单价显示“缺资料”。</p></div><button class="secondary" onclick="partTimeRatesDashboard('${returnRunId}')">管理兼职单价</button></div><p class="core-rule-summary">兼职单价单独版本化，保存时不会混入核心规则版本。</p></section>`, false);
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
    showMessage(`核心规则已保存为新版本${savedId ? `：${savedId}` : ""}。历史核算不会自动改变。`, "success");
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
    tab = ["REVIEW_REQUIRED", "PASS"].includes(current.status) ? "issues" : "materials";
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
    tab = ["REVIEW_REQUIRED", "PASS"].includes(current.status) ? "issues" : "materials";
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
    shell(`<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h1>教师星级</h1><p class="muted">工资核算按月份绑定当时生效的星级版本，不会用新年度名单覆盖历史月份。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></div><div class="banner info"><strong>当前最新版本：${latest ? `${escapeHtml(latest.effective_from)} ～ ${escapeHtml(latest.effective_to)}` : "尚未导入"}</strong><span>${latest ? `下一次更新时间：${escapeHtml(String(Number(latest.effective_to.slice(0, 4)) + 1))}-10` : "请先导入年度星级名单。"}</span></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>星级</th><th>生效期</th><th>数据来源</th><th>状态</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="6" class="muted">尚未保存星级名单。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建星级修正版" : "导入新的星级版本"}</h2><p class="muted">${correction ? "原版本会保留并标记为 SUPERSEDED；请在下面修正后保存新版本。" : "每行填写：教师姓名，星级，岗位，工资表是否允许不显示星级。"}</p><input id="rating-supersedes" type="hidden" value="${escapeHtml(correction?.id || "")}"><div class="decision-form"><label>生效开始<input id="rating-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="rating-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label>数据来源<input id="rating-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：2025年度星级评定"></label><label>版本名称<input id="rating-version" value="${escapeHtml(correction ? `${correction.source_version} corrected` : "")}" placeholder="例如：2025-10 v2"></label><label class="wide">名单<textarea id="rating-list" placeholder="张三，4，教师，否">${escapeHtml(list)}</textarea></label></div><div class="action-bar"><span class="muted small">保存不会修改工资表，也不会自动改变历史核算。</span><button onclick="saveRatings('${returnRunId}')">保存星级版本</button></div></section>`, false);
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
    const [versions, registry] = await Promise.all([api("/api/policies"), api(`/api/payroll-policy-registry?run_id=${encodeURIComponent(returnRunId || "")}`)]);
    const correction = versions.find(v => v.id === correctionId);
    const rows = versions.flatMap((version) => version.profiles.map((profile) => `<tr><td>${escapeHtml(profile.teacher)}</td><td>${escapeHtml(profile.role)}</td><td>${escapeHtml(profile.employment_type || "FULL_TIME")}</td><td>${profile.allow_no_teaching ? "是" : "否"}</td><td>${profile.rating_override || profile.rating || "待确认"} 星</td><td>${profile.obligation_hours_deduction_enabled ? `${profile.obligation_hours} 小时，扣除` : "不扣除"}</td><td>${escapeHtml(profile.special_approval || "无")}</td><td>${escapeHtml(version.effective_from)} ～ ${escapeHtml(version.effective_to)}</td><td>${escapeHtml(version.status || "ACTIVE")}</td><td><button class="quiet" onclick="policyDashboard('${returnRunId}', '${version.id}')">创建修正版</button></td></tr>`));
    policyProfileRows = correction?.profiles ? JSON.parse(JSON.stringify(correction.profiles)) : [{}];
    const registryRows = (registry.rows || []).map((item) => `<tr><td>${escapeHtml(item.display_name || "—")}</td><td>${escapeHtml(item.teacher_id || "未绑定")}</td><td>${escapeHtml(item.policy_type)}</td><td>${item.rate == null ? (item.obligation_hours == null ? "—" : `${item.obligation_hours} 小时`) : `${item.rate} 元/节`}</td><td>${escapeHtml(item.effective_from || "—")} ～ ${escapeHtml(item.effective_to || "—")}</td><td>${escapeHtml(item.source || "—")}</td><td><span class="status ${item.status === "ACTIVE" ? "ok" : item.status === "NEEDS_CONFIRMATION" ? "bad" : "warn"}">${escapeHtml(item.status)}</span></td></tr>`).join("");
    const registryPanel = `<section class="card"><div class="section-head"><div><p class="eyebrow">生产政策注册表</p><h2>薪酬政策</h2><p class="muted">只将 ACTIVE 且覆盖本月的政策带入新的核算；July 历史资料保留为 HISTORICAL_ONLY，不会自动延续。</p></div><span class="small muted">优先级：PERSONAL_POLICY ＞ PART_TIME_RATE ＞ DEFAULT_FULL_TIME</span></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>教师 ID</th><th>政策类型</th><th>单价/义务课时</th><th>生效期</th><th>来源</th><th>状态</th></tr></thead><tbody>${registryRows || '<tr><td colspan="7" class="muted">当前月份暂无政策记录。</td></tr>'}</tbody></table></div></section>`;
    shell(`${registryPanel}<section class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h1>教师工资政策档案</h1><p class="muted">逐人明确教师 ID、全职/兼职、个人义务课时和是否允许管理岗当月无课；不会根据岗位文字自动猜测。</p></div><button class="secondary" onclick="${returnRunId ? `authorityDashboard('${returnRunId}')` : "authorityDashboard()"}">返回基础资料</button></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>身份</th><th>用工类型</th><th>允许无课</th><th>星级</th><th>义务课时</th><th>特殊审批</th><th>生效期</th><th>状态</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="10" class="muted">尚未保存工资政策档案。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建政策修正版" : "保存政策版本"}</h2><p class="muted">每位教师一行。教师 ID 用于身份绑定；允许无课必须显式勾选。</p><input id="policy-supersedes" type="hidden" value="${escapeHtml(correction?.id || "")}"><div class="decision-form"><label>生效开始<input id="policy-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="policy-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label class="wide">数据来源<input id="policy-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：年度工资政策确认"></label></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>教师</th><th>教师 ID</th><th>身份</th><th>用工类型</th><th>允许无课</th><th>基础星级</th><th>特批星级</th><th>义务小时</th><th>扣除义务小时</th><th>特殊审批</th><th></th></tr></thead><tbody id="policy-profile-editor">${policyProfileRows.map(policyProfileEditorRow).join("")}</tbody></table></div><div class="action-bar"><button type="button" class="secondary" onclick="addPolicyProfileRow()">新增教师</button><span class="muted small">保存不会修改工资表，也不会自动改变历史核算。</span><button onclick="savePolicies('${returnRunId}')">保存政策版本</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

function policyProfileEditorRow(profile = {}) {
  const employment = profile.employment_type || "FULL_TIME";
  return `<tr><td><input class="policy-teacher" value="${escapeHtml(profile.teacher || "")}" placeholder="教师姓名"></td><td><input class="policy-teacher-id" value="${escapeHtml(profile.teacher_id || "")}" placeholder="稳定 ID"></td><td><input class="policy-role" value="${escapeHtml(profile.role || "")}" placeholder="例如 教师/管理岗"></td><td><select class="policy-employment">${option("FULL_TIME", employment, "全职")}${option("PART_TIME", employment, "兼职")}</select></td><td><label class="inline-check"><input class="policy-no-teaching" type="checkbox" ${profile.allow_no_teaching ? "checked" : ""}>允许</label></td><td><input class="policy-rating" type="number" min="1" max="6" step="1" value="${escapeHtml(profile.rating ?? "")}"></td><td><input class="policy-rating-override" type="number" min="1" max="6" step="1" value="${escapeHtml(profile.rating_override ?? "")}" placeholder="可空"></td><td><input class="policy-obligation" type="number" min="0" step="0.01" value="${escapeHtml(profile.obligation_hours ?? 0)}"></td><td><label class="inline-check"><input class="policy-deduct" type="checkbox" ${profile.obligation_hours_deduction_enabled ? "checked" : ""}>扣除</label></td><td><input class="policy-approval" value="${escapeHtml(profile.special_approval || "")}" placeholder="可空"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function addPolicyProfileRow() { $("#policy-profile-editor")?.insertAdjacentHTML("beforeend", policyProfileEditorRow()); }

function collectPolicyProfiles() {
  return editorRows("#policy-profile-editor").map((row) => ({
    teacher: inputValue(row, ".policy-teacher"),
    teacher_id: inputValue(row, ".policy-teacher-id"),
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
    partTimeRateRows = correction?.profiles ? JSON.parse(JSON.stringify(correction.profiles)) : [{ teacher: "", grade_scope: "", pricing_mode: "FIXED_GRADE_RATE", fixed_rate: "" }];
    const rows = versions.flatMap((version) => (version.profiles || []).map((profile) => `<tr><td>${escapeHtml(profile.teacher)}</td><td>${escapeHtml(profile.grade_scope || "全部年级")}</td><td>${escapeHtml(profile.pricing_mode || "FIXED_GRADE_RATE")}</td><td>${escapeHtml(profile.base_rate ?? profile.fixed_rate ?? profile.rate_per_session)}</td><td>${escapeHtml(version.effective_from || "—")} ～ ${escapeHtml(version.effective_to || "持续")}</td><td>${escapeHtml(version.source || "—")}</td><td>${escapeHtml(version.actor || "—")}</td><td><button class="quiet" onclick="partTimeRatesDashboard('${returnRunId}', '${escapeHtml(version.id)}')">创建修正版</button></td></tr>`));
    shell(`<section class="section-head"><div><p class="eyebrow">基础资料与规则</p><h1>兼职课时定价</h1><p class="muted">按教师×年级配置 COEFFICIENT_BASED 或 FIXED_GRADE_RATE；目标覆盖价只使用稳定 student_id/class_id。</p></div><button class="secondary" onclick="coreRulesDashboard('${returnRunId}')">返回核心规则面板</button></section>${returnRunId ? `<section class="card rebind-card"><h2>当前核算的兼职版本</h2><p class="muted">需要切换时请返回核心规则面板并显式选择版本。</p></section>` : ""}<section class="card"><div class="section-head"><div><h2>已有定价版本</h2><p class="muted">旧版本保留；同一核算月份有多个版本时由你显式选择。</p></div><span class="muted">${versions.length} 个版本</span></div><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>年级</th><th>方式</th><th>基础价/固定价</th><th>生效期</th><th>来源</th><th>操作人</th><th></th></tr></thead><tbody>${rows.join("") || '<tr><td colspan="8" class="muted">尚未保存兼职定价版本。</td></tr>'}</tbody></table></div></section><section class="card"><h2>${correction ? "创建兼职定价修正版" : "保存兼职定价版本"}</h2><p class="muted">${correction ? `当前复制自 ${escapeHtml(correction.id)}；保存会新建版本，不会覆盖旧版本。` : "每位教师和年级范围各填一行；如需目标覆盖，请填写 student_id 或 class_id。"}</p><div class="decision-form"><label>生效开始<input id="part-time-from" type="month" value="${escapeHtml(correction?.effective_from || "")}"></label><label>生效结束<input id="part-time-to" type="month" value="${escapeHtml(correction?.effective_to || "")}"></label><label>数据来源<input id="part-time-source" value="${escapeHtml(correction?.source || "")}" placeholder="例如：2026-09 兼职确认表"></label><label>操作人<input id="part-time-actor" value="${escapeHtml(correction?.actor || "")}" placeholder="填写姓名"></label></div><div class="table-wrap"><table class="table editable-table"><thead><tr><th>教师</th><th>年级</th><th>定价方式</th><th>基础价</th><th>固定价</th><th>student_id</th><th>class_id</th><th>覆盖价</th><th></th></tr></thead><tbody id="part-time-rate-editor">${partTimeRateRows.map(partTimeRateEditorRow).join("")}</tbody></table></div><div class="action-bar"><button type="button" class="secondary" onclick="addPartTimeRateRow()">新增一行</button><span class="muted small">保存不会修改工资表，也不会自动改变历史核算。</span><button onclick="savePartTimeRates('${returnRunId}')">保存兼职定价版本</button></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

function partTimeRateEditorRow(profile = {}) {
  return `<tr><td><input class="part-time-teacher" value="${escapeHtml(profile.teacher || "")}" placeholder="教师姓名"></td><td><input class="part-time-grade" value="${escapeHtml(profile.grade_scope || "*")}" placeholder="年级"></td><td><select class="part-time-mode">${option("COEFFICIENT_BASED", profile.pricing_mode || "FIXED_GRADE_RATE", "按班型系数")}${option("FIXED_GRADE_RATE", profile.pricing_mode || "FIXED_GRADE_RATE", "年级统一价")}</select></td><td><input class="part-time-base" type="number" min="0" step="0.01" value="${escapeHtml(profile.base_rate ?? "")}" placeholder="基础价"></td><td><input class="part-time-fixed" type="number" min="0" step="0.01" value="${escapeHtml(profile.fixed_rate ?? profile.rate_per_session ?? "")}" placeholder="固定价"></td><td><input class="part-time-student-id" value="${escapeHtml(profile.student_id || "")}" placeholder="可选"></td><td><input class="part-time-class-id" value="${escapeHtml(profile.class_id || "")}" placeholder="可选"></td><td><input class="part-time-override" type="number" min="0" step="0.01" value="${escapeHtml(profile.override_rate ?? "")}" placeholder="可选"></td><td><button type="button" class="quiet danger-link" onclick="this.closest('tr').remove()">删除</button></td></tr>`;
}

function addPartTimeRateRow() {
  $("#part-time-rate-editor")?.insertAdjacentHTML("beforeend", partTimeRateEditorRow());
}

function collectPartTimeProfiles() {
  return [...document.querySelectorAll("#part-time-rate-editor tr")].map((row) => {
    const teacher = inputValue(row, ".part-time-teacher");
    const grade_scope = inputValue(row, ".part-time-grade");
    const mode = inputValue(row, ".part-time-mode") || "FIXED_GRADE_RATE";
    const base = inputValue(row, ".part-time-base");
    const fixed = inputValue(row, ".part-time-fixed");
    if (!teacher && !grade_scope && !base && !fixed) return null;
    if (!teacher || !grade_scope || (mode === "COEFFICIENT_BASED" ? !base : !fixed)) throw new Error("兼职定价每行都要填写教师、年级和对应价格。");
    return { teacher, grade_scope, pricing_mode: mode, base_rate: base ? Number(base) : null, fixed_rate: fixed ? Number(fixed) : null, rate_per_session: Number(mode === "COEFFICIENT_BASED" ? base : fixed), student_id: inputValue(row, ".part-time-student-id"), class_id: inputValue(row, ".part-time-class-id"), override_rate: inputValue(row, ".part-time-override") ? Number(inputValue(row, ".part-time-override")) : null };
  }).filter(Boolean);
}

async function savePartTimeRates(returnRunId = "") {
  try {
    const profiles = collectPartTimeProfiles();
    const payload = { profiles, source: $("#part-time-source")?.value.trim() || "", effective_from: $("#part-time-from")?.value || "", effective_to: $("#part-time-to")?.value || "", actor: $("#part-time-actor")?.value.trim() || "" };
    if (!profiles.length || !payload.source || !payload.effective_from || !payload.effective_to || !payload.actor) throw new Error("请填写兼职单价、来源、生效月份和操作人。");
    const saved = await api("/api/part-time-rates", { method: "POST", body: JSON.stringify(payload) });
    const savedId = versionList(saved)[0]?.id;
    showMessage(`兼职单价已保存为新版本${savedId ? `：${savedId}` : ""}。历史核算不会自动改变。`, "success");
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
    return `<article class="history-row"><div><strong>${escapeHtml(run.period)}</strong><div class="small muted">编号 ${escapeHtml(run.id)} · 更新于 ${fmtDate(run.updated_at || run.created_at)}</div></div><div>${statusBadge(run)}<div class="small muted">材料 ${run.health.readiness}% · 审计问题 ${groupCount} 个${fieldCount ? `（字段核查 ${fieldCount} 项）` : ""}</div></div><button class="secondary" onclick="openRun('${run.id}')">${next}</button></article>`;
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
    const operatorRole = $("#operator-role")?.value || "";
    const selectedGroups = checkedGroups("selected-group");
    if (!operatorRole) return showMessage("请选择 DOS / 教学管理者或学科组长后再创建核算。", "error");
    if (operatorRole === "SUBJECT_LEADER" && !selectedGroups.length) return showMessage("学科组长模式请至少选择负责科组（可多选）。", "error");
    const selectedGroup = selectedGroups.length === 1 ? selectedGroups[0] : "";
    current = await api("/api/runs", { method: "POST", body: JSON.stringify({ period: $("#period").value, mode, operator_role: operatorRole, selected_groups: operatorRole === "SUBJECT_LEADER" ? selectedGroups : [], selected_group: selectedGroup, period_start: $("#period-start")?.value || "", period_end: $("#period-end")?.value || "", period_boundary_source: $("#period-start")?.value || $("#period-end")?.value ? "USER_CONFIRMED" : "LEGACY_CALENDAR_DEFAULT" }) });
    baseSalaryImportPreview = null;
    renewalMaterialPreview = null;
    pendingHistoryReferenceFile = null;
    pendingHistoryReferenceGroup = "";
    tab = "materials";
    renderRun();
  } catch (error) { showMessage(error.message); }
}

function toggleLeaderGroupChoice() {
  const visible = $("#operator-role")?.value === "SUBJECT_LEADER";
  $("#selected-group-wrap")?.classList.toggle("hidden", !visible);
}

function defaultPayrollPeriod(now = new Date()) {
  if (now.getDate() >= 21) return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
  const month = now.getMonth();
  const year = month === 0 ? now.getFullYear() - 1 : now.getFullYear();
  return `${year}-${String(month === 0 ? 12 : month).padStart(2, "0")}`;
}

async function openRun(id) {
  try {
    if (current?.id !== id) {
      baseSalaryImportPreview = null;
      renewalMaterialPreview = null;
      pendingHistoryReferenceFile = null;
      pendingHistoryReferenceGroup = "";
    }
    current = await api(`/api/runs/${id}`);
    tab = current.status === "STALE" || current.status === "DRAFT" || current.status === "FILES_READY" ? "materials" : (current.issue_groups || []).length ? "issues" : (current.generated_payroll || (current.mode === "GENERATE" && current.core_calculation?.rows?.length)) ? "payroll" : "materials";
    renderRun();
  } catch (error) { showMessage(error.message); }
}

function runSteps() {
  const steps = [["materials", "准备核算材料"], ["staff", "教师名单与归属"], ["issues", "待处理问题"], ["payroll", "工资预览与导出"]];
  const index = Math.max(0, steps.findIndex(([id]) => id === tab));
  const numbers = ["①", "②", "③", "④"];
  return `<div class="steps">${steps.map(([id, label], stepIndex) => `<span class="${stepIndex < index ? "done" : stepIndex === index ? "active" : ""}">${numbers[stepIndex]} ${label}</span>`).join("")}</div>`;
}

function navigation() {
  const todo = currentTodoSummary();
  const items = [["materials", "准备核算材料"], ["staff", "教师名单与归属"], ["issues", "待处理问题"], ["payroll", "工资预览与导出"]];
  const activeIndex = Math.max(0, items.findIndex(([id]) => id === tab));
  const back = activeIndex > 0 ? items[activeIndex - 1] : null;
  const next = activeIndex < items.length - 1 ? items[activeIndex + 1] : null;
  const currentLabel = items[activeIndex]?.[1] || "准备核算材料";
  const nextLabel = tab === "issues" ? "下一步：工资预览" : "下一步";
  return `<div class="flow-location" aria-live="polite"><strong>当前位置：${currentLabel}</strong><span>待处理 ${todo.pending} · 已处理 ${todo.processed} · 暂缓 ${todo.deferred}</span></div><div class="flow-footer"><button class="secondary" ${back ? `onclick="setTab('${back[0]}')"` : "disabled"}>上一步</button><button ${next ? `onclick="continueFlow('${next[0]}')"` : "disabled"}>${nextLabel}</button></div>`;
}

function groupHasPendingUserAction(group) {
  const decision = group?.decision || {};
  return !decision.status || decision.status === "NEEDS_RECONFIRMATION";
}

function actionKeyForCause(cause) {
  return ({
    base_salary_input: "salary-basis",
    renewal_result_source: "renewal-source",
    compensation_fee_policy: "af-policy",
    support_department_source: "support-source",
  })[cause] || `issue:${cause || "unknown"}`;
}

function currentTodoSummary() {
  const groups = current?.issue_groups || [];
  const pendingGroups = groups.filter(groupHasPendingUserAction);
  const pendingGroupIds = new Set(pendingGroups.map((item) => item.id));
  const pendingKeys = new Set();
  const representedGroups = new Set();
  for (const action of current?.user_actions || []) {
    const memberIds = (action.group_ids || []).filter((id) => pendingGroupIds.has(id));
    if (!memberIds.length) continue;
    memberIds.forEach((id) => representedGroups.add(id));
    pendingKeys.add(actionKeyForCause(action.cause));
  }
  for (const group of pendingGroups) {
    if (!representedGroups.has(group.id)) pendingKeys.add(`issue-group:${group.id}`);
  }

  if (gradeSupportSection(current?.grade_help)) pendingKeys.add("grade-help");
  if (current?.material_inputs?.renewal && !current.run_renewal_result_snapshot && !renewalMaterialPreview) pendingKeys.add("renewal-source");
  if (renewalMaterialPreview?.run_id === current?.id) pendingKeys.add("renewal-source");
  if (periodMismatchCard()) pendingKeys.add("period-month");
  if (coverageWarningCard()) pendingKeys.add("period-coverage");
  if (current?.period_check?.outside_authority) pendingKeys.add("period-authority-review");
  if (current?.period_authority?.is_fallback) pendingKeys.add("period-authority");
  if (current?.support_department_pending_preview?.status === "PENDING_CONFIRMATION") pendingKeys.add("support-source");
  for (const [key, item] of Object.entries(current?.pending_subject_group_imports || {})) {
    pendingKeys.add(`subject-group:${subjectGroupCandidateKey(item, key)}`);
  }
  const historyPending = current?.historical_salary_reference_pending_preview || {};
  if (historyPending.status === "PENDING_CONFIRMATION") pendingKeys.add(`history-membership:${historyPending.source_sha256 || historyPending.source_name || "pending"}`);
  if (pendingHistoryReferenceFile) pendingKeys.add("history-reference-group");
  const supportBound = Boolean(current?.support_source?.bound);
  const references = savedHistoricalSalaryReferences();
  if (!supportBound && historyPending.status !== "PENDING_CONFIRMATION") {
    for (const reference of references.filter((item) => !(item.use_confirmations || []).length)) {
      const group = reference.selected_group || reference.group_membership?.group || "";
      pendingKeys.add(`history-use:${reference.reference_id || `${reference.source_sha256 || ""}:${group}`}`);
    }
  }
  const unknownBasisCount = Number(current?.employment?.salary_basis_counts?.SOURCE_UNKNOWN || 0);
  const salaryBasisDeferred = Boolean(current?.base_salary_deferred);
  if (unknownBasisCount > 0 && !salaryBasisDeferred) pendingKeys.add("salary-basis");
  if (baseSalaryTodoCard()) pendingKeys.add("salary-basis");
  if (current?.mode === "GENERATE" && !current.af_policy_confirmation) pendingKeys.add("af-policy");

  const processedKeys = new Set();
  const deferredKeys = new Set();
  for (const decision of current?.business_decisions || []) {
    if (decision.status === "NEEDS_RECONFIRMATION") continue;
    const key = `issue-group:${decision.group_id || decision.root_cause_key || "unknown"}`;
    if (decision.status === "ACTIVE" && decision.action === "DEFERRED") deferredKeys.add(key);
    else if (decision.status === "ACTIVE") processedKeys.add(key);
  }
  for (const decision of current?.decisions || []) {
    const key = `legacy-issue:${decision.issue_id || decision.field || "unknown"}`;
    if (decision.action === "DEFERRED") deferredKeys.add(key);
    else if (decision.action) processedKeys.add(key);
  }
  if (current?.support_source?.bound) processedKeys.add("support-source");
  for (const material of current?.subject_group_materials || []) {
    if (material.status === "CONFIRMED" && !material.removed_at) processedKeys.add(`subject-group:${subjectGroupCandidateKey(material, material.material_id)}`);
  }
  for (const item of current?.subject_group_pending_history || []) {
    if (item.event === "CANCELLED" || item.event === "LEGACY_UNCONFIRMED_FILE_CANCELLED") deferredKeys.add(`subject-group:${subjectGroupCandidateKey(item, item.material_id || "candidate")}`);
  }
  if ((current?.support_department_pending_history || []).some((item) => item.event === "CANCELLED")) deferredKeys.add("support-source");
  for (const reference of references) {
    const group = reference.selected_group || reference.group_membership?.group || "";
    const key = `history-membership:${reference.reference_id || `${reference.source_sha256 || ""}:${group}`}`;
    if (reference.group_membership?.confirmed) processedKeys.add(key);
    if ((reference.use_confirmations || []).length) processedKeys.add(`history-use:${reference.reference_id || `${reference.source_sha256 || ""}:${group}`}`);
  }
  if (current?.historical_salary_reference_pending_history?.some((item) => item.event === "CANCELLED")) deferredKeys.add("history-membership:deferred");
  if (current?.run_renewal_result_snapshot) processedKeys.add("renewal-source");
  const salaryBasisTeachers = current?.employment?.teachers || [];
  const hasConfirmedSalaryBasis = salaryBasisTeachers.some((item) =>
    item.salary_basis && item.salary_basis !== "SOURCE_UNKNOWN" && item.salary_basis_source
  );
  if (!unknownBasisCount && !salaryBasisDeferred && (
    Object.keys(current?.salary_basis_confirmations || {}).length > 0
    || Boolean(current?.base_salary_input_snapshot)
    || hasConfirmedSalaryBasis
  )) processedKeys.add("salary-basis");
  if (salaryBasisDeferred) deferredKeys.add("salary-basis");
  if (current?.af_policy_confirmation) processedKeys.add("af-policy");
  if (["SWITCHED", "KEPT"].includes(current?.period_check?.decision)) processedKeys.add("period-month");
  if (current?.period_authority && !current.period_authority.is_fallback && (current.period_authority.source_file || current.period_authority.source_label || current.period_authority.boundary_source)) processedKeys.add("period-authority");
  if ((current?.period_window_history || []).length) processedKeys.add("period-coverage");
  for (const key of current?.ui_deferred_todo_keys || []) deferredKeys.add(key);

  // A single user-visible action can have several backend representations.
  // Keep its current state exclusive even if stale history also mentions it.
  for (const key of deferredKeys) {
    pendingKeys.delete(key);
    processedKeys.delete(key);
  }
  for (const key of pendingKeys) processedKeys.delete(key);

  return { pending: pendingKeys.size, processed: processedKeys.size, deferred: deferredKeys.size };
}

function continueFlow(nextTab) {
  if (nextTab === "payroll" && !(current.generated_payroll || current.core_calculation?.rows?.length)) return showMessage("请先点击开始核算。");
  if (nextTab === "issues" && !current.files?.schedule) return showMessage("请先在材料准备中导入当前人工月排课表。");
  setTab(nextTab);
}

function reconfirmationBanner(run) {
  const count = (run.business_decisions || []).filter(d => d.status === "NEEDS_RECONFIRMATION").length;
  return count ? `<div class="banner error"><strong>${count} 条人工决定需要重新确认</strong><span>依据已变化，原意见仅保留为历史记录，不再自动生效。更新材料并重新核对后，请重新判断。</span></div>` : "";
}

function renderRun() {
  if (current.operator_selection_required) {
    const heading = '<div class="run-title"><div><p class="eyebrow">历史核算流程升级</p><h1>旧流程记录</h1><div class="small muted">请选择处理角色后继续；此操作只保存流程信息，不会重新核算或改写历史工资结果。</div></div></div>';
    shell(`${heading}<section class="card"><div class="banner info"><strong>旧流程记录，请选择按 DOS 或学科组长继续。</strong><span>确认角色前不会进入新流程。</span></div><label>继续使用<select id="legacy-run-operator" onchange="toggleLegacyRunGroup()"><option value="">请选择角色</option><option value="DOS">DOS / 教学管理者（全教学部）</option><option value="SUBJECT_LEADER">学科组长（负责一个或多个科组）</option></select></label><div id="legacy-run-group-wrap" class="hidden"><strong>负责科组（可多选）</strong><div id="legacy-run-group" class="checkbox-list" style="display:flex;flex-wrap:wrap;gap:8px;margin:8px 0 14px">${payrollGroups.map((group) => `<label style="display:inline-flex;align-items:center;gap:7px;padding:7px 10px;border:1px solid #dfe3e8;border-radius:7px;background:#fff;font-weight:500"><input type="checkbox" value="${group}" data-legacy-run-group style="width:auto;margin:0"> ${group}</label>`).join("")}</div></div><label>确认人<input id="legacy-run-confirmed-by" placeholder="填写确认人姓名"></label><div class="action-bar"><button onclick="saveLegacyRunOperator()">保存角色并继续</button><span class="small muted">现有历史结果保留；需由你之后主动点击“开始核算”才会生成新范围结果。</span></div></section>`);
    return;
  }
  const stale = reconfirmationBanner(current) + (current.status === "STALE" ? '<div class="banner error"><strong>原始文件已发生变化</strong><span>请重新选择标记为“已变化”的材料，再重新核对。旧结果不会继续显示为有效。</span></div>' : "");
  const lastError = current.last_error ? `<div class="banner error"><strong>上次核对未完成</strong><span>${escapeHtml(current.last_error)}</span></div>` : "";
  const roleRecheck = runNeedsRecalculation(current) ? `<div class="banner warn"><strong>工资结果需要重新核算</strong><span>${escapeHtml(current.recalculation_required_reason || "人员范围或工资基础已变化")}；旧结果已保留为历史记录，不会自动重算。请确认材料后主动点击“开始核算”。</span></div>` : "";
    const authority = current.period_authority || {};
    const sourceText = authority.source_file || authority.source?.source_file || authority.source_label || "自然月兜底（尚无人工月资料）";
    const roleLabel = (current.operator_role || "DOS") === "SUBJECT_LEADER" ? `学科组长 · ${escapeHtml(runGroupsLabel(current, "待选科组"))}` : "DOS / 教学管理者 · 全教学部";
    const periodBanner = `<div class="banner info"><strong>工资月份：${escapeHtml(current.period_label || current.period)}</strong><span>人工月：${escapeHtml(current.period_start || "—")} ～ ${escapeHtml(current.period_end || "—")} · 来源：${escapeHtml(sourceText)}</span></div>`;
    const monthControl = `<div class="run-period-control"><label class="small muted">更改工资月份<input id="run-period-select" type="month" value="${escapeHtml(current.period)}"></label><button class="secondary" onclick="changeRunPeriod()">更改月份</button></div>`;
    shell(`<div class="run-title"><div><p class="eyebrow">${escapeHtml(roleLabel)} · 工资月份 ${escapeHtml(current.period_label || current.period)}</p><h1>工资核算</h1><div class="small muted">人工月 ${escapeHtml(current.period_start || "—")} ～ ${escapeHtml(current.period_end || "—")} · 来源：${escapeHtml(sourceText)} · 记录编号 ${escapeHtml(current.id)}</div></div><div class="run-title-actions">${statusBadge(current)}${monthControl}</div></div>${periodBanner}${runSteps()}${stale}${lastError}${roleRecheck}${authoritySummary()}${navigation()}<section id="view"></section>`);
  renderTab();
}

function toggleLegacyRunGroup() {
  const visible = $("#legacy-run-operator")?.value === "SUBJECT_LEADER";
  $("#legacy-run-group-wrap")?.classList.toggle("hidden", !visible);
}

async function saveLegacyRunOperator() {
  const role = $("#legacy-run-operator")?.value || "";
  const selectedGroups = checkedGroups("legacy-run-group");
  const group = selectedGroups.length === 1 ? selectedGroups[0] : "";
  const actor = $("#legacy-run-confirmed-by")?.value?.trim() || "";
  if (!role) return showMessage("请选择按 DOS 或学科组长继续。", "error");
  if (role === "SUBJECT_LEADER" && !selectedGroups.length) return showMessage("请至少选择负责科组（可多选）。", "error");
  if (!actor) return showMessage("请填写确认人。", "error");
  try {
    current = await api(`/api/runs/${current.id}/operator-role`, { method: "POST", body: JSON.stringify({ operator_role: role, selected_groups: role === "SUBJECT_LEADER" ? selectedGroups : [], selected_group: group, confirmed_by: actor }) });
    tab = "materials";
    renderRun();
    showMessage("已保存新的流程角色元数据；没有重新核算，也没有改写历史工资结果。", "success");
  } catch (error) { showMessage(error.message); }
}

async function changeRunPeriod() {
  const period = $("#run-period-select")?.value || "";
  if (!period) return showMessage("请选择工资月份。", "error");
  const release = markBusy("正在切换工资月份…");
  try {
    current = await api(`/api/runs/${current.id}/period`, { method: "POST", body: JSON.stringify({ period }) });
    baseSalaryImportPreview = null;
    renewalMaterialPreview = null;
    supportImportPreview = null;
    pendingHistoryReferenceFile = null;
    pendingHistoryReferenceGroup = "";
    tab = "materials";
    renderRun();
    showMessage(`已切换到 ${current.period}。人工月和来源已按该月份 authority 重新绑定。`, "success");
  } catch (error) { await refreshAfterError(error); }
  finally { release(); }
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
  return `<details class="authority-summary"><summary>当前核对依据</summary><div class="facts">${fact("schedule", "排课权威源")}${fact("rating", "星级权威版本")}${fact("policy", "教师政策版本")}${fact("rules", legacyRuleLabel)}${extra}</div><div class="action-bar"><span class="muted small">发现基础资料录入错误时，请创建修正版；旧版本与历史核算会继续保留。</span><button class="secondary" onclick="authorityDashboard('${current.id}')">查看、修正或改用版本</button></div></details>`;
}

function setTab(next) {
  if (next === "overview") next = "issues";
  if (next === "base-salary") next = "materials";
  tab = next;
  renderRun();
}
function renderTab() {
  const view = $("#view");
  if (tab === "materials") view.innerHTML = materialsPage();
  if (tab === "materials") bindMaterialDropZones();
  if (tab === "staff") view.innerHTML = teacherScopePage();
  if (tab === "base-salary") { tab = "materials"; view.innerHTML = materialsPage(); bindMaterialDropZones(); }
  if (tab === "overview") { tab = "issues"; view.innerHTML = issuesPage(); }
  if (tab === "issues") view.innerHTML = issuesPage();
  if (tab === "payroll") {
    view.innerHTML = payrollPreviewPage();
    const advisories = current.source_formula_advisories || [];
    if (advisories.length) {
      const details = document.createElement("details");
      details.className = "card source-formula-advisory";
      details.innerHTML = `<summary>来源工资表有 ${escapeHtml(advisories.length)} 处公式异常（不影响系统按当前核算生成）</summary><p class="small muted">这些位置属于导入的提交表。生成工资表会使用当前 Core 结果，并单独验证最终导出的 Excel。</p><ul>${advisories.map((item) => `<li>${escapeHtml(item.sheet)} · ${escapeHtml(item.cell)} · ${escapeHtml(item.status)}</li>`).join("")}</ul>`;
      view.appendChild(details);
    }
  }
  if (tab === "management") view.innerHTML = managementPage();
  if (tab === "reconciliation") {
    view.innerHTML = '<section class="card"><h2>历史工资对账</h2><p class="muted">正在读取历史工资表与当前核心计算的逐教师差异……</p></section>';
    loadHistoricalReconciliation();
  }
}

function baseSalaryImportMarkup() {
  const preview = baseSalaryImportPreview?.run_id === current?.id ? baseSalaryImportPreview : null;
  const runRows = current.core_calculation?.rows || current.generated_payroll?.rows || [];
  const namesById = new Map(runRows.map((row) => [String(row.teacher_id || row.teacher), row.teacher]));
  const issueNames = {
    UNMATCHED_TEACHER_ID: "教师编号未匹配", UNMATCHED_TEACHER_NAME: "教师姓名未匹配",
    AMBIGUOUS_TEACHER_NAME: "同名教师无法消歧", DUPLICATE_SOURCE_TEACHER: "来源中教师重复",
    MISSING_REQUIRED_COLUMNS: "缺少 G～L 必需列", AMBIGUOUS_SHEET_LAYOUT: "发现多个可能的工资表区域",
    FORMULA_CACHE_MISSING: "公式没有可用的计算结果", INVALID_REQUIRED_VALUE: "必需单元格为空或不是数字",
    MISSING_TEACHER_IDENTIFIER: "来源行缺教师身份", UNREADABLE_WORKBOOK: "文件无法读取",
  };
  // Structural problems block an import; a teacher who is simply not part of
  // this month's calculation is a scope fact, not an error, so the two are
  // listed separately instead of both reading as "unrecognised".
  const issues = [...(preview?.errors || []), ...(preview?.conflicts || [])];
  const issueMarkup = issues.length ? `<div class="warning-list"><strong>导入前要核实</strong>${issues.map((item) => `<p>${escapeHtml(issueNames[item.code] || item.code)}${item.sheet ? ` · ${escapeHtml(item.sheet)}` : ""}${item.source_row ? ` 第 ${escapeHtml(item.source_row)} 行` : ""}${item.field ? ` · ${escapeHtml(item.field)}` : ""}</p>`).join("")}</div>` : "";
  const matchedRows = (preview?.rows || []).map((row) => `<tr><td>${escapeHtml(namesById.get(String(row.teacher_id)) || row.teacher_id)}</td>${["G", "H", "I", "J", "K", "L"].map((code) => `<td>${escapeHtml(row.fields?.[code] ?? "待确认")}</td>`).join("")}</tr>`).join("");
  const counts = preview?.counts || {};
  const roster = preview?.roster || {};
  const countParams = (preview?.counts || preview?.roster) ? `<div class="table-wrap"><table class="table"><thead><tr><th>来源资料教师</th><th>当前核算教师</th><th>自动匹配</th><th>本月教师缺历史资料</th><th>历史资料有、本月未核算</th><th>需要确认身份</th></tr></thead><tbody><tr><td>${escapeHtml(counts.source_teachers ?? "—")}</td><td>${escapeHtml(counts.current_run_teachers ?? "—")}</td><td>${escapeHtml(counts.matched ?? "—")}</td><td>${escapeHtml(counts.month_without_history ?? "—")}</td><td>${escapeHtml(counts.history_only ?? "—")}</td><td>${escapeHtml(counts.identity_required ?? "—")}</td></tr></tbody></table></div><p class="small muted">匹配名单：${escapeHtml(roster.origin_label || "当前核算教师")}（${escapeHtml(roster.member_count ?? "—")} 人）。${escapeHtml(roster.note || "")}</p>` : "";
  const monthMissing = (preview?.month_without_history || []).map((item) => item.teacher).filter(Boolean);
  const historyOnly = preview?.history_only || [];
  const missingReferenceList = monthMissing.length ? `<details><summary>历史资料尚未覆盖 ${escapeHtml(monthMissing.length)} 位教师</summary><p class="small muted">${escapeHtml(monthMissing.join("、"))}</p></details>` : "";
  const scopeNote = historyOnly.length ? `<details><summary>历史资料里有、但本月未参与核算的 ${escapeHtml(historyOnly.length)} 人</summary><p class="small muted">${escapeHtml(historyOnly.map((item) => item.teacher).filter(Boolean).join("、"))}</p><p class="small muted">这些人不是“无法识别”，而是本月还没有他们的核算记录（例如本月学科组提交表里没有他们）。</p></details>` : "";
  const isSupportPreview = preview?.source_type === "SUPPORT_DEPARTMENT_PAYROLL_SOURCE";
  const confirmationLabel = isSupportPreview ? "确认本月支持部工资资料" : "保存为历史参考（不生效）";
  const membership = preview?.group_membership_preview || {};
  const primaryMarkup = (membership.primary_members || []).length ? `<div class="banner info"><strong>按主学科自动归组：${escapeHtml((membership.primary_members || []).length)} 人</strong><span>${(membership.primary_members || []).map((item) => escapeHtml(item.teacher)).join("、")}</span></div>` : "";
  const secondaryMarkup = (membership.secondary_candidates || []).length ? `<details><summary>待确认的小学科/归属不明教师 ${membership.secondary_candidates.length} 位</summary><p>${(membership.secondary_candidates || []).map((item) => `${escapeHtml(item.teacher)}${item.subjects?.length ? `（${escapeHtml(item.subjects.join("、"))}）` : ""}`).join("、")}</p><p class="small muted">请在“待处理问题”中逐一确认是否属于本组。</p></details>` : "";
  const groupMembershipMarkup = !isSupportPreview && preview ? `${primaryMarkup}${secondaryMarkup}${(membership.other_group_candidates || []).length ? `<details><summary>排课主科属于其他科组 ${membership.other_group_candidates.length} 人</summary><p>${membership.other_group_candidates.map((item) => `${escapeHtml(item.teacher)}：${escapeHtml(item.suggested_group)}`).join("、")}</p></details>` : ""}` : "";
  const review = preview ? `<div class="base-import-review"><p class="small">历史工资参考 ${escapeHtml(preview.source_people?.length || preview.rows?.length || 0)} 人；当前人工月排课仍决定本月工资名单，参考文件不会扩大 roster。</p>${issueMarkup}${groupMembershipMarkup}${matchedRows ? `<div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>基本工资</th><th>岗位津贴</th><th>工龄/等级</th><th>其他待遇</th><th>应出勤</th><th>实际出勤</th></tr></thead><tbody>${matchedRows}</tbody></table></div>` : ""}<div class="action-bar"><span class="small muted">${isSupportPreview ? "支持部资料确认后才成为本月正式来源。" : "历史工资仅保存为参考；科组成员确认请在待处理问题页完成。"}</span>${preview.can_import ? `<button onclick="setTab('issues')">去待处理问题确认</button>` : '<span class="warn">来源仍有冲突，不能保存。</span>'}</div></div>` : "";
  const groups = selectedRunGroups(current);
  const selectedGroup = groups.length === 1 ? groups[0] : "";
  const groupOptions = current.operator_role === "SUBJECT_LEADER" ? groups : payrollGroups;
  return `<section id="base-salary-import" class="base-import-card"><h3>工资资料</h3><p class="muted">本月工资资料是正式权威来源，优先级最高。历史工资参考可提供教师身份、科组与 G～L 参考，但不自动带入上月续费、退费、激励、课时费或最终工资。</p><label for="history-reference-group">历史参考所属科组<select id="history-reference-group"><option value="">请选择科组</option>${groupOptions.map((group) => `<option value="${group}" ${selectedGroup === group ? "selected" : ""}>${group}</option>`).join("")}</select></label><div class="base-import-actions"><button type="button" onclick="$('#support-salary-file').click()">导入本月工资资料</button><button type="button" class="secondary" onclick="$('#base-salary-history-file').click()">导入历史工资参考</button><span class="small muted">预览后确认；历史组籍选择会保留来源证据。</span><input id="support-salary-file" class="sr-only" type="file" accept=".xls,.xlsx,.xlsm" onchange="previewSupportFile(event)"><input id="base-salary-history-file" class="sr-only" type="file" accept=".xls,.xlsx,.xlsm" onchange="previewBaseSalaryFile(event)"></div><div id="base-salary-import-status" role="status" aria-live="polite" class="small muted"></div>${review}</section>`;
}

// 用工性质：全职 / 兼职 是人的长期事实，不是每月重填的选项。
// 兼职教师按课时计酬，不适用全职基本工资，所以不会出现在“缺 G～L”的待办里。
function partTimePayCard(partTime) {
  if (!partTime.length) return "";
  const decisions = current.part_time_pay_decisions || {};
  const standardProfiles = current.run_policy_snapshot?.part_time_rates || [];
  const standardSource = current.authority_context?.part_time_rates?.source || "";
  const standardNote = standardProfiles.length
    ? `本次核算绑定了 ${standardProfiles.length} 条兼职标准；系统按教师和课程条件匹配。`
    : "当前知识库没有兼职费率条款，本次核算也没有适用的标准版本。公司标准选项会保持待确认，不会套用上月或写死单价。";
  const rows = partTime.map((person) => {
    const decision = decisions[person.teacher] || {};
    const kind = decision.manual_kind || "TOTAL";
    const status = decision.status === "DEFERRED" ? "暂时留白，待补充" : decision.status === "WAITING_FOR_AUTHORITY" ? "待公司标准来源" : decision.status === "CONFIRMED" ? "已保存" : "尚未选择";
    return `<tr class="part-time-pay-row" data-teacher="${escapeHtml(person.teacher)}"><td><strong>${escapeHtml(person.teacher)}</strong><div class="small muted">${escapeHtml(status)}</div></td><td><select class="part-time-method"><option value="" ${!decision.method ? "selected" : ""}>请选择</option><option value="COMPANY_STANDARD" ${decision.method === "COMPANY_STANDARD" ? "selected" : ""}>按公司标准自动计算</option><option value="MANUAL" ${decision.method === "MANUAL" ? "selected" : ""}>手动填写</option><option value="DEFERRED" ${decision.method === "DEFERRED" ? "selected" : ""}>暂时留白</option></select><select class="part-time-manual-kind"><option value="TOTAL" ${kind === "TOTAL" ? "selected" : ""}>填写本月工资总额</option><option value="UNIT_RATE" ${kind === "UNIT_RATE" ? "selected" : ""}>填写每节单价</option></select></td><td><input class="part-time-pay-amount" type="number" min="0" step="0.01" value="${escapeHtml(decision.amount ?? "")}" placeholder="${kind === "UNIT_RATE" ? "元/节" : "元"}"></td><td><input class="part-time-pay-reason" value="${escapeHtml(decision.reason || "")}" placeholder="填写依据；暂时留白可默认说明"></td><td><span class="small muted">${escapeHtml(decision.source || standardSource || "—")}</span><button type="button" onclick="savePartTimePayDecision('${escapeHtml(person.teacher)}')">保存本月方式</button></td></tr>`;
  }).join("");
  return `<section id="part-time-pay-card" class="card part-time-pay-card"><div class="section-head"><div><h3>本月兼职工资</h3><p class="muted">每位教师选一种方式；兼职身份会跨月沿用，工资金额按本月决定。</p></div></div><div class="banner ${standardProfiles.length ? "info" : "warning"}"><strong>公司标准</strong><span>${escapeHtml(standardNote)}</span></div><label class="person-field">确认人<input id="part-time-pay-confirmed-by" value="${escapeHtml(current.part_time_pay_decisions?.[partTime[0].teacher]?.confirmed_by || current.support_source?.confirmed_by || current.af_policy_confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>处理方式</th><th>金额 / 单价</th><th>本次依据</th><th>来源 / 操作</th></tr></thead><tbody>${rows}</tbody></table></div><p class="small muted">手动填写可选择本月总额或每节单价；暂时留白会保持待补充，不按 0 计算。</p></section>`;
}

function employmentCard() {
  const employment = current.employment || {};
  const counts = employment.counts || {};
  if (!counts.total) return "";
  const people = employment.teachers || [];
  const editableGroups = current.operator_role === "SUBJECT_LEADER" ? selectedRunGroups(current) : payrollGroups;
  const groupCounts = employment.group_counts || {};
  const rows = people.map((item) => {
    const groupStatus = item.teacher_group_status || "NEEDS_CONFIRMATION";
    const initialGroup = groupStatus === "CONFIRMED" ? (item.teacher_group || "") : "";
    const groupLabel = groupStatus === "CONFIRMED" ? "已确认" : groupStatus === "SUGGESTED" ? `候选：${item.teacher_group}` : "待确认";
    const basis = item.salary_basis || "SOURCE_UNKNOWN";
    const basisLabel = basis === "HAS_BASE_SALARY" ? "有底薪" : basis === "HOURLY_SUBMISSION_ONLY" ? "明确无底薪 · 组表提供结果" : "资料未知";
    return `<tr class="staff-roster-row" data-teacher="${escapeHtml(item.teacher)}" data-teacher-id="${escapeHtml(item.teacher_id || item.teacher)}" data-group-initial="${escapeHtml(initialGroup)}" data-group-status="${escapeHtml(groupStatus)}" data-group-suggestion="${escapeHtml(item.teacher_group || "")}"><td><strong>${escapeHtml(item.teacher)}</strong><div class="small muted">${escapeHtml((item.subjects || []).join("、") || item.detail || "")}</div></td><td><select class="staff-group" aria-label="${escapeHtml(item.teacher)}归属学科组"><option value="">${escapeHtml(groupLabel)}</option>${editableGroups.map((group) => `<option value="${group}" ${initialGroup === group ? "selected" : ""}>${group}</option>`).join("")}</select><div class="small muted">${escapeHtml(item.teacher_group_source || "")}</div></td><td><span class="status ${basis === "SOURCE_UNKNOWN" ? "warn" : basis === "HAS_BASE_SALARY" ? "ok" : "info"}">${escapeHtml(basisLabel)}</span><div class="small muted">${escapeHtml(item.salary_basis_source || item.teacher_group_source || "")}</div></td><td><span class="small muted">${escapeHtml(item.salary_basis_reason || item.detail || "")}</span></td></tr>`;
  }).join("");
  const unconfirmedGroups = employment.group_needs_confirmation?.length || 0;
  const scope = current.processing_scope || {};
  const basisCounts = employment.salary_basis_counts || {};
  const scopeGroupsLabel = (scope.selected_groups || selectedRunGroups(current)).join("、");
  return `<section id="staff-batch-card" class="card"><div class="section-head"><div><p class="eyebrow">教师名单与归属</p><h2>${scope.operator_role === "SUBJECT_LEADER" ? escapeHtml(scopeGroupsLabel || "本组") : "全教学部"}处理范围</h2><p class="muted">排课事实名单仍保持全人工月 Roster；本页只展示当前角色需要处理的人员。组长范围由历史组籍、历史参考和本组提交资料的确认成员组成。</p></div><span class="status ${(unconfirmedGroups || basisCounts.SOURCE_UNKNOWN) ? "warn" : "ok"}">${unconfirmedGroups || basisCounts.SOURCE_UNKNOWN ? `待确认：归组 ${unconfirmedGroups} 位 · 工资基础 ${basisCounts.SOURCE_UNKNOWN || 0} 位` : "当前范围已确认"}</span></div><div class="metric-grid"><div class="metric"><span>全排课 Roster</span><strong>${escapeHtml(scope.canonical_roster_count ?? current.roster_facts?.member_count ?? counts.total ?? people.length)}</strong><small>不被组长视图改写</small></div><div class="metric"><span>本次处理人数</span><strong>${escapeHtml(scope.scope_count ?? people.length)}</strong><small>${scope.operator_role === "SUBJECT_LEADER" ? escapeHtml(scopeGroupsLabel || "所选组") : "全教学部"}</small></div><div class="metric"><span>按课时人员</span><strong>${escapeHtml(basisCounts.HOURLY_SUBMISSION_ONLY || 0)}</strong><small>金额只读取本组提交结果</small></div></div><div class="staff-group-counts">${Object.entries(groupCounts).map(([name, count]) => `<span>${escapeHtml(name)} <strong>${escapeHtml(count)}</strong></span>`).join("")}</div><div class="staff-bulk-actions"><button type="button" class="secondary" onclick="applySuggestedStaffGroups()">采用所有明确的学科建议</button><button type="button" class="secondary" onclick="markUnknownSalaryBasis()">把未知状态保持待确认</button></div>${(scope.outside_roster || []).length ? `<details><summary>参考/提交资料中有但不在本月排课 Roster 的 ${scope.outside_roster.length} 人（不进入本月工资）</summary><p>${scope.outside_roster.map((item) => `${escapeHtml(item.teacher || "教师")}：${escapeHtml(item.reason || "")}`).join("；")}</p></details>` : ""}<label class="person-field">本次确认人<input id="staff-batch-confirmed-by" value="${escapeHtml(current.support_source?.confirmed_by || current.base_salary_input_snapshot?.confirmed_by || "")}" placeholder="填写确认人姓名"></label><div class="table-wrap staff-roster-wrap"><table class="table staff-roster-table"><thead><tr><th>教师</th><th>长期归属科组</th><th>工资基础</th><th>当前依据</th></tr></thead><tbody>${rows}</tbody></table></div><div class="action-bar"><span class="small muted">“资料未知”不等于兼职；明确无底薪只代表工资金额由组内提交结果提供，本系统不计算兼职工资。</span><button onclick="confirmStaffBatch()">保存批量确认</button></div></section>`;
}

function applySuggestedStaffGroups() {
  document.querySelectorAll(".staff-roster-row[data-group-status='SUGGESTED']").forEach((row) => {
    const suggestion = row.dataset.groupSuggestion || "";
    if (suggestion) row.querySelector(".staff-group").value = suggestion;
  });
}

function markUnknownSalaryBasis() {
  showMessage("未确认的工资基础继续保持“资料未知”；缺资料不会自动判定为兼职或按课时。", "info");
}

function teacherScopePage() {
  const scope = current.processing_scope || {};
  const group = scope.operator_role === "SUBJECT_LEADER" ? ((scope.selected_groups || selectedRunGroups(current)).join("、") || "所选科组") : "全教学部";
  const outside = scope.outside_roster || [];
  const people = current.employment?.teachers || [];
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 2 步</p><h2>教师名单与归属 · ${escapeHtml(group)}</h2><p class="muted">${scope.operator_role === "SUBJECT_LEADER" ? "本页只列本组处理范围；其它组教师不会生成缺资料问题。" : "DOS 对当前人工月排课中的全教学部教师负责。"}</p></div><span class="status info">本次处理 ${escapeHtml(scope.scope_count ?? people.length)} 人</span></div><div class="metric-grid"><div class="metric"><span>全排课 Roster</span><strong>${escapeHtml(scope.canonical_roster_count ?? current.roster_facts?.member_count ?? 0)}</strong><small>事实名单保持全教学部</small></div><div class="metric"><span>本次处理范围</span><strong>${escapeHtml(scope.scope_count ?? people.length)}</strong><small>${escapeHtml(group)}</small></div><div class="metric"><span>明确按课时</span><strong>${escapeHtml(current.employment?.salary_basis_counts?.HOURLY_SUBMISSION_ONLY || 0)}</strong><small>系统只读取组表结果</small></div></div>${outside.length ? `<details><summary>资料里有但不在本月排课 Roster 的 ${outside.length} 人（不新增工资行）</summary><p>${outside.map((item) => `${escapeHtml(item.teacher || "教师")}：${escapeHtml(item.reason || "")}`).join("；")}</p></details>` : ""}</section>${employmentCard() || '<section class="card"><div class="empty">请先准备人工月排课表。</div></section>'}`;
}

async function confirmStaffBatch() {
  const confirmedBy = $("#staff-batch-confirmed-by")?.value?.trim() || "";
  if (!confirmedBy) return showMessage("请填写人员资料批量确认人。");
  const employment_updates = [];
  const group_updates = [];
  document.querySelectorAll(".staff-roster-row").forEach((row) => {
    const group = row.querySelector(".staff-group")?.value || "";
    if (group && (row.dataset.groupStatus !== "CONFIRMED" || group !== row.dataset.groupInitial)) {
      group_updates.push({ teacher_id: row.dataset.teacherId, teacher: row.dataset.teacher, group, reason: "负责人在月度工资收口中确认长期归属科组。" });
    }
  });
  if (!employment_updates.length && !group_updates.length) return showMessage("没有新的归组确认或修改。", "info");
  try {
    const result = await api(`/api/runs/${current.id}/staff-batch`, { method: "POST", body: JSON.stringify({ confirmed_by: confirmedBy, employment_updates, group_updates }) });
    current = result.run;
    renderRun();
    showMessage(`已一次保存 ${result.groups_confirmed} 位教师归组。`, "success");
  } catch (error) { await refreshAfterError(error); }
}

async function saveEmploymentProfile(teacher) {
  const row = document.querySelector(`.employment-row[data-teacher="${CSS.escape(teacher)}"]`);
  const person = $("#employment-confirmed-by")?.value?.trim() || current.base_salary_input_snapshot?.confirmed_by || "";
  if (!person) {
    $("#employment-confirmed-by")?.focus();
    return showMessage("请填写用工性质确认人。");
  }
  try {
    await api(`/api/runs/${current.id}/employment`, { method: "POST", body: JSON.stringify({
      teacher,
      employment_type: row?.querySelector(".employment-type")?.value || "FULL_TIME",
      reason: row?.querySelector(".employment-reason")?.value?.trim() || "",
      confirmed_by: person,
    }) });
    current = await api(`/api/runs/${current.id}`);
    renderRun();
    showMessage(`已保存 ${teacher} 的用工性质；该教师以后各月沿用。`, "success");
  } catch (error) { showMessage(error.message); }
}

async function savePartTimePayDecision(teacher) {
  const row = [...document.querySelectorAll(".part-time-pay-row")].find((item) => item.dataset.teacher === teacher);
  if (!row) return showMessage("找不到这位兼职教师的本月工资行。", "error");
  const method = row.querySelector(".part-time-method")?.value || "";
  const manualKind = row.querySelector(".part-time-manual-kind")?.value || "TOTAL";
  const rawAmount = row.querySelector(".part-time-pay-amount")?.value;
  const confirmedBy = $("#part-time-pay-confirmed-by")?.value?.trim() || "";
  if (!method) return showMessage("请选择公司标准、手动填写或暂时留白。", "error");
  if (!confirmedBy) {
    $("#part-time-pay-confirmed-by")?.focus();
    return showMessage("请填写本次兼职工资确认人。", "error");
  }
  if (method === "MANUAL" && (rawAmount === "" || !Number.isFinite(Number(rawAmount)))) {
    row.querySelector(".part-time-pay-amount")?.focus();
    return showMessage(manualKind === "UNIT_RATE" ? "请填写本月兼职每节单价。" : "请填写本月兼职工资总额。", "error");
  }
  try {
    current = await api(`/api/runs/${current.id}/part-time-pay-decision`, {
      method: "POST",
      body: JSON.stringify({
        teacher_id: teacher,
        method,
        confirmed_by: confirmedBy,
        amount: method === "MANUAL" ? Number(rawAmount) : null,
        manual_kind: manualKind,
        reason: row.querySelector(".part-time-pay-reason")?.value?.trim() || "",
      }),
    });
    renderRun();
    const saved = current.part_time_pay_decisions?.[teacher] || {};
    showMessage(saved.status === "WAITING_FOR_AUTHORITY"
      ? "已记录公司标准选项；当前没有该教师本月适用的权威费率，工资保持待确认。"
      : saved.status === "DEFERRED"
        ? "已记录暂时留白；本月兼职工资保持空白，不按 0 计算。"
        : "本月兼职工资方式已保存，并已重新核算。", saved.status === "CONFIRMED" || saved.status === "DEFERRED" ? "success" : "info");
  } catch (error) { await refreshAfterError(error); }
}

function supportMaterialCard() {
  const source = current.support_source || {};
  const pending = current.support_department_pending_preview || {};
  const preview = supportImportPreview?.run_id === current?.id ? supportImportPreview : null;
  const waiting = Boolean(preview || pending.status === "PENDING_CONFIRMATION");
  const state = waiting ? "已识别 · 待确认" : source.bound ? "已确认" : "未提供";
  const stateClass = waiting ? "warn" : source.bound ? "ok" : "muted";
  const fileName = preview?.source_name || supportImportName || pending.source_name || source.source_name || "";
  const sheet = preview?.sheet || pending.source_sheet || source.source_sheet || "";
  const teacherCount = preview?.counts?.matched ?? preview?.rows?.length ?? pending.matched_count ?? source.entries ?? 0;
  const commentCount = preview?.counts?.source_comment_count ?? pending.comment_count ?? source.comment_count ?? 0;
  const fieldRows = (source.field_map || []).filter((item) => item.business_name).map((item) => `<tr><td>${escapeHtml(item.business_name)}</td><td>${escapeHtml(item.final_field)}</td><td>${escapeHtml(item.source_column || "—")}</td><td>${item.inherited ? "沿用" : "不沿用"}</td></tr>`).join("");
  const previewSummary = waiting ? `<div class="support-preview-summary"><p><strong>${escapeHtml(fileName || "支持部工资资料候选")}</strong></p><div class="facts"><span>工作表：${escapeHtml(sheet || "待识别")}</span><span>匹配教师：${escapeHtml(teacherCount)}</span><span>源批注：${escapeHtml(commentCount)}</span><span>文件标识：${escapeHtml(String(preview?.source?.sha256 || pending.source_sha256 || "").slice(0, 10))}</span></div>${source.bound ? '<p class="small warn">当前已确认版本继续生效；候选版本确认前不会替换。</p>' : ""}<p class="small muted">预览只读；确认、替换或暂缓请到“待处理问题”完成。</p><button class="secondary" onclick="setTab('issues')">去待处理问题</button></div>` : "";
  const boundDetails = source.bound ? `<details class="support-source-details"><summary>查看已确认资料与字段范围</summary><p class="small muted">文件：${escapeHtml(source.source_name || "—")} · 工作表：${escapeHtml(source.source_sheet || "—")} · 教师覆盖：${escapeHtml(source.entries || 0)} 人 · 批注：${escapeHtml(source.comment_count ?? 0)} 条 · 确认人：${escapeHtml(source.confirmed_by || "—")}</p>${fieldRows ? `<div class="table-wrap"><table class="table"><thead><tr><th>工资项目</th><th>字段</th><th>来源列</th><th>采用情况</th></tr></thead><tbody>${fieldRows}</tbody></table></div>` : ""}</details>` : "";
  const remove = source.bound || pending.status === "PENDING_CONFIRMATION" ? `<label class="person-field">本次移除确认人<input id="support-remove-confirmed-by" value="" placeholder="填写确认人姓名"></label><button class="quiet danger-link" onclick="removeSupportSource()">${source.bound ? "从本次核算移除" : "取消这份待确认资料"}</button>` : "";
  return `<section id="support-material-card" class="salary-source-panel support-material-card"><div class="material-top"><strong>本月工资资料（权威）</strong><span class="status ${stateClass}">${state}</span></div><p class="small muted">来源：支持部提供。本月正式工资基础资料优先级最高；一张表可提供 G～L、身份及支持部项目。</p>${source.bound ? `<div class="facts"><span>文件：${escapeHtml(source.source_name || "—")}</span><span>工作表：${escapeHtml(source.source_sheet || "—")}</span><span>教师：${escapeHtml(source.entries || 0)} 人</span><span>批注：${escapeHtml(source.comment_count ?? 0)} 条</span><span>确认人：${escapeHtml(source.confirmed_by || "—")}</span></div>${boundDetails}` : '<div class="empty compact">本次还没有已确认的本月工资资料。</div>'}${previewSummary}<div data-drop-role="support" tabindex="0" role="button" aria-label="拖入本月工资资料" class="drop-zone">${waiting ? "可拖入另一版本重新预览" : source.bound ? "拖入新版本，预览后再确认替换" : "拖入 Excel 文件，或选择文件预览"}</div><input id="support-material-file" class="sr-only" type="file" accept=".xls,.xlsx,.xlsm" onchange="previewSupportFile(event)"><div class="action-bar"><button class="secondary" onclick="document.querySelector('#support-material-file').click()">${source.bound ? "更换本月工资资料" : "导入本月工资资料"}</button>${remove}</div><div id="support-material-import-status" role="status" aria-live="polite" class="small muted"></div></section>`;
}

function cancelSupportPreview() {
  supportImportPreview = null;
  supportImportPath = "";
  supportImportName = "";
  baseSalaryImportPreview = null;
  renderRun();
}

async function openHistoricalImport() {
  document.querySelector("#base-salary-history-file")?.click();
}

function stageHistoricalReferenceFile(file) {
  if (!file) return;
  pendingHistoryReferenceFile = file;
  const groups = selectedRunGroups(current);
  pendingHistoryReferenceGroup = groups.length === 1 ? groups[0] : "";
  baseSalaryImportPreview = null;
  renderRun();
  showMessage("已选择历史工资文件；请确认所属科组后继续识别。", "info");
}

function setPendingHistoricalReferenceGroup(group) {
  pendingHistoryReferenceGroup = String(group || "").trim();
}

function cancelStagedHistoricalReference() {
  pendingHistoryReferenceFile = null;
  pendingHistoryReferenceGroup = "";
  const input = document.querySelector("#base-salary-history-file");
  if (input) input.value = "";
  renderRun();
}

async function previewStagedHistoricalReference() {
  if (!pendingHistoryReferenceFile) return showMessage("请先选择历史工资文件。", "error");
  if (!pendingHistoryReferenceGroup) return showMessage("请选择这份历史工资资料所属的科组。", "error");
  const file = pendingHistoryReferenceFile;
  const group = pendingHistoryReferenceGroup;
  await previewBaseSalaryFileObject(file, group);
}

async function removeSupportSource() {
  const actor = $("#support-remove-confirmed-by")?.value?.trim() || "";
  if (!actor) return showMessage("请填写确认人后再移除本次绑定。");
  if (!window.confirm("只会从当前工资核算移除支持部资料绑定；不会删除电脑上的原文件。确定继续吗？")) return;
  try {
    current = await api(`/api/runs/${current.id}/support-remove`, { method: "POST", body: JSON.stringify({ confirmed_by: actor }) });
    supportImportPreview = null;
    renderRun();
    showMessage("已从本次核算移除支持部资料；原文件未删除。", "success");
  } catch (error) { await refreshAfterError(error); }
}

function supportSourceCard() {
  const source = current.support_source || {};
  if (!source.bound) {
    return `<section id="support-source-card" class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>支持部工资资料</h2><p class="muted">支持部提供的教学部薪资表是 B / D / E / F、基本工资和社保、补发工资等项目的正式来源。一张表一次导入，多个字段一起使用，不需要重复上传。</p></div><span class="status warn">未绑定</span></div><div class="action-bar"><button class="secondary" onclick="openBaseSalaryPage('${escapeHtml(current.id)}')">去导入支持部工资资料</button></div></section>`;
  }
  const rows = (source.field_map || []).filter((item) => item.business_name).map((item) => `<tr><td>${escapeHtml(item.business_name)}</td><td>${escapeHtml(item.final_field)}</td><td>${escapeHtml(item.source_column || "—")}</td><td>${escapeHtml(item.source === "NOT_PRESENT_IN_MATERIAL" ? "本期资料没有" : item.source)}</td><td>${item.inherited ? "原值沿用" : "不沿用"}</td><td>${item.feeds_av ? "是" : "否"}</td></tr>`).join("");
  const identity = Object.entries(source.identity_fields || {}).filter(([, value]) => value).map(([name, value]) => `${escapeHtml(String(value).split("\n")[0])}`).join("、");
  const gaps = (source.gaps || []).map((item) => item.business_name).filter(Boolean);
  const commentStatus = source.comment_count == null
    ? "这份历史工资资料还没有保存源表批注；工资值不会改动，批注需要从原确认文件补齐。"
    : `源表 ${escapeHtml(source.source_comment_count ?? 0)} 条批注，涉及 ${escapeHtml((source.source_comment_fields || []).join("、") || "无字段")}；本次工资已匹配 ${escapeHtml(source.comment_count)} 条，目标字段 ${escapeHtml((source.comment_fields || []).join("、") || "无")}。`;
  return `<section id="support-source-card" class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>支持部工资资料</h2><p class="muted">来源：${escapeHtml(source.source_name || "")} · 工作表 ${escapeHtml(source.source_sheet || "")} · ${escapeHtml(source.entries || 0)} 位教师 · 确认人 ${escapeHtml(source.confirmed_by || "—")}</p></div><span class="status ok">已绑定</span></div><p class="small muted">同时提供的身份字段：${identity || "—"}</p><p class="small muted">批注：${commentStatus}</p>${gaps.length ? `<div class="banner info"><strong>本期资料没有这些项目</strong><span>${escapeHtml(gaps.join("、"))}；系统不会替它们填 0。</span></div>` : ""}<div class="table-wrap"><table class="table"><thead><tr><th>业务名称</th><th>最终字段</th><th>支持部源表列</th><th>来源</th><th>是否直接沿用</th><th>是否参与 AV</th></tr></thead><tbody>${rows}</tbody></table></div><div class="action-bar"><button class="secondary" onclick="openBaseSalaryPage('${escapeHtml(current.id)}')">更新支持部工资资料</button><button class="secondary" onclick="deriveRatingFromSupport()">用这份资料的「教师级别」生成星级版本</button></div></section>`;
}

// 星级正常来自工资资料里的「教师级别」，不需要用户自己维护生效期和版本信息。
async function deriveRatingFromSupport() {
  const person = $("#base-salary-confirmed-by")?.value?.trim() || current.base_salary_input_snapshot?.confirmed_by || "";
  if (!person) return showMessage("请填写星级资料确认人。");
  try {
    const result = await api(`/api/runs/${current.id}/rating-from-support`, { method: "POST", body: JSON.stringify({ confirmed_by: person }) });
    current = await api(`/api/runs/${current.id}`);
    renderRun();
    showMessage(`已按支持部资料生成星级版本：${result.created.ratings} 位教师，生效期 ${result.created.effective_from} ～ ${result.created.effective_to}。`, "success");
  } catch (error) { showMessage(error.message); }
}

function baseSalaryPage() {
  const rows = current.core_calculation?.rows || current.generated_payroll?.rows || [];
  const snapshot = current.base_salary_inputs || {};
  const fields = [["G", "基本工资"], ["H", "岗位津贴"], ["I", "工龄工资/教师等级"], ["J", "其他待遇"], ["K", "应出勤"], ["L", "实际出勤"]];
  const rowHtml = rows.map((row) => {
    const entry = snapshot[row.teacher] || {};
    const values = entry.fields || {};
    const mState = entry.m?.state || "BLOCKED_BY_INPUT";
    const stateLabel = mState === "DETERMINED" ? "已确定" : entry.fields ? "待补齐" : "待确认";
    return `<tr class="base-salary-row" data-teacher="${escapeHtml(row.teacher)}"><td><strong>${escapeHtml(row.teacher)}</strong><input class="base-teacher-id" type="hidden" value="${escapeHtml(entry.teacher_id || row.teacher)}"></td>${fields.map(([code, label]) => `<td><label class="small">${label}<input class="base-${code.toLowerCase()}" type="number" step="0.01" value="${escapeHtml(values[code]?.value ?? "")}" placeholder="${code}"></label></td>`).join("")}<td><strong class="base-m-value">${escapeHtml(entry.m?.value ?? "待填写")}</strong><div class="small muted">M=(G+H+I+J)/K×L，只读计算</div></td><td><span class="status ${mState === "DETERMINED" ? "ok" : "warn"}">${stateLabel}</span></td></tr>`;
  }).join("");
  const deferred = current.base_salary_deferred ? `<div class="banner info"><strong>基本工资暂不录入</strong><span>已保存此选择，本次尚未重新核算；M 保持“待补充”，补录 G～L 后可统一开始核算。</span></div>` : "";
  return `${historicalSalaryReferenceCard()}<section class="card"><div class="section-head"><div><p class="eyebrow">生产输入</p><h2>本月基本工资</h2><p class="muted">本月支持部资料优先。历史工资只作为参考候选；没有明确确认前，不会自动成为本月工资来源。</p></div></div>${deferred}${baseSalaryImportMarkup()}<details class="base-salary-manual"><summary>查看或补录未匹配教师</summary><div class="table-wrap"><table class="table base-salary-table"><thead><tr><th>教师</th>${fields.map(([, label]) => `<th>${label}</th>`).join("")}<th>M 实际基本工资</th><th>状态</th></tr></thead><tbody>${rowHtml || '<tr><td colspan="9" class="muted">请先导入排课资料并完成一次核算。</td></tr>'}</tbody></table></div><div class="decision-form"><label>确认人<input id="base-salary-confirmed-by" value="${escapeHtml(current.base_salary_input_snapshot?.confirmed_by || current.af_policy_confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><label>输入来源<input id="base-salary-source" value="${escapeHtml(current.base_salary_input_snapshot?.source || "本次核算补录")}"></label></div><div class="action-bar"><span class="muted small">缺少任何 G～L 时，M 保持待补充；兼职教师不需要填写。</span><button onclick="saveBaseSalary()" ${rows.length ? "" : "disabled"}>保存本月基本工资并重新预览</button></div></details><div class="action-bar"><button class="secondary" onclick="deferBaseSalaryQuick()" ${rows.length ? "" : "disabled"}>暂不录入</button></div></section>${supportSourceCard()}`;
}

function historicalSalaryReferenceCard() {
  const references = savedHistoricalSalaryReferences();
  const people = current.employment?.teachers || [];
  const stagedFile = pendingHistoryReferenceFile;
  const leaderGroups = selectedRunGroups(current);
  const selectedGroup = pendingHistoryReferenceGroup || (leaderGroups.length === 1 ? leaderGroups[0] : "");
  const allowedGroups = current.operator_role === "SUBJECT_LEADER" ? leaderGroups : payrollGroups;
  const lockGroup = current.operator_role === "SUBJECT_LEADER" && leaderGroups.length === 1;
  const stagedMarkup = stagedFile ? `<div class="history-reference-stage"><div class="facts"><strong>已选择文件：</strong><span>${escapeHtml(stagedFile.name)}</span></div><label for="history-reference-group">这份资料属于哪个科组？<select id="history-reference-group" ${lockGroup ? "disabled" : ""} onchange="setPendingHistoricalReferenceGroup(this.value)"><option value="">请选择科组</option>${allowedGroups.map((group) => `<option value="${group}" ${selectedGroup === group ? "selected" : ""}>${group}</option>`).join("")}</select></label>${current.operator_role === "SUBJECT_LEADER" ? `<p class="small muted">本次负责科组：${escapeHtml(runGroupsLabel(current))}${lockGroup ? "（已自动选择）" : "；请为每份历史参考选择一个所属科组"}</p>` : ""}<div id="history-reference-import-status" role="status" aria-live="polite" class="small muted"></div><div class="action-bar"><button onclick="previewStagedHistoricalReference()">继续：识别并预览</button><button class="secondary" onclick="openHistoricalImport()">更换文件</button><button class="quiet" onclick="cancelStagedHistoricalReference()">取消</button></div></div>` : "";
  const referenceRows = references.map((reference) => {
    const group = reference.selected_group || reference.group_membership?.group || "待确认科组";
    const count = reference.group_membership?.members?.length || reference.teacher_count || reference.entries?.length || Object.keys(reference.entries || {}).length;
    const applied = (reference.use_confirmations || []).length > 0;
    return `<div class="file-name"><strong>${escapeHtml(group)} · ${escapeHtml(reference.source_name || reference.source || "历史工资参考")}</strong><span class="small ${applied ? "ok" : "info"}">${applied ? "已明确采用到本月" : "已确认，仅作参考"}</span><span class="small muted">教师 ${escapeHtml(count)} 人 · ${escapeHtml(String(reference.source_sha256 || "").slice(0, 10))}</span></div>`;
  }).join("");
  const status = references.length ? `已保存 ${references.length} 份历史参考` : "未提供历史工资参考";
  return `<section id="historical-salary-reference-card" class="salary-source-panel historical-reference-card"><div class="material-top"><strong>历史工资参考</strong><span class="status ${references.length ? "info" : "muted"}">${escapeHtml(status)}</span></div><p class="small muted">只作为教师身份、归组与 G～L 候选参考；不会自动成为本月工资，也不会带入上月其它工资项目。</p>${references.length ? `<div class="subject-group-confirmed-list">${referenceRows}</div>` : `<div class="empty compact">尚未提供历史工资参考资料。</div>`}${stagedMarkup}<div class="facts"><span>本月处理教师 ${escapeHtml(people.length)} 人</span></div>${stagedFile ? "" : `<div class="action-bar"><span class="small muted">先选文件，再确认科组；识别后仍需在待处理问题页确认。</span><button class="secondary" onclick="openHistoricalImport()">${references.length ? "继续添加历史工资参考" : "导入历史工资参考"}</button></div>`}<input id="base-salary-history-file" class="sr-only" type="file" accept=".xls,.xlsx,.xlsm" onchange="previewBaseSalaryFile(event)"></section>`;
}

function savedHistoricalSalaryReferences() {
  const references = [...(current.historical_salary_reference_snapshots || [])];
  const legacy = current.historical_salary_reference_snapshot;
  if (legacy && !references.some((item) => (item.reference_id || `${item.source_sha256}|${item.selected_group || item.group_membership?.group || ""}`) === (legacy.reference_id || `${legacy.source_sha256}|${legacy.selected_group || legacy.group_membership?.group || ""}`))) references.push(legacy);
  return references;
}

function normalizeUiTeacher(value) {
  return String(value || "").replace(/[\s　]+/g, "").trim();
}

async function useHistoricalSalaryReference(sourceSha256, selectedGroup) {
  const reference = savedHistoricalSalaryReferences().find((item) => item.source_sha256 === sourceSha256 && (item.selected_group || item.group_membership?.group || "") === selectedGroup) || {};
  const confirmedBy = $("#todo-historical-reference-confirmed-by")?.value?.trim() || "";
  if (!reference.source_sha256) return showMessage("当前没有可使用的历史工资参考快照，请先导入并保存参考资料。");
  if (!confirmedBy) return showMessage("请填写本月确认人。");
  if (!window.confirm(`确认仅在本月暂按 ${reference.source_name || "这份历史工资参考"}（${selectedGroup}）的 G～L 使用？其它历史工资字段、上月计算结果和最终工资不会因此沿用。`)) return;
  try {
    current = await api(`/api/runs/${current.id}/base-salary-reference/use`, { method: "POST", body: JSON.stringify({ confirmed_by: confirmedBy, source_sha256: reference.source_sha256, selected_group: selectedGroup }) });
    renderRun();
    showMessage("已确认本月暂按历史 G～L 参考值使用；其它历史月份工资项目不会带入。", "success");
  } catch (error) { await refreshAfterError(error); }
}

function bindBaseSalaryDropZone() {
  const zone = $("#base-salary-import");
  if (!zone) return;
  const verifiedZeros = baseSalaryImportPreview?.run_id === current?.id ? baseSalaryImportPreview.formula_verified_zero_count || 0 : 0;
  if (verifiedZeros && zone.querySelector(".base-import-review")) {
    const note = document.createElement("p");
    note.className = "small muted";
    note.textContent = `${verifiedZeros} 个空白津贴/工龄格已由原工资表同排 M 公式及缓存结果验证为 0；其它空白仍待补充。`;
    zone.querySelector(".base-import-review").prepend(note);
  }
  zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("dragging"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
  zone.addEventListener("drop", async (event) => {
    event.preventDefault();
    zone.classList.remove("dragging");
    const files = [...(event.dataTransfer?.files || [])];
    if (files.length !== 1) return showMessage("请一次选择一张历史工资表。");
    stageHistoricalReferenceFile(files[0]);
  });
}

async function previewBaseSalaryFile(event) {
  const file = event.target?.files?.[0];
  if (file) stageHistoricalReferenceFile(file);
}

// 支持部工资资料：一次上传同时供基本工资 G～L 与支持部字段使用，
// 所以走同一张文件、同一次确认，不再要求用户分开上传。
async function previewSupportFile(event) {
  const file = event.target?.files?.[0];
  if (!file) return;
  const status = $("#support-material-import-status") || $("#base-salary-import-status");
  if (status) status.textContent = "正在读取支持部工资资料…";
  try {
    if (!/\.(xls|xlsx|xlsm)$/i.test(file.name)) throw new Error("请选择 Excel 工资表（.xls、.xlsx 或 .xlsm）。");
    const bytes = new Uint8Array(await file.arrayBuffer());
    const uploaded = await api("/api/upload", { method: "POST", body: JSON.stringify({ name: file.name, content_base64: bytesToBase64(bytes) }) });
    const preview = await api(`/api/runs/${current.id}/support-preview`, { method: "POST", body: JSON.stringify({ path: uploaded.path }) });
    current = preview.run || current;
    supportImportPath = uploaded.path;
    supportImportName = file.name;
    supportImportPreview = { ...preview, run_id: current.id };
    baseSalaryImportPath = uploaded.path;
    baseSalaryImportName = file.name;
    baseSalaryImportPreview = { ...preview, run_id: current.id };
    renderRun();
    showMessage(preview.can_import ? `支持部资料已识别 ${preview.counts?.matched ?? preview.rows.length} 位教师，请确认后一次导入。` : "支持部资料中有待核实项目，请查看预览。", preview.can_import ? "success" : "error");
  } catch (error) {
    if (status?.isConnected) status.textContent = "支持部资料预览未完成。";
    showMessage(error.message);
  }
}

async function confirmSupportImport() {
  const pending = current.support_department_pending_preview || {};
  const preview = supportImportPreview?.run_id === current?.id ? supportImportPreview : null;
  if (pending.status !== "PENDING_CONFIRMATION" || (!pending.can_confirm && !preview?.can_import)) return showMessage("请先在材料准备中识别当前支持部工资资料。");
  const actor = $("#todo-support-confirmed-by")?.value?.trim() || "";
  if (!actor) {
    return showMessage("请在待处理问题中填写支持部资料确认人。");
  }
  try {
    const result = await api(`/api/runs/${current.id}/support`, { method: "POST", body: JSON.stringify({ path: pending.source_path || supportImportPath, source_sha256: pending.source_sha256 || preview?.source?.sha256 || "", confirmed_by: actor, source_name: pending.source_name || supportImportName }) });
    supportImportPreview = null;
    baseSalaryImportPreview = null;
    current = await api(`/api/runs/${current.id}`);
    renderRun();
    showMessage(`支持部工资资料已确认导入：基本工资 ${result.imported_base_salary} 位，支持部字段 ${result.entries} 位。`, "success");
  } catch (error) { showMessage(error.message); }
}

async function cancelSupportCandidate() {
  if (!window.confirm("暂缓这份候选资料？已确认的本月工资资料不会被移除。")) return;
  try {
    current = await api(`/api/runs/${current.id}/support-cancel`, { method: "POST", body: JSON.stringify({}) });
    supportImportPreview = null;
    renderRun();
    showMessage("已暂缓本份支持部候选；原文件和已有确认资料均保留。", "info");
  } catch (error) { await refreshAfterError(error); }
}

async function previewBaseSalaryFileObject(file, selectedGroup) {
  baseSalaryImportPreview = null;
  baseSalaryImportPath = "";
  baseSalaryImportName = "";
  const status = $("#history-reference-import-status") || $("#base-salary-import-status");
  if (status) status.textContent = "正在读取并匹配教师…";
  try {
    if (!/\.(xls|xlsx|xlsm)$/i.test(file.name)) throw new Error("请选择 Excel 工资表（.xls、.xlsx 或 .xlsm）。");
    if (!selectedGroup) throw new Error("请先选择这份历史工资参考所属的科组。");
    const bytes = new Uint8Array(await file.arrayBuffer());
    const uploaded = await api("/api/upload", { method: "POST", body: JSON.stringify({ name: file.name, content_base64: bytesToBase64(bytes) }) });
    const result = await api(`/api/runs/${current.id}/base-salary-reference-preview`, { method: "POST", body: JSON.stringify({ path: uploaded.path, selected_group: selectedGroup }) });
    const preview = result;
    current = preview.run || current;
    baseSalaryImportPath = uploaded.path;
    baseSalaryImportName = file.name;
    baseSalaryImportPreview = { ...preview, run_id: current.id };
    pendingHistoryReferenceFile = null;
    pendingHistoryReferenceGroup = "";
    renderRun();
    showMessage(preview.can_import ? `已识别 ${preview.matched.length} 位教师；这是历史参考资料，不会自动进入本月工资。` : "历史工资参考表中有待核实项目，请查看预览。", preview.can_import ? "info" : "error");
  } catch (error) {
    if (status?.isConnected) status.textContent = "导入预览未完成。";
    showMessage(error.message);
  }
}

async function previewExistingSupportMaterial() {
  const pending = current.support_department_pending_preview || {};
  if (!pending.source_path) return showMessage("没有可继续预览的支持部候选资料。");
  try {
    const result = await api(`/api/runs/${current.id}/support-preview`, { method: "POST", body: JSON.stringify({ path: pending.source_path }) });
    current = result.run || current;
    supportImportPath = pending.source_path;
    supportImportName = pending.source_name || "";
    supportImportPreview = { ...result, run_id: current.id };
    baseSalaryImportPath = supportImportPath;
    baseSalaryImportName = supportImportName;
    baseSalaryImportPreview = { ...result, run_id: current.id };
    renderRun();
  } catch (error) { await refreshAfterError(error); }
}

async function confirmBaseSalaryImport() {
  const pending = current.historical_salary_reference_pending_preview || {};
  const preview = baseSalaryImportPreview?.run_id === current?.id ? baseSalaryImportPreview : pending.preview;
  if (!preview?.can_import || pending.status !== "PENDING_CONFIRMATION") return showMessage("请先在材料准备中预览历史工资参考。");
  const actor = $("#todo-historical-reference-confirmed-by")?.value?.trim() || "";
  if (!actor) return showMessage("请在待处理问题中填写确认人。");
  const selectedGroup = pending.selected_group || preview.group_membership_preview?.selected_group || "";
  const secondaryTeacherIds = [...document.querySelectorAll("[data-history-secondary]:checked")].map((item) => item.value);
  try {
    const result = await api(`/api/runs/${current.id}/base-salary/import`, { method: "POST", body: JSON.stringify({ path: pending.source_path, source_name: pending.source_name, source_sha256: pending.source_sha256, confirmed_by: actor, selected_group: selectedGroup, secondary_teacher_ids: secondaryTeacherIds }) });
    current = result.run;
    baseSalaryImportPreview = null;
    renderRun();
    showMessage(`已保存 ${result.imported} 位教师的历史工资参考，并确认 ${result.group_membership?.members?.length || 0} 位本组成员；工资值不会自动进入本月。`, "success");
  } catch (error) { showMessage(error.message); }
}

function focusBaseSalary() {
  document.querySelector(".base-salary-table input")?.focus();
  document.querySelector(".base-salary-table")?.scrollIntoView({behavior: "smooth", block: "center"});
}

async function saveBaseSalary() {
  try {
    const inputs = [...document.querySelectorAll(".base-salary-row")].map((row) => {
      const prior = current.base_salary_inputs?.[row.dataset.teacher]?.fields || {};
      const fields = {};
      for (const code of ["G", "H", "I", "J", "K", "L"]) {
        const value = row.querySelector(`.base-${code.toLowerCase()}`).value;
        fields[code] = prior[code] && String(prior[code].value ?? "") === value
          ? prior[code]
          : { value, source: "本次核算补录", provenance: { kind: "MANUAL_BASE_SALARY_COMPLETION", field: code } };
      }
      if (!["G", "H", "I", "J", "K", "L"].some((code) => fields[code].value !== "" && fields[code].value != null)) return null;
      return {teacher: row.dataset.teacher, teacher_id: row.querySelector(".base-teacher-id").value, fields};
    }).filter(Boolean);
    if (!inputs.length) throw new Error("请先导入历史工资表，或至少补录一位教师的基本工资资料。");
    current = await api(`/api/runs/${current.id}/base-salary`, {method: "POST", body: JSON.stringify({inputs, confirmed_by: $("#base-salary-confirmed-by").value, source: $("#base-salary-source").value})});
    tab = "payroll";
    renderRun(); showMessage("基本工资输入已保存并冻结到当前 Run。", "success");
  } catch (error) { showMessage(error.message); }
}

async function deferBaseSalary() {
  try {
    const person = $("#base-salary-confirmed-by")?.value?.trim();
    if (!person) throw new Error("请填写确认人，才能暂不录入基本工资。");
    const saved = await api(`/api/runs/${current.id}/base-salary-defer`, { method: "POST", body: JSON.stringify({ confirmed_by: person, reason: "用户选择暂不录入基本工资；之后可补充。" }) });
    current = { ...current, ...saved };
    renderRun();
    showMessage(saved.defer_outcome?.message || "已记录暂不录入基本工资；没有开始核算。", "success");
  } catch (error) { showMessage(error.message); }
}

async function deferBaseSalaryQuick() {
  const person = $("#defer-base-confirmed-by")?.value?.trim() || $("#base-salary-confirmed-by")?.value?.trim() || current.af_policy_confirmation?.confirmed_by || "";
  if (!person) {
    $("#defer-base-confirmed-by")?.focus();
    return showMessage("请填写确认人，才能暂不录入基本工资。");
  }
  try {
    const saved = await api(`/api/runs/${current.id}/base-salary-defer`, { method: "POST", body: JSON.stringify({ confirmed_by: person, reason: "用户选择暂不录入基本工资；之后可补充。" }) });
    current = { ...current, ...saved };
    renderRun();
    showMessage(saved.defer_outcome?.message || "已记录暂不录入基本工资；没有开始核算。", "success");
  } catch (error) { refreshAfterError(error); }
}

async function avSourceMapPage(runId = current?.id || "") {
  try {
    const query = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
    const data = await api(`/api/av-source-map${query}`);
    const fields = data.fields || [];
    const directCodes = data.direct_components || data.components || [];
    const upstream = data.upstream_dependencies || {AK: ["AH", "AI", "AJ"]};
    const statusClass = (status) => ["DETERMINED", "NOT_APPLICABLE", "DONE"].includes(status) ? "ok" : (["NO_EVIDENCE", "HUMAN_REQUIRED", "SOURCE_MISSING", "RULE_NOT_DEFINED", "MANUAL_INPUT_REQUIRED", "BLOCKED_BY_COMPONENTS"].includes(status) ? "warn" : "info");
    const statusLabel = (status) => ({
      DETERMINED: "已确定", NOT_APPLICABLE: "不适用", HUMAN_REQUIRED: "待补来源/确认",
      SOURCE_MISSING: "缺来源", RULE_NOT_DEFINED: "规则未定义", MANUAL_INPUT_REQUIRED: "需人工输入",
      SOURCE_AVAILABLE_NOT_CONNECTED: "已有来源，尚未接入", DERIVED_OUTPUT: "衍生输出", BLOCKED_BY_COMPONENTS: "由组成项阻塞",
      DONE: "已完成", NO_EVIDENCE: "NO EVIDENCE",
    }[status] || status);
    const row = (item) => `<tr><td><strong>${escapeHtml(item.column)}</strong></td><td>${escapeHtml(item.business_name)}</td><td>${escapeHtml(item.relationship || "—")}${item.template_formula ? `<div class="small muted">模板公式：${escapeHtml(item.template_formula)}</div>` : ""}</td><td>${escapeHtml(item.source || "—")}</td><td>${escapeHtml(item.source_type || "—")}</td><td><span class="status ${statusClass(item.category)}">${escapeHtml(statusLabel(item.category))}</span><div class="small muted">当前：${escapeHtml(statusLabel(item.current_system_status))}</div></td><td>${escapeHtml(item.authoritative_source || "—")}</td></tr>`;
    const direct = directCodes.map((code) => fields.find((item) => item.column === code)).filter(Boolean);
    const av = fields.find((item) => item.column === "AV");
    const upstreamCodes = [...new Set(Object.values(upstream).flat())];
    const upstreamFields = upstreamCodes.map((code) => fields.find((item) => item.column === code)).filter(Boolean);
    const missing = direct.filter((item) => ["SOURCE_MISSING", "RULE_NOT_DEFINED", "MANUAL_INPUT_REQUIRED"].includes(item.category));
    const avState = data.av_status_model?.state || av?.current_system_status || "NO_EVIDENCE";
    const back = current ? "renderRun()" : "home()";
    shell(`<section class="section-head"><div><p class="eyebrow">只读证据</p><h1>总工资来源地图</h1><p class="muted">${data.period ? `当前 Run：${escapeHtml(data.period)} · ` : ""}来源、规则和缺口来自现有代码、Run 证据与真实工资模板；本页面不会写入任何核算状态。</p></div><button class="secondary" onclick="${back}">返回</button></section><section class="card"><div class="section-head"><div><h2>AV（总工资）</h2><p class="muted">AV 是衍生输出，不是人工填报字段。</p></div><span class="status ${statusClass(avState)}">${escapeHtml(statusLabel(avState))}</span></div><div class="formula-box">${escapeHtml(data.av_formula || "NO EVIDENCE")}</div><p class="small muted">AV ↓ ${directCodes.length} 个直接组成项（M 在第一项）；只有 DETERMINED / NOT_APPLICABLE 才计入完整度。</p><div class="component-flow">${directCodes.map((code) => `<span class="status info">${escapeHtml(code)}</span>`).join(" ")}</div><strong class="readiness">FULL_PAYROLL_COMPLETENESS = ${escapeHtml(data.full_payroll_completeness?.label || "—")}</strong></section><section class="card"><h2>AV 直接组成项（${directCodes.length}）</h2><div class="table-wrap"><table class="table"><thead><tr><th>字段</th><th>业务含义</th><th>关系</th><th>来源</th><th>来源类型</th><th>状态</th><th>权威来源</th></tr></thead><tbody>${direct.map(row).join("")}</tbody></table></div></section><section class="card"><h2>上游依赖（不计入 AV 分母）</h2><p class="muted">AK 的直接组成是 AH、AI、AJ；它们只作为 AK 的上游缺口展示。</p><div class="table-wrap"><table class="table"><thead><tr><th>上游字段</th><th>当前状态</th><th>来源</th><th>关系</th></tr></thead><tbody>${upstreamFields.map((item) => `<tr><td><strong>${escapeHtml(item.column)}</strong> · ${escapeHtml(item.business_name)}</td><td><span class="status ${statusClass(item.current_system_status)}">${escapeHtml(statusLabel(item.current_system_status))}</span></td><td>${escapeHtml(item.source || "—")}</td><td>${escapeHtml(item.relationship || "—")}</td></tr>`).join("")}</tbody></table></div></section><section class="card"><h2>缺口清单</h2>${missing.length ? `<div class="evidence-list">${missing.map((item) => `<div class="evidence-card"><div><span>${escapeHtml(item.column)} ${escapeHtml(item.business_name)}</span><strong>${escapeHtml(statusLabel(item.category))}</strong></div><div><span>当前系统</span><strong>${escapeHtml(statusLabel(item.current_system_status))}</strong></div><div><span>依据</span><strong>${escapeHtml(item.authoritative_source || "NO EVIDENCE")}</strong></div></div>`).join("")}</div>` : '<div class="empty success">当前没有直接组成项缺口。</div>'}</section>`, false);
  } catch (error) { showMessage(error.message); }
}

async function loadHistoricalReconciliation() {
  try {
    const data = await api(`/api/runs/${current.id}/historical-reconciliation`);
    if (tab === "reconciliation") $("#view").innerHTML = historicalReconciliationPage(data);
  } catch (error) {
    if (tab === "reconciliation") $("#view").innerHTML = `<section class="card"><h2>历史工资对账</h2><div class="empty">${escapeHtml(error.message)}</div></section>`;
  }
}

function historicalReconciliationPage(data) {
  const labels = {AA: "AA", AC: "AC", AD: "AD", AE: "AE", AF: "AF（总课时费）"};
  const stats = Object.entries(data.field_stats || {}).map(([field, stat]) => `<div class="metric"><span>${labels[field] || field}</span><strong>${stat.matches}/${stat.comparable}</strong><small>可比教师一致</small></div>`).join("");
  const rows = (data.rows || []).map((row) => {
    const fields = Object.entries(row.fields || {}).map(([field, value]) => {
      const courseEvidence = (value.evidence || []).find((item) => Array.isArray(item.course_contributions));
      const courseRows = courseEvidence?.course_contributions || [];
      const courseTable = courseRows.length ? `<details class="evidence-details"><summary>查看逐课证据（${courseRows.length} 条）</summary><div class="table-wrap"><table class="table"><thead><tr><th>日期</th><th>课程/学生</th><th>状态</th><th>实到</th><th>年级/班型</th><th>贡献</th><th>来源行</th></tr></thead><tbody>${courseRows.map((course) => `<tr><td>${escapeHtml(course.date || "—")}</td><td>${escapeHtml([course.class_name, course.student].filter(Boolean).join(" / ") || "—")}</td><td>${escapeHtml(course.lesson_status || "—")}</td><td>${escapeHtml(String(course.attended ?? "—"))}</td><td>${escapeHtml([course.grade, course.class_type].filter(Boolean).join(" / ") || "—")}</td><td>${formatNumber(course.contribution)}</td><td>${escapeHtml(course.source_row || "—")}</td></tr>`).join("")}</tbody></table></div></details>` : "";
      return `<tr><td><strong>${labels[field] || field}</strong></td><td>${formatNumber(value.historical)}</td><td>${formatNumber(value.current)}</td><td class="warn-text">${formatNumber(value.diff)}</td><td><span class="field-state">${escapeHtml(value.difference_category)}</span><div class="small muted">${historicalEvidenceText(value.evidence)}</div>${courseTable}</td></tr>`;
    }).join("");
    return `<details class="reconciliation-row"><summary><strong>${escapeHtml(row.teacher)}</strong><span class="status warn">${escapeHtml(row.difference_category)}</span><span class="small muted">${Object.keys(row.fields || {}).length} 个字段差异</span></summary><div class="table-wrap"><table class="table"><thead><tr><th>字段</th><th>历史值</th><th>当前值</th><th>差异</th><th>证据分类</th></tr></thead><tbody>${fields}</tbody></table></div></details>`;
  }).join("");
  const differenceLabel = data.unexplained ? `待解释差异：${data.difference_teachers} 人` : `已分类差异：${data.difference_teachers} 人`;
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">真实 July Run · ${escapeHtml(data.period_start || "—")} ～ ${escapeHtml(data.period_end || "—")}</p><h2>历史工资对账</h2><p class="muted">仅比较同时存在历史工资字段与当前计算值的教师；历史工资表是 oracle，当前值来自本次 Run 的版本化计算。</p></div><span class="status ${data.unexplained ? "bad" : "ok"}">${data.unexplained ? `${data.unexplained} 个未解释` : "未解释差异：0"}</span></div><div class="metric-grid">${stats}</div><div class="banner ${data.difference_teachers ? "info" : "success"}"><strong>${differenceLabel}</strong><span>可比教师：${data.teachers_compared} 人；分类均保留原始来源与课程证据。</span></div>${rows || '<div class="empty success">所有可比教师字段一致。</div>'}</section>`;
}

function historicalEvidenceText(items) {
  const course = (items || []).find((item) => item.course_contributions);
  const base = (items || []).find((item) => item.course_contribution_count || item.historical_formula || item.reason);
  const policy = (items || []).find((item) => item.source_classification === "PART_TIME_RATE");
  const parts = [];
  if (base?.historical_formula) parts.push(`历史公式：${base.historical_formula}`);
  if (base?.historical_obligation_hours != null || base?.current_obligation_hours != null) parts.push(`义务课时：历史 ${base.historical_obligation_hours ?? "未知"} / 当前 ${base.current_obligation_hours ?? "未知"}`);
  if (course?.course_contribution_count != null) parts.push(`逐课证据 ${course.course_contribution_count} 条`);
  else if (base?.course_contribution_count != null) parts.push(`逐课证据 ${base.course_contribution_count} 条`);
  if (policy) parts.push(`兼职政策：${policy.rate} 元/节 × ${policy.lesson_count} 节；来源：${policy.source_cell || policy.source || "—"}`);
  return escapeHtml(parts.join("；") || "已保留来源与差异证据");
}

function formatNumber(value) { return value == null ? "—" : Number(value).toFixed(2); }

function materialsPage() {
  const warnings = [...new Set(current.health.warnings || [])];
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 1 步</p><h2>准备核算材料</h2><p class="muted">先导入当前人工月排课表、学科组资料和工资来源。确认、选择与暂缓全部进入待处理问题页；本步不启动完整核算。</p></div><strong class="readiness">${current.health.readiness}%</strong></div><div class="package-drop" data-drop-role="package" tabindex="0" role="button" aria-label="批量识别辅助资料" style="border:1px dashed #b9c4cf;border-radius:8px;padding:14px;text-align:center;color:#68717d;background:#fbfcfd;cursor:pointer"><strong>批量识别辅助资料（可选）</strong><span>可辅助读取排课、续费、退费、星级等资料；工资资料和学科组提交表仍需在对应区域逐份确认。</span></div><div class="action-bar"><button data-action="choose-package" onclick="choosePackage()">选择辅助资料文件夹</button><span class="muted small">选择按钮仅作为备用入口，不影响拖拽和粘贴。</span></div><div class="material-grid">${productionMaterialCards()}</div>${salaryMaterialsModule()}${warnings.length ? `<div class="warning-list"><strong>材料提示</strong>${warnings.map((warning) => `<p>⚠ ${escapeHtml(warning)}</p>`).join("")}</div>` : ""}<div class="action-bar"><div>${current.health.missing.length ? `<strong>材料待补：</strong>${current.health.missing.map(escapeHtml).join("、")}` : "材料状态已保存；请继续确认本次教师名单与归属。"}</div><button class="secondary" onclick="refreshRun()">重新检查材料</button></div></section>`;
}

function salaryMaterialsModule() {
  const source = current.support_source || {};
  const references = savedHistoricalSalaryReferences();
  const stateText = source.bound ? "已导入本月权威工资资料" : references.length ? `暂无本月权威资料，已有 ${references.length} 份历史工资参考` : "暂无本月权威工资资料或历史工资参考";
  return `<section id="salary-material-module" class="salary-material-module card"><div class="section-head"><div><p class="eyebrow">工资资料</p><h2>工资资料</h2><p class="muted">${escapeHtml(stateText)}</p></div><span class="status ${source.bound ? "ok" : references.length ? "info" : "warn"}">${source.bound ? "本月权威" : references.length ? "历史参考" : "未提供"}</span></div><div class="salary-material-options">${supportMaterialCard()}${historicalSalaryReferenceCard()}</div></section>`;
}

function productionMaterialCards() {
  const byRole = Object.fromEntries((current.materials || []).map((item) => [item.role, item]));
  const schedule = byRole.schedule;
  const subjectFiles = [byRole.math, byRole.science].filter((item) => item?.file);
  return [
    schedule ? materialCard(schedule) : "",
    subjectGroupCard(subjectFiles),
    businessMaterialCard("renewal", "续费表", current.renewal_reports || [], "读取已经确认的续费结果，不重新判断业务原因。"),
    businessMaterialCard("refund", "退费表", current.refund_reports || [], "读取已经确认的退费结果，不重新判断责任归属。"),
  ].join("");
}

function subjectGroupCard(files) {
  const confirmedMaterials = current.subject_group_materials || [];
  const names = confirmedMaterials.length ? "" : files.map((item) => {
    const role = item.role;
    const label = item.file?.recognized_group || (role === "math" ? "数学组" : "理化组");
    const status = item.confirmed_for_run ? "已确认用于本月工资" : "待人工确认，不会进入工资";
    const pendingEntry = Object.entries(current.pending_subject_group_imports || {}).find(([, candidate]) => candidate.role === role && candidate.source_sha256 === item.file?.sha256);
    const candidateId = pendingEntry?.[0] || pendingEntry?.[1]?.candidate_id || "";
    const action = item.confirmed_for_run ? "" : `<button class="secondary" onclick="previewExistingSubjectGroup('${escapeHtml(role)}','${escapeHtml(candidateId)}')">预览并确认当前资料</button>`;
    return `<div class="file-name">${escapeHtml(label)} · ${escapeHtml(item.file.name)} <span class="small ${item.confirmed_for_run ? "ok" : "warn"}">${status}</span>${action}</div>`;
  }).join("");
  const confirmedMarkup = confirmedMaterials.length ? `<div class="subject-group-confirmed-list"><strong>本次已确认资料（${confirmedMaterials.length} 份）</strong>${confirmedMaterials.map((item) => {
    const role = item.recognized_role || "";
    const label = item.recognized_group || (role === "math" ? "数学组" : role === "science" ? "理化组" : role || "学科组");
    const legacy = String(item.material_id || "").startsWith("legacy-");
    const removeInputId = `subject-group-remove-confirmed-by-${String(item.material_id || "").replace(/[^a-zA-Z0-9_-]/g, "")}`;
    return `<div class="subject-group-confirmed-item"><div><strong>${escapeHtml(label)} · ${escapeHtml(item.source_name || item.name || "资料")}</strong><div class="small muted">已确认 · 教师 ${escapeHtml(item.teacher_count ?? item.teachers ?? "—")} 人 · 记录 ${escapeHtml(item.record_count ?? item.records ?? "—")} 条 · 确认人 ${escapeHtml(item.confirmed_by || "—")} · ${escapeHtml(String(item.source_sha256 || item.sha256 || "").slice(0, 10))}</div></div>${legacy ? '<span class="small muted">旧版单份资料（当前暂不能单独移除）</span>' : `<div class="subject-group-remove"><label>移除确认人<input id="${escapeHtml(removeInputId)}" placeholder="填写姓名"></label><button class="quiet danger-link" onclick="removeSubjectGroupMaterial('${escapeHtml(item.material_id)}','${escapeHtml(removeInputId)}')">从本次核算移除</button></div>`}</div>`;
  }).join("")}</div>` : "";
  const sourceConflicts = current.subject_group_source_conflicts || current.source_conflicts || [];
  const conflictingTeachers = new Set(sourceConflicts.map((item) => normalizeUiTeacher(item.teacher || item.source_teacher || "")));
  const duplicateTeachers = current.subject_group_duplicate_teachers || [];
  const duplicateMarkup = duplicateTeachers.length ? `<div class="banner info"><strong>跨资料重复教师</strong><span>${duplicateTeachers.map((item) => `${escapeHtml(item.teacher || "教师")}（${conflictingTeachers.has(normalizeUiTeacher(item.teacher)) ? "字段冲突，见下方" : "重复但一致"}）：${escapeHtml((item.sources || []).join("、") || "多份资料")}`).join("；")}。重复本身不会阻塞整个核算。</span></div>` : "";
  const sourceConflictMarkup = sourceConflicts.length ? `<div class="warning-list"><strong>学科组资料字段冲突</strong>${sourceConflicts.map((item) => {
    const values = (item.values || []).map((value, index) => `${item.sources?.[index] || "来源"}：${value == null ? "空白" : value}`).join("；");
    return `<p>${escapeHtml(item.teacher || item.source_teacher || "相关教师")}${item.field_label ? ` · ${escapeHtml(item.field_label)}` : item.field ? ` · ${escapeHtml(item.field)}` : ""}：${escapeHtml(item.reason || "不同资料内容不一致")}${values ? `（${escapeHtml(values)}）` : ""}</p>`;
  }).join("")}</div>` : "";
  const pending = current.pending_subject_group_imports || {};
  const candidateCards = Object.values(pending).map((item) => {
    const label = item.recognized_group || (item.role === "science" ? "理化组" : "学科组");
    const state = item.preview_required ? "待重新预览" : "待确认或暂缓";
    return `<div class="file-name"><strong>${escapeHtml(label)} · ${escapeHtml(item.source_name || "学科组资料")}</strong><span class="small warn">${state}</span> · 教师 ${escapeHtml(item.teacher_count ?? "—")} · 行 ${escapeHtml(item.record_count ?? "—")} · ${escapeHtml(String(item.source_sha256 || "").slice(0, 10))}<button class="secondary" onclick="setTab('issues')">到待处理问题处理</button></div>`;
  }).join("");
  const leaderGroups = selectedRunGroups(current);
  const lockGroup = current.operator_role === "SUBJECT_LEADER" && leaderGroups.length === 1;
  const groupOptions = current.operator_role === "SUBJECT_LEADER" ? leaderGroups : payrollGroups;
  return `<article class="material-card material-group-card"><div class="material-top"><strong>学科组提交表</strong><span class="muted">资料只在负责人确认后进入本月工资</span></div><p class="small muted">每份资料独立登记。选择本文件所属科组后再添加；确认前不会改变工资结果或教师名单。移除只解除本次绑定，不删除原文件。</p><label for="subject-group-selected-group">本次资料所属科组<select id="subject-group-selected-group" ${lockGroup ? "disabled" : ""}><option value="">请选择科组</option>${groupOptions.map((group) => `<option value="${group}" ${(lockGroup ? leaderGroups[0] : "") === group ? "selected" : ""}>${group}</option>`).join("")}</select></label>${current.operator_role === "SUBJECT_LEADER" && !lockGroup ? `<p class="small muted">负责科组：${escapeHtml(leaderGroups.join("、"))}。每份提交资料需单独指定所属科组。</p>` : ""}${confirmedMarkup}${duplicateMarkup}${sourceConflictMarkup}<div data-drop-role="subject_group" tabindex="0" role="button" aria-label="拖入学科组提交表文件" class="drop-zone" style="border:1px dashed #b9c4cf;border-radius:8px;padding:14px;text-align:center;color:#68717d;background:#fbfcfd;cursor:pointer">拖入 Excel 文件，或直接粘贴</div>${names || (!confirmedMaterials.length ? '<div class="empty compact">尚未选择已确认的学科组提交表</div>' : "")}<button class="secondary full" onclick="choose('subject_group')">添加学科组提交表并预览</button>${candidateCards}</article>`;
}

async function removeSubjectGroupMaterial(materialId, inputId) {
  const removedBy = document.getElementById(inputId)?.value?.trim() || "";
  if (!removedBy) return showMessage("请填写从本次核算移除资料的操作人。");
  if (!window.confirm("只会从当前工资核算移除这份学科组资料；原文件和历史审计记录都会保留。确定继续吗？")) return;
  try {
    const result = await api(`/api/runs/${current.id}/subject-group-remove`, { method: "POST", body: JSON.stringify({ material_id: materialId, removed_by: removedBy }) });
    current = result.run;
    renderRun();
    showMessage("已从本次核算移除该资料；原文件未删除。", "success");
  } catch (error) { await refreshAfterError(error); }
}

function businessMaterialCard(kind, title, records, description) {
  const meta = current.material_inputs?.[kind] || {};
  const count = Array.isArray(records) && records.length ? records.length : Number(meta.records || 0);
  const state = count ? "✓ 已识别" : "可稍后补充";
  const detail = count ? `已读取 ${count} 条结果，来源和版本已保存。` : "尚未选择文件";
  return `<article class="material-card"><div class="material-top"><strong>${escapeHtml(title)}</strong><span class="${count ? "ok" : "muted"}">${state}</span></div><p class="small muted">${escapeHtml(description)}</p><div data-drop-role="${kind}" tabindex="0" role="button" aria-label="拖入${escapeHtml(title)}文件" class="drop-zone" style="border:1px dashed #b9c4cf;border-radius:8px;padding:14px;text-align:center;color:#68717d;background:#fbfcfd;cursor:pointer">拖入 Excel 或 CSV 文件，或直接粘贴</div>${meta.name ? `<div class="file-name">${escapeHtml(meta.name)}</div>` : `<div class="empty compact">${escapeHtml(detail)}</div>`}<button class="secondary full" onclick="choose('${kind}')">选择${escapeHtml(title)}</button></article>`;
}

async function choosePackage() {
  const button = document.querySelector("[data-action='choose-package']");
  if (button) { button.disabled = true; button.textContent = "正在读取…"; }
  try {
    const picked = await api("/api/pick-directory", { method: "POST", body: "{}" });
    if (!picked.path) return;
    const result = await api(`/api/runs/${current.id}/package`, { method: "POST", body: JSON.stringify({ path: picked.path }) });
    current = result.run;
    renderRun();
    showMessage("已完成可识别辅助资料的读取；工资资料和学科组提交表仍需在对应区域分别预览确认。", "success");
  } catch (error) { showMessage(error.message); }
  finally { if (button) { button.disabled = false; button.textContent = "选择辅助资料文件夹"; } }
}

function periodMismatchCard() {
  const check = current?.period_check;
  if (!check) return "";
  if (check.conflict) {
    const details = (check.sources || []).map((item) => `${escapeHtml(item.source_file || item.role)}：${escapeHtml(item.source_month || "未知")}`).join("；");
    const months = [...new Set((check.sources || []).map((item) => item.source_month).filter(Boolean))];
    const choices = months.map((month) => `<button onclick="switchPeriodTo('${escapeHtml(month)}')">按 ${escapeHtml(month)} 继续</button>`).join("");
    return `<section class="card warning-card" data-todo-key="period-month"><h2>材料月份不一致</h2><p class="muted">系统检测到不同材料对应不同工资月份，不能自动替你选择。${details}</p><p class="small warn">请选择本次实际工资月份；系统不会替你猜测。</p><div class="action-bar">${choices}</div></section>`;
  }
  // PENDING means the user still needs to choose.  Only an explicit choice
  // may dismiss this card.
  if (!check.mismatch || ["SWITCHED", "KEPT"].includes(check.decision)) return "";
  const source = check.source_month || "未知月份";
  return `<section class="card" data-todo-key="period-month"><h2>课表月份需要确认</h2><p class="muted">检测到课表主要属于 ${escapeHtml(source)}，当前核算月份为 ${escapeHtml(check.run_month)}。</p><div class="action-bar"><button onclick="resolvePeriod('SWITCH')">切换到 ${escapeHtml(source)}</button><button class="secondary" onclick="resolvePeriod('KEEP')">仍按 ${escapeHtml(check.run_month)}</button></div></section>`;
}

function periodNeedsDecision(check = current?.period_check) {
  return Boolean(check && (check.conflict || (check.mismatch && !["SWITCHED", "KEPT"].includes(check.decision))));
}

function coverageWarningCard() {
  const coverage = current?.period_check?.coverage;
  if (!coverage || !coverage.incomplete_tail || current?.period_check?.decision === "PENDING") return "";
  const blocking = current?.period_check?.final_generation_blocked;
  const authority = current?.period_authority || {};
  const boundary = authority.period_end
    ? `人工周期截止日 ${authority.period_end}` : "自然月月末";
  return `<section class="card ${blocking ? "warning-card" : ""}"><h2>确认实际排课周期</h2><p class="muted">当前读取的课程日期为 ${escapeHtml(coverage.first_date || "?")} 至 ${escapeHtml(coverage.last_date || "?")}；记录中的核算周期为 ${escapeHtml(coverage.period_start || current.period)} 至 ${escapeHtml(coverage.period_end || "?")}。</p><p class="small warn">最后一节课早于${escapeHtml(boundary)}，不足以单独证明课表缺失。请核对实际截止日后保存；系统会按确认的周期重新核算。</p><details><summary>设置本次实际核算周期</summary><div class="decision-form"><label>开始日期<input id="confirmed-period-start" type="date" value="${escapeHtml(coverage.first_date || current.period_start || "")}"></label><label>结束日期<input id="confirmed-period-end" type="date" value="${escapeHtml(coverage.last_date || current.period_end || "")}"></label><label>确认人<input id="confirmed-period-person" value="${escapeHtml(current.af_policy_confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><label>确认依据<input id="confirmed-period-reason" value="已核对本期排课来源的实际截止日" placeholder="说明实际核算周期依据"></label></div><div class="action-bar"><span class="muted small">这是例外修正入口。若该周期对整月都成立，请改用下方“人工月 / 工资周期”保存一次，之后不必再重复确认。</span><button onclick="confirmActualPeriod()">保存周期并重新核对</button></div></details></section>`;
}

// ------------------------------------------------------------------ 人工月 / 工资周期
//
// 工资月份 → 该月的人工周期 → 用它筛选排课并判断完整性。文件名和课表日期都只是
// 校验证据，不能反过来定义人工月。

function periodAuthorityForm(authority, prefix) {
  const coverage = current?.period_check?.coverage || {};
  return `<div class="decision-form"><label>开始日期<input id="${prefix}-authority-start" type="date" value="${escapeHtml(authority.period_start || coverage.first_date || "")}"></label><label>结束日期<input id="${prefix}-authority-end" type="date" value="${escapeHtml(authority.period_end || coverage.last_date || "")}"></label><label>确认人<input id="${prefix}-authority-person" value="${escapeHtml(current?.af_policy_confirmation?.confirmed_by || authority.confirmed_by || "")}" placeholder="填写姓名"></label><label>依据<input id="${prefix}-authority-reason" value="${escapeHtml(authority.reason || "")}" placeholder="例如：公司工资周期按每月 1 日～30 日"></label></div><div class="action-bar"><span class="muted small">保存后这个周期会成为 ${escapeHtml(authority.payroll_period || current?.period || "")} 的长期依据，并立即按新周期重新核对本次核算。</span><button onclick="savePeriodAuthority('${prefix}')">保存人工月并重新核对</button></div>`;
}

async function savePeriodAuthority(prefix) {
  const person = $(`#${prefix}-authority-person`)?.value?.trim() || "";
  if (!person) {
    $(`#${prefix}-authority-person`)?.focus();
    return showMessage("请填写确认人，才能保存人工月。");
  }
  const payload = {
    payroll_period: current.period,
    period_start: $(`#${prefix}-authority-start`)?.value || "",
    period_end: $(`#${prefix}-authority-end`)?.value || "",
    boundary_source: "MANUAL_PERIOD_RECORD",
    confirmed_by: person,
    reason: $(`#${prefix}-authority-reason`)?.value?.trim() || "用户在界面确认的人工月 / 工资周期",
  };
  try {
    await api("/api/period-authorities", { method: "POST", body: JSON.stringify(payload) });
    // 本次核算必须改用刚保存的人工月（即使它此前已有一个例外周期）。
    current = await api(`/api/runs/${current.id}/period-authority`, { method: "POST", body: JSON.stringify({ force: true }) });
    renderRun();
    showMessage(`已保存 ${current.period} 的人工月，并按该周期重新核对。以后这个月份不会再要求重复确认。`, "success");
  } catch (error) { await refreshAfterError(error); }
}

function periodAuthorityCard() {
  const authority = current?.period_authority || {};
  if (!authority.payroll_period) return "";
  const check = current?.period_check || {};
  const range = `${escapeHtml(authority.period_start || "?")} ～ ${escapeHtml(authority.period_end || "?")}`;
  const outside = check.outside_authority
    ? `<p class="small warn">排课来源里出现了人工周期之外的日期：${escapeHtml((check.outside_authority_dates || []).join("、") || "见来源文件")}。这些课程没有计入本期；请确认人工周期或更正排课来源。</p>`
    : "";
  if (authority.is_fallback) {
    return `<section class="card warning-card"><h2>人工月 / 工资周期：暂按自然月兜底</h2><p class="muted">${escapeHtml(authority.payroll_period)} 还没有人工月资料，因此筛选与完整性判断暂按自然月 ${range}。若本单位该月的实际工资周期不是自然月，请在这里确认一次。</p>${outside}<details><summary>设置 ${escapeHtml(authority.payroll_period)} 的人工月 / 工资周期</summary>${periodAuthorityForm(authority, "materials")}</details></section>`;
  }
  const documentLine = (authority.source || {}).source_file
    ? `<p class="small muted">人工月来源：${escapeHtml(authoritySourceText(authority))}${(authority.source || {}).imported_at ? ` · 导入 ${escapeHtml(fmtDate(authority.source.imported_at))}` : ""}</p>`
    : "";
  return `<section class="card"><h2>人工月 / 工资周期</h2><p class="muted">${escapeHtml(authority.payroll_period)} 的人工周期为 ${range}（${escapeHtml(authority.source_label || "")}${authority.confirmed_by ? `，确认人：${escapeHtml(authority.confirmed_by)}` : ""}）。排课筛选和完整性都按这个周期判断，不再使用自然月月末。</p>${documentLine}${outside}<details><summary>修正该工资月份的人工周期</summary>${periodAuthorityForm(authority, "materials")}</details></section>`;
}

// ------------------------------------------------------------- 人工月权威资料
//
// 人工月资料是「基础权威资料」：导入一次，对应月份以后自动沿用。
// 资料导入（MANUAL_PERIOD_DOCUMENT）与用户在界面上手填（USER_CONFIRMED）
// 必须在界面上区分开。

let periodAuthorityList = [];
let periodDocumentPreview = null;
let periodDocumentReturnRun = "";

function authoritySourceText(item) {
  const source = item?.source || {};
  if (source.source_file) {
    const name = String(source.source_file).replace(/\.[^.]+$/, "");
    return `《${name}》${source.source_section ? ` · ${source.source_section}` : ""}`;
  }
  if (item?.source_label) return item.source_label;
  return "未标明来源";
}

function periodAuthorityDashboardCard(runId, authorityList) {
  const active = (authorityList || []).filter((item) => item.status !== "SUPERSEDED");
  const years = [...new Set(active.map((item) => String(item.payroll_period).slice(0, 4)))].sort();
  const documents = [...new Set(active.map((item) => (item.source || {}).source_file).filter(Boolean))];
  const importedAt = active.map((item) => (item.source || {}).imported_at).filter(Boolean).sort().slice(-1)[0] || "";
  const runPeriod = runId ? (current?.period || "") : "";
  const runAuthority = (runId && current?.period_authority) || {};
  const hasRunMonth = Boolean(runId && active.some((item) => item.payroll_period === runPeriod));
  const headline = active.length
    ? `已导入${years.length === 1 ? ` ${years[0]} 年` : ""}人工月：${active.length} 条`
    : "尚未导入人工月资料";
  const summary = active.length
    ? `<div class="facts"><div><span>已导入</span><strong>${escapeHtml(headline)}</strong></div><div><span>来源</span><strong>${escapeHtml(documents.map((name) => `《${String(name).replace(/\.[^.]+$/, "")}》`).join("、") || "本机手工设置")}</strong></div><div><span>最近导入</span><strong>${escapeHtml(importedAt ? fmtDate(importedAt) : "—")}</strong></div></div>`
    : '<p class="warn small">还没有导入过人工月资料；当前只能按自然月兜底。</p>';
  const monthLine = !runId
    ? '<p class="muted small">打开一个工资核算记录后，可在这里维护该月份的人工月。</p>'
    : hasRunMonth
      ? `<p class="muted small">本次核算 ${escapeHtml(runPeriod)}：${escapeHtml(runAuthority.period_start || "?")} ～ ${escapeHtml(runAuthority.period_end || "?")}（${escapeHtml(runAuthority.source_label || "未设置")}${(runAuthority.source || {}).source_file ? ` · ${escapeHtml(authoritySourceText(runAuthority))}` : ""}）</p>`
      : `<p class="warn small">当前月份 ${escapeHtml(runPeriod)} 没有人工月资料。</p>`;
  const detailRows = (authorityList || []).map((item) => {
    const state = item.status === "SUPERSEDED"
      ? `历史版本（第 ${item.revision} 版）`
      : (runId && item.payroll_period === runPeriod ? "当前核算使用" : "已保存");
    const imported = (item.source || {}).imported_at;
    return `<tr><td><strong>${escapeHtml(item.payroll_period)}</strong></td><td>${escapeHtml(item.period_start)} ～ ${escapeHtml(item.period_end)}</td><td>${escapeHtml(authoritySourceText(item))}${imported ? `<div class="small muted">导入 ${escapeHtml(fmtDate(imported))} · 确认人 ${escapeHtml(item.confirmed_by || "—")}</div>` : ""}</td><td>${escapeHtml(state)}</td></tr>`;
  }).join("");
  const detail = authorityList && authorityList.length
    ? `<details><summary>查看明细（${authorityList.length} 条）</summary><div class="table-wrap"><table class="table"><thead><tr><th>工资月份</th><th>人工周期</th><th>来源</th><th>状态</th></tr></thead><tbody>${detailRows}</tbody></table></div></details>`
    : "";
  const manual = runId
    ? `<details><summary>手工设置 ${escapeHtml(runPeriod)} 的人工月</summary>${periodAuthorityForm(runAuthority, "dashboard")}</details>`
    : "";
  return `<section id="period-authority-card" class="card"><div class="section-head"><div><p class="eyebrow">基础资料</p><h2>人工月 / 工资周期</h2><p class="muted">公司的薪资计算周期，非自然月。导入资料后对应月份自动沿用，不需要每月重复确认。</p></div><span class="status ${active.length && hasRunMonth ? "ok" : "warn"}">${active.length ? (hasRunMonth ? "已设置" : "缺本月资料") : "未导入"}</span></div>${summary}${monthLine}<div class="action-bar"><button onclick="importPeriodDocument()">导入人工月资料</button>${runId ? `<button class="secondary" onclick="setTab('materials')">返回本核算</button>` : ""}</div>${detail}${manual}</section>`;
}

async function importPeriodDocument() {
  periodDocumentReturnRun = current?.id || "";
  try {
    const picked = await api("/api/pick-period-document", { method: "POST", body: "{}" });
    if (!picked.path) return;
    periodDocumentPreview = await api(`/api/period-document/preview?path=${encodeURIComponent(picked.path)}`);
    shell(periodDocumentPreviewMarkup(), false);
  } catch (error) { showMessage(error.message); }
}

function periodDocumentPreviewMarkup() {
  const preview = periodDocumentPreview || {};
  const rows = preview.rows || [];
  const source = preview.source || {};
  const problems = preview.problems || [];
  const actionLabels = { NEW: "新增", UPDATE: "更新为资料口径", UNCHANGED: "无变化" };
  const rowHtml = rows.map((row) => `<tr><td><strong>${escapeHtml(row.label || "—")}</strong></td><td>${escapeHtml(row.weeks || "—")}</td><td>${escapeHtml(row.period_start || "?")} ～ ${escapeHtml(row.period_end || "?")}</td><td>${escapeHtml(row.payroll_period || "—")}</td><td>${escapeHtml(actionLabels[row.action] || row.action || "")}</td><td class="small muted">${escapeHtml(row.mapping_rule || "")}</td></tr>`).join("");
  return `<div class="section-head"><div><p class="eyebrow">人工月资料</p><h1>识别结果预览</h1><p class="muted">${escapeHtml(source.source_file || "")} · 识别到 ${rows.length} 条 · 年份 ${escapeHtml(String(preview.year || "未标明"))}</p></div><button class="secondary" onclick="cancelPeriodDocumentImport()">取消</button></div>${problems.length ? `<section class="card warning-card"><h2>需要先修正资料</h2>${problems.map((item) => `<p class="small warn">${escapeHtml(item)}</p>`).join("")}</section>` : ""}<section class="card"><div class="table-wrap"><table class="table"><thead><tr><th>人工月</th><th>周数</th><th>人工周期</th><th>工资月份</th><th>处理</th><th>工资月份依据</th></tr></thead><tbody>${rowHtml || '<tr><td colspan="6" class="muted">没有识别到人工月。</td></tr>'}</tbody></table></div><p class="muted small">工资月份按资料自身确定：资料给出「工资月份」列就直接采用；否则用「文档年份 + 人工月序号」（例如 2026 年第 8 个人工月 = 2026-08）。不会按周期内自然月天数占比推断；两者不一致或都无法确定时不会导入，需要先修正资料。确认后写入的是可复用的权威记录，以后同月份核算不再重复询问，课表日期只用于校验。</p><label>导入确认人<input id="period-document-confirmed-by" value="${escapeHtml(current?.af_policy_confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><div class="action-bar"><button class="secondary" onclick="cancelPeriodDocumentImport()">取消</button><button onclick="confirmPeriodDocumentImport()" ${preview.can_import ? "" : "disabled"}>${preview.can_import ? `确认导入这 ${rows.length} 条人工月` : "资料需要修正后才能导入"}</button></div></section>`;
}

function cancelPeriodDocumentImport() {
  periodDocumentPreview = null;
  if (periodDocumentReturnRun) authorityDashboard(periodDocumentReturnRun);
  else authorityDashboard();
}

async function confirmPeriodDocumentImport() {
  const person = $("#period-document-confirmed-by")?.value?.trim() || "";
  if (!person) {
    $("#period-document-confirmed-by")?.focus();
    return showMessage("请填写导入确认人。");
  }
  const preview = periodDocumentPreview || {};
  const runId = periodDocumentReturnRun;
  try {
    const result = await api("/api/period-document/import", {
      method: "POST",
      body: JSON.stringify({ path: (preview.source || {}).path || "", source_sha256: (preview.source || {}).sha256 || "", confirmed_by: person }),
    });
    const counts = result.counts || {};
    periodDocumentPreview = null;
    if (runId) {
      // 权威资料优先于本 Run 上此前手填的周期：直接改绑并重新读取排课。
      current = await api(`/api/runs/${runId}/period-authority`, { method: "POST", body: JSON.stringify({ force: true }) });
      tab = "materials";
      renderRun();
      showMessage(`已导入人工月 ${result.imported} 条（新增 ${counts.created || 0}、更新 ${counts.updated || 0}、无变化 ${counts.unchanged || 0}）；本次核算已改用 ${current.period_start} ～ ${current.period_end} 并重新读取排课。`, "success");
    } else {
      showMessage(`已导入人工月 ${result.imported} 条（新增 ${counts.created || 0}、更新 ${counts.updated || 0}、无变化 ${counts.unchanged || 0}）。`, "success");
      await authorityDashboard();
    }
  } catch (error) { await refreshAfterError(error); }
}

async function openBaseSalaryPage(runId) {
  try {
    await openRun(runId);
    tab = "materials";
    renderRun();
  } catch (error) { showMessage(error.message); }
}

async function confirmActualPeriod() {
  try {
    const payload = {
      period_start: $("#confirmed-period-start")?.value || "",
      period_end: $("#confirmed-period-end")?.value || "",
      confirmed_by: $("#confirmed-period-person")?.value?.trim() || "",
      reason: $("#confirmed-period-reason")?.value?.trim() || "",
    };
    current = await api(`/api/runs/${current.id}/period-window`, { method: "POST", body: JSON.stringify(payload) });
    current = await api(`/api/runs/${current.id}/check`, { method: "POST", body: "{}" });
    tab = (current.issue_groups || []).length ? "issues" : "payroll";
    renderRun();
    showMessage("实际核算周期已保存，并按新周期重新核对。", "success");
  } catch (error) { await refreshAfterError(error); }
}

async function resolvePeriod(decision) {
  try { current = await api(`/api/runs/${current.id}/period-check`, { method: "POST", body: JSON.stringify({ decision }) }); renderRun(); showMessage("已记录月份处理方式。", "success"); }
  catch (error) { showMessage(error.message); }
}

async function switchPeriodTo(period) {
  try {
    current = await api(`/api/runs/${current.id}/period`, { method: "POST", body: JSON.stringify({ period }) });
    renderRun();
    showMessage(`已切换到 ${period}，请继续检查材料月份和覆盖范围。`, "success");
  } catch (error) { showMessage(error.message); }
}

function gradeSupportSection(help) {
  if (!help?.available || !help.count) return "";
  return `<section class="card" id="grade-help-card"><div class="section-head"><div><p class="eyebrow">年级补齐</p><h2>有 ${help.count} 名学生暂时无法确定年级</h2><p class="muted">部分赠送、换购、特批课程没有写年级，或者当前排课表中的班级名称已经发生变化。年级会影响课时折算，因此需要先确认这些学生的年级。</p></div></div><div class="material-grid"><article class="material-card"><strong>① 从以前的排课表自动查找</strong><p class="small muted">如果这些学生以前上过正常课程，可以上传过去的排课记录。建议上传过去一年的记录，文件越完整，自动找到的学生越多。系统只提取学生年级证据，不会修改这些历史文件。</p><button class="secondary full" onclick="chooseGradeHistory()">选择历史排课表</button></article><article class="material-card"><strong>② 我自己填写</strong><p class="small muted">如果你知道学生在指定日期的年级，可以直接填写。保存后以后不需要重复填写。</p><button class="secondary full" onclick="showManualGradeForm()">手动填写年级</button></article></div><p class="small muted">每年 9 月 20 日起，系统会自动将已保存学生统一升一个年级。历史月份不会因此改变。</p><div id="grade-manual-form"></div></section>`;
}

async function chooseGradeHistory() {
  try {
    const picked = await api("/api/pick", { method: "POST", body: "{}" });
    if (!picked.path) return;
    const result = await api(`/api/runs/${current.id}/grade-history`, { method: "POST", body: JSON.stringify({ path: picked.path }) });
    current = result.run;
    renderRun();
    showMessage(`本次读取 ${result.import.direct_grade_evidence} 条有效年级记录，已自动解决 ${result.resolved} 名学生，仍有 ${result.remaining} 名需要确认。`, result.remaining ? "success" : "success");
  } catch (error) { showMessage(error.message); }
}

function showManualGradeForm() {
  const help = current.grade_help || {};
  const grades = ["一年级", "二年级", "三年级", "四年级", "五年级", "六年级", "七年级", "八年级", "九年级", "高一", "高二", "高三"];
  const rows = (help.students || []).filter(item => item.manual_allowed).map((item) => `<tr><td><strong>${escapeHtml(item.student)}</strong><div class="small muted">问题：${escapeHtml(item.student)}在 ${escapeHtml(item.first_course_date)} 上课时是几年级？</div>${item.crosses_grade_boundary ? '<div class="small warn">系统会从该日期开始，按每年9月20日自动升年级。</div>' : ""}</td><td><select class="grade-confirmation" data-student="${escapeHtml(item.student)}"><option value="">请选择</option>${grades.map(grade => `<option value="${grade}">${grade}</option>`).join("")}</select></td></tr>`).join("");
  const blocked = (help.students || []).filter(item => !item.manual_allowed).map(item => escapeHtml(item.student)).join("、");
  $("#grade-manual-form").innerHTML = `<section class="action-first"><h3>填写学生年级</h3><p class="muted small">请按每位学生显示的具体课程日期填写当时的年级。同一学生的多条课程只需填写一次，系统会按 9 月 20 日规则处理后续课程。</p><div class="table-wrap"><table class="table"><thead><tr><th>学生与课程日期</th><th>当时年级</th></tr></thead><tbody>${rows || '<tr><td colspan="2" class="muted">没有可手动填写的学生。</td></tr>'}</tbody></table></div>${blocked ? `<p class="small warn">以下课程没有填写学生姓名，无法按学生补齐：${blocked}</p>` : ""}<div class="decision-form"><label>确认人<input id="grade-confirmed-by" placeholder="填写姓名"></label></div><div class="action-bar"><button class="secondary" onclick="$('#grade-manual-form').innerHTML=''">取消</button><button onclick="saveManualGrades()">保存并继续核算</button></div></section>`;
}

async function saveManualGrades() {
  try {
    const confirmations = [...document.querySelectorAll(".grade-confirmation")].filter(node => node.value).map(node => ({ student: node.dataset.student, grade: node.value }));
    if (!confirmations.length) throw new Error("请至少选择一名学生的年级。");
    const result = await api(`/api/runs/${current.id}/grade-confirmations`, { method: "POST", body: JSON.stringify({ confirmations, confirmed_by: $("#grade-confirmed-by").value }) });
    current = result.run;
    renderRun();
    showMessage(`已保存 ${result.saved} 名学生的年级；剩余 ${result.remaining} 名待确认。`, "success");
  } catch (error) { showMessage(error.message); }
}

function coreCalculationCell(field, compact = false) {
  if (!field || typeof field !== "object") return `<div class="core-result-cell"><strong>${escapeHtml(field ?? "—")}</strong></div>`;
  const state = String(field.state || "NEEDS_INPUT").toUpperCase();
  const label = coreStateLabels[state] || escapeHtml(field.state || "缺资料");
  const className = state === "DETERMINED" ? "determined" : state === "ESTIMATED" ? "estimated" : state === "NOT_APPLICABLE" ? "not-applicable" : "needs-input";
  const evidence = Array.isArray(field.evidence) && field.evidence.length ? `<details><summary>依据</summary><div class="small muted">${field.evidence.map((item) => escapeHtml(typeof item === "object" ? Object.values(item).join(" · ") : item)).join("<br>")}</div></details>` : "";
  const reason = field.reason ? `<small>${escapeHtml(field.reason)}</small>` : "";
  const detail = compact && (reason || evidence) ? `<details><summary>查看依据</summary>${reason}${evidence}</details>` : `${reason}${evidence}`;
  return `<div class="core-result-cell ${className}"><strong>${escapeHtml(field.value ?? "—")}</strong><span>${label}</span>${detail}</div>`;
}

function coreCalculationSection() {
  const calculation = current.core_calculation;
  const rows = calculation?.rows || [];
  if (!rows.length) return "";
  const fieldKey = (row, key) => row.fields?.[key] || row.fields?.[key.toLowerCase()] || row[key] || null;
  const rendered = rows.map((row) => `<tr><td><strong>${escapeHtml(row.teacher || row.teacher_id || "—")}</strong></td><td>${coreCalculationCell(fieldKey(row, "AA"))}</td><td>${coreCalculationCell(fieldKey(row, "AC"))}</td><td>${coreCalculationCell(fieldKey(row, "AD"))}</td><td>${coreCalculationCell(fieldKey(row, "AE"))}</td><td>${coreCalculationCell(fieldKey(row, "AF"))}</td><td>${coreCalculationCell(fieldKey(row, "PART_TIME"))}</td></tr>`).join("");
  const versionNote = [current.core_rule_version_id ? `核心规则 ${current.core_rule_version_id}` : "", current.part_time_rate_version_id ? `兼职单价 ${current.part_time_rate_version_id}` : ""].filter(Boolean).join(" · ");
  return `<section class="card core-calculation-card"><div class="section-head"><div><p class="eyebrow">核心计算结果</p><h2>每位教师的核心字段</h2><p class="muted">状态为“估算”“缺资料”或“不适用”的项目不会冒充全薪通过。${escapeHtml(versionNote)}</p></div></div><div class="table-wrap"><table class="table core-calculation-table"><thead><tr><th>教师</th><th>${escapeHtml(fieldDisplayLabel("AA"))}</th><th>${escapeHtml(fieldDisplayLabel("AC"))}</th><th>${escapeHtml(fieldDisplayLabel("AD"))}</th><th>${escapeHtml(fieldDisplayLabel("AE"))}</th><th>${escapeHtml(fieldDisplayLabel("AF"))}</th><th>兼职按节课时费</th></tr></thead><tbody>${rendered}</tbody></table></div></section>`;
}

// The final fields are the single canonical result: the workbook export
// renders exactly the same object.  Reading them first is what keeps the
// screen and the exported Excel from disagreeing (the core row only carries
// AA/AC/AD/AE/AF/PART_TIME and has no M at all).
const CORE_ONLY_CODES = new Set(["AA", "AC", "AD", "AE", "AF", "PART_TIME"]);

function payrollPreviewField(row, code, fallback = null) {
  const finalField = row?.final_fields?.[code];
  if (finalField && typeof finalField === "object") return finalField;
  if (!CORE_ONLY_CODES.has(code)) {
    const core = row?.fields?.[code];
    if (core && typeof core === "object" && core.state && core.state !== "NOT_APPLICABLE") return core;
  }
  const core = row?.fields?.[code];
  if (core && typeof core === "object") return core;
  const values = { AA: row?.one_to_one, AC: row?.class_value, AD: row?.teaching_hours, AE: row?.ae, AF: row?.af, PART_TIME: row?.part_time_amount };
  return { value: values[code] ?? fallback, state: values[code] == null ? "NEEDS_INPUT" : "DETERMINED" };
}

// 字段代码 + 中文业务名称。名称来自公司工资模板与支持部工资表的正式表头，
// 这里只是同一份映射的前端副本；查不到的字段明确写“名称待确认”，不由界面起名。
const FIELD_DISPLAY_LABELS = {
  M: "实际基本工资",
  AA: "折算小时数",
  AC: "班课折算小时数",
  AD: "最终授课小时数据",
  AE: "该档每小时金额",
  AF: "总课时费",
  AG: "领航伴学课时费",
  AH: "一对一续费",
  AI: "班课续费",
  AJ: "领航续费",
  AK: "续费绩效",
  AL: "进步率奖金",
  AM: "管理团队奖",
  AN: "退费/拒收学员",
  AO: "房租",
  AP: "社保",
  AQ: "工装费",
  AR: "内部推荐奖金",
  AS: "月度激励",
  AT: "补发工资",
  AU: "考勤罚款",
  AV: "总工资数",
};

function fieldDisplayLabel(code) {
  const name = FIELD_DISPLAY_LABELS[String(code).toUpperCase()];
  return name ? `${String(code).toUpperCase()} ${name}` : `${String(code).toUpperCase()}｜名称待确认`;
}

function renewalPreviewMarkup() {
  if (tab !== "issues") return "";
  const preview = renewalMaterialPreview?.run_id === current?.id ? renewalMaterialPreview : null;
  if (!preview) return "";
  const rows = (preview.matched || []).map((item) => `<tr><td>${escapeHtml(item.teacher)}</td><td>${escapeHtml(item.AH)}</td><td>${escapeHtml(item.AI)}</td><td>${escapeHtml(item.AJ)}</td><td>${escapeHtml(item.sheet)} 第 ${escapeHtml(item.source_row)} 行</td></tr>`).join("");
  const counts = preview.match_counts || {};
  const noRows = preview.no_renewal_row || [];
  const identity = preview.identity_unmatched || [];
  const outside = preview.outside_roster || [];
  const sourceConflicts = preview.source_conflicts || [];
  const categories = `<div class="metric-grid"><div class="metric"><span>已匹配续费资料</span><strong>${escapeHtml(counts.matched ?? preview.matched.length)}</strong></div><div class="metric"><span>本月续费资料没有该教师记录</span><strong>${escapeHtml(counts.no_renewal_row ?? noRows.length)}</strong></div><div class="metric"><span>身份需要确认</span><strong>${escapeHtml(counts.identity_unmatched ?? identity.length)}</strong></div><div class="metric"><span>资料教师不在本月排课名单</span><strong>${escapeHtml(counts.outside_roster ?? outside.length)}</strong></div></div>`;
  const sections = `${noRows.length ? `<details><summary>本月续费资料没有该教师记录（${noRows.length}）</summary><p>${noRows.map((item) => escapeHtml(item.teacher)).join("、")}</p><p class="small muted">这是“无续费行”，不代表身份匹配失败，也不会自动填 0。</p></details>` : ""}${identity.length ? `<details open><summary>身份需要确认（${identity.length}）</summary>${identity.map((item) => `<p class="small bad">${escapeHtml(item.source_teacher || "来源教师")} · ${escapeHtml(item.sheet || "")} 第 ${escapeHtml(item.source_row || "?")} 行：${escapeHtml(item.reason)}${item.candidate_teachers?.length ? ` 候选：${item.candidate_teachers.map(escapeHtml).join("、")}` : ""}</p>`).join("")}</details>` : ""}${outside.length ? `<details><summary>资料教师不在本月排课名单（${outside.length}）</summary>${outside.map((item) => `<p class="small muted">${escapeHtml(item.source_teacher || "来源教师")} · ${escapeHtml(item.sheet || "")} 第 ${escapeHtml(item.source_row || "?")} 行：${escapeHtml(item.reason)}</p>`).join("")}</details>` : ""}${sourceConflicts.length ? `<details open><summary>续费合计或来源行有问题（${sourceConflicts.length}）</summary>${sourceConflicts.map((item) => `<p class="small bad">${escapeHtml(item.source_teacher || "来源教师")} · ${escapeHtml(item.sheet || "")} 第 ${escapeHtml(item.source_row || "?")} 行：${escapeHtml(item.reason)}</p>`).join("")}</details>` : ""}`;
  return `<section class="renewal-preview"><h3>本月续费资料</h3><p class="small muted">来源：${escapeHtml(preview.source_name)} · 工资月份：${escapeHtml(preview.period)} · ${escapeHtml(preview.source_rows)} 条来源</p>${categories}${sections}${rows ? `<div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>AH｜一对一续费</th><th>AI｜班课续费</th><th>AJ｜领航续费</th><th>来源行</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}${preview.can_confirm ? `<label class="inline-check"><input id="renewal-source-approved" type="checkbox" onchange="$('#renewal-confirm-button').disabled = !this.checked">我确认这张表的 ${escapeHtml(preview.period)} 记录是本次工资核算的最终有效续费来源</label><label>确认人<input id="renewal-confirmed-by" value="${escapeHtml(current.af_policy_confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><div class="action-bar"><button id="renewal-confirm-button" disabled onclick="confirmRenewalMaterial()">确认并用于本次工资</button></div>` : '<p class="small bad">身份冲突、重复来源或合计缺失尚未处理，不能确认续费来源。</p>'}</section>`;
}

async function previewRenewalMaterial() {
  try {
    const preview = await api(`/api/runs/${current.id}/renewal-preview`);
    renewalMaterialPreview = { ...preview, run_id: current.id };
    tab = "issues";
    renderRun();
    showMessage(`已找到本月 ${preview.matched.length} 位匹配教师的续费课时，请检查后确认。`, "success");
  } catch (error) { showMessage(error.message); }
}

async function confirmRenewalMaterial() {
  const preview = renewalMaterialPreview;
  if (!preview?.can_confirm || preview.run_id !== current?.id || !$("#renewal-source-approved")?.checked) return showMessage("请先核对并确认本月续费来源。");
  try {
    current = await api(`/api/runs/${current.id}/renewal-confirm`, { method: "POST", body: JSON.stringify({ source_sha256: preview.source_sha256, confirmed_by: $("#renewal-confirmed-by")?.value?.trim() || "" }) });
    renewalMaterialPreview = null;
    tab = "issues";
    renderRun();
    const counts = preview.match_counts || {};
    showMessage(`续费来源已确认：已匹配 ${counts.matched ?? preview.matched.length} 位；无续费行 ${counts.no_renewal_row ?? preview.no_renewal_row.length} 位；身份待确认 ${counts.identity_unmatched ?? preview.identity_unmatched.length} 位；不在本月排课名单 ${counts.outside_roster ?? preview.outside_roster.length} 条。`, "success");
  } catch (error) { await refreshAfterError(error); }
}

// 义务课时例外直接显示真实值，不藏在“查看例外”后面。
// 数据来自当前 Run 已确认的 AF 政策，界面不写死任何教师或小时数。
function afExceptionsMarkup() {
  const policy = current.af_policy_confirmation;
  if (!policy?.confirmed) return "";
  const exceptions = Object.entries(policy.exceptions || {});
  const rows = exceptions.map(([teacher, item]) => `<tr><td><strong>${escapeHtml(teacher)}</strong></td><td>${escapeHtml(item.obligation_hours ?? "—")} 小时</td><td>${item.deduction_enabled ? "扣减" : "不扣减"}</td><td>${escapeHtml(item.reason || "—")}</td></tr>`).join("");
  return `<details class="preview-details" open><summary>义务课时与教师例外</summary><div class="preview-secondary"><div><span>默认义务课时</span><strong>${escapeHtml(policy.default_obligation_hours ?? "—")} 小时</strong><div class="small muted">确认人：${escapeHtml(policy.confirmed_by || "—")} · ${escapeHtml(policy.reason || "")}</div></div></div>${rows ? `<div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>义务课时</th><th>是否扣减</th><th>原因</th></tr></thead><tbody>${rows}</tbody></table></div>` : '<p class="small muted">本月没有教师例外。</p>'}<div class="action-bar"><button class="secondary" onclick="setTab('materials')">查看 / 修改例外</button></div></details>`;
}

function payrollPreviewPage() {
  if (runNeedsRecalculation(current)) {
    return `<section class="card"><h2>工资结果需要重新核算</h2><p class="muted">${escapeHtml(current.recalculation_required_reason || "当前处理范围或工资基础已变化")}。旧工资结果已保留为历史记录；只有你主动点击“开始核算”后才会生成新结果。</p><div class="action-bar"><button onclick="setTab('issues')">去待处理问题并开始核算</button></div></section>`;
  }
  const generated = current.generated_payroll || {};
  const rows = generated.rows?.length ? generated.rows : (current.core_calculation?.rows || []);
  if (!rows.length) {
    return `<section class="card"><h2>工资预览尚未生成</h2><p class="muted">请先完成材料准备并自动核算。</p><div class="action-bar"><button onclick="setTab('materials')">返回材料准备</button></div></section>`;
  }
  const starAuthority = current.authority_context?.rating || {};
  const starSource = [starAuthority.source, starAuthority.effective_period, starAuthority.name].filter(Boolean).join(" · ") || "尚未绑定星级来源";
  const periodAuthority = current.period_authority || {};
  const periodRange = periodAuthority.period_start
    ? `${periodAuthority.period_start} ～ ${periodAuthority.period_end}` : "—";
  const basisPanel = `<details class="preview-details preview-basis"><summary>本期使用的依据（人工月 / 星级来源）</summary><div class="preview-secondary"><div><span>人工月 / 工资周期</span><strong>${escapeHtml(periodRange)}</strong><div class="small muted">来源：${escapeHtml(periodAuthority.source_label || "—")}${periodAuthority.confirmed_by ? ` · 确认人：${escapeHtml(periodAuthority.confirmed_by)}` : ""}</div></div><div><span>教师星级来源</span><strong>${escapeHtml(starAuthority.name || "尚未绑定")}</strong><div class="small muted">版本：${escapeHtml(starAuthority.version_id || "—")} · 生效期：${escapeHtml(starAuthority.effective_period || "—")} · 来源：${escapeHtml(starAuthority.source || "—")}</div></div></div></details>`;
  const periodNotes = [
    periodAuthority.is_fallback
      ? `<div class="banner info"><strong>周期暂按自然月兜底</strong><span>${escapeHtml(periodAuthority.payroll_period || current.period)} 还没有人工月资料，筛选与完整性暂按自然月。确认一次后该月份长期沿用。</span><button class="secondary" onclick="setTab('materials')">去确认人工月</button></div>` : "",
    current.period_check?.outside_authority
      ? `<div class="banner info"><strong>课表日期超出人工周期</strong><span>超出 ${escapeHtml(periodRange)} 的日期没有计入本期；请先确认人工周期或更正排课来源。</span><button class="secondary" onclick="setTab('materials')">去确认人工月</button></div>` : "",
  ].join("");
  const rowHtml = rows.map((row) => {
    const primaryCodes = ["M", "AA", "AC", "AD", "AE", "AF", "AV"];
    const fields = primaryCodes.map((code) => `<td>${coreCalculationCell(payrollPreviewField(row, code), true)}</td>`).join("");
    const starEvidence = (row.fields?.AE?.evidence || []).map((item) => item?.inputs?.rating).find((value) => value != null && value !== "");
    const star = row.star ?? starEvidence ?? "—";
    const blockers = (row.blockers || []).join("、");
    const secondaryLabels = { AH: fieldDisplayLabel("AH"), AI: fieldDisplayLabel("AI"), AJ: fieldDisplayLabel("AJ"), AK: fieldDisplayLabel("AK"), PART_TIME: "兼职按节课时费" };
    const secondary = ["AH", "AI", "AJ", "AK", "PART_TIME"].map((code) => `<div><span>${escapeHtml(secondaryLabels[code])}</span>${coreCalculationCell(payrollPreviewField(row, code), true)}</div>`).join("");
    const shortStatus = row.status === "FINAL" ? "已确认" : blockers ? `待确认（${(row.blockers || []).length} 项）` : "待确认";
    return `<tr><td><strong>${escapeHtml(row.teacher || row.teacher_id || "—")}</strong><div class="small muted">${escapeHtml(shortStatus)}</div><details class="preview-details"><summary>查看续费、星级与依据</summary>${blockers ? `<p class="small muted">待处理：${escapeHtml(blockers)}</p>` : ""}<div class="preview-secondary">${secondary}<div><span>教师星级（与 AE 课时单价不同）</span>${coreCalculationCell({ value: star, state: star === "—" ? "NEEDS_INPUT" : "DETERMINED", reason: starSource }, true)}</div></div></details></td>${fields}</tr>`;
  }).join("");
  const status = generated.status || (current.summary?.core_calculation_complete ? "待导出" : "待确认");
  const periodCheck = current.period_check || {};
  const periodNeedsChoice = periodCheck.conflict || (periodCheck.mismatch && !["SWITCHED", "KEPT"].includes(periodCheck.decision));
  const path = generated.path ? `<p class="small muted">最近导出：${escapeHtml(generated.path)}</p>` : "";
  const exportNote = current.mode === "GENERATE"
    ? "导出会自动选择不冲突的新文件名，绝不覆盖已有工资表。状态为草稿时仍可导出，但文件会保留待确认标记。"
    : "核对模式只对照已有工资表，不会在这里生成新的工资表。";
  const renewal = current.run_renewal_result_snapshot;
  const importedRenewal = current.material_inputs?.renewal;
  const confirmation = current.renewal_source_confirmation || {};
  const renewalCounts = confirmation.match_counts || null;
  const noRenewalRows = confirmation.no_renewal_row || [];
  const identityUnmatched = confirmation.identity_unmatched || [];
  const outsideRoster = confirmation.outside_roster || [];
  const renewalClassification = renewalCounts
    ? `已匹配续费资料 ${escapeHtml(renewalCounts.matched || 0)} 位；本月无续费记录 ${escapeHtml(renewalCounts.no_renewal_row || 0)} 位；身份需要确认 ${escapeHtml(renewalCounts.identity_unmatched || 0)} 位；续费资料有记录但本月排课未出现 ${escapeHtml(renewalCounts.outside_roster || 0)} 位。`
    : "这是旧教师范围下的确认记录；旧“未匹配”数量不再作为身份失败结论，请按本月排课名单重新分类。";
  const renewalNote = renewal
    ? `<div class="banner info"><strong>本月续费已确认并进入工资</strong><span>来源：${escapeHtml(confirmation.source_name || current.material_inputs?.renewal?.name || "续费结果表")} · 月份：${escapeHtml(renewal.period_label || current.period)} · 已绑定 ${escapeHtml(Object.keys(renewal.entries || {}).length)} 位教师 · 确认人：${escapeHtml(confirmation.actor || "—")}。AH 一对一续费、AI 班课续费、AJ 领航续费已保存；AK 续费绩效由同一快照计算。${renewalClassification}</span><button class="secondary" onclick="previewRenewalMaterial()">按本月排课名单查看续费分类</button>${noRenewalRows.length ? `<details><summary>本月无续费记录（${noRenewalRows.length} 位）</summary><p>${noRenewalRows.map((item) => escapeHtml(item.teacher)).join("、")}</p></details>` : ""}${identityUnmatched.length ? `<details open><summary>身份需要确认（${identityUnmatched.length}）</summary>${identityUnmatched.map((item) => `<p class="small bad">${escapeHtml(item.source_teacher || "来源教师")}：${escapeHtml(item.reason)}</p>`).join("")}</details>` : ""}${outsideRoster.length ? `<details><summary>资料有记录但本月排课未出现（${outsideRoster.length} 条来源）</summary>${outsideRoster.map((item) => `<p class="small muted">${escapeHtml(item.source_teacher || "来源教师")} · ${escapeHtml(item.sheet || "")} 第 ${escapeHtml(item.source_row || "?")} 行：${escapeHtml(item.reason)}</p>`).join("")}</details>` : ""}</div>`
    : importedRenewal
      ? `<div class="banner info"><strong>续费资料已导入，工资字段待确认</strong><span>系统会读取当前月份的 1V1、班课和领航合计；确认后才进入 AH、AI、AJ、AK。</span><button class="secondary" onclick="previewRenewalMaterial()">核对本月续费课时</button></div>`
      : "";
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 4 步</p><h2>工资预览</h2><p class="muted">工资月份 ${escapeHtml(current.period_label || current.period)} · ${rows.length} 位教师 · 当前状态：${escapeHtml(status)}</p></div><span class="status ${status === "FINAL" ? "ok" : "warn"}">${escapeHtml(status)}</span></div><div class="action-bar"><span class="small muted">AE 的 42/43 等数值是每小时金额；教师星级另由当期星级资料确定。</span><button class="secondary" onclick="ratingDashboard('${escapeHtml(current.id)}')">查看星级来源</button></div>${periodNotes}${basisPanel}${afExceptionsMarkup()}<div class="table-wrap"><table class="table core-calculation-table payroll-preview-table"><thead><tr><th>教师</th><th>${escapeHtml(fieldDisplayLabel("M"))}</th><th>${escapeHtml(fieldDisplayLabel("AA"))}</th><th>${escapeHtml(fieldDisplayLabel("AC"))}</th><th>${escapeHtml(fieldDisplayLabel("AD"))}</th><th>${escapeHtml(fieldDisplayLabel("AE"))}</th><th>${escapeHtml(fieldDisplayLabel("AF"))}</th><th>${escapeHtml(fieldDisplayLabel("AV"))}</th></tr></thead><tbody>${rowHtml}</tbody></table></div>${renewalNote}${renewalPreviewMarkup()}${path}<details class="preview-details"><summary>查看导出说明</summary><div class="banner info"><strong>导出说明</strong><span>${escapeHtml(exportNote)}</span></div></details><div class="action-bar"><button class="secondary" onclick="setTab('issues')">查看异常核对</button><button aria-label="导出工资表" ${current.mode === "GENERATE" && !periodNeedsChoice ? "" : "disabled"} onclick="exportPayroll()">${periodNeedsChoice ? "请先确认工资月份" : "生成工资表"}</button></div></section>`;
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

function issueResultState() {
  const groups = current.issue_groups || [];
  const teacher = filters.teacher.trim();
  return {
    groups,
    rows: groups.filter((group) => !teacher || String(group.teacher || "").includes(teacher)),
    actions: (current.user_actions || []).filter((action) => !teacher || (action.teachers || []).some((name) => String(name).includes(teacher))),
    fieldCount: current.issues?.length || groups.reduce((total, group) => total + (group.count || group.field_records?.length || 0), 0),
  };
}

function issueResultsMarkup() {
  const { groups, rows, actions, fieldCount } = issueResultState();
  const issueTable = (items) => items.length ? `<div class="table-wrap"><table class="table issues"><thead><tr><th>程度</th><th>问题</th><th>教师</th><th>影响字段</th><th>系统值</th><th>工资表值</th><th>差异</th><th><span class="sr-only">操作</span></th></tr></thead><tbody>${items.map(issueRow).join("")}</tbody></table></div>` : '<div class="empty">当前筛选条件下没有问题。</div>';
  const groupsById = new Map(rows.map((group) => [group.id, group]));
  const actionBlocks = actions.map((action) => {
    const members = (action.group_ids || []).map((id) => groupsById.get(id)).filter(Boolean);
    const subjectCount = action.subject_count_label || `${action.teacher_count || 0} 位教师`;
    return `<article class="user-action"><div><strong>${escapeHtml(action.title)}：${escapeHtml(subjectCount)}</strong><div class="small muted">${members.length ? escapeHtml(members[0].reason || "打开对应问题，查看依据并继续处理。") : "打开对应核查动作并继续处理。"}</div></div><button type="button" class="secondary" onclick="handleUserAction('${action.id}')">处理</button></article>`;
  }).join("");
  const actionSummary = actions.length
    ? `<div class="action-summary"><strong>需要完成 ${actions.length} 个核查动作</strong><span class="muted">先处理以下业务动作；教师级问题只在展开动作后显示。</span><div class="action-list">${actionBlocks}</div></div>`
    : (filters.teacher.trim() ? '<div class="empty">没有符合筛选条件的教师或待处理问题。</div>' : '<div class="empty success">当前没有需要人工处理的核算异常。</div>');
  const auditDetails = rows.length ? `<details class="audit-details"><summary>查看审计明细（${rows.length} 个业务问题，${fieldCount} 条字段记录）</summary><p class="small muted">审计明细仅用于追溯，不代表需要逐条人工处理。</p>${issueTable(rows)}</details>` : "";
  return `${actionSummary}<div class="result-count">后台记录 ${rows.length} 个业务问题（字段核查记录 ${fieldCount} 条）</div>${auditDetails}`;
}

function handleUserAction(actionId) {
  const action = (current.user_actions || []).find((item) => item.id === actionId);
  if (!action) return showMessage("这个处理项已更新，请重新检查问题列表。");
  if (action.cause === "base_salary_input") {
    tab = "issues";
    renderRun();
    document.querySelector("#todo-salary-basis-confirmed-by")?.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (action.cause === "compensation_fee_policy") {
    tab = "issues";
    renderRun();
    requestAnimationFrame(openAfPolicyExceptions);
    return;
  }
  const group = (current.issue_groups || []).find((item) => (action.group_ids || []).includes(item.id));
  if (group) evidence(group.id);
  else showMessage("没有找到对应的问题明细，请重新核对材料。");
}

function afPolicyBlock() {
  if (current.mode !== "GENERATE") return "";
  const afTeachers = [...new Set((current.core_calculation?.rows || []).map((row) => row.teacher).filter(Boolean))];
  const afExceptions = current.af_policy_confirmation?.exceptions || {};
  const exceptionRows = afTeachers.map((teacher) => { const item = afExceptions[teacher] || {}; return `<tr><td>${escapeHtml(teacher)}</td><td><input class="af-exception-enabled" data-teacher="${escapeHtml(teacher)}" type="checkbox" ${Object.keys(item).length ? "checked" : ""}></td><td><input class="af-exception-hours" data-teacher="${escapeHtml(teacher)}" type="number" min="0" step="0.01" value="${escapeHtml(item.obligation_hours ?? 30)}"></td><td><label class="inline-check"><input class="af-exception-deduct" data-teacher="${escapeHtml(teacher)}" type="checkbox" ${item.deduction_enabled !== false ? "checked" : ""}>扣除</label></td><td><input class="af-exception-reason" data-teacher="${escapeHtml(teacher)}" value="${escapeHtml(item.reason || "")}" placeholder="填写原因"></td></tr>`; }).join("");
  const confirmation = current.af_policy_confirmation;
  const confirmed = Boolean(confirmation);
  const exceptionCount = Object.keys(confirmation?.exceptions || {}).length;
  const confirmationNote = confirmed
    ? `默认惯例已按 30 小时记录。${confirmation.confirmed_by ? `确认人：${escapeHtml(confirmation.confirmed_by)}。` : ""}${exceptionCount ? `当前核算有 ${exceptionCount} 项教师例外。` : "当前核算没有例外。"}`
    : "默认惯例：适用教师按 30 小时。若个别教师不同，只录入这些教师的例外；无需逐人填写。";
  const primaryAction = confirmed
    ? '<button class="secondary" onclick="openAfPolicyExceptions()">查看/修改当前核算例外</button>'
    : '<button onclick="confirmAfPolicy()">确认默认惯例：全部按30小时扣除</button><button class="secondary" onclick="openAfPolicyExceptions()">有特殊情况 / 设置例外</button>';
  const saveLabel = confirmed ? "保存当前核算例外" : "保存默认惯例和例外";
  return `<section id="af-policy-confirmation" class="action-first af-policy-confirmation"><h3>义务课时惯例</h3><p class="muted">${confirmationNote}</p><div class="action-bar">${primaryAction}</div><details id="af-policy-exceptions"><summary>${confirmed ? "查看或修改当前核算例外" : "设置个别教师例外"}</summary><p class="small muted">默认 30 小时属于惯例；这里只维护适用于当前核算的教师例外。未勾选的教师仍使用默认惯例。</p><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>设置例外</th><th>义务课时</th><th>是否扣除</th><th>原因/备注</th></tr></thead><tbody>${exceptionRows || '<tr><td colspan="5" class="muted">核算后才会显示教师名单。</td></tr>'}</tbody></table></div><label>本次确认人<input id="af-policy-confirmed-by" value="${escapeHtml(confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><div class="action-bar"><button onclick="confirmAfPolicy()">${saveLabel}</button></div></details></section>`;
}

function scopeDecisionCards() {
  const cards = [];
  const grades = gradeSupportSection(current.grade_help);
  if (grades) cards.push(grades);
  if (current.material_inputs?.renewal && !current.run_renewal_result_snapshot && !renewalMaterialPreview) {
    const renewalMaterial = current.material_inputs.renewal;
    cards.push(`<section class="card todo-decision"><div class="section-head"><div><p class="eyebrow">续费来源</p><h3>核对本月续费资料</h3><p class="muted">${escapeHtml(renewalMaterial.name || "续费资料")} 已识别；确认后才会进入 AH / AI / AJ / AK。</p></div><span class="status warn">待预览确认</span></div><button class="secondary" onclick="previewRenewalMaterial()">预览并确认续费来源</button></section>`);
  }
  const periodMismatch = periodMismatchCard();
  const coverage = coverageWarningCard();
  if (periodMismatch) cards.push(periodMismatch);
  if (coverage) cards.push(coverage);
  if (current.period_authority?.is_fallback) cards.push(periodAuthorityCard());
  const support = current.support_department_pending_preview || {};
  if (support.status === "PENDING_CONFIRMATION") {
    const supportPreview = support.preview_snapshot || {};
    const supportProblems = [...(supportPreview.errors || []), ...(supportPreview.conflicts || [])];
    cards.push(`<section class="card todo-decision" id="todo-support-confirm"><div class="section-head"><div><p class="eyebrow">工资资料确认</p><h3>本月支持部工资资料</h3><p class="muted">${escapeHtml(support.source_name || "支持部资料")} · ${escapeHtml(support.source_sheet || "待识别工作表")} · 教师覆盖 ${escapeHtml(support.matched_count ?? "—")} 人 · 源批注 ${escapeHtml(support.comment_count ?? 0)} 条</p><p class="small muted">文件标识 ${escapeHtml(String(support.source_sha256 || "").slice(0, 12))}</p>${supportProblems.length ? `<div class="warning-list">${supportProblems.map((item) => `<p>${escapeHtml(item.code || item.message || "来源问题")}${item.teacher ? ` · ${escapeHtml(item.teacher)}` : ""}</p>`).join("")}</div>` : ""}</div><span class="status warn">${support.can_confirm ? "待确认" : "需先核实"}</span></div><label>本月确认人<input id="todo-support-confirmed-by" placeholder="填写确认人姓名"></label><div class="action-bar"><span class="small muted">确认后本月支持部资料优先成为工资权威来源。</span><button onclick="confirmSupportImport()" ${support.can_confirm ? "" : "disabled"}>确认本月工资资料</button><button class="secondary" onclick="cancelSupportCandidate()">暂缓</button></div></section>`);
  }
  const groupPending = Object.entries(current.pending_subject_group_imports || {});
  for (const [key, item] of groupPending) {
    const role = item.role || key;
    const label = item.recognized_group || (role === "science" ? "理化组" : "数学组");
    if (item.preview_required) {
      cards.push(`<section class="card todo-decision"><div class="section-head"><div><p class="eyebrow">科组资料确认</p><h3>${escapeHtml(label)} · ${escapeHtml(item.source_name || "旧版候选")}</h3><p class="muted">该资料尚未以本轮可审阅快照确认，不会进入当前工资。</p></div><span class="status warn">待预览</span></div><button class="secondary" onclick="previewExistingSubjectGroup('${escapeHtml(role)}','${escapeHtml(item.candidate_id || key)}')">继续预览</button></section>`);
      continue;
    }
    const inputId = `todo-group-confirm-${String(key).replace(/[^a-zA-Z0-9_-]/g, "")}`;
    const duplicates = item.cross_file_duplicates || [];
    cards.push(`<section class="card todo-decision"><div class="section-head"><div><p class="eyebrow">科组资料确认</p><h3>${escapeHtml(label)} · ${escapeHtml(item.source_name || "提交资料")}</h3><p class="muted">教师 ${escapeHtml(item.teacher_count || 0)} 人 · 记录 ${escapeHtml(item.record_count || 0)} 条 · 文件标识 ${escapeHtml(String(item.source_sha256 || "").slice(0, 12))}</p>${duplicates.length ? `<p class="small warn">与已确认文件重复 ${duplicates.length} 人；重复不会阻塞其它教师，字段冲突会单独列出。</p>` : ""}</div><span class="status warn">待确认</span></div><label>本次确认人<input id="${escapeHtml(inputId)}" placeholder="填写确认人姓名"></label><div class="action-bar"><button ${item.can_confirm ? "" : "disabled"} onclick="confirmSubjectGroup('${escapeHtml(role)}','${escapeHtml(item.source_sha256)}',false,'${escapeHtml(inputId)}','${escapeHtml(item.recognized_group || "")}','${escapeHtml(item.candidate_id || key)}')">确认用于本月工资</button><button class="secondary" onclick="cancelSubjectGroup('${escapeHtml(role)}','${escapeHtml(item.source_sha256)}','${escapeHtml(item.candidate_id || key)}','${escapeHtml(item.recognized_group || "")}')">暂缓</button></div></section>`);
  }
  const historyPending = current.historical_salary_reference_pending_preview || {};
  if (historyPending.status === "PENDING_CONFIRMATION") {
    const preview = historyPending.preview || {};
    const membership = preview.group_membership_preview || {};
    cards.push(`<section class="card todo-decision" id="todo-history-reference"><div class="section-head"><div><p class="eyebrow">历史工资参考组籍确认</p><h3>${escapeHtml(historyPending.source_name || "历史工资表")} · ${escapeHtml(historyPending.selected_group || "所选科组")}</h3><p class="muted">参考教师 ${escapeHtml(preview.source_people?.length || preview.rows?.length || 0)} 人；历史数据不会自动成为本月工资。</p></div><span class="status warn">待确认</span></div>${(membership.primary_members || []).length ? `<div class="banner info"><strong>主学科自动归组 ${membership.primary_members.length} 人</strong><span>${membership.primary_members.map((item) => escapeHtml(item.teacher)).join("、")}</span></div>` : ""}${(membership.secondary_candidates || []).length ? `<fieldset class="secondary-membership"><legend>请勾选实际属于${escapeHtml(historyPending.selected_group)}的小学科教师</legend>${membership.secondary_candidates.map((item) => `<label class="inline-check"><input type="checkbox" data-history-secondary value="${escapeHtml(item.teacher_id || item.teacher)}">${escapeHtml(item.teacher)}${item.subjects?.length ? `（${escapeHtml(item.subjects.join("、"))}）` : ""}</label>`).join("")}</fieldset>` : ""}${(membership.other_group_candidates || []).length ? `<details><summary>主学科已属于其他科组 ${membership.other_group_candidates.length} 人</summary><p>${membership.other_group_candidates.map((item) => `${escapeHtml(item.teacher)}：${escapeHtml(item.suggested_group)}`).join("、")}</p></details>` : ""}<label>历史参考确认人<input id="todo-historical-reference-confirmed-by" placeholder="填写确认人姓名"></label><div class="action-bar"><button onclick="confirmBaseSalaryImport()">保存历史参考与本组成员</button><button class="secondary" onclick="cancelHistoricalReferencePreview()">暂缓</button></div></section>`);
  }
  if (renewalMaterialPreview?.run_id === current?.id) {
    cards.push(`<section class="card todo-decision"><div class="section-head"><div><p class="eyebrow">续费来源确认</p><h3>核对并确认本月续费资料</h3><p class="muted">确认前不会写入 AH / AI / AJ / AK。</p></div><span class="status warn">待确认</span></div>${renewalPreviewMarkup()}<button class="secondary" onclick="deferRenewalPreview()">暂缓这份来源</button></section>`);
  }
  const references = savedHistoricalSalaryReferences();
  const supportBound = Boolean(current.support_source?.bound);
  const pendingUse = references.filter((reference) => !(reference.use_confirmations || []).length);
  if (pendingUse.length && !supportBound && historyPending.status !== "PENDING_CONFIRMATION") {
    cards.push(`<section class="card todo-decision"><div class="section-head"><div><p class="eyebrow">本月采用来源</p><h3>历史 G～L 是否暂用于本月</h3><p class="muted">每份资料可分别确认；历史参考仍不是本月权威工资资料。</p></div><span class="status warn">待确认 ${pendingUse.length} 份</span></div><label>本月确认人<input id="todo-historical-reference-confirmed-by" placeholder="填写确认人姓名"></label>${pendingUse.map((reference) => {
      const group = reference.selected_group || reference.group_membership?.group || "待确认科组";
      return `<div class="file-name"><strong>${escapeHtml(group)} · ${escapeHtml(reference.source_name || "历史工资参考")}</strong><span class="small muted">${escapeHtml(String(reference.source_sha256 || "").slice(0, 10))}</span><button onclick="useHistoricalSalaryReference('${escapeHtml(reference.source_sha256 || "")}','${escapeHtml(group)}')">仅采用本月 G～L</button></div>`;
    }).join("")}<p class="small muted">教师重合且同字段数值冲突时，系统会停止本次采用，不会覆盖已确认值。</p></section>`);
  }
  const unknownBasis = (current.employment?.teachers || []).filter((item) => item.salary_basis === "SOURCE_UNKNOWN");
  if (unknownBasis.length) {
    cards.push(`<section class="card todo-decision"><div class="section-head"><div><p class="eyebrow">工资基础状态</p><h3>有 ${unknownBasis.length} 位教师尚不能判断工资基础</h3><p class="muted">资料缺失不等于兼职/按课时。请按本组实际情况选择；本组无底薪人员的最终金额只从组表读取。</p></div><span class="status warn">待确认</span></div><label>确认人<input id="todo-salary-basis-confirmed-by" placeholder="填写确认人姓名"></label><div class="table-wrap"><table class="table"><thead><tr><th>教师</th><th>工资基础</th></tr></thead><tbody>${unknownBasis.map((item) => `<tr data-salary-basis-row data-teacher="${escapeHtml(item.teacher)}" data-teacher-id="${escapeHtml(item.teacher_id || item.teacher)}"><td>${escapeHtml(item.teacher)}</td><td><select class="todo-salary-basis"><option value="SOURCE_UNKNOWN" selected>资料未知</option><option value="HAS_BASE_SALARY">有底薪（随后需有来源）</option><option value="HOURLY_SUBMISSION_ONLY">明确无底薪，按组表结果</option></select></td></tr>`).join("")}</tbody></table></div><button onclick="confirmSalaryBasisBatch()">保存工资基础确认</button></section>`);
  }
  return cards.length ? `<div class="todo-decisions">${cards.join("")}</div>` : "";
}

async function cancelHistoricalReferencePreview() {
  try {
    current = await api(`/api/runs/${current.id}/base-salary-reference-cancel`, { method: "POST", body: JSON.stringify({}) });
    baseSalaryImportPreview = null;
    renderRun();
    showMessage("已暂缓历史工资参考；原文件保留。", "info");
  } catch (error) { await refreshAfterError(error); }
}

function deferRenewalPreview() {
  current.ui_deferred_todo_keys = [...new Set([...(current.ui_deferred_todo_keys || []), "renewal-source"])];
  renewalMaterialPreview = null;
  renderRun();
  showMessage("已暂缓续费来源确认；原始资料保留，未写入本月续费工资项目。", "info");
}

async function confirmSalaryBasisBatch() {
  const confirmedBy = $("#todo-salary-basis-confirmed-by")?.value?.trim() || "";
  if (!confirmedBy) return showMessage("请填写工资基础确认人。");
  const salary_basis_updates = [...document.querySelectorAll("[data-salary-basis-row]")].map((row) => ({
    teacher_id: row.dataset.teacherId, teacher: row.dataset.teacher,
    state: row.querySelector(".todo-salary-basis")?.value || "SOURCE_UNKNOWN",
    group: "",
    reason: "负责人在待处理问题中确认工资基础状态。",
  })).filter((item) => item.state !== "SOURCE_UNKNOWN");
  if (!salary_basis_updates.length) return showMessage("没有选择新的工资基础状态。", "info");
  try {
    const result = await api(`/api/runs/${current.id}/staff-batch`, { method: "POST", body: JSON.stringify({ confirmed_by: confirmedBy, salary_basis_updates }) });
    current = result.run;
    tab = "issues";
    renderRun();
    showMessage(`已保存 ${result.salary_basis_confirmed} 位教师的工资基础状态。`, "success");
  } catch (error) { await refreshAfterError(error); }
}

function issuesPage() {
  const needsRecalculation = runNeedsRecalculation(current);
  const recalculationBanner = needsRecalculation
    ? `<div class="banner info"><strong>需要重新核算</strong><span>${escapeHtml(current.recalculation_required_reason || "范围或工资基础已变化")}。旧问题不作为当前结果；下方资料和确认事项仍可继续处理。点击“开始核算”才会重新读取并计算。</span></div>`
    : "";
  const issueResults = needsRecalculation
    ? '<div id="issues-content"><p class="small muted">当前问题清单将在你开始核算后生成。</p></div>'
    : `<div id="issues-content">${issueResultsMarkup()}</div>`;
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">第 3 步</p><h2>待处理问题</h2><p class="muted">所有需要确认、选择、接受或暂缓的事项都集中在这里；处理后保持当前位置。</p></div><button onclick="recheck()">${needsRecalculation || !current.core_calculation?.rows?.length ? "开始核算" : "重新核算"}</button></div>${recalculationBanner}${scopeDecisionCards()}<div class="filters"><label for="filter-teacher">教师<input id="filter-teacher" placeholder="输入教师姓名" value="${escapeHtml(filters.teacher)}" oninput="updateFilters(event)" oncompositionend="updateFilters(event)"></label></div>${baseSalaryTodoCard()}${issueResults}${afPolicyBlock()}<div id="issue-detail"></div></section>`;
}

function baseSalaryTodoCard() {
  return current.mode === "GENERATE" && !current.base_salary_input_snapshot && !current.base_salary_deferred && (current.employment?.salary_basis_counts?.SOURCE_UNKNOWN || 0) > 0
    ? `<section class="action-first base-salary-action"><h3>导入基本工资</h3><p class="muted">本月支持部资料优先；历史工资先作为参考。暂不录入时，M 和总工资保持待补充，核算稍后由你统一启动。</p><div class="action-bar"><button onclick="setTab('base-salary')">查看工资来源选项</button><button class="secondary" onclick="showMessage('可以稍后从材料准备页补充；当前不会按 0 计算。', 'success')">稍后补充</button></div><label class="person-field">暂不录入确认人<input id="defer-base-confirmed-by" value="${escapeHtml(current.af_policy_confirmation?.confirmed_by || "")}" placeholder="填写姓名"></label><div class="action-bar"><button class="secondary" onclick="deferBaseSalaryQuick()">暂不录入</button></div></section>`
    : "";
}

function issueRow(group) {
  const severity = group.severity_rank <= 1 ? "bad" : group.severity_rank === 2 ? "warn" : "ok";
  return `<tr><td><span class="${severity}">${escapeHtml(group.severity_label)}</span></td><td>${escapeHtml(group.title)}<div class="small muted">${escapeHtml(group.decision_label || "待处理")}</div></td><td>${escapeHtml(group.teacher)}</td><td>${escapeHtml((group.fields || []).join("、"))}</td><td>${escapeHtml(group.expected ?? "—")}</td><td>${escapeHtml(group.actual ?? "—")}</td><td>${escapeHtml(group.difference ?? "—")}</td><td><button class="quiet" aria-label="查看 ${escapeHtml(group.teacher)}：${escapeHtml(group.title)} 的明细" onclick="evidence('${group.id}')">查看明细</button></td></tr>`;
}

function updateFilters(event = null) {
  if (event?.isComposing) return;
  filters.teacher = $("#filter-teacher")?.value || "";
  const content = $("#issues-content");
  if (content) content.innerHTML = issueResultsMarkup();
}

function openAfPolicyExceptions() {
  const details = $("#af-policy-exceptions");
  if (!details) return;
  details.open = true;
  details.scrollIntoView?.({ behavior: "smooth", block: "nearest" });
}

async function confirmAfPolicy() {
  const buttons = [...document.querySelectorAll(".af-policy-confirmation button")];
  const original = buttons.map((button) => button.textContent);
  buttons.forEach((button) => { button.disabled = true; button.textContent = "正在保存…"; });
  try {
    const person = $("#af-policy-confirmed-by")?.value?.trim();
    if (!person) throw new Error("请填写确认人。");
    const exceptions = {};
    document.querySelectorAll(".af-exception-enabled:checked").forEach((node) => {
      const teacher = node.dataset.teacher;
      exceptions[teacher] = { obligation_hours: Number(document.querySelector(`.af-exception-hours[data-teacher="${CSS.escape(teacher)}"]`)?.value || 30), deduction_enabled: document.querySelector(`.af-exception-deduct[data-teacher="${CSS.escape(teacher)}"]`)?.checked !== false, reason: document.querySelector(`.af-exception-reason[data-teacher="${CSS.escape(teacher)}"]`)?.value?.trim() || "" };
    });
    current = await api(`/api/runs/${current.id}/af-policy`, { method: "POST", body: JSON.stringify({ default_obligation_hours: 30, exceptions, confirmed_by: person, reason: Object.keys(exceptions).length ? "普通教师按30小时扣除；已记录个别特殊情况。" : "本月没有义务课时特殊情况。" }) });
    renderRun(); showMessage("已确认本月普通全职教师按30小时扣除，特殊人员可另设例外。", "success");
  } catch (error) { showMessage(error.message); }
  finally { buttons.forEach((button, index) => { if (button.isConnected) { button.disabled = false; button.textContent = original[index]; } }); }
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
    const panel = typeof document.createElement === "function" ? document.querySelector("#issue-detail .detail-panel") : null;
    if (panel) {
      const breadcrumb = document.createElement("div");
      breadcrumb.className = "issue-breadcrumb";
      breadcrumb.textContent = `待处理问题 > ${group.teacher} > ${group.title}`;
      panel.prepend(breadcrumb);
      const locationActions = document.createElement("div");
      locationActions.className = "issue-location-actions";
      locationActions.innerHTML = `<button class="secondary" type="button">返回问题列表</button><button type="button">保存并处理下一项</button>`;
      const [returnButton, nextButton] = locationActions.querySelectorAll("button");
      returnButton.addEventListener("click", () => { $("#issue-detail").innerHTML = ""; document.querySelector("#issues-content")?.scrollIntoView({ behavior: "smooth", block: "start" }); });
      nextButton.addEventListener("click", () => decide(id, true));
      panel.prepend(locationActions);
    }
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
  return `<section class="card"><div class="section-head"><div><p class="eyebrow">人工确认</p><h2>管理岗位确认</h2><p class="muted">系统只提供可靠事实；当前没有可靠自动数据的项目由负责人填写最终确认值。</p></div></div><div class="table-wrap"><table class="table management"><thead><tr><th>项目</th><th>系统参考值</th><th>人工最终确认值</th></tr></thead><tbody>${fields.map((field) => `<tr><td>${field}</td><td class="muted">暂无可靠自动数据</td><td><input id="m-${field}" value="${escapeHtml(values[field] || "")}" placeholder="填写确认值或说明"></td></tr>`).join("")}</tbody></table></div><label class="person-field">确认人<input id="m-person" value="${escapeHtml(person)}" placeholder="填写姓名"></label><div class="action-bar"><span class="muted small">这里不会自动推荐数值，也不会修改工资表。</span><button onclick="saveManagement()">保存人工确认</button></div></section>`;
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
  if (periodNeedsDecision()) {
    tab = "materials";
    renderRun();
    showMessage("请先确认材料对应的工资月份，再开始核对。");
    return;
  }
  const release = markBusy("正在核对…");
  try { current = await api(`/api/runs/${current.id}/check`, { method: "POST", body: "{}" }); tab = (current.issue_groups || []).length ? "issues" : (current.mode === "GENERATE" ? "payroll" : "issues"); renderRun(); showMessage("已重新核对全部材料。", "success"); }
  catch (error) { await refreshAfterError(error); }
  finally { release(); }
}

function markBusy(label) {
  const button = document.activeElement?.tagName === "BUTTON" ? document.activeElement : null;
  if (!button) return () => {};
  const original = button.textContent;
  button.disabled = true;
  button.textContent = label;
  return () => { if (button.isConnected) { button.disabled = false; button.textContent = original; } };
}

async function preparePayrollPreview() {
  if (periodNeedsDecision()) {
    tab = "materials";
    renderRun();
    showMessage("请先确认材料对应的工资月份，再开始核算。");
    return;
  }
  const release = markBusy("正在自动核算…");
  try {
    current = await api(`/api/runs/${current.id}/preview`, { method: "POST", body: "{}" });
    tab = (current.issue_groups || []).length ? "issues" : "payroll";
    renderRun();
    showMessage((current.issue_groups || []).length ? "自动核算已完成，请先处理异常，再打开工资预览。" : "自动核算已完成，请检查工资预览后导出。", "success");
  } catch (error) { await refreshAfterError(error); }
  finally { release(); }
}

async function refreshAfterError(error) {
  try { current = await api(`/api/runs/${current.id}`); renderRun(); } catch (_) { /* retain current screen */ }
  showMessage(error.message);
}

async function decide(id, advance = false) {
  const pendingQueueBeforeSave = (current.issue_groups || [])
    .filter((group) => group.id !== id && groupHasPendingUserAction(group))
    .map((group) => group.id);
  try {
    current = await api(`/api/runs/${current.id}/decisions`, { method: "POST", body: JSON.stringify({ issue_id: id, action: $("#decision").value, person: $("#person").value, reason: $("#reason").value, fingerprint: detailBasisToken }) });
    const groups = current.issue_groups || [];
    const next = advance
      ? pendingQueueBeforeSave.map((nextId) => groups.find((item) => item.id === nextId)).find((item) => item && groupHasPendingUserAction(item)) || groups.find((item) => item.id !== id && groupHasPendingUserAction(item))
      : groups.find((item) => item.id === id);
    renderRun();
    if (next) await evidence(next.id);
    else { tab = "issues"; renderRun(); }
    showMessage(advance ? "处理意见已保存，仍停留在待处理问题。" : "处理意见已保存；可继续在待处理问题查看状态。", "success");
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
  const release = markBusy("正在导出报告…");
  try {
    const response = await fetch(`/api/runs/${current.id}/export.csv`, { headers: { "X-Payroll-Token": token } });
    if (!response.ok) { const payload = await response.json(); throw new Error(payload.error || "报告导出未完成。"); }
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `工资核对报告_${current.period}.csv`; anchor.click(); URL.revokeObjectURL(url);
    showMessage("核对报告已导出。", "success");
  } catch (error) { showMessage(error.message); }
  finally { release(); }
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
    shell(`<section class="section-head"><div><p class="eyebrow">教师个人工资表</p><h1>多表合并成标准工资表</h1><p class="muted">单个老师的表、多个老师的表、已汇总的总表，都先转成标准内部数据，再生成统一工资表。系统不复制粘贴单元格。</p></div><button class="secondary" onclick="home()">返回工作台</button></section><section class="card"><h2>待上传</h2><p class="muted small">可反复点击添加；格式有歧义时系统会停下来让你确认，确认过的格式下次自动复用。</p><div class="action-bar"><button id="add-payroll-sheet" class="secondary" onclick="addSheetPath()">添加工资表</button><span class="muted small">已添加 ${sheetPaths.length} 份</span><button ${sheetPaths.length ? "" : "disabled"} onclick="importSheets()">导入并合并</button></div></section><section class="card"><h2>批次</h2><div class="table-wrap"><table class="table"><thead><tr><th>月份</th><th>状态</th><th>文件数</th><th>标准工资表</th><th></th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">暂无批次。</td></tr>'}</tbody></table></div></section>`, true);
  } catch (error) { showMessage(error.message); }
}

async function addSheetPath() {
  const button = $("#add-payroll-sheet");
  if (button) { button.disabled = true; button.textContent = "正在选择…"; }
  try { const picked = await api("/api/pick", { method: "POST", body: "{}" }); if (picked.path) { sheetPaths.push(picked.path); await payrollSheetsPage(); } }
  catch (error) { showMessage(error.message); }
  finally { if (button) { button.disabled = false; button.textContent = "添加工资表"; } }
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
// 历史班型规则：仅用于解释旧核算；新核算统一由“核心规则面板”绑定规则包。
async function classTypeRulesPage(runId = "") {
  try {
    const versions = await api("/api/class-type-rules");
    const summarize = (rules) => Object.entries(rules?.special_class_coefficients || {}).map(([name, table]) => `${name}（${Object.entries(table || {}).map(([count, value]) => `${count}人=${value}`).join("、")}）`).join("；") || "—";
    const rows = versions.map((item) => `<tr><td>${escapeHtml(item.id)}</td><td>${escapeHtml(item.effective_from)} ～ ${escapeHtml(item.effective_to)}</td><td>${escapeHtml(item.status || "ACTIVE")}</td><td>${escapeHtml(summarize(item.rules))}</td><td>${escapeHtml(item.source || "")}</td></tr>`).join("");
    shell(`<div class="section-head"><div><p class="eyebrow">历史兼容</p><h1>历史班型规则</h1><p class="muted">这里只读展示旧核算 的规则快照。新核算请进入“核心规则面板”，它是唯一可编辑、唯一用于新核算 的规则入口。</p></div><button class="secondary" onclick="authorityDashboard('${runId}')">返回基础资料</button></div><section class="card"><h2>历史版本</h2><div class="table-wrap"><table class="table"><thead><tr><th>版本</th><th>生效期</th><th>状态</th><th>特殊班型（班型 × 实到人数）</th><th>来源</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="muted">暂无历史版本。</td></tr>'}</tbody></table></div></section>`, false);
  } catch (error) { showMessage(error.message); }
}

// ---------------------------------------------------------------------------
// 生成模式：同一套 Core 结果直接渲染成标准工资表（不复制任何提交表）
async function exportPayroll() {
  const release = markBusy("正在生成文件…");
  let suggested = "";
  const filename = `工资表-${current.period}.xlsx`;
  try { suggested = (await api(`/api/default-export-path?filename=${encodeURIComponent(filename)}`)).path; } catch (_) { suggested = filename; }
  const output = suggested || filename;
  try {
    const result = await api(`/api/runs/${current.id}/generate`, { method: "POST", body: JSON.stringify({ output_path: output, production: true }) });
    const blockers = [...new Set(result.blockers || [])];
    showMessage(result.status === "FINAL" ? `已生成标准工资表，保存在：${result.path}` : `已生成草稿，仍有待确认项：${blockers.join("、")}`, result.status === "FINAL" ? "success" : "error");
    await openRun(current.id);
    tab = "payroll";
    renderRun();
  } catch (error) {
    if (String(error.message).includes("尚未设置公司工资模板")) {
      const runId = current.id;
      await authorityDashboard(runId, "template");
      showMessage("请先选择公司工资模板；保存后会返回当前工资预览。");
    } else showMessage(error.message);
  }
  finally { release(); }
}

// Backward-compatible name for callers from older local pages.
const generatePayroll = exportPayroll;

// Local browser drag/drop uses the same inspected, read-only import path as the
// native picker.  The uploaded copy is kept in the local run data directory.
function bindMaterialDropZones() {
  if (!window.__payrollDropGuard) {
    window.__payrollDropGuard = true;
    document.addEventListener("dragover", (event) => event.preventDefault());
    document.addEventListener("drop", (event) => {
      if (!event.target?.closest?.("[data-drop-role]")) event.preventDefault();
    });
  }
  document.querySelectorAll("[data-drop-role]").forEach((zone) => {
    zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.style.borderColor = "#1f6feb"; });
    zone.addEventListener("dragleave", () => { zone.style.borderColor = ""; });
    zone.addEventListener("drop", async (event) => {
      event.preventDefault(); zone.style.borderColor = "";
      const files = [...(event.dataTransfer?.files || [])];
      if (zone.dataset.dropRole === "support") {
        if (files.length !== 1) return showMessage("请一次预览一份支持部工资资料。");
        await previewSupportFile({ target: { files } });
      } else if (files.length) await uploadMaterialFiles(zone.dataset.dropRole, files);
    });
    zone.addEventListener("paste", async (event) => {
      const files = [...(event.clipboardData?.files || [])];
      if (!files.length) {
        files.push(...[...(event.clipboardData?.items || [])]
          .filter((item) => item.kind === "file")
          .map((item) => item.getAsFile?.())
          .filter(Boolean));
      }
      if (files.length) {
        event.preventDefault();
        if (zone.dataset.dropRole === "support") {
          if (files.length !== 1) return showMessage("请一次预览一份支持部工资资料。");
          await previewSupportFile({ target: { files } });
        } else await uploadMaterialFiles(zone.dataset.dropRole, files);
      }
    });
    zone.addEventListener("click", () => {
      if (zone.dataset.dropRole === "support") document.querySelector("#support-material-file")?.click();
      else choose(zone.dataset.dropRole);
    });
  });
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunk = 0x8000;
  for (let index = 0; index < bytes.length; index += chunk) binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
  return btoa(binary);
}

function setMaterialBusy(role, busy) {
  const zone = document.querySelector(`[data-drop-role="${role}"]`);
  if (!zone) return;
  zone.setAttribute("aria-busy", busy ? "true" : "false");
  zone.textContent = busy ? "正在读取并识别…" : (role === "package" ? "拖入辅助资料；工资资料和学科组提交表仍需分别确认" : "拖入文件，或直接粘贴");
  zone.style.opacity = busy ? "0.65" : "";
  zone.style.pointerEvents = busy ? "none" : "";
}

async function uploadMaterialFiles(role, files) {
  if (materialBusy.has(role)) return;
  materialBusy.add(role); setMaterialBusy(role, true);
  try {
    const selectedGroup = role === "subject_group" ? ($("#subject-group-selected-group")?.value || (selectedRunGroups(current).length === 1 ? selectedRunGroups(current)[0] : "")) : "";
    if (role === "subject_group" && !selectedGroup) throw new Error("请先选择这份资料所属的科组。");
    for (const file of files) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      const uploaded = await api("/api/upload", { method: "POST", body: JSON.stringify({ name: file.name, content_base64: bytesToBase64(bytes) }) });
      const result = await api(`/api/runs/${current.id}/material`, { method: "POST", body: JSON.stringify({ kind: role, path: uploaded.path, selected_group: selectedGroup }) });
      current = result.run;
    }
    renderRun();
    showMessage(role === "subject_group" ? "学科组资料已解析为预览；确认前不会进入工资。" : files.length > 1 ? `已读取 ${files.length} 份材料并自动归类。` : "文件已识别并放入对应材料。", "success");
  } catch (error) { showMessage(error.message); }
  finally { materialBusy.delete(role); }
}

// Keep the existing material card markup and add a small, accessible drop target.
function materialCard(material) {
  const copy = roleCopy[material.role];
  const file = material.file;
  const stateClass = material.state === "失效" ? "bad" : file ? "ok" : material.required ? "warn" : "muted";
  const stateText = material.state === "失效" ? "● 已变化，需重新选择" : file ? "✓ 已识别" : material.required ? "○ 必需材料" : "可稍后补充";
  const risk = file ? [file.missing_cache ? `${file.missing_cache} 个公式结果不可读取` : "", file.external_references ? `${file.external_references} 处依赖其他文件` : ""].filter(Boolean) : [];
  const busy = materialBusy.has(material.role);
  return `<article class="material-card ${material.state === "失效" ? "stale" : ""}"><div class="material-top"><strong>${escapeHtml(copy[0])}</strong><span class="${stateClass}">${busy ? "正在读取…" : stateText}</span></div><p class="small muted">${escapeHtml(copy[2])}</p><div data-drop-role="${escapeHtml(material.role)}" tabindex="0" role="button" aria-label="拖入${escapeHtml(copy[0])}文件" class="drop-zone" aria-busy="${busy ? "true" : "false"}">${busy ? "正在读取并识别…" : "拖入文件，或直接粘贴"}</div>${file ? `<div class="file-name">${escapeHtml(file.name)}</div><div class="facts"><span>${file.records} 条记录</span><span>${file.teachers} 名教师</span></div>${risk.length ? `<p class="small warn">⚠ ${risk.join("；")}</p>` : ""}<details><summary>查看文件信息</summary><p class="small muted">工作表：${file.sheets.map(escapeHtml).join("、")}<br>文件标识：${file.sha256.slice(0, 10)}</p></details>` : '<div class="empty compact">尚未选择文件</div>'}<button class="secondary full" ${busy ? "disabled" : ""} onclick="choose('${material.role}')">${escapeHtml(copy[1])}</button></article>`;
}

async function importMaterialPath(role, path) {
  if (["subject_group", "renewal", "refund", "package"].includes(role)) {
    const selectedGroup = role === "subject_group" ? ($("#subject-group-selected-group")?.value || (selectedRunGroups(current).length === 1 ? selectedRunGroups(current)[0] : "")) : "";
    if (role === "subject_group" && !selectedGroup) throw new Error("请先选择这份资料所属的科组。");
    const result = await api(`/api/runs/${current.id}/material`, { method: "POST", body: JSON.stringify({ kind: role, path, selected_group: selectedGroup }) });
    current = result.run;
    renderRun();
    showMessage(role === "subject_group" ? "学科组资料已生成预览；负责人确认前不会参与工资。" : "文件已识别并放入对应材料。", "success");
    return;
  }
  const inspected = await api("/api/inspect", { method: "POST", body: JSON.stringify({ path }) });
  if (role === "schedule") {
    let preview = null;
    try { preview = await api(`/api/import-mapping?path=${encodeURIComponent(path)}&role=schedule&period=${encodeURIComponent(current.period)}`); } catch (_) { preview = null; }
    if (preview && preview.status !== "KNOWN_LAYOUT" && preview.status !== "MAPPED") return mappingPage(path, role, preview);
    if (preview && preview.status === "MAPPED" && preview.profile_id) showMessage("已按之前确认过的格式识别字段。", "success");
  }
  if (!inspected.recognized && role !== "schedule") throw new Error(`无法识别这张表。检测到的工作表：${inspected.sheets.join("、") || "无"}。${inspected.missing.join("；")}`);
  current = await api(`/api/runs/${current.id}/files`, { method: "POST", body: JSON.stringify({ role, path }) });
  showMessage(`已将文件识别为“${roleCopy[role][0]}”。`, "success");
  renderRun();
}

async function previewExistingSubjectGroup(role, candidateId = "") {
  const pendingEntries = Object.entries(current.pending_subject_group_imports || {});
  const pendingEntry = candidateId
    ? pendingEntries.find(([key, item]) => key === candidateId || item.candidate_id === candidateId)
    : pendingEntries.find(([, item]) => item.role === role && item.preview_required);
  if (candidateId && !pendingEntry) return showMessage("这份待处理资料已变化，请刷新后重新选择。", "error");
  const pending = pendingEntry?.[1];
  const file = pending ? null : current.files?.[role];
  const path = pending?.source_path || file?.path;
  if (!path) return showMessage("找不到这份学科组资料，请重新选择文件。");
  try {
    const pendingGroup = pending?.recognized_group || pendingEntries.find(([, item]) => item.role === role)?.[1]?.recognized_group;
    const group = current.operator_role === "SUBJECT_LEADER" ? (pendingGroup || file?.recognized_group || (selectedRunGroups(current).length === 1 ? selectedRunGroups(current)[0] : "")) : (file?.recognized_group || pendingGroup || { math: "数学组", science: "理化组" }[role]);
    if (!group) return showMessage("联合组长请先明确选择这份资料所属的科组，再重新预览。", "error");
    const result = await api(`/api/runs/${current.id}/material`, { method: "POST", body: JSON.stringify({ kind: "subject_group", path, selected_group: group }) });
    current = result.run;
    renderRun();
    showMessage("预览已更新；请核对教师名单后确认，当前工资尚未使用该预览。", "success");
  } catch (error) { showMessage(error.message); }
}

async function confirmSubjectGroup(role, sourceSha256, replaceExisting = false, confirmInputId = "", selectedGroup = "", candidateId = "") {
  const actor = (confirmInputId ? document.getElementById(confirmInputId) : document.querySelector(`#subject-group-confirmed-by-${CSS.escape(role)}`))?.value?.trim() || "";
  if (!actor) return showMessage("请填写本次学科组提交表确认人。");
  const pending = Object.entries(current.pending_subject_group_imports || {}).find(([key, item]) =>
    item.role === role && item.source_sha256 === sourceSha256
    && (!selectedGroup || item.recognized_group === selectedGroup)
    && (!candidateId || key === candidateId || item.candidate_id === candidateId)
  )?.[1];
  if (!pending?.can_confirm || pending.source_sha256 !== sourceSha256) return showMessage("预览已变化或无法安全匹配，请重新预览。");
  try {
    const result = await api(`/api/runs/${current.id}/subject-group-confirm`, { method: "POST", body: JSON.stringify({ role, source_sha256: sourceSha256, selected_group: pending.recognized_group || selectedGroup, candidate_id: pending.candidate_id || candidateId, confirmed_by: actor, replace_existing: replaceExisting }) });
    current = result.run;
    renderRun();
    showMessage("学科组提交表已确认并用于本月工资；教师名单仍以人工月排课表为准。", "success");
  } catch (error) { await refreshAfterError(error); }
}

async function cancelSubjectGroup(role, sourceSha256 = "", candidateId = "", selectedGroup = "") {
  try {
    current = await api(`/api/runs/${current.id}/subject-group-cancel`, { method: "POST", body: JSON.stringify({ role, source_sha256: sourceSha256, candidate_id: candidateId, selected_group: selectedGroup }) });
    renderRun();
    showMessage("未确认的学科组资料已取消，不会进入本月工资。", "info");
  } catch (error) { await refreshAfterError(error); }
}

async function choose(role) {
  if (materialBusy.has(role)) return;
  materialBusy.add(role);
  try {
    const picked = await api("/api/pick", { method: "POST", body: "{}" });
    if (picked.path) await importMaterialPath(role, picked.path);
  } catch (error) { showMessage(error.message); }
  finally { materialBusy.delete(role); }
}
