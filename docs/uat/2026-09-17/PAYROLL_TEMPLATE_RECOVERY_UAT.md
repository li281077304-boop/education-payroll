# Payroll 公司工资模板恢复回归 UAT

日期：2026-09-17

## 结论

本次是 UAT 回归，不是新的业务资料缺失。公司真实模板已经存在，系统已恢复自动识别、跨 Run 复用和导出；找不到任何真实模板时仍 fail-closed。

## 现场证据

- 最新 Run：`40360d851ace`，`2026-08`，`GENERATE`
- 回归前：`template_path = null`，`package_root = null`，Run 只有排课源文件
- 历史成功 Run：`a1c9e2563e37`，同为 `2026-08`，曾持久化真实模板：
  `/Users/macos/Desktop/payroll_read_test/薪资表模板.xlsx`
- 历史模板 SHA-256：`fe483e5e95df2049e638375fc8e25ab1ba4d2b00e1f1945c95119e280031ecaf`
- 历史实现已在 commit `850b069` 通过资料包扫描绑定模板；当前分支仍保留该 package-import 行为。

## 根因

新 Run 的 `create()` 只初始化排课、星级、政策等 Run 字段，没有从同周期历史 Run 的已验证 `template_path` 继承模板。当前资料包扫描只有在本次调用 `import_package()` 时才会执行；本次最新 Run 是直接创建并导入排课，因此既没有 `package_root`，也没有再次触发模板扫描。SQLite 没有丢字段：旧 Run `a1c9e2563e37` 的 `template_path` 仍在库中。属于“新 Run 未继承已持久化模板 / 导入链未被调用”的回归，不是模板不存在，也不是 renderer 需要放宽 fail-closed。

## 修复

1. 新 Run 创建时，从同周期优先、再按最近历史顺序读取已持久化模板路径和历史资料包目录。
2. 当前 Run 有模板路径时验证文件存在和真实工资模板信号，补齐 SHA-256、大小、来源 Run、绑定时间；不覆盖资料包导入的原始 provenance。
3. `get()` / resume 也执行同一确定性恢复，因此进程或页面重载后仍能复用。
4. 页面显示“已绑定公司工资模板”及真实文件名/来源。
5. 没有任何可信真实模板时，renderer 继续拒绝导出，不生成系统自创“标准工资表”。

## 真实导出回归

- Run：`40360d851ace`
- 自动恢复来源：历史 Run `a1c9e2563e37`
- 导出：`/private/tmp/payroll-template-recovery-uat/工资表-2026-08-recovered.xlsx`
- 输出 SHA-256：`1e464f73327543ec0c9875b171b5b98e59a36a8d4c43087281cd7959ef738810`
- 结果：文件成功生成并重新打开；计算仍按真实业务输入状态返回 `NEEDS_CONFIRMATION`，这不是模板错误。
- 公司模板工作表 `Sheet1` 保留。
- 原模板合并区域 19，输出保留 19，全部包含。
- 原模板列数 49，输出列数 49；原模板行数 34，输出业务行扩展到 55。
- 输出附加可审计证据页：`核验与来源`、`外围字段状态`。
- `#REF!` / `#VALUE!` / `#NAME?`：0。

## 自动化回归

- 真实资料包模板绑定：PASS
- 新 Run 复用历史真实模板：PASS
- 缺少模板时仍不自动生成伪模板：PASS（renderer 既有 fail-closed 测试）
- `tests/test_payroll_ui_service.py`、`tests/test_standard_payroll_output.py`、`tests/test_core_service_chain.py`：`60 passed`
- `node --check payroll_ui/static/app.js`：PASS

## 剩余状态

模板绑定不再是 HUMAN_REQUIRED。当前 Run 仍可能因星级、AF、续费、退费及外围字段等真实业务输入保持 `NEEDS_CONFIRMATION`；这些与模板回归无关，未被伪造为 PASS。
