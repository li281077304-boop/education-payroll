# Ralph Loop Task — Payroll UAT 2026-09-17

task_id: payroll-uat-2026-09-17-close-real-flow
source: real manual UAT by user
priority: P0
target: education-payroll

## GOAL

闭合真实工资 UAT 流程：
待处理问题 → 基本工资/特殊情况确认 → 30 小时扣除 → 生成工资 → 工资预览 → 按公司原工资模板导出。

不要新增业务范围，不碰续费/退费/推荐/管理绩效扩展。先修真实 UAT 阻断。

## DURABLE UAT INPUT

先读 `UAT_2026-09-17_MANUAL_PAYROLL.md`，每一条 UAT ID 都必须在结果里给出：
- ROOT_CAUSE
- FIX
- TEST
- STATUS: PASS / BLOCKED / HUMAN_REQUIRED

## P0 ORDER

### P0-1 教师筛选输入
当前可见代码中 `updateFilters()` 在每次 `oninput` 后执行 `renderTab()`，会替换输入框 DOM 并导致焦点丢失。
修复：禁止每个字符立即销毁整个页面；使用 debounce + 恢复焦点，或只更新结果区域。
必须加回归测试：连续输入 `abc` / 中文名字不会只留下首字符。

### P0-2 星级缺失不得默认二星
当前 Core 存在：
`无系统权威 + 无上传资料 -> rating=2, state=DETERMINED, DEFAULT_TWO_STAR`
按 2026-09-17 UAT 新口径修改：
`无系统权威 + 无上传资料 -> value=None, state=NEEDS_INPUT`
绿色只允许权威已确定；缺资料必须黄色；权威与上传冲突必须红色。
不得用工资结果反推星级。

### P0-3 工资模板导出
当前 renderer 在 `template_path` 缺失时会自行 `Workbook()` 生成系统自定义“标准工资表”。
这是明确回归。
修复原则：
- 最终工资导出必须基于公司既有工资模板；
- 未绑定模板时 fail closed，禁止输出自设计“标准工资表”；
- UI 在当前流程内提供“选择/上传工资模板”入口；
- 已绑定模板时保留 Sheet、列顺序、表头、合并单元格、宽高和既有格式；
- 用历史正确 fixture 做结构回归。

### P0-4 30 小时确认失败
用户真实 UAT 多次触发：
“系统处理失败，系统已记录错误（错误编号 ...），请重试。”
其中一次错误编号：`4ac7c59609da3256`。
今天本机版本的 30 小时功能在当前可见远端分支中未找到，禁止猜修。
必须在运行环境读取 `technical-errors.log`，按错误编号定位 traceback。
同时前端必须立即显示 processing，并防重复提交。

### P0-5 基本工资与特殊情况动作闭环
待处理问题卡内直接提供：
- 现在上传基本工资
- 稍后上传
- 若业务允许：直接生成教师工资
- 确认无特殊情况
- 有特殊情况 / 设置例外

禁止要求用户再去主导航猜下一步。

## P1

- “51 位教师”聚合卡显式可点，提供“查看教师明细”；
- 工资预览统一 GREEN / YELLOW / RED；
- 去掉每个单元格重复长说明，详细依据折叠；
- 表头简化；
- 修复滚动到底部；
- 每个“核查动作”改成明确动词和结果描述。

## GATES

1. 先跑当前基线测试，记录基线。
2. 每个 P0 单独加回归测试。
3. 不允许因修 UI 改 AA/AC 公式。
4. 不允许无模板时回退到自设计最终工资表。
5. 不允许把未知星级转成二星“已确定”。
6. 每轮都写 durable result 到 `devlog/2026-09-17/...`。
7. 若 30 小时失败无法从错误日志定位，状态必须 HUMAN_REQUIRED，并准确写出缺失证据，不得猜。

## DONE

只有以下同时成立才允许结束循环：
- UAT-0917-01 / 03 / 04 / 05 / 07 / 12 全 PASS；
- 预览可用性 P1 至少完成三色状态 + 滚动；
- 使用真实公司工资模板完成一次导出结构验证；
- 无新增 UNEXPLAINED 回归；
- 给出 July 真实流程重新 UAT 的最短点击路径。
