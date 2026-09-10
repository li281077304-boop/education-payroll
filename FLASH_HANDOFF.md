# FLASH_HANDOFF

## 项目是什么

`education-payroll` 是本地工资核对与审计系统：权威来源 → 规则 → 系统计算 → 工资表结果 → 差异证据 → 人工处理 → 历史留档。Skill 仍保留，但正确性应由 Python/Core、配置和结构化人工决定承担。

## 当前现场

- Branch：`feature/payroll-resolution-workflows`
- HEAD：`3efd8e1 feat: add authority revision workflow and AC calculation evidence`
- 测试：`79 passed`
- 工作区：只有未跟踪的 `payroll_core/reconcile/ac_resolution.py`；它是未审计、未集成、未提交的 resolution 半成品，不能删除或混入文档提交。
- `feature/payroll-resolution-workflows` 已存在；不要另造分支或假设它已完成。

## 已完成能力

真实 2026-08 Run 的 27 人范围、AA/AC 独立核对、星级权威版本、AE/AF 政策检查、公式完整性、provenance、Business Issue 聚合、证据详情、人工决定持久化/失效、基础资料修正版和 AC 逐课证据已在此前提交中存在并有测试。当前不是声称 resolution workflow 已完成。

## 下一步

先读 `AGENTS.md`、`CURRENT_STATE.md`、`TASK.md`，再按需读 `DEVLOG.md`、`docs/PAYROLL_CORE_V1.md`、`docs/CURRENT_PAYROLL_SYSTEM.md`、相关 Core/UI 代码和测试。第一件事是审计未跟踪 `ac_resolution.py` 与现有 persistence/UI 的缺口，然后完成 `SOURCE_DATA_CORRECTION` 和 `APPROVED_PAYROLL_OVERRIDE`。

## 最重要的业务原则

胡长春是“修正上游事实”，不是工资特例；董葛飞是“批准的局部核算口径”，不是排课错误。原始排课不可覆盖。只有反事实重算精确闭合差额才能标记 `EXACT_CAUSE`。无法确定董葛飞具体课程时必须问一个最小确认问题，不能猜。

## 明确不要做

不要接续费、退费、AV；不要改 AA/星级/公式算法；不要写回真实 Excel；不要提交真实数据；不要做 UI 美化、打包或合并 `main`。

不要仅依据本文修改代码；先检查真实仓库状态并运行测试。
