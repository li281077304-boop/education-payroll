# Payroll Core V1

## 为什么单独建立 Core

现行工资流程已经有可靠的局部规则，但规则分散在 Skill、Excel 公式、多个时期脚本和人工聊天中。最直接的风险是“工资表公式看起来正常”，但某类差值根本没有被检查。Core V1 先解决可验证性，不试图替代现行系统。

## 当前边界

已实现：

- Python 3.11+ 的标准化数据对象：排课、工资、续费、退费、人工裁决；
- CSV adapter，作为脱敏 fixture 和未来 Excel adapter 的稳定边界；
- YAML 配置加载，支持 period、tolerance、角色排除和带生效期的对账调整；
- `ManualDecision`，把人工覆盖保存为 period/target/field/system/override/reason/source/confirmed_by/note；
- 通用字段级对账：MATCH、EXPLAINED_DIFFERENCE、UNEXPLAINED_DIFFERENCE、MISSING_SOURCE、MISSING_TARGET、NEEDS_MANUAL_REVIEW；
- coverage 统计和 PASS 门禁；
- 一对一、班课、名单差集的标准化测试；
- 一个轻量 CLI，接受已标准化的 CSV。

未实现：

- 真实 Excel 多布局、公式缓存、批注、外部 VLOOKUP 的生产 adapter；
- 从原始排课记录完整重算当前所有工资字段；
- 续费消息自然语言 parser 的迁移；
- 退费/管理绩效全量业务计算；
- 自动读取真实 8 月文件的生产命令；
- UI、数据库、商业化功能。

这些未实现项没有用猜测填充，保留在 adapter 和字段地图的 UNKNOWN/TODO 边界内。

## 数据模型

`ScheduleRecord` 表示一节标准化排课记录，保留 period、teacher、grade、subject、class_type、attended、student、lesson_time 和 source。

`PayrollRecord` 表示一位教师在一个期间的标准化工资字段，包括 one_to_one、class_value、production、ae、af、av。

`RenewalRecord` 和 `RefundRecord` 分别保存续费结构化字段和退费扣款字段。`RefundRecord.total_amount` 只做明确的两列相加，不推断月份或归属。

`ManualDecision` 是不可隐式推导的业务覆盖。对账时必须匹配 period、target、field、system_value 和 override_value；旧裁决与新实际值不一致时，结果是 NEEDS_MANUAL_REVIEW，不会静默吞掉差异。

## Reconciliation 机制

调用方提供 expected、actual 和 required_fields。每个 required field 都必须产生一条结果。两边数值相等为 MATCH；配置的生效期调整后相等为 EXPLAINED_DIFFERENCE；存在已确认且值完全匹配的人工裁决为 EXPLAINED_DIFFERENCE；没有解释的差值为 UNEXPLAINED_DIFFERENCE；一边缺少为 MISSING_SOURCE/MISSING_TARGET；字段没有提供为 NEEDS_MANUAL_REVIEW。

差值定义为 `actual - expected`。因此脱敏漏洞样本“系统 36、工资表 30”得到 `-6`，且整体不能 PASS。

## Coverage 机制

Coverage 不是“当前列表里没有异常”的同义词。调用方必须声明 required_fields。引擎会报告 required_checks、completed_checks、coverage_percent、各状态数量和 overall_status。没有提供的必查字段会产生 NEEDS_MANUAL_REVIEW，coverage 不完整，整体不能 PASS。

只有同时满足以下条件才返回 PASS：

1. 所有 required fields 都产生了完成结果；
2. UNEXPLAINED_DIFFERENCE 为 0；
3. MISSING_SOURCE、MISSING_TARGET 为 0，或被完整人工裁决覆盖；
4. NEEDS_MANUAL_REVIEW 为 0。

## 配置 V0

已抽出的配置只有当前最适合外置的部分：期间、数值容差、角色排除，以及带 `effective_from`/`effective_to` 的对账调整。固定解析算法、Excel 操作、姓名规范化和通用差值计算仍在代码中。

`config/default.yaml` 是空调整的默认配置。`config/example_2026_08.yaml` 只使用虚构人员和虚构调整，作为测试配置，不代表真实业务政策。

## 与现行 Skill 的关系

现行 Skill、旧脚本、references、8 月资产和 1 月 legacy 全部保留。Core V1 不是替换，也没有修改它们。将来的 Skill 可以准备输入、调用 Core、解释 report，但当前 Core 也可以脱离 WorkBuddy 执行测试和标准化 CSV 对账。

## 真实 8 月 dry-run 状态

已做只读结构 dry-run，没有写回任何真实文件。8 月目录共发现 26 个 Excel 文件/备份，按名称分类为：2 个排课源、17 个工资/核对表及备份、1 个续费表、1 个退费表、2 个统计表、3 个考核表。23 个 OOXML 工作簿可以读取 sheet 结构；3 个旧式 xls 文件没有被 Core 的 CSV adapter 伪装成已接入。

dry-run 确认的未映射层为：真实 Excel 多布局、xls 读取、公式缓存、单元格批注、外部 VLOOKUP 链接和最终人工合并。由于这些含义不能从文件名安全猜出，本阶段没有把真实数据标准化导入 Core，也没有把真实教师、学生、工资或续退费明细写入仓库。这个结果是“结构适用性检查完成、生产 Excel adapter 未完成”，不是工资正确性结论。

## 当前已知限制

V1 能证明“给定标准化 expected/actual 后，哪些字段被检查、差异是否解释、coverage 是否完整”。它还不能证明“从真实 Excel 到标准化字段的每一步都正确”。因此当前 CLI 的 PASS 只适用于已确认 schema 的标准化输入，不应被解释成真实 8 月工资已经自动复核通过。
