# 论文实验图表

集群进度取自 2026-11-25 的最近回执。实线轨迹来自候选记录，进度条来自独立的状态快照。

[整套图 PDF](paper-figures.pdf) · [绘图源码](../../tools/paper_figures.py) · [输入文件与 SHA-256](source-manifest.json) · [科研汇报](../RESEARCH_PROGRESS.md)

实验以 U 为研究主体。EoH 提供直接演化求解规则的对照，Ross-style 提供同状态和规则库下的传统路由对照，Best Fixed H 检验按状态切换规则的收益。

在 TSP 上，三种方法使用相同的训练外实例，并以统一设置的 LKH 求解结果作为评价参考。所有 J 均为相对参照成本的平均差距，越小越好。

## TSP

| 图 | 读图要点 | 数据与统计口径 |
| --- | --- | --- |
| 01 · [tsp-01-holdout-quality.pdf](tsp-01-holdout-quality.pdf) · [PNG](tsp-01-holdout-quality.png) | U 的训练外平均 J 为 12.14%，接近 Ross-style 的 12.04%。EoH 的均值最低，为 10.76%。 | [逐种子数据](tsp-seed-quality-cost.csv)和[方法汇总](tsp-method-summary.csv)。每种方法三个独立搜索，误差棒为均值 ± 样本标准差。 |
| 02 · [tsp-02-train-vs-holdout.pdf](tsp-02-train-vs-holdout.pdf) · [PNG](tsp-02-train-vs-holdout.png) | 每点是一个冻结冠军，横轴为训练 J，纵轴为训练外 J。虚线表示两项 J 相等。九个冠军的训练外 J 均高于训练 J，U、EoH、Ross-style 平均分别高 2.55、1.86、2.55 个百分点。 | [逐种子数据](tsp-seed-quality-cost.csv)，训练与外评成对显示，坐标等尺度。 |
| 03 · U · [tsp-03-convergence-u.pdf](tsp-03-convergence-u.pdf) · [PNG](tsp-03-convergence-u.png)<br>EoH · [tsp-03-convergence-eoh.pdf](tsp-03-convergence-eoh.pdf) · [PNG](tsp-03-convergence-eoh.png)<br>Ross-style · [tsp-03-convergence-ross.pdf](tsp-03-convergence-ross.pdf) · [PNG](tsp-03-convergence-ross.png) | U、EoH 和 Ross-style 的九条阶梯曲线及各自的三种子均值均已核实。细线为各次搜索截至当步的最佳训练 J，粗线为三种子均值。 | [有序候选数据](training-curves.csv)。U 和 EoH 统计模型成功返回的演化候选。Ross-style 统计搜索考察的候选，含初始化。 |
| 04 · [tsp-04-instance-pairs.pdf](tsp-04-instance-pairs.pdf) · [PNG](tsp-04-instance-pairs.png) | U 在 22/60 例优于 EoH，在 26/60 例优于 Ross-style。平均差分别为 +1.38%、+0.10%，负值对 U 有利。 | [60 例配对表](tsp-instance-pairs.csv)与[原始 540 条方法×种子×实例记录](tsp-instance-seed-raw.csv)。先在同一实例内平均三个种子，每例只作一个差值，按 LKH 路长排序。 |
| 05 · [tsp-05-seed-variation.pdf](tsp-05-seed-variation.pdf) · [PNG](tsp-05-seed-variation.png) | 同一种子内的空心点、实心点分别表示训练、外评。U 的 501 种子在三个 U 冠军中训练 J 最高，外评 J 最低。 | [逐种子数据](tsp-seed-quality-cost.csv)，展示九个冠军的两次测量。 |
| 06 · [tsp-06-quality-cost.pdf](tsp-06-quality-cost.pdf) · [PNG](tsp-06-quality-cost.png) | U 的训练求解启动数少于 EoH。外评求解进程 CPU 时间平均为 U 6.32 秒、EoH 3.93 秒。 | [计时与成本](tsp-seed-quality-cost.csv)。训练统计实际启动的实例求解，含复核和启动后失败。外评均基于同一台 Mac 的双遍复核，横轴为逐例求解进程 CPU 秒之和。 |

实际训练求解启动数范围和外评 CPU 秒均值如下。训练求解数包含初始化，不含共享 H 生成、模型推理和排队。训练 CPU 只在有回执的方法中保留。

| 方法 | 每种子训练求解启动数范围 | 平均外评求解进程 CPU 秒 |
| --- | ---: | ---: |
| U | 21,841–26,043 | 6.320 |
| EoH | 39,760–40,040 | 3.930 |
| Ross-style | 36,080–40,440 | 5.487 |

各方法使用的训练计算预算不可由候选数换算。已知 token 为记录小计，未返回用量的请求单列。正式外评所有 60 个实例都是 50 城市、均匀分布，现有数据不支持按城市规模或分布分组。

图 03 中，第 500 个成功返回候选时，U 的平均最佳训练 J 为 9.74%，EoH 为 9.89%。到第 1000 个时，两者分别为 9.58% 和 8.90%。该横轴衡量候选进度，计算开销另见图 06。

## FJSP

- **训练进度**　[fjsp-01-training-progress.pdf](fjsp-01-training-progress.pdf) · [PNG](fjsp-01-training-progress.png)。以最新回执为准，进度条按各自预算展示，只用于说明完成程度。数据见[训练进度快照](training-progress.csv)。
- **训练轨迹**　[fjsp-03-convergence.pdf](fjsp-03-convergence.pdf) · [PNG](fjsp-03-convergence.png)。Ross-style 501 的横轴为累计考察候选数，历史 U 501 的横轴为演化尝试数。经核对实例和下界，Ross-style 面板可画同一训练集的 Best Fixed H 水平线（J = 1.111805）。正式外评待补。数据见[有序候选数据](training-curves.csv)及[固定 H 逐例记录](../fjsp-execution-20261112/fixed-H-reuse-v3/fixed-H-train21-J.csv)。

## OBP

- **训练进度**　[obp-01-training-progress.pdf](obp-01-training-progress.pdf) · [PNG](obp-01-training-progress.png)。数据见[训练进度快照](training-progress.csv)。中途成绩不参与正式外评排序。

## 轨迹覆盖与缺项

- **TSP**　当前 R15 成功返回序列已读到 EoH 501、EoH 502、EoH 503、U 501、U 502、U 503。
- **FJSP**　当前 R15 成功返回序列已读到 无。
- **OBP**　当前 R15 成功返回序列已读到 无。
- TSP U/EoH 各三个种子的逐步训练记录均已取回，与冻结冠军训练 J 核对一致。
- FJSP 和 OBP 的逐步训练记录覆盖以表中列出的种子为准。FJSP 历史 U 501 的曲线单列。
- 缺少各方法逐候选累计 CPU 或统一计时回执，暂不提供按训练计算成本对齐的收敛图。OBP 固定 H 需要可核验的逐例成本与同一参照。FJSP、OBP 正式外评数据到齐后再生成同集比较。
- 阶梯线仅保持已知的截至当步最优值。均值使用三个种子都有观测的步数。各曲线的结束位置由实际记录决定。

## D06 · 评价参考如何产生

D06 是项目中给 TSP 固定参考值生成方案的编号。LKH 是启发式求解器。返回的闭合路线是可行解，给出数学最优路线长度的上界，未提供最优性证明。

- **版本与调用**　绑定的二进制为 LKH 3.0.13。实际编译输入为项目留档的第三方候选源码，官方源码逐字节等价未核实。每个实例启动一个进程，最多 10 轮内部搜索（`RUNS=10`），每轮最多 1000 次试探（`MAX_TRIALS=1000`），单轮搜索内部按 10 秒 CPU 计时检查（`TIME_LIMIT=10`）。参考生成种子为 `SEED=1`。外层对每个实例进程另有 120 秒 CPU 硬上限和 150 秒墙钟上限。
- **路线长度**　用单位方形上的原始浮点欧氏距离构造矩阵，乘以 1,000,000 后按 `floor(x + 0.5)` 转为 LKH 的显式整数矩阵。取得闭合路线后，用原始浮点欧氏距离重算含返程的长度，作为该实例的评价分母。
- **训练与留出分别生成**　核对了训练 20 例与留出 60 例的参考文件。二进制、参数和距离协议一致，实例内容与执行回执不同。留出集回执确认 60 个 LKH 进程全部结束。
- **原始证据**　[冻结规格](../../experiments/triad/lkh.pending.json) · [参数写入与外层执行](../../experiments/triad/assets.py) · [原操作规约](../../docs/统一实验包操作指南.md)。正式训练和外评参考文件及执行回执见[输入清单](source-manifest.json)。

## 复绘

在仓库根目录使用装有 [`requirements-closeout.txt`](../../requirements-closeout.txt) 的 Python。默认读归档的 TSP 历史，输出中文 340 DPI PNG 和矢量 PDF。

```bash
python3 -B tools/paper_figures.py
```

英文标签用 `python3 -B tools/paper_figures.py --lang en --output reports/paper-figures-en`。Matplotlib 找不到中文字体时可用 `--font /path/to/CJK.ttf`。`--prototype-root` 和 `--outbox` 可指定已有输入目录的位置。

TSP U/EoH 的六份原始历史保存在[归档 CSV](inputs/tsp-training-history-20261125.csv.gz)。需要重取时，脚本使用平时的 SSH 登录方式，只读取已经核验的六个归档断点。

```bash
python3 -B tools/pull_tsp_history.py
python3 -B tools/paper_figures.py --history "$HOME/Developer/transfer-outbox/tsp-training-history-20261125.csv"
```

其他已部署训练记录可通过通用只读入口取得。

```bash
ssh hdl-cluster \
  '"$HOME/hdl-envs/portable-v2/bin/python" -I -B - "$HOME/hdl-deploy"' \
  < tools/figure_training_history.py > "$HOME/Downloads/hdl-training-history.csv" && \
python3 -B tools/paper_figures.py --history "$HOME/Downloads/hdl-training-history.csv"
```

后续先刷新[实验状态矩阵](../EXPERIMENT_STATUS.md)，再运行同一绘图命令。正式外评图纳入预先指定的同一留出集与参照上的三种子核验结果。验证集结果不会当成正式测试。
