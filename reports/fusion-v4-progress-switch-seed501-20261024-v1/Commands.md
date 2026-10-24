# Fusion V4 复现与证据命令

工作区：`/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space`；起点 `270e068`。以下均从该根目录执行，使用原 `.venv`。禁止针对本轮既有预留或旧隔离策略补评。

## 实际执行次序

1. 离线测试（79项，合成实例/Mock，无正式train评价）：

```sh
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_fusion_v4 tests.test_fusion_v3 tests.test_fusion_v2 tests.test_U_usage_v2 tests.test_fjsp_usage_v2 tests.test_b1_timeout_boundary -q
```

2. 真实spawn合成生命周期验收（不访问FJSP数据/网络，已有验收不能覆盖）：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v4/run.py accept
```

3. 根据真实测试输出保存 `Offline_tests.json`，然后建立独立协议并只读认证：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v4/run.py prepare
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v4/run.py check
```

`prepare`会复制已冻结H/train资产并绑定源码、基线、旧隔离记录及测试哈希；没有正式求解。

4. 正式本地评价（最多126项、252遍，无API/holdout）：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v4/run.py run
```

该命令串行执行六个策略，每实例首解/复检共享原15秒结果等待。已完成策略不会重评；未知预留、旧Stop或身份变化必须停止。

5. 离线分析与报告（只读取已存评分矩阵，不进行额外求解/H调用）：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v4/run.py report
```

6. 最终交付审计（只读原始证据及CSV，保存Final_audit.json，无新求解）：

```sh
PYTHONPATH=code:. .venv/bin/python -B reports/fusion-v4-progress-switch-seed501-20261024-v1/audit_delivery.py
```

`DECISION_ZH.md`为基于已生成表格撰写的科研决策解读；重建定量报告不会自动改写该解释文本。

## 核查与独立复现实验

本轮默认目录是 `runs/fusion-v4-progress-switch-seed501-20261024-v1`，派生报告在同名 `reports/`；`runs/`受Git忽略，但原始评分矩阵、逐实例状态、进程回执和源码身份在本地保留。报告 `Artifact_index.json`记录全部新原始证据的路径、大小、SHA256；`raw/`另存结果及身份/生命周期JSON。固定基线来源见 `Baseline_sources.json`。

只读认证和重建派生报告可以重复，不会重评。需要另一次独立正式复现时，须获得该新批次评价预算授权，在相同环境/完整历史资产下使用新的直接runs子目录：对prepare/check/run/report一致添加 `--run-dir runs/新目录名`。不能覆盖本轮目录、删除预留或通过新目录绕过旧预算。

旧V1/V2/V3记录和源码均保留；旧H0/H5 Borda结果不追认。源码身份检查在prepare/check、子进程前后及父进程文件边界重复执行。单实例失败的全Fitness始终null。
