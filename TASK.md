# TASK — Windows 实机 UAT（v0.21.0-rc1）

## 目标

在 Windows 10/11 x64 机器拉取 `feature/payroll-core-config-chain` 的 rc1 提交，验证现有 Mac 主线可以稳定运行。先做源码模式，再做 Windows 本机构建的 `--onedir` 打包验证。

## 开始前

1. 阅读 `AGENTS.md`、`CURRENT_STATE.md`、本文件与最新 `DEVLOG.md`。
2. 确认分支、提交、工作区干净状态；不要基于未提交的 resolution workflow 半成品。
3. 使用 Python 3.11 x64、独立 venv 和脱敏 fixtures。真实业务数据只允许本机只读使用，不能进入 Git 或安装包。

## 必须验证

- 完整 pytest。
- 中文路径、空格路径、LocalAppData 数据目录、SQLite Run/Decision 持久化、hash/STALE 检测、端口选择、浏览器启动与文件锁错误提示。
- 脱敏流程：导入 → 建 Run → 核对 → Business Issue → 证据 → 人工决定 → rerun → 重启恢复。
- 在 Windows 本机用 PyInstaller `--onedir` 打包后，再重复完整脱敏 E2E；产物不得依赖系统 Python。

## 禁止事项

- 不改变 AA/AC/AD/AE/AF 业务规则，不合并 main。
- 不接续费、退费、推荐、管理绩效、AV，不触碰 Source correction / approved override 开发线。
- 不提交真实工资、姓名、学生、排课、续退费数据或真实 Excel。

## 完成标准

测试员解压 Windows RC1 压缩包后，双击即可启动 UI，并能用 demo 脱敏材料完成一次核对、保存人工决定、重启恢复与 STALE 验证。若出现跨平台问题，只修平台适配，不改工资算法。
