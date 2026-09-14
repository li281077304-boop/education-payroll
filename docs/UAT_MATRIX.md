# Payroll V1 真实 UAT 矩阵

本矩阵基于真实 Fresh August Run `c51dd5f3b544`、其导出工作簿及当前本地 UI 复核结果。`PASS` 只表示用户可理解的交付证据已存在；缺少业务来源不会被默认值掩盖。

| UAT_ID | 场景 | STATUS | ISSUE_TYPE | EVIDENCE | ISSUE / FIX | RETEST | BLOCKING | BUSINESS_CONFIRMATION_NEEDED |
|---|---|---|---|---|---|---|---|---|
| UAT-01 | 进入系统与导航 | PASS | UX | 首页 `/api/runs/index`、历史 Run 卡片、返回工作台入口 | 历史核算入口与首页导航已修复 | 页面复核通过 | NO | NO |
| UAT-02 | 新建真实工资 Run | PASS | DATA | Run `c51dd5f3b544`，2026-08-03～2026-08-30 | 新 Run 独立保存，未继承旧人工决策 | Run 读取通过 | NO | NO |
| UAT-03 | 导入真实资料 | PASS | DATA | 真实资料包；排课 2,385 行、51 位教师、模板已绑定 | 月份页与模板识别通过 | 真实 Run 复核通过 | NO | NO |
| UAT-04 | 数据准备与异常 | PASS_WITH_WARNING | DATA | 真实 Run summary；仍保留 grade warnings | 警告不阻断核心计算，原始证据保留 | 复核通过 | NO | NO |
| UAT-05 | 基本工资 M | BLOCKED | SOURCE_GAP | G～L 输入缺失；生成结果明确不按 0 | 缺少实际基本工资输入 | 待权威 G～L 来源 | YES | YES |
| UAT-06 | 核心课时工资 AA/AC/AD/AE/AF | PASS | DATA | AA/AC/AD/AE/AF 51/51 DETERMINED；unexplained=0 | 核心计算链通过 | 真实 Run + 导出复核通过 | NO | NO |
| UAT-07 | 兼职定价 | NOT_TESTED | SOURCE_GAP | 本期无可核验的 ACTIVE 兼职政策目标 | 不用历史价格自动填充 | 待本期兼职政策来源 | NO | YES |
| UAT-08 | 续费与 AK | BLOCKED | SOURCE_GAP | August 续费表无 APPROVED/NO_EVENT 标记且无稳定 teacher_id | 不能把历史表直接当生产审核结果 | 待审核结果与身份绑定 | YES | YES |
| UAT-09 | 退费 AN | NOT_TESTED | SOURCE_GAP | 真实 `宣城二校退费统计表2026年.xls` 可见，但未绑定审核身份 | 需审核/绑定后才可进入工资 | 待审核退费来源 | NO | YES |
| UAT-10 | 其它 AV 组成项 | BLOCKED | SOURCE_GAP | AG/AL/AM/AO/AP/AQ/AR/AS/AT/AU 无权威来源或规则 | 保留 UNKNOWN/MISSING_SOURCE，不静默计算 | 待来源/规则 | YES | YES |
| UAT-11 | 待办中心 | PASS | UX | core summary automatic_required=102、manual_review=0、user_actions=0；聚合层保留 | 顶层只呈现真正动作 | 真实 Run 页面复核通过 | NO | NO |
| UAT-12 | 批注/回填 | PASS_WITH_WARNING | UX | 现有 comment-candidates/writeback API 与回归测试 | 技术链可用；业务批注仍按来源逐条保留 | 测试通过 | NO | 仅具体批注需确认时 |
| UAT-13 | 工资预览 | PASS_WITH_WARNING | UX | 真实页面显示 M、AA、AC、AD、AE、AF、AH/AI/AJ、AK、AV 状态与周期 | 核心字段可读；外围缺口明确显示 | 页面复核通过 | NO | NO |
| UAT-14 | 历史工资对账 | PASS_WITH_WARNING | DATA | 核心字段 unexplained=0；历史续费与工资表 29 人 AH/AI/AJ/AK 对齐 | 外围来源缺口单独分类 | 对账复核通过 | NO | 外围差异需来源时 |
| UAT-15 | 正常 UI 导出 | PASS | UX | `/Users/macos/Desktop/工资导出/标准工资表 (28).xlsx`；重复导出不覆盖 | 正常导出路径与 safe output 通过 | 文件存在复核通过 | NO | NO |
| UAT-16 | Excel 重开 | PASS | DATA | 3 sheets、19 merged ranges；AA/AD/AF/AK/AV 公式存在 | 模板结构保持 | `data_only=False` 重开通过 | NO | NO |
| UAT-17 | 第二次使用 | PASS | UX | 首页历史 Run 列表与恢复入口 | 重新进入不会跳到错误新建页 | 页面复核通过 | NO | NO |

## 统计

- PASS: 8
- PASS_WITH_WARNING: 4
- BLOCKED: 3
- NOT_TESTED: 2
- 技术问题已修复：真实月度续费表按 period/公式缓存导入；历史 Run 导航与恢复入口。
- 当前仍需业务来源或明确口径：M 的 G～L、审核且可绑定的续费/退费结果、其余 AV 外围字段规则。
