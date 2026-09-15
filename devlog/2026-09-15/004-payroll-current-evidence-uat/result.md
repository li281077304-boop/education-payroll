# Payroll current evidence UAT

日期：2026-09-15
任务：`payroll-current-evidence-uat`

## 可复现检查

| 检查 | 命令/范围 | 结果 |
|---|---|---|
| 项目运行时 | `/Users/macos/.local/bin/python3.12 --version` | `Python 3.12.13`，符合 `pyproject.toml` 的 `>=3.11` |
| 默认运行时 | `/usr/bin/python3 --version` | `Python 3.9.6`；低于声明版本，导入时因 `enum.StrEnum` 失败 |
| 测试套件 | `/Users/macos/.local/bin/python3.12 -m pytest -q` | 未执行：该解释器没有 `pytest`（退出 1） |
| CLI 脱敏夹具 | `...python3.12 -m payroll_core.cli check --config config/default.yaml --expected tests/fixtures/minimal_payroll/cli_expected.csv --payroll tests/fixtures/minimal_payroll/cli_actual.csv` | 未执行：环境没有 `openpyxl`，CLI 导入阶段失败（退出 1） |
| 依赖恢复尝试 | 临时 venv `/private/tmp/payroll-uat-venv`，`pip install -e '.[test]'` | 失败：网络代理不可用，无法取得 `setuptools>=68`（退出 1） |
| UI 文档 | 检查 `docs/UI_SPEC_V1.md` | 文件不存在 |

## 证据结论

- 仓库已有 Core/CLI 及脱敏 CSV/Excel fixtures；fixture README 明确所有值均为虚构数据。
- 当前环境无法完成 pytest 或 CLI 的运行时验证，原因是 Python 3.12 环境缺少依赖且无法联网安装；Python 3.9 也不满足项目最低版本。
- 仓库规则明确真实工资表、教师收入、学生名单、续费/退费明细、原始排课与生成结果不提交。`CURRENT_STATE.md` 和 `ASSET_INDEX.md` 也确认真实 8 月输入未复制，因此本轮没有真实数据结果。
- `docs/PAYROLL_CORE_V1.md` 明确真实 Excel 多布局、公式缓存、批注、外部引用和最终人工合并仍属未实现/需人工复核范围；未将这些字段标记为完成。

## 缺口分类

1. 技术环境缺口：可用主机解释器无 pytest/openpyxl；隔离安装受网络限制阻断。
2. UI 文档缺口：任务引用的 `docs/UI_SPEC_V1.md` 在工作树中不存在，因此没有可执行的仓库 UI/UAT 步骤。
3. 真实来源缺口：敏感真实工作簿按设计不在仓库，无法在本轮访问或验证真实工资结果。
4. 业务/实现未覆盖：真实 Excel adapter、自然语言续费迁移、退费/管理绩效全量计算及最终人工合并仍按 Core 文档保持 UNKNOWN/TODO。

本记录不构造工资规则，不把脱敏 fixture 的潜在结果或历史 dry-run 误报为真实工资 PASS。
