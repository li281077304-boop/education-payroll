# Windows 正式入口（PRODUCTION LOCAL APP · Windows）

本文件说明 Windows 上普通用户**唯一**应该使用的工资核算入口。
它是 [`LOCAL_APP.md`](LOCAL_APP.md)（macOS 版）的 Windows 对应版本，
两者的端口、数据目录语义和验收清单保持一致。

## 1. 两条入口，互不混用

| 入口 | 使用者 | 路径 | 端口 | 数据目录 |
|---|---|---|---|---|
| **PRODUCTION LOCAL APP** | 真实用户 | `工资核算助手.exe` | 固定 `8760` | `%LOCALAPPDATA%\EducationPayroll` |
| DEVELOPMENT / UAT | 开发与测试 | `python -m payroll_ui --port 0 --no-browser` | 随机 | 临时目录（用完即弃） |

`run_ui.bat` 保留为开发/诊断入口，**不再是正式用户入口**。

普通用户不需要：CMD / PowerShell、`.bat`、`python` 命令、安装 Python 或 pip 依赖、
知道 `localhost`、知道端口号、知道仓库目录或虚拟环境。

## 2. 双击之后发生什么

1. `工资核算助手.exe` 从自身位置解析配置，不依赖调用时的当前目录。
2. 用互斥体串行化并发双击，保证只有一个实例进入“启动服务”分支。
3. 探测 `127.0.0.1:8760`：
   - 没有服务 → 用**自己**这个可执行文件重新进入 `--service` 模式启动服务，
     显式传入正式数据目录；
   - 已经是本项目服务且数据目录指纹一致 → 直接复用；
   - 是本项目服务但数据目录不同 → 拒绝接管并提示；
   - 端口被其它程序占用 → 明确提示，**不杀进程、不改端口**。
4. 等待 `GET /api/health` 成功。
5. 用系统默认浏览器打开首页。全程没有 CMD 黑窗口，也不需要管理员权限。

## 3. 发布包里有什么

```
EducationPayroll/
├── 工资核算助手.exe            ← 用户唯一需要双击的文件
├── 重启工资服务.exe            ← 安全重启（只结束本启动器启动的服务）
├── 工资核算助手-命令行.exe      ← 排障：--status / --stop / --inventory / --diagnostics
├── 使用说明.txt
└── _internal/                  ← Python 运行时、依赖与静态资源
    ├── payroll_ui/static/      ← index.html / app.js / app.css / teacher.html
    └── config/core_rules_2026.yaml
```

程序自包含：不依赖系统 Python、不依赖 pip、不依赖 Git、不依赖 DeepSeek/Codex。
只有 `工资核算助手.exe` 需要被双击；其它文件不需要用户操作，但**不能单独复制 exe**，
必须整个目录一起移动。

## 4. 固定数据目录（P0）

正式数据目录只有一个：

```
%LOCALAPPDATA%\EducationPayroll\
├── payroll-ui.sqlite3      # 正式数据库（历史 Run、星级、政策、规则、年级证据）
├── technical-errors.log
├── uploads/
└── launcher\               # 启动器自身状态，不参与工资计算
    ├── service.json            # 本启动器启动的服务记录（pid、端口、数据目录）
    ├── diagnostics.log         # 启动/复用/停止的诊断流水
    ├── service-output.log      # 服务进程自身的标准输出
    └── last-problem.md         # 最近一次失败诊断
```

启动器**不会**：

- 把数据库放在 exe 旁边、Downloads、Desktop 或临时目录；
- 每次启动新建 data-dir；
- 因为升级程序而覆盖数据库。

替换或重新解压程序目录时，正式 SQLite 保持原位不动。

## 5. 端口与单实例

- 端口固定 `8760`，定义在 `tools/payroll_launcher/paths.py` 的 `DEFAULT_PORT`。
- **不要仅仅通过“端口能连接”就认为是自己的服务。** 启动器复用前会校验
  `GET /api/health` 的 `contract` / `app` / `service`，并比对
  `data_dir_fingerprint`（数据目录绝对路径的 sha256 前 12 位）。
- 单实例由三层共同保证：
  1. 启动器互斥体（Windows 命名互斥体，进程被杀也会由内核释放）；
  2. 启动前探测健康契约，已有实例直接复用；
  3. 服务端**独占绑定**端口 —— Windows 的 `SO_REUSEADDR` 允许重复绑定同一端口，
     因此发布包显式关闭它，让第二个实例在启动时直接失败，而不是悄悄跑第二套服务。

## 6. 服务身份握手

`GET /api/health`（**无需 token**）返回：

```json
{
  "contract": "payroll-ui/1",
  "app": "education-payroll",
  "service": "payroll-ui",
  "pid": 12345,
  "port": 8760,
  "data_dir_fingerprint": "8a64cbc71037",
  "started_at": "2026-09-28T13:00:00+00:00",
  "run_count": 8
}
```

该接口只描述进程身份，不含教师、学生、金额或任何文件内容，因此可以免 token
暴露在 loopback 上。

## 7. 如何安全重启

双击 `重启工资服务.exe`。停止前必须同时满足：

- 启动器记录里的数据目录与当前一致；
- `/api/health` 返回的 pid 与记录一致，且是本项目服务；
- 记录的 pid 仍然存活，且其可执行文件镜像与本发布包一致。

任一条件不满足就跳过并提示，**绝不做按端口的 `taskkill`，更不会结束所有 `python.exe`**。

满足条件时，先向服务写入一次停止请求（`launcher\stop-request.json`，
带 pid 与数据目录指纹）让服务**自己**关闭数据库并退出；超时后才终止该 pid。

## 8. 出错时的体验

启动失败不静默退出、不显示 traceback，而是：

1. 写入 `%LOCALAPPDATA%\EducationPayroll\launcher\diagnostics.log`；
2. 写入 `last-problem.md`；
3. 弹出中文对话框：

> 工资核算助手启动失败，请查看诊断信息。

Windows 使用系统消息框：**是 = 重试 / 否 = 打开诊断文件 / 取消 = 关闭**。
诊断文件里只有路径和技术信息，**不含任何工资、教师或学生数据**。

## 9. 构建（可重复）

```bat
python windows\build_windows.py
```

产出（默认在 `windows\dist`，已加入 `.gitignore`）：

```
windows\dist\EducationPayroll-Windows-v1\
└── EducationPayroll\...
windows\dist\EducationPayroll-Windows-v1.zip
windows\dist\EducationPayroll-Windows-v1.zip.sha256
```

构建从当前 checkout 完全可重复，不会把本机路径写进可执行文件。构建产物不提交 Git。

PyInstaller 只在 `_internal` 里放运行时；脚本用 ASCII 名构建后再重命名为中文名，
而入口脚本通过读取自身文件名决定默认动作，因此不依赖构建期的非 ASCII 文件名。

## 10. Windows 与 macOS 的差异

| 项目 | macOS | Windows |
|---|---|---|
| 正式入口 | `~/Applications/工资核算助手.app` | `工资核算助手.exe` |
| 运行方式 | bundle 里的 shell bootstrap 调仓库 Python | exe 自带运行时，用 `--service` 重新进入自身 |
| 数据目录 | `~/Library/Application Support/EducationPayroll` | `%LOCALAPPDATA%\EducationPayroll` |
| 打开浏览器 | `/usr/bin/open` | 系统默认浏览器关联 |
| 失败对话框 | `osascript` | Win32 消息框 |
| 文件选择器 | `osascript choose file/folder` | Win32 通用对话框（`comdlg32`） |
| 并发锁 | `flock` | 命名互斥体 |
| 进程身份 | `ps -p … -o command=` | `QueryFullProcessImageNameW` |

端口、数据目录语义、健康契约与安全重启规则完全一致。
操作系统相关的原语集中在 `tools/payroll_launcher/host.py`
与 `payroll_ui/native_dialogs.py`，业务代码不出现平台分支。

## 11. 真实验收清单

| 步骤 | 结果 |
|---|---|
| 1. 当前没有 Payroll 服务运行 | 见 FINAL REPORT |
| 2. 双击「工资核算助手.exe」 | 见 FINAL REPORT |
| 3. 没有 CMD 黑窗口 | 见 FINAL REPORT |
| 4. 服务自动启动，`/api/health` 正常 | 见 FINAL REPORT |
| 5. 默认浏览器自动打开 | 见 FINAL REPORT |
| 6. 首页正常加载 | 见 FINAL REPORT |
| 7. data_dir 是 `%LOCALAPPDATA%\EducationPayroll` | 见 FINAL REPORT |
| 8. 再双击一次不产生第二个服务/数据库 | 见 FINAL REPORT |
| 9. 极速生成工资表（手选 2026-08）成功 | 见 FINAL REPORT |
| 10. 关闭浏览器后数据仍在 | 见 FINAL REPORT |
| 11. 换目录（`C:\Payroll Release\`、桌面）仍可运行 | 见 FINAL REPORT |
| 12. 重启电脑后再次双击仍可使用 | 见 FINAL REPORT |

自动化部分：

```bat
.venv\Scripts\python.exe -m pytest -q tests\test_launcher.py tests\test_launcher_windows.py
.venv\Scripts\python.exe -m pytest -q tests\test_browser_uat_windows.py
```

## 12. 已知限制

- 发布包未签名。首次运行若被 SmartScreen 拦，选择“仍要运行”一次即可。
- 正式服务是**单实例固定端口**：端口被无关程序占用时不会自动改端口，这是刻意的取舍。
- 服务身份靠 `/api/health` 自报，足以避免误杀和误复用，但不等同于加密认证；
  本服务只监听 loopback。
- 重复启动时若用户在不同会话（快速用户切换）各开一次，互斥体不共享，
  此时由服务端独占绑定兜底。
