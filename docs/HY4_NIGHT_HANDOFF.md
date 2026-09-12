# HY4 Night Handoff（2026-09-12）

本文件用于 Luna 或其他 agent 从 GitHub 直接接手。

- **BRANCH** = `night/hy4-uat-20260912`
- **WORKTREE** = `/private/tmp/education-payroll-night-hy4-uat`（独立，未触碰任何其他 worktree）
- **BASE** = `361774c release: prepare v0.21.0-rc1 mac core`
- **LAST_SAFE_COMMIT** = `d57d037 fix: keep engineering concepts out of user-facing UI copy`
- **PUSHED** = YES（`origin/night/hy4-uat-20260912`）
- **TESTS** = 226 passed（全量）
- **LUNA_HANDOFF_READY** = YES

---

## WORK_COMPLETED

1. `docs/UAT_BASELINE.md`：19 条真人 UAT 验收基线（含状态与证据）
2. `docs/DEVELOPMENT_PRINCIPLES.md`：20 条开发原则
3. `README.md`：增加"重要任务开始前请先阅读"入口
4. **默认核算月份**（P0）：20 日前默认上月、20 日起默认本月
   - `payroll_core/period.py::default_period_for(today)`（时钟注入，不读机器时间）
   - 前端 `defaultPayrollPeriod(now)`，同一规则；node 测试覆盖真实渲染器
5. **上传课表月份 vs UI 月份冲突**（P0）
   - `service._period_evidence()`：按**文件内上课日期**判断月份，文件名仅辅助
   - 导入**不拒绝、不静默改月份**，只生成 `period_check`（mismatch/PENDING）
   - `service.change_period()` / `resolve_period_check()`：切换或保留两个明确动作
   - 切换后：文件保留、状态保留、不要求重新上传、状态为 FILES_READY 可继续
6. **日期覆盖完整性 warning**（P0）
   - `coverage_for()`：最早/最晚日期、跨月、缺尾
   - 缺尾是 warning 不是 blocker（系统无法证明剩余日期本来没课）
7. **同名导出自动递增**（P0）
   - `payroll_core/excel/output_paths.py::safe_output_path()`：工资表.xlsx → (2) → (3)，补空洞
   - 接进 `render_generated_payroll` 与 `write_new_workbook`（含批注回填）
   - 服务层回报**实际落盘路径**（原来回报请求路径）
8. **输出位置**（P0）：默认 `~/Desktop/工资导出`，`default_export_path()` 回报可读位置，失败有 fallback
9. **旧 UAT 扫雷**：界面文案移除 13 处 `Run` 工程术语（新增测试守住）

## WORK_IN_PROGRESS

无（所有改动已提交并推送，工作区干净）

## REMAINING

1. **Golden Baseline**：本机与其他 worktree 均未找到 Golden 数据集（只读查找过），
   本轮以 AA / AC / AD 专项测试代替（`test_ac_calculation_evidence.py`、`test_payroll_scope.py`）。
   若 Golden 数据在受保护目录，需由用户提供安全运行方式。
2. **"打开所在文件夹"**：目前只在结果消息里明确告知保存位置，未做点击打开文件夹
   （属 best-effort，未重写文件选择 UI）。
3. **真人 UAT 待验**：默认月份、月份冲突确认流程、导出递增都只有自动化测试，
   建议明天用真实 8 月课表走一遍。

## KNOWN_FAILURES

无。全量 226 passed。

修改过两条既有测试（行为是本次 P0 明确要求的变更）：
- `test_generate_mode_marks_draft_and_never_overwrites`：同名导出不再报错，改为断言自动改名且旧文件一字不动
- `test_no_output_overwrite_and_multiple_candidates_same_cell_are_preserved`：同上，回填输出改断言实际路径

## BUSINESS_DECISIONS_NEEDED

1. 20 日规则是否适用于所有校区/所有月份？（当前按统一规则实现）
2. 课表跨月时（如 8/30–9/2）默认取"课程最多的月份"，是否需要改成"以核算月为准 + 提示"？
3. `1对3` 是否应对所有历史月份生效？（当前规则种子对 2026-08 起都生效）

## NEXT_ACTION

1. 用真实 8 月课表 + UI 选 9 月，验证冲突提示与切换流程
2. 导出两次同名文件，确认得到 `工资表.xlsx` 与 `工资表 (2).xlsx`
3. 若需要合流，请由 Chief 审 `origin/night/hy4-uat-20260912` 的 PR
