# education-payroll

宣城二校工资核算相关 Skill、脚本、规则和历史版本的私有归档仓库。

本仓库先保存现有资产和版本关系，并在独立 feature 分支中逐步建立可审计的 Payroll Core 与本地只读核对工具。

## 重要任务开始前请先阅读

- `docs/UAT_BASELINE.md`：真人 UAT 验收基线（真实 UAT 优先）
- `docs/DEVELOPMENT_PRINCIPLES.md`：开发原则（20 条）
- `docs/MANUAL_DECISIONS.md`：已确认的人工业务决策

## 两条入口（不要混用）

**真实用户只走 PRODUCTION LOCAL APP：**

- 双击 `~/Applications/工资核算助手.app` — 打开工资核算助手（必要时自动启动服务）
- 双击 `~/Applications/重启工资服务.app` — 安全重启（只结束启动器自己启动的进程）
- 固定端口 `8760`，正式数据目录 `~/Library/Application Support/EducationPayroll`
- 详见 `docs/LOCAL_APP.md`

**开发与 UAT 才走命令行**（随机端口 + `/tmp` 数据目录，用完即弃）：

- `python -m payroll_ui --port 0 --no-browser`

普通用户不需要 `python` 命令、`localhost` 地址、端口号或 Terminal。

## 当前入口

- 当前工资 Skill：`skill/payroll/SKILL.md`
- 2026-08 运行脚本：`legacy/2026-08/`
- 早期工资核对项目：`legacy/2026-01/`
- 管理岗位考核独立模块：`src/modules/管理岗位考核/`
- 本地工具启动（开发环境）：`python -m payroll_ui`

## 安全边界

真实工资表、教师收入、学生名单、续费退费明细、排课原始数据和生成结果不提交到本仓库。
这些文件只在原始工作目录保留，具体排除项见 `ASSET_INDEX.md`。

## 文档

- `CURRENT_STATE.md`：截至 2026-09-08 的事实状态
- `ASSET_INDEX.md`：原始资产、复制状态和敏感性判断
- `docs/LOCAL_APP.md`：正式本地入口、固定端口、正式数据目录、安全重启、验收清单
- `docs/PAYROLL_FIELD_LINEAGE.md`：AA、AC、AE、AF、AV 的真实数据血缘和核对边界
- `docs/UI_SPEC_V1.md`：本地工资核算助手 V0.1 的界面与交互说明
