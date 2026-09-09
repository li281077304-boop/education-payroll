# 工资核算助手 V0.1 技术决策

采用 Python 3.11 本地服务、内置 HTML/CSS/JavaScript 和 SQLite。服务仅监听 `127.0.0.1`，启动后自动打开浏览器；不依赖 Node、CDN、远程字体、遥测或模型。Python 直接调用 Payroll Core 和 Excel Adapter，页面只展示状态和采集人工确认。

当前选择比 FastAPI + React/Vite 更适合 V1：现有资产是 Python，离线运行和可靠审计比前端构建工具更重要。后续可用 PyInstaller 封装本地启动器；macOS 与 Windows 均可用 `python -m payroll_ui`，并分别提供启动脚本。当前是开发版，运行电脑仍需 Python 3.11 和项目依赖。

SQLite 只保存 run、文件路径、SHA-256、大小/修改时间、摘要和人工决定；不复制工作簿或课程明细。每次打开、检查、查看证据和导出都复验文件版本。版本变化将 run 标为 `STALE`，旧决定失效。

V0.1 已实现本机文件选择器；浏览器原生拖放尚未接入，避免为了拖放把真实工作簿复制进应用目录而破坏原文件版本追踪。Core 是唯一的核对判定源；UI 不能通过点击“已处理”自行显示 PASS。
