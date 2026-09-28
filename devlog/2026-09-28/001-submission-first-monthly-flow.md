# 2026-09-28｜DS-V4.1 月度工资流程收口

## 目标与边界

落实产品确认的 Submission-First 新月度流程：学科组提交表决定输出教师并集；没有提交表时回退到人工月排课名单。历史工资参考、长期工资基础和全职/兼职资料继续保留为兼容/审计数据，但不参与新 Run 的月度名单、B～L 或工资基础判断。旧 Run 不迁移，不做数据库 destructive migration。

本轮不改变 AA、AC、AD、AE、AF、AK、AV、退费公式、人工月 authority、模板结构或批注规则；不读取或写入生产 SQLite，不启动正式工资助手。

## 实现记录

- 新显式标记：`monthly_flow_version=SUBMISSION_FIRST_V1`；无此标记的旧 Run 继续走旧兼容分支。
- 新 Run 不预载历史工资 G～L 和旧 AF 确认；月度流程不查询长期工资基础/用工状态来扩展名单或生成待办。
- 学科组提交表通过当前资料入口导入后直接成为有效来源；无需科组选择、预览或再次确认。多份提交表按教师姓名规范化后的精确匹配合并；不同教师可跨组，重复一致合并，真实字段冲突保留待处理记录。
- 输出名单：至少一份有效组表时使用所有组表教师并集；否则使用完整人工月排课 Roster。组表中无排课教师仍保留工资行。提交教师无法唯一对应存在身份冲突的排课身份时 fail closed。
- B～L 按字段级来源合并：本月支持部权威值优先，其次学科组提交表值，再到空白；不读取历史工资或长期档案。Run 记录字段值及来源文件/工作表/单元格/hash，最终 renderer 将当前 Run 的 B～L 写入真实工资模板。星级 F 不再从星级权威自动回填，而只遵守 B～L 当前工资来源。
- 已确认的续费快照中不存在该教师记录时，AH/AI/AJ 为 0，AK 继续由既有公式派生；真实身份或来源冲突仍保留异常。
- AF 规则卡在第三步前置显示；默认 30 小时，只有被勾选例外的教师填写小时数和原因。新流程通过“下一步：工资预览”调用现有核算链。
- 简化新 Run 隐藏历史工资、归组、用工性质、工资基础及兼职待办；星级只展示自动应用/管理员配置状态；GENERATE 模式不将来源公式 advisory 显示成普通用户红色告警。旧 Run UI 保持兼容。

## 回归证据

新增离线回归覆盖：51 人排课+15 人组表输出严格为 15 人；无组表回退 51 人且 B～L 留白；组表 B～L 写入；支持部 B～L 覆盖；提交表无需科组选择且多文件并集；重复同值合并；冲突字段产生一项待处理；已确认续费缺行归零；无工资基础/用工待办；AF 规则确认及例外原因校验；简化 UI 隐藏旧流程概念、AF 卡与自动预览导航、GENERATE 公式 advisory 隐藏。

## 最终验证

- `sh tools/run_tests.sh`：655 passed。
- Python compile：PASS（`uv run python -m compileall -q payroll_ui payroll_core tests`）。
- JavaScript syntax：PASS（`node --check payroll_ui/static/app.js`）。
- `git diff --check`：PASS。
- 实现提交：`46655a7a5909ce8418d25adbdb25a1be50cf9598`。
- GitHub Actions：run `36383977866`（`tests`）对实现提交完成验证，`success`。
- HUMAN_REQUIRED：NONE。
