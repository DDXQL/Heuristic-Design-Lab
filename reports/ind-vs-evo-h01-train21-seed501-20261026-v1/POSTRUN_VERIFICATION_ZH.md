# 收尾、恢复与离线复核

本目录以 `FINAL_REPORT_ZH.md` 为最终入口；`REPORT_ZH.md` 是自动汇总，`partial_109/` 保留最初109槽位快照。原始科学协议、首个6小时截止及其109槽位终态没有覆盖。独立续跑授权最多2小时，只追加原计划剩余槽位；恢复探测沿用该截止，不重新抽样。最终113/120，117次API尝试，余7个未启动。

连续6次503后，依用户“再重试／自行解决”要求，先只读核查余额与模型列表，再在下一个原定槽位按2次上限尝试，仍均为503。账户原始点余额为正；未发现可认证为余额耗尽的证据，也没有确定可修复的本地配置错误。具体上游故障未知。没有换模型、充值、重新生成失败候选或启动未授权诊断求解。已认证保护锁与两个Stop均保留，不能直接删除后重跑。

14项离线 unittest 在收尾复跑全部通过（11项主流程、3项续跑）；不调用API或正式求解。尝试用pytest运行时环境缺少该包，随后使用测试原生的unittest入口，通过；未安装新依赖。原始协议及109／112任务前缀、115次请求前缀和续跑源码绑定复核通过。

正式执行源码冻结后没有修改。原自动归档尝试发生文件系统超时；仅停止过离线报告进程，没有终止正式评价。未认证的不完整压缩包留在本机，**不纳入本地提交**。独立离线汇总工具读取既有记录，新的主证据压缩包经过逐项SHA回读和输入未改变检查。仅不打包重复的单实例行副本，完整result/raw_result仍含原始行；本机副本保留。`Raw_primary_manifest.json`列明取舍及所有来源。

环境缺少matplotlib，曲线以`Search_curves.csv`完整交付；没有将未生成的图形列为已完成。`Final_verification.json`的passed仅认证现有记录与流程重放，不表示120槽位或3次完整重复完成。原始P0两端点物理指纹证据缺口、历史B2执行包装差异和未核实费用均保留。

以下命令仅离线复核／报告，不生成、不求解。须在本工作区根目录运行：

```sh
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_ind_evo_h01 tests.test_ind_evo_h01_continue -q
PYTHONPATH=code:. .venv/bin/python -B -m tools.ind_evo_h01_report_core
PYTHONPATH=code:. .venv/bin/python -B -m tools.ind_evo_h01_verify
PYTHONPATH=code:. .venv/bin/python -B -m tools.ind_evo_h01_finish
PYTHONPATH=code:. .venv/bin/python -B -m tools.ind_evo_h01_pack
```

后续须待原模型接口恢复、确认剩余有效时间授权，并通过保留的Stop及身份保护程序恢复；不直接运行原run或重新prepare。已失败槽位仍占预算。没有推送远端，没有修改A4、CROSS反馈实验或其他工作区。
