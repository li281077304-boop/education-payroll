# 2026-07 核心工资规则重建证据

本文件记录 July 规则版本的来源、结构证据和隔离边界。原始工资、排课和核对工作簿只在本机只读使用；仓库不保存其内容、教师姓名、学生姓名或金额明细。

## 证据指纹

| 证据角色 | 本机路径 | SHA-256 | 结构摘要 |
|---|---|---|---|
| July 工资表 / 模板证据 | `/Users/macos/Desktop/7月工资表制作与核查/2026年7月份数学&理化组薪资.xlsx` | `1f0533f1a7ca08357aa2a852fa6c6de1ed747297d92a5cd968ccfb072a2810ae` | `教学部`，35 行 × 49 列，167 个公式，65 条批注 |
| July 工资核对表 | `/Users/macos/Desktop/7月工资表制作与核查/工资核对表7月.xlsx` | `c15a36c760ae7853d922ae7e53d6b6874eeca0fa24c8119ec3b20eacd710abcb` | `排课记录`、`工资核对`、`Sheet1`，共 11,983 个公式 |
| July 排课导出 | `/Users/macos/Desktop/7月工资表制作与核查/排课列表_06月29日到08月02日_202608040931.xls` | `e9ca1e8d3f0799e7a5d492695998310041e86f348ee3d0642f155e1d5f35e486` | OOXML 内容的 `.xls` 文件；1 张排课表，3,695 行 × 26 列 |

哈希用于确认本机再次导入的文件没有被替换；不把哈希当作业务规则或教师身份。

## July 规则版本

实现文件：`config/core_rules_2026_07.yaml`；存储版本 ID：`core_rules_2026_07_v1`；生效范围严格为 `2026-07`。

| 字段 | July 证据结论 | 处理 |
|---|---|---|
| 每节时长 | 工资核对表与排课导出样本均为 2 小时口径 | `lesson_hour_factor=2` |
| 年级系数 | July 工资表 AA 公式明确使用小学 `0.85`、初中 `0.9/1.0`、高中 `1.1/1.25/1.35`、雅思/托福 `1.5` | 写入 July 规则包 |
| 一对一 | `AA` 由年级系数 × 2 小时 × 有效实到汇总 | Core 固定逻辑 |
| 普通小班 | `AC` 使用实到人数系数 `1..10`；未知年级/人数不补零 | Core 固定逻辑 |
| 1 对 2 | July 核对表公式为普通实到人数系数再乘 `1.2`；July 版本保存为按实到人数展开的特殊系数表 | `july_historical_one_to_two` |
| AD | 工资表公式为 `AA + AC` | Core 固定逻辑 |
| AE | July 工资表存在“按 AD 档位 + 星级加成”的结构；档位和 1–6 星加成与现行 AE 证据一致 | July 规则包独立保存，不读取 August 版本 |
| AF 普通候选 | July 工资表重复出现 `(AD-30)*AE` | July 规则包只保存为默认候选，未把候选伪装成个人确认 |
| AF 例外 | July 工资表存在 `AD*AE` 的 TRMT 个体公式以及按节数×单价的行 | 由历史对账按来源分类为 `PERSONAL_EXCEPTION` / `PART_TIME_RATE`，不按姓名硬编码 |

July 规则包没有把未观察到的业务事实扩展为新的规则。未识别年级、未知班型、缺失实到、冲突星级和个人 AF 政策仍会产生 `NEEDS_INPUT` 或人工核对项。

## 差异分类边界

`PayrollService.historical_reconciliation()` 对 AA、AC、AD、AE、AF 逐字段比较，并为每个差异保留工资表公式、当前 Core 结果、逐课贡献或批注来源。分类依据是来源证据，而不是教师姓名或预先写入的 Golden 数值：

- `COURSE_CONTRIBUTION`：AA/AC/AD 的逐课来源、年级、班型、实到或课程贡献导致的差异。
- `PERSONAL_EXCEPTION`：历史 AF 公式明确不扣义务课时，而当前候选/确认政策存在不同。
- `PART_TIME_RATE`：历史批注同时给出按节单价和节数，且 AF 公式可与之对应。
- `MISSING_SOURCE`：历史字段或政策来源不足，不能可靠归因。
- `RULE_DIFFERENCE`：双方来源完整但版本化规则不同。
- `DATA_QUALITY` / `INPUT_SCOPE` / `UNEXPLAINED`：保留为异常，不对平、不猜测。

工资表的缓存值只作为历史对照目标；当前 AA/AC/AD/AE/AF 均由排课、版本规则和显式政策链独立计算。

## 本机真实 July Run 回放

2026-09-17 使用上述三份原始文件做了直接选文件回放，临时数据库和导出文件均在仓库外：

- `2026-07` Run 自动绑定 `core_rules_2026_07_v1`；July 日历范围纳入 3,383 条排课记录和 31 条工资表记录。
- 核查结果为 `REVIEW_REQUIRED`，预览生成 31 行；字段状态为 `DETERMINED=122`、`ESTIMATED=26`、`NEEDS_INPUT=7`、`NOT_APPLICABLE=31`，保留 21 个阻塞项。
- `generate_payroll()` 成功写出导出工作簿，状态为 `NEEDS_CONFIRMATION`，不会把未确认的字段伪装成最终确定值。
- 历史对账使用 `math` 角色的 July 工资表作为只读历史证据，共比较 31 个对象；差异分类计数为 `COURSE_CONTRIBUTION=76`、`PART_TIME_RATE=3`、`RULE_DIFFERENCE=26`，其余分类为 0。

以上统计只保留结构、状态和分类计数，不把教师姓名或金额写入仓库。

## August 隔离回归

- 创建 `2026-07` Run 时，系统按生效期加载 `core_rules_2026_07_v1`；创建 `2026-08` Run 时仍绑定 `core_rules_2026_08_09_v1`。
- July 的 `1对2` 历史系数只存在于 July 规则快照；不会改变 August 的规则表或既有 Run。
- `af_policy_confirmation`、基本工资快照、业务决定、解决记录和导出状态均存储在 Run 内；新建 August Run 不复制 July Run 的这些状态。
- July 规则版本写入独立不可变记录；后续修订只能新建版本并显式 rebind，不能覆盖 August 或历史 Run。
