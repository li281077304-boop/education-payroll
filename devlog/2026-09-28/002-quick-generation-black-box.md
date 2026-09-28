# 2026-09-28｜极速生成工资表黑盒入口

## 产品边界

新增快速入口作为 `SUBMISSION_FIRST_V1` 的 UI / orchestration 模式，不创建第二套工资 engine。快速 Run 仍为正常 `GENERATE` Run，`ui_mode=QUICK` 只控制展示；进入专业模式时原 Run ID、已导入材料和已生成结果保留。

## 实现

- 首页增加主入口“极速生成工资表”和次级“专业核算”。专业模式仍保留既有角色选择与四步流程。
- 快速页仅展示拖入/选择文件、排课/组表识别状态、生成过程、简洁异常或成功结果。
- quick API 创建同一正式 Run；复用 `import_material_file`、现有 parser、人工月 authority、ACTIVE 星级版本、`confirm_af_policy(30, QUICK_GENERATE)`、`check()` 与 `generate_payroll()`。
- 快速材料以 Run 本地 staging 元数据保存，批量识别后先导入排课再导入组表，支持用户以任意顺序上传。排课只有一份；多份组表继续走现有并集/冲突路径。
- 续费、退费、支持部资料识别后引导专业模式；已识别资料可在同一 Run 导入专业流程，未知类型原路径保留并在专业材料页提供原文件导入口。
- 星级有效 ACTIVE 版本缺失或重叠作为管理员配置错误；Core AA/AC/AD/AE/AF 缺项、周期阻塞、资料冲突会阻止快速导出。快速编排不实现工资公式。
- 成功文件通过本地 token 保护的同 Run 下载端点打开/下载。

## 回归验证

- Quick API / UI 新测试共 22 项，覆盖正常生成、仅排课、15/51 输出范围、多组并集与去重、字段冲突、支持部/续费/退费转专业、未分类文件同 Run 保留、星级缺失/重叠、周期越界、AF 默认 30、同 Run 专业接管、下载权限、专业/快速结果一致性和无第二套公式实现。
- 全量 `sh tools/run_tests.sh`：678 passed。
- Python compile、JavaScript syntax、`git diff --check`：PASS。
- 无生产 SQLite 读写，无正式工资助手启动，无 main 合并。
