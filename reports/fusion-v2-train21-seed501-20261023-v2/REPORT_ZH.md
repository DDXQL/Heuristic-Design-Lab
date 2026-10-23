> 后续完整审计与浮点端点表述修正见 **FINAL_REPORT_ZH.md**；以最终报告为准。

# Tier 2 V2 融合算子可行性实验

固定 H、train21、seed501；三个预先指定成员对，各评价 WEIGHTED_SUM(0.5/0.5)、MAX、MIN。
全部双成员逐列沿用 V1 min–max，常量列归零；精确同分沿用合法动作原枚举首项。
归一化 SUM 与等权加权和只差正常数比例，故不单列。SELECT/单正项加权保持原始 H 分数。

## 完整训练结果

| 策略 | Fitness | 相对 H0 | 相对 H0/H1 等权 |
|---|---:|---:|---:|
| H0_H1_WEIGHTED_SUM | -1.9831442949150015 | 0.12866066571104717 | 0.0 |
| H0_H1_MAX | -2.073695483437209 | 0.0381094771888395 | -0.09055118852220767 |
| H0_H1_MIN | -2.112728513220014 | -0.0009235525939654821 | -0.12958421830501266 |
| H0_H5_WEIGHTED_SUM | 无效 | None | None |
| H0_H5_MAX | 无效 | None | None |
| H0_H5_MIN | 无效 | None | None |
| H5_H9_WEIGHTED_SUM | 无效 | None | None |
| H5_H9_MAX | 无效 | None | None |
| H5_H9_MIN | 无效 | None | None |

## 同成员对算子比较

| 成员对 | 算子相对等权 | ΔFitness | 胜/负/平 | 不同物理排程实例 |
|---|---|---:|---|---:|
| 0/1 | MAX | -0.090551188522 | 3/16/2 | 21 |
| 0/1 | MIN | -0.129584218305 | 1/18/2 | 21 |

## 相同状态动作差异

每个首解状态保存完整物理状态、全部合法动作和两个 H 的原始评分；离线在同一矩阵上计算三种算子的选择。
分别报告三种来源轨迹和去重并集；并集不是均匀随机状态样本。动作差异只表示局部决策差异，不表示续排收益。

| 成员对 | 去重状态数 | MAX≠WS | MIN≠WS | MAX≠MIN |
|---|---:|---:|---:|---:|
| 0/1 | 11346 | 8992 | 7727 | 10624 |
| 0/5 | 9571 | 6295 | 4009 | 7483 |
| 5/9 | 9328 | 5548 | 3399 | 6763 |

## 行为、成本和证据边界

完整 train21 物理排程行为组：3；分组见 Summary.json，逐实例相同数见 Physical_schedule_pairs.csv。
正式预留 189 项；实际首解 189 遍，复检 189 遍。
主评价 wall time 451.698 秒；成功实例 CPU 354.342 秒。
两遍 H 调用 46424688；API=0，新增诊断求解=0，诊断额外 H 调用=0。
首解包含状态/评分记录开销，复检不记录；跨策略耗时仅为串行本机描述性比较。异常和进程终态见 raw/。
MAX 取两列归一化评分的最大值，往往产生更多顶端同分；结果会依赖被冻结的精确同分规则。
数学上 MAX 的最终动作必为某个成员的首选动作，故可由某个单成员端点实现；不同于等权不等于超出所有加权和的动作能力。
MIN 可选择折衷动作；本报告未仅凭不同于等权就声称超出全部连续权重空间。
训练集已用于研究开发，本轮不作确认性显著性或独立泛化结论；没有读取 validation11/test28。
本轮固定策略均为人工构造，不是 LLM 发现；接口支持可信 U 按状态切换算子/成员/权重，但未扩展模型 AST 或进行演化。

## 复现

```bash
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py prepare --run-dir runs/新的独立目录
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py check --run-dir runs/新的独立目录
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py run --run-dir runs/新的独立目录
PYTHONPATH=code:. .venv/bin/python -B experiments/tier2/fusion_v2/run.py report --run-dir runs/新的独立目录
```

prepare 固定协议；run 不重复已完成或未知中断的预留任务。所有原始评分矩阵位于 Artifact_index.json 指向的独立 runs 目录。
