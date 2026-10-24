# Baseline-A 实际命令与复现

根目录：`/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space`；基于eace08f。使用本地原`.venv`，本轮不连接LLM、账户服务或其他收费接口。

## 已执行流程

离线验收（90项；合成求解及已有矩阵/缓存只读复核，无新增正式train求解）：

```sh
PYTHONPATH=code:. .venv/bin/python -B -m unittest tests.test_baseline_a tests.test_fusion_v4 tests.test_fusion_v3 tests.test_fusion_v2 tests.test_U_usage_v2 tests.test_fjsp_usage_v2 tests.test_b1_timeout_boundary -q
```

只读审计并写入新报告目录，然后根据真实测试输出保存Offline_tests.json（命令、数量、结果及测试源码SHA）：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_a/run.py audit
```

建立独立协议，复制train/H及已认证缓存，冻结55策略、扣除14缓存后的861/1722预算、源码身份及保护清单；没有正式求解：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_a/run.py prepare
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_a/run.py check
```

正式本地评价，仅执行预定41对；首解/复检各一次，共享每实例15秒等待；无重试或延期：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_a/run.py run
```

离线分析，保留全部1155行（包括null失败），计算Oracle，无新增求解、H调用或API：

```sh
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_a/run.py report
PYTHONPATH=code:. .venv/bin/python -B reports/tier2-baseline-a-train21-seed501-20261024-v1/audit_delivery.py
```

## 恢复与长期复用

默认独立目录：`runs/tier2-baseline-a-train21-seed501-20261024-v1`。14项缓存来自原始封存10H和4对等权结果；Cache_audit.json逐项列明来源选择路径、哈希、源码口径及证据等级。不能把旧没有保存的PID终态凭空补成现代认证。

run只跳过已完成且结果哈希、预算及身份都匹配的记录，包括已认证无效策略。未知reserved、孤立证据、Stop或身份变化必须停止；不删除锁、预留或Stop绕过门禁。已完成本批不应再次启动求解。

check可只读复核；report可以重建定量派生表。新结果及原始逐实例/进程记录在runs，Git忽略该运行目录；报告另保存全部55项认证结果、来源表、关键进程证据及原始路径/SHA，便于长期读取而不重算。

未来研究可直接引用本轮同身份完整有效策略的逐实例结果及来源哈希；需要变更H、数据、执行语义或未知缓存时应建立新协议。额外独立复现需另获评价预算授权，且prepare/check/run/report必须使用同一个全新直接runs子目录（`--run-dir runs/新目录名`）。不能用新目录重置已消耗预算。

`DECISION_ZH.md`为最终数据驱动解读；定量表、Oracle、源清单和审计可由上述离线命令复建。

## 不依赖旧runs的结果复用

整个报告文件夹可作为只读基线数据集复用。Dataset_manifest.json绑定全部55项结果、H资产和科学协议；load_dataset.py只依赖Python标准库，不调用排程器、模型或网络，也不需要旧runs目录：

```sh
.venv/bin/python -B reports/tier2-baseline-a-train21-seed501-20261024-v1/load_dataset.py
```

Python调用`load(报告目录)`返回全部55项（无效项Fitness保留None），`load(报告目录, valid_only=True)`只返回完整有效项。证据等级仍应连同manifest及报告一起读取；加载历史数据不构成新的进程终态认证。复用已存数据与重新执行正式求解是两项不同操作。
