# DEVLOG

## 2026-09-10 — 跨 Agent 交接整理

- 历史 macOS V1 RC 实机验收已通过：真实 2026-08 Run 可恢复，27 人范围、AA、星级、公式完整性、AC 证据、人工决定持久化与失效机制已经在此前工作中验证。
- `3efd8e1` 增加了基础资料修正版 workflow，以及 AC 逐课计算证据和批注结构化展示。
- 真实 UAT 发现一条班课差异：独立排课计算与工资表相差 0.38；该问题指向 8 月升年级后排课系统年级未同步，不能简单归为工资表错误。
- 业务上明确区分两类处理：`SOURCE_DATA_CORRECTION` 修正上游事实的有效副本；`APPROVED_PAYROLL_OVERRIDE` 针对明确课程和本 Run 的特殊核算口径。二者都不得覆盖原始排课事实。
- 之所以新增结构化 resolution workflow，是为了让差异经反事实重算后可验证闭合，并让人工决定绑定稳定业务问题，而不是停留在“接受例外”文字上。
- 本次交接审计发现工作区有未跟踪的 `payroll_core/reconcile/ac_resolution.py`。它看起来是上述 resolution workflow 的未提交半成品；尚未完成集成、审计或测试，本次不删除、不修改、不提交。

## 既有背景

历史文档和提交记录显示，项目已从 Skill 驱动的散落脚本逐步增加独立核对、来源追溯、Coverage/PASS 门禁、Business Issue 聚合和本地 UI。本文档只记录演变原因；当前可执行状态以 `CURRENT_STATE.md` 和仓库测试为准。
