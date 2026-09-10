# TASK — 下一位 Agent 接力任务

## 当前目标

在不破坏既有 Core/UI 能力的前提下，完成并验收两个班课差异处理 workflow：

1. `SOURCE_DATA_CORRECTION`：对具体排课记录建立不可变的事实修正层，生成 effective fact，并重算 AC。
2. `APPROVED_PAYROLL_OVERRIDE`：对明确课程建立本 Run/本月范围的特殊核算口径，并重算 AC。

优先审计现有未跟踪 `payroll_core/reconcile/ac_resolution.py`，不要先重写。任何实现前先运行测试并确认它与现有模型、UI、SQLite 的关系。

## 已确认业务语义

- 胡长春案例是上游事实错误：一节被记录为高三 6 人班，业务确认应按高二口径；典型原因码为 `GRADE_ROLLOVER_NOT_UPDATED`。原始 AC 68.43，修正后应为 68.05，与工资表一致。
- 董葛飞案例是排课事实正确但经批准的特殊折算；必须绑定具体课程。当前历史 `ACCEPTED_EXCEPTION` 不能在无法确定课程时擅自迁移。
- `EXACT_CAUSE` 只能由反事实重算精确闭合差额证明；否则只能是 `POSSIBLE_CAUSE`、`AMBIGUOUS_CAUSE` 或 `UNEXPLAINED`。
- 原始事实永远保留；修正/override 需记录来源、hash、原因、确认人、时间、范围、指纹和重算前后结果。

## 必须保持

- 保留 `CONFIRMED_ERROR`、`ACCEPTED_EXCEPTION`、`DEFERRED` 兼容性。
- 通过结构化输入避免“总数相抵”掩盖逐课 contribution mismatch。
- 真实 8 月数据只读留在本机；不得修改真实 Excel、上传真实数据或合并 `main`。

## 回归验收

至少覆盖：保留原始事实、年级修正闭合 0.38、Run 级 override、不改变排课事实、精确原因判定、模糊原因不冒充精确、相互抵消课程错误仍可识别，以及旧 `ACCEPTED_EXCEPTION` 兼容。真实 UAT 需要通过 UI 完成；不能用后台 SQLite 伪造。

## 最终汇报

报告两类 workflow 是否完成、胡长春 68.43→68.05、董葛飞是否需要最小确认、审计链、EXACT_CAUSE 依据、抵消错误测试、pytest、branch/commit/push/working tree 和安全检查。完成后停止，不扩展续费、退费或 AV。
