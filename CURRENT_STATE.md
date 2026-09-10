# CURRENT_STATE

盘点日期：2026-09-10

本文件只记录当前仓库和已确认能力，不提出未来架构方案。

## 0. 仓库现场

- 当前 branch：`feature/payroll-resolution-workflows`
- 最新提交：`3efd8e1 feat: add authority revision workflow and AC calculation evidence`
- `feature/payroll-resolution-workflows` 已创建；本次审计没有创建新分支。
- 当前测试：`79 passed`（命令见 `AGENTS.md`）。
- 当前 `git status` 只有一个未跟踪文件：`payroll_core/reconcile/ac_resolution.py`；无 staged 修改，无已提交业务逻辑变更。
- 该文件是上一轮/上一位 Agent 留下的 resolution workflow 半成品；本次未修改、未删除、未提交，完成度尚未确认。

## 1. 已完成能力

- Payroll Core 标准模型、AA 一对一与 AC 班课独立核对。
- 本组 2026-08 Run 的 27 人范围处理。
- 星级权威版本、教师工资政策档案、AE/AF 检查和 AD 门槛规则。
- Excel layout/fingerprint、公式完整性审计、provenance、Coverage/PASS 门禁。
- Business Issue 聚合：字段级审计事实保留，UI 层聚合展示。
- 完整证据详情、人工决定持久化、rerun/restart 恢复和 source/authority/rule/fingerprint 变化后的重新确认机制。
- 基础资料修正版 workflow，以及 AC 逐课程计算证据和工资表批注独立展示。

## 2. 当前真实 Run 事实

- 本机存在真实 2026-08 Run；真实数据未复制进仓库。
- 已验证的匿名业务结论：AA 27/27 一致；星级 27/27 一致；公式完整性通过；AC 有 2 个独立差异；AE/AF 各有 2 条字段差异，已聚合为业务问题。
- 一条 AC 差异为 0.38：独立排课计算 68.43，工资表/人工批注为 68.05；业务线索是 8 月升年级后排课系统年级未同步。该事实尚未在当前提交中完成结构化 correction workflow。
- 另一类已知案例是排课事实正确但部分一人班有批准的特殊折算；当前历史决定仍是 `ACCEPTED_EXCEPTION`，具体课程未可靠确定，尚不能自动迁移成 override。

## 3. 当前状态与未完成事项

- 当前分支是 resolution workflow 的开发现场，但 `SOURCE_DATA_CORRECTION` 与 `APPROVED_PAYROLL_OVERRIDE` 尚不能视为已完成或已通过真实 UI 验收。
- 未完成项：审计并整合未跟踪 `ac_resolution.py`；建立持久化/UI 入口；完成有效事实/局部 override 重算；补齐回归测试和真实 8 月 UI 验收。
- 当前 RC 状态：不能宣称 resolution workflow 已达到 release candidate。

## 4. 安全与范围

- 本次未读取、修改或提交真实 Excel；未提交真实姓名、工资、学生、排课、续费退费数据。
- 当前交接不扩展续费、退费、AV，不修改既有 AA/星级/公式算法，不合并 `main`。

## 1. 当前最新版工资 Skill

- 原始位置：`/Users/macos/.workbuddy/skills/工资核对表制作/`
- 当前入口：`SKILL.md`
- 当前文件修改时间：2026-09-08 17:28:41
- 当前文件 SHA-256：`8c835af6eca6b7a097dff67f3aad6cab7946817aa5722ade95bcf088c9b79ab7`
- 原始目录未发现 Git 仓库，因此没有可记录的 Git commit hash。
- 当前版本候选优先级高于 `SKILL.md.bak-20260805`。

## 2. 当前 Skill 文件组成

- `SKILL.md`
- `SKILL.md.bak-20260805`
- 3 个 Python 脚本：`_grade_extractor.py`、`import_paikeshi.py`、`verify_ae_af.py`
- 2 个安全规则/模板类文本：`ae_tier_rules.md`、`star_override_template.csv`
- 原始目录另有学生年级 CSV、学生年级 Markdown 查表和 1 个工资核对表 Excel 模板；它们含真实学生/排课/教师数据，本仓库没有复制。

## 3. 2026-09-08 全盘复查加固

在当前 `SKILL.md` 第十四节发现新增的“全量检查流程总纲（2026-09-08 归纳，每月按此逐项过，防漏）”。

已记录的内容：

1. 先全扫工资核对表 S 列 1v1 差值和 V 列班课差值；
2. 对非零差值做排课记录溯源；
3. 做 AE 档位和星级加成校验；
4. 检查 AD、AF、AV 公式完整性；
5. 检查年级完整性；
6. 交叉核对续费、退费、兼职；
7. 做排课老师与工资表名单差集检查；
8. 每一项输出结果后再进入下一项。

这次加固目前确认是 Skill 指令/流程规则，不是新增 Python 脚本。当前 Skill 目录中的 Python 文件仍为原有 3 个脚本。实际执行入口是 WorkBuddy 调用工资 Skill 后，按 SKILL.md 逐项人工/脚本复查；本轮没有发现专门实现“全盘复查总纲”的独立入口，也没有发现对应自动化测试或已审核的复查结果。

## 4. 当前工资流程涉及的输入

Skill 中明确列出的输入包括：

- 排课列表（xls/xlsx）；
- 数学组和理化组工资填报表；
- 续费+推荐数据；
- 退费统计表；
- 5 月工资表作为星级参考；
- 组课时生产周报/统计表；
- 学生年级查表。

真实输入文件均保留在原始 Desktop/Documents 目录，没有复制进仓库。

## 5. 当前已知自动化部分

- `_grade_extractor.py`：从排课记录/课程信息中提取年级相关信息。
- `import_paikeshi.py`：导入/处理排课记录。
- `verify_ae_af.py`：检查 AE/AF 相关值。
- 2026-08 工作区的 `parse_续费校对.py`、`parse_续费校对_v3.py`：续费数据校对解析。
- 2026-08 工作区的 `build_8月核对表.py`：8 月工资核对表构建。
- 管理岗位考核模块的 `compute_kh_metrics.py`：计算周平均、续推人次、退费人次等考核指标。
- 早期项目的 `process_jan.py`、`create_wage_sheet.py`、`check_missing.py`、`check_missing_final.py`：1 月工资核对与排课记录处理。

## 6. 当前仍需人工裁决的部分

Skill 明确保留人工确认的环节包括：

- 续费/退费月份缺失或来源不清时的处理；
- 教师名单和学科组归属；
- 星级特殊值和 AE 档位异常；
- 班课批注与系统排课不一致时的确认；
- 代课、兼职、请假、实到 0 等特殊课时情况；
- 退费是否计入相关绩效；
- 管理绩效和异常差值的最终采用值。

## 7. 8 月实际运行资产

原始目录：`/Users/macos/Desktop/8月工资表/`

已复制到本仓库的代码：

- `parse_续费校对.py`
- `parse_续费校对_v3.py`
- `build_8月核对表.py`

8 月工资表、续费表、退费表、考核表、校对 JSON、校对报告和所有 Excel 备份均未复制。

## 8. 版本关系事实

- 7 月项目目录包含大量工资表、核对表、考核表、排课表及备份，但未发现 Python 脚本。
- 8 月目录包含 3 个实际运行 Python 脚本和大量真实 Excel/JSON 输出。
- 早期 1 月项目包含独立的工资处理脚本，已按 legacy 保存。
- 当前 Skill、7 月项目、8 月项目和 1 月项目之间存在规则演变关系，但没有发现可直接证明的 Git 历史或统一版本号。
- 当前无法确定哪个 Python 是唯一正式入口；Skill 脚本、8 月脚本和早期脚本均保留原样。
- 当前无法确定 7 月脚本缺失是因为未生成、已移出，还是仅使用了人工/Skill 流程。
