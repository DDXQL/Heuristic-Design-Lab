# 复现与恢复

工作区：`FJSP-Heuristic-Research-h-usage-space`，分支`codex/h-usage-space`，起点`df28b3d`。

正式评价前冻结的协议SHA256：

```text
ea3c8f8d8005c5ceff5fc9c9e44b9c1270e7e88b6209b3ec5b47395eccd78e32
```

本轮实际执行的顺序（仓库根目录、Python3.12.10）：

```bash
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_supplemental/run.py accept
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_supplemental/run.py prepare
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_supplemental/run.py run
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_supplemental/run.py report
```

`accept`为合成消息/进程、toy及历史矩阵重放；其中真实无结果Mock等待30秒以检验终止和接收线程解除，未求解任何train实例。初步12项验收后增加了这一真实超时验收，初步收据另存`Offline_acceptance_initial_12tests.json`；正式门禁使用最终13项全通过的`Offline_acceptance.json`及对应源码SHA，随后才prepare。

`prepare`只在唯一新run目录不存在时创建并冻结文件，不重评；`run`是唯一正式评价阶段。禁止删除目录／账本／Stop来重跑；未结算reservation或孤立证据会停止，不能自动恢复消费。全部九项completed后再次`run`只检查并返回，不加载或求解新实例。

完成后可安全重算派生报告：

```bash
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_supplemental/run.py check
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/baseline_supplemental/run.py report
```

这些命令只核对身份／读取已有结果／写当前报告，不发API或执行求解。原始证据位于`runs/baseline-a-supplemental-T30-seed501-20261024-v1/`；报告包含认证结果副本、协议和原始evidence压缩归档。Git忽略的train数据与完整历史runs仍是重新执行评价的前提；从报告CSV无法恢复原始训练实例或完整历史源码闭包。

`NEXT_STATIC_SEARCH_PROTOCOL_ZH.md`仅为下一轮设计，没有在本轮进行候选抽样、离线搜索回放、新求解或LLM演化。

报告生成后的纯离线交付复核及阶段诊断：

```bash
.venv/bin/python -B reports/baseline-a-supplemental-T30-seed501-20261024-v1/verify_delivery.py
.venv/bin/python -B reports/baseline-a-supplemental-T30-seed501-20261024-v1/mechanism_diagnostics.py
```

二者只解析保存的JSON/CSV/归档，不导入排程器或H。前者复核450项原始evidence摘要、协议SHA、9/189/45/945覆盖、指纹及预算；后者生成原失败位置阶段表和189项成员调用次数表。`RESEARCH_FINDINGS_ZH.md`为独立整理的科研解释，重生成自动报告不会改写它。
