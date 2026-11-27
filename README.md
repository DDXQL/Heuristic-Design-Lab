# Heuristic Design Lab

1. [科研实验进展汇报](reports/RESEARCH_PROGRESS.md) · [论文实验图表](reports/paper-figures/README.md)　正式结果、演化轨迹、逐例差异和计算开销。
2. [实验状态矩阵](reports/EXPERIMENT_STATUS.md)　逐种子训练、冠军、外评、作业和最后核实时间。
3. [工程详细记录](PROJECT_MAP.md)　源码、原始结果、历史版本和复现入口。
4. [研究人员指南](DECISIONS.md) 与 [开始新实验](docs/实验导航.md)　查阅冻结协议，选择方法和配置。

```text
JSON 或终端菜单 → tools/experiment.py → 每个种子一个 Slurm 作业
                                        ├─ 同批 API 并发与节奏
                                        └─ 训练冠军 → 冻结 → 训练外评价 → 汇总
```

| 问题 | 常用配置与缺项 |
| --- | --- |
| [TSP](docs/实验导航.md#tsp) | U、EoH、Ross-style、Best Fixed H。训练用 train20 与 D06。正式外评用 confirm60 的独立 D06 参照。 |
| [FJSP](docs/实验导航.md#fjsp) | U、EoH、Ross-style、Best Fixed H。训练用 train21 与 LB_v5。 |
| [OBP](docs/实验导航.md#obp) | U、EoH、Best Fixed H。训练用 train96 与 R_code，U 用 H401 冻结资产。Ross-style 已有模板，绑定和真实验收另见导航。 |

开发主线支持三种子独立执行。新命令需要包含相应提交的部署。现有 R15p3 使用[原操作手册](docs/研究人员实验操作手册.md)。

## 刷新实验状态矩阵

在本仓库根目录用已安装依赖的 Python 运行。命令读现有记录，刷新两份派生报告。省略 `--refresh` 可只在终端预览。

```bash
python3 -s -B tools/experiment.py dashboard --refresh
```

默认读本项目的批次、Ross-style 本地记录和 TSP confirm60 结果，再合并已有快照。用 `--root` 加入能读取的发布目录，用 `--archive` 加入已取回的 R15 导出 ZIP。历史 Ross-style 可用 `--prototype-root` 指向保留的工作树或解压后的归档。没有访问到的记录保留原时间并标记待确认。

如果集群和 Mac 分开存放，在**集群上包含此命令的独立工作树**取得纯 JSON 快照。命令只查询 Slurm 队列。

```bash
P="$HOME/hdl-envs/portable-v2/bin/python"
"$P" -s -B tools/experiment.py dashboard --root "$HOME/hdl-deploy" --slurm --format json > "$HOME/hdl-status-snapshot.json"
```

用已有 SCP 路线取回 JSON 后，在 **Mac 的本仓库根目录**合并。输出仍为 [实验状态矩阵](reports/EXPERIMENT_STATUS.md) 及其快照。

```bash
python3 -s -B tools/experiment.py dashboard --import-snapshot "$HOME/Downloads/hdl-status-snapshot.json" --refresh
```

## 刷新科研汇报

状态矩阵刷新后，在仓库根目录运行 `python3 -B tools/research_progress.py --refresh`。它只读同一份状态快照，更新[科研实验进展汇报](reports/RESEARCH_PROGRESS.md)。省略 `--refresh` 可在终端预览。历史身份与复现记录继续通过状态矩阵和工程详细记录查看。

## 路线一 · Mac IDE 改 JSON，集群提交

在 Mac 的项目根目录打开 VS Code 或 Cursor，复制一份模板并换 `name`。在 `research.runs` 写 1～3 个独立的方法／种子组合。设置训练清单、冻结 H 和参照路径。相对路径从项目根解析。API 并发、超时和请求上限在 `execution.api`，CPU 和时限在 `execution.slurm`。

Mac 本地已有环境可直接预检。若需要新环境，在项目根运行 `python3.12 -m venv "$HOME/.venvs/hdl-r15"` 和 `"$HOME/.venvs/hdl-r15/bin/python" -m pip install -r requirements.txt`。

`execution.slurm.wall_seconds` 是每个训练分段的上限。`execution.slurm.review_wall_seconds` 是每次接续审核的独立上限，默认 `3600` 秒，可按整分钟调整。审核结束即释放资源。新 R15 批次保留物理请求上限。独立批次可将 `execution.max_segments` 设为 `null`，由 Slurm 分段继续，直到训练达标或触及原请求预算。冻结旧部署沿用自己的记录。启动前确认所选分区接受两个 Slurm 时限。

```bash
P=$HOME/Developer/cluster-deployment/mac-portability-env-v2/bin/python
CFG=configurations/experiments/tsp-502.json
"$P" -s -B tools/experiment.py prepare "$CFG"
```

本地可编辑、预检和运行离线 Mock。正式搜索交给集群计算节点。上校园网后用 SSH 登录，配置可用 `scp` 传到新发布目录。

## 路线二 · 在家用 UU，进入实验室 Windows 的 CMD

Windows 只用来登录和传文件，无需安装项目 Python。以下以本地 SSH 配置中的 `hdl-cluster` 为示例别名，也可用自己已有的登录命令。Slurm 模板中的 `YOUR_SLURM_ACCOUNT` 需换成本账户的项目名。

```cmd
ssh hdl-cluster
```

Mac 在校园网使用同一条登录命令。在出现 `[user@master ~]$` 后，进入已部署的发布根目录。以下命令在集群 Linux 终端执行。

```bash
P=$HOME/hdl-envs/portable-v2/bin/python
"$P" -s -B tools/experiment.py configure --platform cluster
```

菜单只保存真实 JSON，显示资产、预算、源码和对应命令。也可以直接用已有 JSON。

## 预检、启动、查询和取回

```bash
CFG=configurations/experiments/tsp-502.json
"$P" -s -B tools/experiment.py prepare "$CFG"
"$P" -s -B tools/experiment.py run "$CFG" --approve
"$P" -s -B tools/experiment.py status "$CFG"
"$P" -s -B tools/experiment.py export "$CFG" --out "$HOME/tsp-502-results.zip"
```

`pending: []` 表示资产预检通过。真实运行使用已验收的发布版本和已授权的并发。提交收到作业号后可关闭电脑。申请暂停用 `pause`，等 `status` 显示 `operator_paused` 后用 `resume`。正常时限接续由 Slurm 自行处理。12 小时后看应用状态，候选还没达标时可查已完成数量及原因。

从实验室电脑 **本地 CMD** 取回 ZIP，再用 UU 传回 Mac。

```cmd
scp hdl-cluster:tsp-502-results.zip "G:\Experiment\transfer-outbox\tsp-502-results.zip"
```

## 训练和自动外评

修改新批次 JSON 的 `research.holdout`，或在配置器的“训练外评价”选 `auto`。[TSP EoH 三种子配置](configurations/experiments/r15-tsp-eoh-confirm60-example.json) 预留了 confirm60 清单和 D06 参照路径，使用前按项目地图绑定实际文件。现有九冠军的正式结果见[逐种子汇总](reports/tsp-confirm60-nine-20261124/seed-results.csv)。

- `mode: auto` 在 Slurm 审核确认种子训练完成后排入独立 CPU 外评，Mac 可断开。评价继承训练分区、账户、QoS 和内存，使用 2 核及按实例数计算的独立时限。
- `mode: manual` 在启动前固定同一套外评资产，训练完成后用 `evaluate` 提交。`"holdout": "not_run"` 保留仅训练模式。
- `split` 支持 `validation`、`test` 和 `prospective-confirmation`，必须与清单一致。TSP 需要独立 D06 参照。FJSP 和 OBP 的 `reference` 可设为 `null`，使用已有 LB_v5 和 R_code。若提供显式参考表，其 `instances` 必须与相应计算规则逐行相同。
- FJSP `test` 可以直接指向已有的 `data/fjsp_manifest.json`，原始 `.fjsp` 文件须位于清单同级的 `fjsp/` 目录。OBP `validation` 可使用 `preparations/triad/obp-official-20261115/validation.manifest.json` 的 32 例。这批验证数据与最终 30Weibull 测试集有各自的实验身份。

```bash
CFG=configurations/experiments/r15-tsp-eoh-confirm60-example.json
"$P" -s -B tools/experiment.py prepare "$CFG"
"$P" -s -B tools/experiment.py run "$CFG" --approve
"$P" -s -B tools/experiment.py status "$CFG"
"$P" -s -B tools/experiment.py export "$CFG" --out "$HOME/tsp-train-and-confirm60.zip"
```

`prepare` 会列出缺少的文件、身份不符和训练集重叠等情况。`status` 的 `lifecycle` 显示训练、冻结和完整完成，各种子另有外评状态与作业号。外评中断或失败后，在集群终端执行 `"$P" -s -B tools/experiment.py evaluate "$CFG"`。它只排入缺少完整外评的已冻结种子，复用已经写盘的逐例前缀，保留失败尝试的成本记录。

训练按既有规则确定冠军，运行目录的 `exports/` 保存程序、冻结记录和 `champion_identity.json`。全部外评结束后，批次 `holdout/` 自动生成三张 CSV。导出 ZIP 同时包含训练原表、外评证据和 `holdout-per-instance.csv`、`seed-results.csv`、`method-summary.csv`。方法统计按配置中的独立种子计算。缺少种子时留空相应外评统计。

自动接续代码已覆盖 TSP、FJSP、OBP 的 R15 U 和 EoH，已通过离线模拟，真实 Slurm 自动外评待现场验收。Ross-style 和固定 H 使用各自的入口。已完成的 TSP 九冠军 confirm60 是独立 Mac CPU 外评的真实结果，见[状态矩阵](reports/EXPERIMENT_STATUS.md)。

[真实验收、固定 H 和 H401 命令](docs/R15真实验收与六组.md) · [现场验收与版本状态](DECISIONS.md#验收与回退) · [历史发布入口](docs/实验导航.md#历史版本)
