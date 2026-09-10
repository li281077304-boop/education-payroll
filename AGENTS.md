# Agent 协作规范

## 项目边界

`education-payroll` 是本地、离线优先的教学机构工资核对与审计系统。核心代码在 `payroll_core/`，本地 UI 在 `payroll_ui/`，历史资产在 `skill/`、`legacy/`，测试在 `tests/`，说明在 `docs/`。

## 开发规则

- 开始工作前先检查 branch、`git status`、最近提交并运行测试。
- 不未经用户明确授权合并 `main`；功能开发使用独立分支。
- 不猜业务规则。代码、Skill、Excel 和人工说明冲突时，记录 UNKNOWN/冲突并请求最小确认。
- 原始排课、工资表及权威资料不可覆盖；修正必须是可审计的 correction/override 层。
- 稳定的解析、匹配和数学逻辑放在 Python；变化的参数放在版本化配置/权威资料；主观判断保留为结构化人工决定。
- 真实事故必须转成永久 regression test。

## 数据安全

- 真实工资、教师/学生姓名、手机号、续费退费明细、真实排课和真实 Excel 只允许在本机只读使用，禁止进入 Git、fixture、日志和脱敏文档。
- 提交前检查 `git status`、`git diff --cached`，并扫描新增文件类型和内容。
- 不修改、删除、移动或重命名真实业务文件；不写回原 Excel。

## 测试

当前推荐命令：

```bash
uv run --no-project --with pytest --with openpyxl --with pyyaml --with xlrd python -m pytest -q
```

核心测试不得依赖 WorkBuddy、真实数据或 LLM。

## 范围纪律

续费、退费、AV、UI 美化、打包和其他产品线不属于当前交接任务。人工裁决必须记录对象、依据、生效范围和时间；不能因为用户点击“已看过”就放行。
