# ASSET_INDEX

盘点日期：2026-09-08

| 资产 | 原始路径 | 类型 | 大致时间 | 用途 | 是否当前使用 | 是否含敏感数据 | 是否已复制 |
|---|---|---|---|---|---|---|---|
| 当前工资核对 Skill | `/Users/macos/.workbuddy/skills/工资核对表制作/SKILL.md` | SKILL.md | 2026-09-08 | 工资表制作与核查规则 | 是，候选最新版 | 含业务规则和教师名单，未含工资明细 | 是 |
| 当前 Skill 旧备份 | `/Users/macos/.workbuddy/skills/工资核对表制作/SKILL.md.bak-20260805` | SKILL.md 备份 | 2026-08-05 | 保留版本关系 | 待确认 | 业务规则 | 是 |
| 工资 Skill Python 脚本 | `/Users/macos/.workbuddy/skills/工资核对表制作/scripts/` | Python | 2026-07/08 | 年级提取、排课导入、AE/AF 检查 | 待确认 | 代码内可能含教师名单/业务规则 | 是 |
| 工资 Skill 规则文件 | `/Users/macos/.workbuddy/skills/工资核对表制作/references/` | Markdown/CSV | 2026-07/09 | 档位、星级和年级规则 | 待确认 | 学生年级 CSV/Markdown 含真实姓名 | 部分；敏感文件未复制 |
| 工资 Skill Excel 模板 | `/Users/macos/.workbuddy/skills/工资核对表制作/assets/工资核对表模板.xlsx` | Excel | 2026-07 | 工资核对模板 | 待确认 | 是，含 1,892 行排课/教师数据 | 否 |
| 管理岗位考核 Skill | `/Users/macos/.workbuddy/skills/管理岗位考核/` | Skill/Python/规则 | 2026-08 | 管理岗位考核指标 | 待确认 | 参考规则，未复制真实考核表 | 是 |
| 8 月续费校对脚本 | `/Users/macos/Desktop/8月工资表/parse_续费校对.py` | Python | 2026-08 | 续费校对 | 是/待确认 | 代码资产，未复制数据 | 是 |
| 8 月续费校对 v3 | `/Users/macos/Desktop/8月工资表/parse_续费校对_v3.py` | Python | 2026-08 | 续费校对版本 | 是/待确认 | 代码资产，未复制数据 | 是 |
| 8 月核对表构建脚本 | `/Users/macos/Desktop/8月工资表/build_8月核对表.py` | Python | 2026-08 | 构建工资核对表 | 是/待确认 | 代码资产，未复制数据 | 是 |
| 8 月工资 Excel 与备份 | `/Users/macos/Desktop/8月工资表/` | Excel | 2026-08 | 实际工资核算输入/输出 | 待确认 | 是 | 否 |
| 8 月续费/退费/考核数据 | `/Users/macos/Desktop/8月工资表/` | Excel/JSON/MD | 2026-08 | 续费、退费、考核和校对 | 待确认 | 是 | 否 |
| 7 月工资项目全部表格 | `/Users/macos/Desktop/7月工资表制作与核查/` | Excel | 2026-07 | 工资核算、考核和排课数据 | 待确认 | 是 | 否 |
| 7 月工作总结 | `/Users/macos/Desktop/7月工资表制作与核查/2026年7月工资工作总结.md` | Markdown | 2026-08-13 | 记录 7 月交付和修正 | 待确认 | 含真实业务结果 | 否 |
| 1 月工资处理脚本 | `/Users/macos/WorkBuddy/一月工资核对与排课记录/` | Python | 2026-01/03 | 早期工资核对与排课处理 | 待确认 | 代码及规则 | 是 |
| 1 月工资核对说明 | `/Users/macos/WorkBuddy/一月工资核对与排课记录/1月工资核对说明.md` | Markdown | 2026-03 | 早期规则说明 | 待确认 | 含业务统计口径，未含工资明细 | 是 |
| 1 月/2 月真实工作簿 | `/Users/macos/WorkBuddy/一月工资核对与排课记录/` | Excel | 2026-01/03 | 早期输入/输出 | 待确认 | 是 | 否 |

## 排除项

以下资产确认存在，但因敏感性未复制：真实工资、教师收入、学生姓名、续费/退费明细、真实排课记录、真实考核表、校对 JSON、真实输出 Excel、当前 Skill 的学生年级 CSV 和已填充工资模板。

## SQL/YAML/TOML 搜索

在 `/Users/macos` 范围内未发现工资业务 `.sql` 文件；也未发现相关 YAML/YML/TOML 配置文件。现有配置主要以 Python 常量、CSV、JSON、Excel 和 Skill 文档存在。
