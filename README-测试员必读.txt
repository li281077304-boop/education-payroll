Education Payroll V1 RC1（Windows x64）

当前 RC1 已在 Windows 11 x64 验证，Windows 10 尚未实机验证。

1. 将整个压缩包解压到一个可写目录。
2. 双击“Education Payroll\Education Payroll.exe”。程序会启动本机服务并打开浏览器。
3. 点击“新建工资核算”，选择月份，再按页面提示导入排课表和工资表。
4. 点击“开始核对”，在“待处理问题”中打开问题并查看证据。
5. 需要人工处理的问题，请填写处理人和理由后保存，再点击“重新核对全部材料”。

演示数据在 demo 文件夹，仅用于脱敏验收。可先用它完成：导入 → 建 Run → 核对 → 查看证据 → 保存人工决定 → rerun。

数据只在本机读取，原 Excel 不会被写回。核算记录、SQLite 和日志保存在：
%LOCALAPPDATA%\EducationPayroll\

反馈 Bug 时请提供：Windows 版本、操作步骤、页面提示、是否能用 demo 重现，以及程序目录下的报错信息。请勿发送真实工资、教师或学生数据。
