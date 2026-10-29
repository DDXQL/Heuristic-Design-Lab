# R1下一步：两条兼容基线

入口：`experiments/common/run_r1_baselines.py`。顶部为实际输入、参考run、固定策略、种子、T30、总时窗和API关闭参数。参考已完成common运行的协议，校验相同H文件/训练清单SHA、21份输入顺序和SHA、相同未取整LB。未知字段和API开关直接拒绝。

用户在项目根目录执行：

```sh
.venv/bin/python -u -B experiments/common/run_r1_baselines.py
```

自动生成并永久保存独立准备配置，调用原experiment_ops.prepare→experiment_ops_run.start（前台、allow_api=False）→原summary写结果。每次新建`runs/b1-v6-r1-legacy-train21-时间戳-随机后缀/`，不恢复或覆盖旧运行。日志在新运行terminal.log，结果在results/，打印全部路径；已完成的12条common候选不重评。

两个固定策略：旧入口恒选H0；旧入口H0/H1各动作评分列独立min-max后0.5/0.5等权。后者为外部MIX参照，不冒充common纯路由。总计42条程序—实例主评价、最多84遍首解/复检、生成/API请求与费用0。每实例完整两遍与结果接收T30，worker最终正常退出另2秒；12小时为旧控制器总时窗，不是预计耗时。

该外部兼容评价器保留原候选串行执行，不新增并发机制；这与此前common候选CPU2不同，时间只如实登记，不直接把两批墙钟差当新版状态开销。R3/B1正式搜索继续API2/评价2，未退回串行。EoH冻结单规则仍待单独接入统一认证，本脚本未包含它，不能据此宣布R1整体完成。

通过标准：phase=completed，certified_strategies=2，failed_or_uncommitted_tasks=0，API_attempts=0，first_starts=42、recheck_starts=42。任何失败保留，不以成功前缀替代完整Fitness；异常不清锁、不重试。

完成后用户返回打印的运行目录及最后摘要。助手只读比较旧H0与新恒选H0的逐实例物理排程/Cmax/LB/Fitness，并将静态等权与两条预登记路由配对比较，保留全部退化、持平和失败记录。

本轮实际检查仅在禁止网络、prepare、solver start的情况下执行check-only，计划2策略/42主评价/最多84遍/API0；3项非法模式/参数拒绝检查通过。证据为legacy-check.log。本轮未启动正式求解，也未重跑工程验收。新文件不修改原冻结执行源码。
