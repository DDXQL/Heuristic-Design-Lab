# Tier1 FJSP 单一通用构造式优先级规则实验

日期：2026-09-20。计划和预注册口径见 [fjsp_tier1_single_rule_plan.md](fjsp_tier1_single_rule_plan.md)。本实验使用原有 `priority()` 接口、实例加载器、append-only 固定调度器、合法性检查以及21/11/28拆分，没有修改 `code/llm4ad/method/eoh/` 或 EoH-S 核心，也没有引入局部搜索算子。

## 1. 实现边界与冻结配置

现有 EoH 在 Evaluation 返回逐实例向量时，用 `np.mean(score)` 作为单规则 fitness，并保留完整 `score_list`。因此直接复用 `FJSPSetEvaluation`：每个候选固定得到21维训练向量，fitness 是其算术平均值。

新增入口：

- `examples/training/fjsp_set/prepare_single_rule.py`：冻结协议、预算和源码哈希；
- `examples/training/fjsp_set/run_eoh_single.py`：运行 EoH、保存全部样本和最终 population；
- `examples/training/fjsp_set/evaluate_single_rule.py`：只用 validation 选择最终规则并完成 train/validation 对比。

正式配置为 [single_rule_config.json](../examples/training/fjsp_set/single_rule_config.json)，SHA-256：

```text
2ab917b041f848f5517746e3415cffaa0bf43ccec4c6b2eb782546c24186d48b
```

2026-09-20 稳定性检查时已从实际文件重新计算该值，并确认它是正确的 64 位十六进制 SHA-256；此前对话中出现的拼接值不是配置文件哈希，也未写入本实验记录。

配置固定 `deepseek-flash`、训练21实例、验证11实例，并明确排除28个 test 实例。最终候选池仅为 EoH final population；选择指标为11个 validation normalized score 的算术平均，平分取较小 population index。

## 2. 小预算预检

首次 `smoke01` 完成了6个候选评价，但审计代码把 `samples_best.json` 重复计入历史样本，产生“实际6、日志7”的计数错误。该目录保留；候选评价与 EoH 无异常。随后只修正任务入口的文件过滤，保留 v1 配置副本并冻结上述 v2 配置。

`smoke02` 参数为 seed `2026092001`、6 samples、5 generations、population 2。结果：

- 6/6候选有效，全部返回长度21的有限向量；
- 每个标量 fitness 与21维向量均值完全一致；
- final population 2个程序，导出后重放训练向量完全一致；
- validation 选择、基线对比和分组汇总均成功；
- test 未评价。

预检产物在 `logs/fjsp_tier1_single_rule/smoke02/`。

## 3. 正式运行

命令不含 API 密钥：

```bash
source config.local.sh
PYTHONPATH=code .venv/bin/python -u \
  examples/training/fjsp_set/run_eoh_single.py \
  --stage formal --run-dir logs/fjsp_tier1_single_rule/formal01

PYTHONPATH=code .venv/bin/python \
  examples/training/fjsp_set/evaluate_single_rule.py \
  --run-dir logs/fjsp_tier1_single_rule/formal01
```

正式参数：seed `2026092002`、40 samples、10 max generations、population 5、单 sampler/evaluator、单候选批次 timeout 180秒。API 没有可确认的服务端 seed，因此 seed 只固定宿主 Python/NumPy 随机过程。

运行结果：

- 40/40 个已评价候选有效，无效率 **0%**；
- final generation 9，final population 5；
- LLM生成和训练评价用时 **144.20秒**；
- 最终5个成员的训练均分为 `[-2.009009, -2.018588, -2.022189, -2.030723, -2.034199]`；
- validation 按预注册规则选择 population index 0，对应原始 sample 20；
- 选中源码 SHA-256 为 `0991e17f833e7ab773b0ff13ea2396a0cb3ccb9d94715984fb1ef421ea89496a`。

最终规则为 [selected_rule.py](../logs/fjsp_tier1_single_rule/formal01/selected_rule.py)。它主要结合 remaining-work density、processing-time reciprocal、ready-time reciprocal 和 earliest-finish penalty，仍使用原七特征接口。

## 4. 总体对比

分数为 `-makespan/lower_bound`，越大越好。胜/平/负均以最终 EoH 规则为参照。

### Train（21个实例）

| 方法 | 平均分 | EoH 对其胜/平/负 | EoH 平均 score 差 | EoH 平均 makespan 相对改善 |
| --- | ---: | ---: | ---: | ---: |
| 最终 EoH | **-2.009009** | — | — | — |
| EFT | -2.017346 | 10/4/7 | +0.008337 | -0.09% |
| SPT | -3.283870 | 21/0/0 | +1.274860 | +34.53% |
| MWKR | -18.638845 | 21/0/0 | +16.629836 | +86.95% |
| EoH-S `heuristic_0` | -2.084727 | 13/6/2 | +0.075718 | +3.08% |

normalized score 均值略高于 EFT，但逐实例平均 makespan 相对改善为 `-0.09%`；这是因为两个聚合方式的实例归一化权重不同，应同时报告。

### Validation（11个实例，用于选择）

| 方法 | 平均分 | EoH 对其胜/平/负 | EoH 平均 score 差 | EoH 平均 makespan 相对改善 |
| --- | ---: | ---: | ---: | ---: |
| 最终 EoH | **-2.194223** | — | — | — |
| EFT | -2.226551 | 8/0/3 | +0.032328 | +1.31% |
| SPT | -3.776172 | 11/0/0 | +1.581949 | +40.88% |
| MWKR | -22.354950 | 11/0/0 | +20.160727 | +88.59% |
| EoH-S `heuristic_0` | -2.282339 | 8/3/0 | +0.088116 | +4.35% |

validation 被用于从 final population 选择规则，因此这张表是选择阶段结果，不是独立泛化检验。

## 5. 固定规模层表现

### Train

| 规模 | n | EoH | EFT | SPT | MWKR | EoH-S h0 | vs EFT 胜/平/负 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100x20 | 1 | -1.377709 | -1.356037 | -3.250774 | -17.783282 | -1.764706 | 0/0/1 |
| 100x40 | 1 | -2.736842 | -2.802632 | -4.815789 | -33.151316 | -2.848684 | 1/0/0 |
| 100x60 | 1 | -4.141414 | -4.181818 | -7.050505 | -51.878788 | -4.303030 | 1/0/0 |
| 10x20 | 4 | -1.440686 | -1.393242 | -2.079830 | -8.430069 | -1.413004 | 0/1/3 |
| 10x40 | 2 | -1.259135 | -1.304006 | -1.527404 | -7.144071 | -1.259135 | 1/1/0 |
| 10x60 | 2 | -1.404412 | -1.426471 | -1.742647 | -7.522059 | -1.404412 | 1/1/0 |
| 20x40 | 2 | -1.744198 | -1.757531 | -2.385185 | -12.835802 | -1.783704 | 1/1/0 |
| 20x60 | 2 | -1.771720 | -1.684030 | -2.438987 | -14.575162 | -1.785418 | 0/0/2 |
| 50x20 | 2 | -1.642530 | -1.639253 | -3.917454 | -16.931631 | -1.820351 | 1/0/1 |
| 50x40 | 2 | -3.129287 | -3.206460 | -5.536797 | -32.947636 | -3.271229 | 2/0/0 |
| 50x60 | 2 | -3.133964 | -3.207658 | -5.213964 | -35.484685 | -3.281171 | 2/0/0 |

### Validation

| 规模 | n | EoH | EFT | SPT | MWKR | EoH-S h0 | vs EFT 胜/平/负 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 100x20 | 1 | -1.388199 | -1.375776 | -3.040373 | -18.040373 | -1.773292 | 0/0/1 |
| 100x40 | 1 | -2.797386 | -2.790850 | -4.875817 | -34.477124 | -2.830065 | 0/0/1 |
| 100x60 | 1 | -4.320000 | -4.350000 | -7.250000 | -53.170000 | -4.420000 | 1/0/0 |
| 10x20 | 1 | -1.521127 | -1.408451 | -2.352113 | -8.211268 | -1.521127 | 0/0/1 |
| 10x40 | 1 | -1.420290 | -1.492754 | -2.202899 | -8.405797 | -1.492754 | 1/0/0 |
| 10x60 | 1 | -1.367647 | -1.411765 | -1.897059 | -9.911765 | -1.367647 | 1/0/0 |
| 20x40 | 1 | -1.712329 | -1.808219 | -3.191781 | -13.698630 | -1.712329 | 1/0/0 |
| 20x60 | 1 | -1.851351 | -1.932432 | -2.743243 | -14.864865 | -1.945946 | 1/0/0 |
| 50x20 | 1 | -1.588957 | -1.595092 | -3.128834 | -17.478528 | -1.742331 | 1/0/0 |
| 50x40 | 1 | -3.142857 | -3.168831 | -5.961039 | -35.896104 | -3.181818 | 1/0/0 |
| 50x60 | 1 | -3.026316 | -3.157895 | -4.894737 | -31.750000 | -3.118421 | 1/0/0 |

## 6. 最差规模组

- 按最终规则绝对平均 normalized score，train 和 validation 最差均为 `100x60`：分别 `-4.141414` 和 `-4.320000`。这部分也受当前简单 lower bound 在不同规模上的松紧影响。
- 按相对 EFT 的平均 score gap，train 最差为 `20x60`，差 `-0.087689`，0/0/2；validation 最差为 `10x20`，差 `-0.112676`，0/0/1。
- validation 每个精确规模层只有一个实例，规模层差异只能描述，不能作稳定推断。

## 7. 运行时间与产物

最终规则单次完整调度评价时间：train `0.917秒`，validation `0.653秒`。对应 EFT 为 `0.726秒` 和 `0.525秒`；EoH-S `heuristic_0` 为 `2.266秒` 和 `1.758秒`。这些是单次本机顺序运行的描述值。

- [全部40个生成程序及逐实例训练分数](../logs/fjsp_tier1_single_rule/formal01/samples/samples_1~200.json)
- [final population manifest](../logs/fjsp_tier1_single_rule/formal01/final_population/manifest.json)
- [最终规则](../logs/fjsp_tier1_single_rule/formal01/selected_rule.py)
- [validation 选择记录](../logs/fjsp_tier1_single_rule/formal01/selection.json)
- [逐实例、胜平负及全部分组结果](../logs/fjsp_tier1_single_rule/formal01/evaluation_result.json)
- [生成统计](../logs/fjsp_tier1_single_rule/formal01/generation_result.json)
- [运行配置](../logs/fjsp_tier1_single_rule/formal01/run_config.json)
- [一致性审计](../logs/fjsp_tier1_single_rule/formal01/post_run_audit.json)
- [EoH profiler 日志](../logs/fjsp_tier1_single_rule/formal01/run_log.txt)

本轮结果说明单规则 EoH 在开发数据上优于现有 EoH-S `heuristic_0`，并在 train/validation 的平均 normalized score 上略优于 EFT。由于 validation 已用于选择，且已打开过的 test split 本轮完全排除，这些结果还不能作为独立测试或跨数据族泛化证据。
