# AI 依赖审计

## 结论

当前工资流程并不是“AI 计算工资”。它是人工准备输入、Skill 提供业务操作说明、Python/Excel 执行部分确定计算、人工确认异常的混合流程。新 Payroll Core V1 把最基本的差值判断、缺失检查和 coverage 门禁交给 Python，不依赖 LLM。

| 现有环节 | AI/Skill 的作用 | 依赖级别 | 应由谁负责 | Phase 1 状态 |
|---|---|---|---|---|
| 文件定位和开工材料确认 | 根据用户描述识别当月文件 | 当前因历史原因使用 AI | 人工/输入清单 | 未接入真实 Excel |
| 排课字段识别 | Skill 解释旧新列名，Python 读取 | 可选 AI | Python adapter + 明确 schema | CSV adapter 已有 |
| 年级/学科/班型提取 | Skill 解释业务优先级，Python 有确定函数 | 不需要 AI | Python + 配置/人工异常 | 现行代码保留；Core 尚未迁移全部 |
| 一对一/班课公式 | Skill 描述公式，Excel/Python 计算 | 不需要 AI | Python/Excel | V1 对账可比较标准化值 |
| AE/AF | Skill 提供规则，`verify_ae_af.py` 计算 | 不需要 AI | Python | 现行验证脚本保留 |
| 续费消息解析 | 当前脚本用规则解析，异常需人回看 | 可选 AI | 规则 parser + 人工复核 | V1 不擅自接入消息格式 |
| 续费/退费外部认定 | 外部表已经给出业务事实 | 不需要 AI | 外部业务表 + adapter | 只定义模型/CSV adapter |
| 代课、特殊退费、兼职、星级 | Skill 描述判断点，用户拍板 | 必须人工，不应交给 AI 猜 | 人工裁决数据 | `ManualDecision` 已有 |
| 全量差值扫描 | 旧流程依赖 Skill 执行清单 | 当前因为历史原因使用 AI | Python reconciliation engine | 已实现 V1 基础门禁 |
| 差额原因解释 | Skill/AI 可以组织说明，但不能生成事实 | 可选 AI | Python 结果 + 人工依据 | V1 只接受配置或裁决依据 |
| 最终 PASS | 旧流程可能因检查范围不足而口头判断 | 不需要 AI | Python coverage/status gate | 已实现 |

## E 类规则的实际含义

“LLM-only”不是说必须让模型去算，而是当前仓库只有自然语言要求、没有程序强制保障。例如全扫 S/V、逐课溯源、批注与源数据交叉检查、每项完成后才能进入下一项。Phase 1 的目标是先把其中的“是否检查、是否有差异、是否缺少输入”变成 Core 的可验证状态；业务原因仍可由人工提供。

## 保留 Skill 的原因

Skill 仍适合承担任务理解、材料清单、异常解释和调用 Core 前后的用户沟通。它不应继续单独承担关键计算和 PASS 判定。

