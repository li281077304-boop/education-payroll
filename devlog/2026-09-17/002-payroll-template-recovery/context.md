# Context

## USER OBSERVATION

公司原工资模板早已存在，旧版本可以按真实公司工资表格式导出；本轮新 Run 却退回“需要人工绑定模板”。用户明确要求继续 Big Loop，不重新索取模板。

## CONFIRMED FACT

历史 Run `a1c9e2563e37` 持久化了 `/Users/macos/Desktop/payroll_read_test/薪资表模板.xlsx`；最新 Run `40360d851ace` 创建时 `template_path` 为空、`package_root` 为空，但 SQLite 没有删除历史字段。历史 commit `850b069` 已有资料包扫描绑定行为。

## TECHNICAL ASSESSMENT

回归点是新 Run 没有继承已验证模板，且本次只导入排课没有调用资料包扫描；不是模板缺失，也不是要求放宽导出安全门。

## REJECTED ASSUMPTIONS

- 不能把已有真实模板当成不存在。
- 不能用自创“标准工资表”绕过模板缺失。
- 不能要求用户重新绑定或重新提供模板。

## DECISION

增加确定性历史 Run / 当前资料包模板恢复，并持久化模板 hash、来源和绑定时间；保留无可信模板时 renderer fail-closed。

## UNKNOWN / OPEN RISKS

其它工资业务输入仍可能阻塞最终金额确认；本轮只处理模板回归。
