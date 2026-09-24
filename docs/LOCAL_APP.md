# 正式本地入口（PRODUCTION LOCAL APP）

本文件说明普通用户以后**唯一**应该使用的工资核算入口。

## 1. 两条入口，互不混用

| 入口 | 使用者 | 路径 | 端口 | 数据目录 |
|---|---|---|---|---|
| **PRODUCTION LOCAL APP** | 真实用户（李老师本人） | `~/Applications/工资核算助手.app` | 固定 `8760` | `~/Library/Application Support/EducationPayroll` |
| DEVELOPMENT / UAT | 开发与测试 | `python -m payroll_ui --port 0 --data-dir /tmp/...` | 随机 | `/tmp/...`（用完即弃） |

真实 UAT 必须从「工资核算助手.app」进入。随机端口和 `/tmp` 数据目录只允许出现在开发测试里。

普通用户不再需要：`python` 命令、`localhost` 地址、端口号、Codex 临时启动的服务、Terminal 窗口。

## 2. 固定端口与来源

- 端口：`8760`（固定，定义在 `tools/payroll_launcher/paths.py` 的 `DEFAULT_PORT`）
- 程序目录：仓库根目录（本机为 `/Users/macos/Documents/做表/education-payroll-longrun-20260913`）
- 启动器状态目录：`~/Library/Application Support/EducationPayroll/launcher/`
  - `service.json` — 本启动器启动的服务记录（pid、端口、数据目录）
  - `diagnostics.log` — 启动/复用/停止的诊断流水
  - `service-output.log` — 服务进程自身的标准输出
  - `last-problem.md` — 最近一次失败诊断（点“查看诊断”打开的就是它）

## 3. 固定数据目录（P0）

**正式数据目录只有一个：**

```
~/Library/Application Support/EducationPayroll/
├── payroll-ui.sqlite3      # 正式数据库（历史 Run、星级、政策、规则、年级证据）
├── technical-errors.log
└── launcher/               # 启动器自身状态，不参与工资计算
```

启动器**不会**改变数据库位置，也**不会**：

- 使用 `/tmp`
- 每次新建 app-data
- 使用测试 fixture 目录
- 因为换个入口就换一套数据库

如果发现端口上的服务虽然也是工资服务、但数据目录指纹不是这一个，启动器会**拒绝接管**并提示，而不是默默连上去。

历史数据不会被迁移：数据库已经在这个位置时，启动器直接继续使用。若首次在别的机器上部署、该位置还没有数据库，服务会在同一位置创建空库，不会去别处找。

## 4. 双击后发生什么

1. 读取启动器配置（程序目录、Python、固定端口、正式数据目录）。
2. 探测固定端口：是**我们的**服务且数据目录一致 → 直接复用。
3. 端口没人监听 → 在正式数据目录上启动服务，等待健康检查通过。
4. 健康检查通过后调用系统默认浏览器打开首页。
5. 用户看不到 Terminal，也不需要知道地址和端口。

**并发保护**：两个双击同时发生时，启动器用文件锁串行化，只有一个实例会真正启动服务。

## 5. 如何安全重启

双击 `~/Applications/重启工资服务.app`。

安全边界：

- 只结束**启动器自己记录的**那个 pid；
- 结束前校验：记录里的数据目录一致、健康检查报告的 pid 与记录一致、该 pid 的命令行确实包含 `payroll_ui`；
- 任一条件不满足就跳过并提示，**不会结束无关进程**；
- 端口上如果跑的不是本启动器管理的实例，只复用、不结束。

命令行等价方式（诊断用）：

```sh
导出工具目录后执行：
  python -m payroll_launcher              # 打开（必要时启动）
  python -m payroll_launcher --mode restart  # 安全重启
  python -m payroll_launcher --stop          # 安全停止
  python -m payroll_launcher --status        # 打印状态
  python -m payroll_launcher --inventory     # 只读列出历史 Run
```

## 6. 出错时的体验

启动失败时**不闪退、不显示 traceback**，而是一个中文对话框：

> 工资核算服务启动失败，请查看诊断信息。

按钮：**重试** / **重新启动** / **查看诊断**。

- 端口被其它程序占用 → 明确提示，绝不结束其它程序；
- Python 环境不完整 → 提示先安装依赖再重试；
- “查看诊断”打开 `last-problem.md`，里面只有路径和技术信息，**不含任何工资/教师/学生数据**。

## 7. 构建与安装

```sh
sh macos/build_app.sh                     # 只在 macos/dist/ 生成
sh macos/build_app.sh --install           # 另外复制到 ~/Applications
sh macos/build_app.sh --install --desktop # 再加桌面入口
```

生成的 bundle 会把**绝对路径**固化进 `Contents/MacOS/launcher`，所以：

- 不依赖调用时的 shell cwd；
- 不依赖终端窗口；
- 不依赖 Codex 或任何外部运行器；
- 不使用 Electron / Tauri，不重写现有 UI——只是把现有 `payroll_ui` 拉起来。

**移动仓库后必须重新执行 `sh macos/build_app.sh --install`**，否则 bundle 里的绝对路径会指向旧位置。

`macos/dist/` 与 `macos/*.app/` 已在 `.gitignore` 中：bundle 里含有本机绝对路径，仓库只保留生成脚本。

## 8. 服务身份握手

服务端 `GET /api/health`（**无需 token**）返回：

```json
{
  "contract": "payroll-ui/1",
  "app": "education-payroll",
  "service": "payroll-ui",
  "pid": 12345,
  "port": 8760,
  "data_dir_fingerprint": "8a64cbc71037",
  "started_at": "2026-09-24T08:13:45+00:00",
  "run_count": 8
}
```

启动器用 `contract` 判断“这是不是我们的服务”，用 `data_dir_fingerprint`（数据目录绝对路径的 sha256 前 12 位）判断“是不是同一个数据目录”。

该接口只描述进程身份，**不含**教师、学生、金额或任何文件内容，因此可以免 token 暴露在 loopback 上。

## 9. 真实验收清单

| 步骤 | 结果 |
|---|---|
| 1. 当前没有 Payroll 服务运行 | 通过 |
| 2. 双击「工资核算助手.app」 | 通过 |
| 3. 服务自动启动 | 通过（第 2 秒健康检查通过） |
| 4. 浏览器自动打开 | 通过（由 `/usr/bin/open` 交给系统默认浏览器） |
| 5. 能看到原来的真实历史 Run | 通过（8 个 Run，其中 6 个 `2026-08`） |
| 6. 公司模板、基础资料仍存在 | 通过（星级 2、政策 3、班型规则 2、核心规则 1、年级证据 28056、导出版本快照 8247） |
| 7. 关闭浏览器 | 通过 |
| 8. 再双击 APP | 通过 |
| 9. 不启动第二套数据库或第二个服务 | 通过（pid 不变、监听数 1、数据目录无新增库） |
| 10. 页面正常重新打开 | 通过（首页 HTTP 200） |
| 11. 重启电脑后再次双击仍可使用 | 待重启后复验（数据目录在 Application Support，不随重启清理） |

启动器自身独立性：不依赖 Codex、不依赖终端、不依赖当前 cwd（从 `/` 与 `/tmp` 运行结果一致）、不依赖临时目录、不使用随机端口。

## 10. 已知限制

- bundle 内的绝对路径在仓库移动后会失效，需重新执行 `--install`。
- `.app` 是本地生成、未签名的 bundle。首次打开若被 Gatekeeper 拦，右键选择“打开”一次即可。
- 正式服务是**单实例固定端口**：端口被无关程序占用时不会自动改端口，这是刻意的取舍（用户入口必须稳定可预期）。
- 服务身份是通过 `/api/health` 自报的。它足以避免误杀和误复用，但不等同于加密认证；本服务只监听 loopback。
