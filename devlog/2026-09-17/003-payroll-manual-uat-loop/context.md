# Context

## USER OBSERVATION

用户提供了真实 Payroll 手工 UAT 的原始观察：教师筛选输入、51 位教师详情入口、特殊情况双向确认、30 小时动作反馈、待处理页就地操作、预览状态表达/滚动、以及公司工资模板导出回归。原文已落盘到 `docs/uat/2026-09-17/evidence/PAYROLL_MANUAL_UAT_RAW_2026-09-17.md`。

## CONFIRMED FACT

此前已经完成公司真实工资模板恢复，模板恢复 UAT 和代码回归通过；本轮新增原始 UAT 观察不能被改写成“需要用户重新提供模板”。现有规范化验收合同是 `docs/uat/2026-09-17/PAYROLL_MANUAL_UAT_2026-09-17.md`，真实产品代码在当前 Payroll worktree。

## TECHNICAL ASSESSMENT

本轮应由 Ralph 从磁盘证据读取原始观察、规范化 UAT、模板恢复证据和当前实现，建立/更新 issue ledger，区分真实技术缺陷、已修复模板回归和真正 Human Boundary。不得凭观察猜测根因，也不得以自创标准工资表绕过模板安全门。

## REJECTED ASSUMPTIONS

- 不把现有真实公司模板重新归类为 HUMAN_REQUIRED。
- 不要求用户再次绑定或上传已经被系统历史证据确认的模板。
- 不把用户的原始观察压缩成另一套需求后丢弃原文。
- 不把普通 UI、解析、测试或导出技术问题升级为人工业务决策。

## DECISION

原始观察作为不可改写 evidence 输入 Ralph；规范化 UAT 作为验收合同；所有 ROOT_CAUSE/FIX/TEST/STATUS 另行落盘。先保持现有 Payroll 业务边界，修真实 UAT 阻断并执行验证。

## UNKNOWN / OPEN RISKS

- 30 小时确认失败的具体运行时错误仍须以当前环境日志和代码证据确认。
- 教师筛选、待处理卡交互、预览状态/滚动的真实实现位置及可回归验证路径需由 Ralph 独立定位。
- 公司模板已恢复，但本轮仍需确保后续 Run 稳定复用且导出结构不回归。
