# TASK — 外围工资权威表 UAT

## 目标

在不影响正在进行的 `v0.21.0-rc1` Windows UAT 的前提下，验证 `feature/payroll-peripheral-authorities` 的脱敏外围工资输入流程。

## 开始前

1. 阅读 `AGENTS.md`、`CURRENT_STATE.md`、本文件与最新 `DEVLOG.md`。
2. 确认在 `feature/payroll-peripheral-authorities`，不修改 `v0.21.0-rc1` Core。
3. 只使用脱敏模板或 fixture；真实业务数据只允许本机只读使用，不能进入 Git。

## 必须验证

- 完整 pytest。
- 续费模板：导入 → 审核 → 绑定 Run → 验证 AH/AI/AJ/AK 结构化结果。
- 退费模板：导入 → 审核 → 验证一笔退费可关联多位教师、重复人头只提示、未确认工资影响不自动计入 AN。
- HR：只验证显式金额权威表入口，不虚构 HR 模板或人事规则。

## 禁止事项

- 不改变 AA/AC/AD/AE/AF 业务规则，不合并 main。
- 不新增续费资格、退费责任、推荐、管理绩效、AV 或人事政策推导，不触碰 Source correction / approved override 开发线。
- 不提交真实工资、姓名、学生、排课、续退费数据或真实 Excel。

## 完成标准

普通管理者能在中文页面下载脱敏模板或直接上传既有业务表，完成续费/退费的导入与审核；任何未确认的退费都不能被自动变成工资扣款。
