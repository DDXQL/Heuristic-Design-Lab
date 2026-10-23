# 本轮实际运行与复现命令

在多策略工作区根目录执行：

```bash
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_fusion_v2 tests.test_U_usage_v2 tests.test_fjsp_usage_v2 tests.test_b1_timeout_boundary -q
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py prepare --run-dir runs/fusion-v2-train21-seed501-20261023-v2
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py check --run-dir runs/fusion-v2-train21-seed501-20261023-v2
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py run --run-dir runs/fusion-v2-train21-seed501-20261023-v2
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py report --run-dir runs/fusion-v2-train21-seed501-20261023-v2
```

重新实验必须换新目录；prepare 不覆盖已存在目录，run 不重评已完成/未知中断的预留任务。

旧 `...-v1` 是第一次启动前的保护配置停止，checkpoint 无任何策略预留，零正式求解。
原因是父进程只放行训练副本，而冻结检查需要读取原 train21 的精确相同文件进行哈希核对。
修正仅允许原 train21 和副本两处精确路径；保留旧目录和停止证据，以新协议目录 ...-v2 执行。
未放行 validation11/test28，未修改任何 B1/B2/Recovery-B 资产。

原始全动作矩阵保留在独立 runs 的 evidence 中，逐文件 SHA256 见 Artifact_index.json。
报告 raw 中保留原始完整/无效结果、身份和进程终态回执；Common_state_actions.csv.gz 是逐状态派生决策表。

最终189行表、异常审计和浮点解释修正：

```bash
PYTHONPATH=code:. .venv/bin/python -B reports/fusion-v2-train21-seed501-20261023-v2/finalize_report.py
```
