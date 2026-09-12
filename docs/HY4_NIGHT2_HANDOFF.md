# HY4 Night Round 2 Handoff（2026-09-12）

- **BRANCH** = `night/hy4-uat2-20260912`
- **WORKTREE** = `/private/tmp/education-payroll-night2-hy4`（独立）
- **BASE** = `6f0f635`（Round 1 安全点）
- **LAST_SAFE_COMMIT** = `d5bece2 test: guard top navigation availability`
- **PUSHED** = YES
- **TESTS** = 243 passed（全量；基线 226 + 新增 17）
- **OTHER_WORKTREES_UNTOUCHED** = YES（开始前与结束后两次核对，全部 0 未提交）

---

## OLD_UAT_CHECKED

| 项 | 结论 |
|---|---|
| 2.1 错文件删除 | **不支持**（service / 路由 / UI 都无删除能力） |
| 2.1 错文件替换 | 支持（重新选择同一类别即覆盖） |
| 2.1 重新选择 / 返回 | 支持 |
| 2.1 重置 / 放弃本次 | 不支持（无 reset / discard 能力） |
| 2.2 重复上传同一文件 | 不报错，可重复导入 |
| 2.2 同一文件充当两个类别 | 明确拒绝，中文提示，原核算仍可用 |
| 2.3 顶部导航消失 | 已加黑盒测试守住（当前正常） |
| 2.3 核算历史 → 新建工资核算 | **确认存在**（见 BUGS_DEFERRED） |
| 2.4 用户可见错误含 traceback | 未发现；已加测试守住 |
| 2.5 中文文件名 / 空格 | 正常 |
| 2.5 合并单元格 / 空行 / 多余工作表 / 隐藏表 | 不崩，记录数正确 |
| 2.5 导出后重新打开 | 正常 |

## REGRESSION_ADDED

新增 `tests/test_uat_round2_recovery.py`（17 条，全黑盒）：
wrong upload recoverable / replacement keeps run state / duplicate upload recoverable /
same file two roles 中文报错 / 非法月份与缺文件报错不含 traceback / 未导材料报错说人话 /
中文带空格文件名 / 合并单元格+空行+多余工作表 / 导出后 reopen / 导航端点可达 / 顶部导航不消失

## BUGS_FOUND

1. **无法删除已上传的错误文件**（2.1）
   - 影响：多传了一个不相关文件后无法移除；只会让"材料齐全度"虚高，不会丢数据
   - 修复需改 `payroll_ui/service.py` + `server.py` + `static/app.js` → **Luna 重叠，未修**
2. **顶部"核算历史"按钮跳到标题为"新建工资核算"的页面**（2.3）
   - 根因：`shell()` 里"核算历史"按钮 `onclick="home()"`，而 `home()` 的 H1 是"新建工资核算"，
     历史列表在该页下方（功能正常，但标题与用户预期不符）
   - 修复需改 `app.js`（改按钮文案或按来源区分标题）→ **Luna 重叠，未修**
3. **旧周报主脚本当前跑不起来**（考古发现，非 payroll 问题）
   - `scripts/auto_weekly.py` 依赖 `xlutils` / `xlwt`，本机 venv **两者都缺失**；
     且 `xlutils` 需要 `xlrd<2`（本机是 2.0.2）

## BUGS_FIXED

本轮 **没有修改任何 Luna 重叠的核心文件**（service.py / app.js / server.py / standard_payroll_render.py /
UAT_BASELINE.md / DEVELOPMENT_PRINCIPLES.md 全部未动）。
新增内容只有：一个测试文件 + 两个新文档。

## BUGS_DEFERRED_DUE_TO_LUNA_OVERLAP

见上 BUGS_FOUND 1、2。建议在 Luna 本轮完成后再处理，或由 Luna 一并处理。

---

## WEEKLY_SKILL_FOUND = YES

- **WEEKLY_SKILL_PATH** = `~/.workbuddy/skills/school-weekly-report/`
  - 子 Skill：`math-weekly-report/SKILL.md`（Hermes Agent v1.0.0）
- **CORE_SCRIPTS** = `scripts/auto_weekly.py`（回填旧 .xls，xlutils）、`templates/auto_fill.py`（从零生成 xlsx）
- **INPUTS** = 上周手动底稿 `.xls`、`排课列表_*.xls/.xlsx`、`二校数学组数据汇总-六月第N周.xls`、
  `2026年度续费+推荐数据*.xlsx`、`宣城二校退费统计表2026年.xls`
- **OUTPUTS** = `数学组数据统计表-宣城二校6月第N周.xls`（回填）/ `数学组周报_第N周_自动生成.xlsx`（生成）

详见 `docs/WEEKLY_REPORT_SKILL_AUDIT.md`（22 个问题全答）。

## WEEKLY_REPORT_AUTHORITY_MODEL

```
上周已确认周报 → 复制基础数据（保留格式与公式）
              → 从可信来源读取能可靠读取的数据
              → 把"变化"展示给人
              → 人工确认/修改
              → 最终填报值 = 本周权威值
              → 写回原来的老 Excel（另存新文件）
```
字段（**本轮只说明，不实现**）：`previous_value` / `suggested_value` / `final_value`（权威）/ `source` /
`manual_adjustment` / `note`

## STUDENT_COUNT_AUTHORITY

**最终人工填报值（WPS 汇总表）就是权威值。** 旧 Skill 原文：
"Student counts | WPS源数据 teacher rows | Primary — NEVER compute from schedule"。
系统推算值只能参考，**不能推翻最终填报值**。停课沿用上周；新增/结课来自 WPS 学员变动表且需人工排除换班。

- **AUTO_CALCULABLE_FIELDS** = 一对一/班课 课时与次数（排课）、总课时当量、周均、满班率、教师数
- **MANUAL_FIELDS** = 学生数（权威）、停课（沿用上周）、新增/结课、退费、换班排除、小初高拆分口径

## REUSE_AS_IS

课时口径（1对1 = 3 课时/次、班课按实到）、**实到=0 必须先过滤**（公司级口径，有真实事故数据）、
交叉验证流程、自恰性校验、只写指定列保留公式列、"差异必须给原因"、生成后校验清单

## REUSE_WITH_ADAPTER

回填机制本身（需换依赖或补 `xlutils`/`xlwt` 并固定 `xlrd<2`）、排课解析（列号改按标签扫描）、
教师名单改读云端 `rosters.md`

## BUSINESS_RULE_ONLY

学生数权威归属、停课沿用上周、新增/结课口径、退费留空、周均预警阈值（<2.0 且 ≥3 学生）、
总课时当量 = v1h + bkh/3、单科数两个口径（班级数 vs 学生数）、满班率经验比例、编制/兼职划分

## DEPRECATE

`auto_fill.py` 的从零生成路线（不保留老 Excel 格式与公式）、写死行号/列号/输出文件名、
写死教师名单、周次→日期映射写死、满班率魔数写死

## PPT_ASSETS_FOUND

周报 Skill 目录内 **未发现任何 PPT 模板 / 脚本 / 图表定义**（无 `*.ppt*` 文件，文档未提及 PPT）。
记录为待确认：若公司现实是"Excel 数据复制粘贴到老 PPT"，就按原样保留，不发明新汇报体系。

---

## NEXT_ACTION

1. Luna 本轮结束后，处理两个 deferred bug（删除文件、核算历史标题）
2. 若要重启周报自动化：先补 `xlutils`/`xlwt` 依赖或改用 openpyxl 回填方案，并把写死行号改为按标签扫描
3. 周报方向已明确为"聪明的 Excel 自动填表助手"，**不要**做 BI / Data Center / 自动纠正人工填报
