# 本轮实际命令与安全停止复现

工作区：FJSP-Heuristic-Research-h-usage-space，分支codex/h-usage-space。

```bash
PYTHONPATH=code:. .venv/bin/python -B tools/fusion_v3_diagnose.py
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_fusion_v3 tests.test_fusion_v2 tests.test_U_usage_v2 tests.test_fjsp_usage_v2 tests.test_b1_timeout_boundary -q
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py prepare --run-dir runs/fusion-v3-borda-train21-seed501-20261024-v1
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py check --run-dir runs/fusion-v3-borda-train21-seed501-20261024-v1
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v3/run.py run --run-dir runs/fusion-v3-borda-train21-seed501-20261024-v1
```

诊断目录已存在时不会覆盖。64项验收通过；正式run在第二策略的unexpected_worker_exit门禁处停止。
本批不得再次run以补评、不得删除Stop.json/修改checkpoint，也不得以新目录重置本批额度。
check仍是只读身份检查；它通过不等于允许恢复。保留第二策略reserved及停止原因；第三策略未启动。

正常report入口要求所有策略终结为completed，本批不满足该前提，因此使用只读停止交付工具：

```bash
PYTHONPATH=code:. .venv/bin/python -B reports/fusion-v3-borda-train21-seed501-20261024-v1/deliver_stopped.py
```

该脚本不解析FJSP实例、不调用H、不求解、不联网；它只认可已有完整门禁通过的result.json，
把第二策略raw_result.json隔离，把第三策略记为未启动，保存全部63行含null的正式结果。
Final_audit.json绑定协议SHA256及此分析脚本SHA256。旧V1/V2和新运行协议/源码/账本都不修改。

原始矩阵保留在本机runs/fusion-v3-borda-train21-seed501-20261024-v1/evidence；Artifact_index.json提供哈希。
raw/保存前后源码身份、进程终态、分类、正式或隔离原始结果；diagnosis/保存V2全状态派生数据与固定样本证书。

若未来需要修正收集器退出留证，应建立明确新工程协议、Mock和已消耗预算审查；本报告不授权续跑。
