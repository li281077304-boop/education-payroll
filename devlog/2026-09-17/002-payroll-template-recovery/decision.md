# Decision

1. 模板回归根因是新 Run 未继承历史 Run 的已持久化 `template_path`，不是 SQLite 丢数据。
2. 资料包扫描仍是有效来源；历史 Run 的真实模板绑定也是可信 durable authority。
3. 自动恢复只接受存在且可识别的真实工资模板；无模板时继续 fail-closed。
4. 模板恢复不会把星级、AF、续费、退费等其它业务阻塞伪造成完成。
