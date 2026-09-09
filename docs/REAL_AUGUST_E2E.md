# 2026-08 真实 UI 端到端验收记录

> 状态：**BLOCKED — 未宣称验收通过。**

## 本次可复现的阻断

在启动 UI 前，对真实工作区进行只读文件生命周期检查时，Python 的
`os.scandir()` 对 8 月目录返回 `InterruptedError: [Errno 4] Interrupted
system call`。对已知排课文件路径进行内容读取也返回同一错误，因此这
不是 Workbook Fingerprint、Excel Adapter、浏览器或 UI 的解析错误。

`diskutil verifyVolume /System/Volumes/Data` 报告 APFS Data 卷“found to be
corrupt and needs to be repaired”。在线校验完成可做的延后修复后，该目录
仍返回 `EINTR`。因此不能安全读取、复制或导入真实工作簿，也不能诚实地
完成 UI 操作验收。

所需的下一项外部动作是：在 macOS 磁盘工具中对 Data 卷执行急救；如果
急救要求重启或恢复模式，应按系统提示完成后再运行本验收。该动作不在
本仓库代码或 UI 的授权范围内，本次未执行破坏性磁盘修复。

## 代码侧处理

- UI 的文件导入和重新核对现在捕获 `OSError errno=4`，显示“文件读取
  失败”及可操作的磁盘工具提示，而非向用户显示 traceback。
- 本地 `payroll-ui.log` 仅记录 run id、材料类别、记录数量、状态和错误码；
  不记录姓名、金额、学生、文件名或路径。
- 读取失败会使已导入 Run 进入 `STALE`，不会保留成“已通过”。

## 已有只读结构证据（非 UI 验收结果）

此前的 Adapter dry-run 曾在本机结构读取阶段识别到：一份 8 月权威排课
源、两份工资表，以及 2,354 条原始排课行。该结构发现**不能**替代本次
要求的产品入口验收；本报告不记录任何姓名、工资值、学生或文件名。

在文件系统修复前，以下项目均保持“未验证”：真实 UI 导入、AA/AC 实际
差异列表、真实 provenance 展示、人工决定持久化后的真实重跑、以及真实
文件修改触发 STALE。
