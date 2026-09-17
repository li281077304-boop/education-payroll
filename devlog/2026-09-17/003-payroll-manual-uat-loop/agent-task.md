# Ralph Task

正式执行 Payroll 真实手工 UAT 闭环。先阅读并保留原始证据 `docs/uat/2026-09-17/evidence/PAYROLL_MANUAL_UAT_RAW_2026-09-17.md`，再读取规范化验收 `docs/uat/2026-09-17/PAYROLL_MANUAL_UAT_2026-09-17.md`、模板恢复证据和当前 Git/运行状态。

建立 durable issue ledger，逐项给出 ROOT_CAUSE、FIX、TEST、STATUS。已存在真实公司工资模板不得重新变成人工资料缺失；保持找不到可信模板时 fail-closed。对真实技术问题自行修复、测试并继续 Big Loop，不修改 Payroll 业务规则之外的项目，不清理用户/运行时证据。所有 Worker/Chief/Gate 结果、checkpoint、恢复决定和最终状态必须落盘。若确实遇到允许的人类业务输入，再按 Human Boundary 进入 HUMAN_REQUIRED；普通 UI、解析、测试、构建、运行时和模板绑定问题均保持技术处理。

完成条件：规范化 UAT 中的 P0/P1 结果有证据，现有模板导出结构回归保持通过，Ralph run 状态可从磁盘恢复，并给出剩余技术/人为阻塞的明确证据。
