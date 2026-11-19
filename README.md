# Heuristic Design Lab

R15 是新实验的主线候选。用 [tools/experiment.py](tools/experiment.py) 读取一份 JSON，就能预检、提交、查询和导出。查代码和日志用 [PROJECT_MAP.md](PROJECT_MAP.md)，查参数来源和采用状态用 [DECISIONS.md](DECISIONS.md)。

## 选配置

| 样例 | 可以运行的内容 |
| --- | --- |
| [TSP U 和 EoH](configurations/experiments/tsp-502.json) | 种子 502。填入已核验的 D06 LKH train20 参照路径。现场验收包已生成 `configurations/experiments/tsp-502-site.json`，可直接预检 |
| [FJSP EoH](configurations/experiments/fjsp-503.json) | 种子 503，使用 train21。FJSP U 已有历史冻结执行器，R15 尚未接入 |
| [OBP U 和 EoH](configurations/experiments/obp-501.json) | EoH 资产预检通过。U 缺 H401 冻结的 10H。只跑 EoH 时，复制配置并在 `research.runs` 中保留 EoH |
| [无 API 验收](configurations/experiments/slurm-no-api-smoke.json) | 合成候选和评价，用于检查实际 Slurm 分段接续 |

复制 JSON 后更改 `name`。在 `research.runs` 填 1 到 2 个方法与种子组合，每一条是一次独立搜索。三次重复可分为多个配置，每批共享同一账户的使用权。训练清单在 `training_manifest`，冻结 H 在 `frozen_h`，TSP 参照在 `reference`。相对路径从项目根解析，`null` 使用该组默认绑定。真实 R15 搜索每种子目标为 1000 个成功返回的演化候选。

在 `execution` 中编辑 Slurm 的 CPU、内存、单段时限，以及 API 超时、排队、请求预留上限和退避。终端会指出当前版本支持的并发及缺少的资产。提交后保留原 JSON，查询与恢复沿用它。

## 在集群上运行

用 UU 连接实验室电脑，从它的本地终端登录：

```bash
ssh -J custom@222.201.144.188:22 qiuqian@110.1.2.1
```

进入独立 R15 部署目录。下面以准备了 D06 参照的 TSP 现场配置为例：

```bash
cd /public2/home/qiuqian/hdl-deploy/triad-candidate-runtime-20261119-r15p3
P=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
CFG=configurations/experiments/tsp-502-site.json

"$P" -s -B tools/experiment.py prepare "$CFG"
```

每组显示 `pending: []` 表示配置和资产预检通过。正式启动需在现场验收、有限真实小试和相应授权后执行：

```bash
"$P" -s -B tools/experiment.py run "$CFG" --approve
```

收到 `submitted: true`、搜索作业号和首个审核作业号后，可以断开 UU。12 小时后按需执行：

```bash
"$P" -s -B tools/experiment.py status "$CFG"
"$P" -s -B tools/experiment.py export "$CFG" --out "$PWD/tsp-502-results.zip"
```

`status` 显示候选数、最优训练 J、请求统计和暂停原因。按时保存的批次由 Slurm 审核作业接续。主动暂停且已结算的批次显示 `operator_paused`，用同一 JSON 执行 `resume`。已导出的结果可在实验室电脑用 SCP 取回。共享 STOP 或未知结算详见 [DECISIONS.md](DECISIONS.md#共享-stop-触发与恢复)。

目前无 API 现场检查已提交。用 `bash "$HOME/r15p3-site-20261120/site.sh" status` 查看，`site_ready: true` 才表示通过。具体部署、回执和恢复示例见 [R15 操作手册](docs/研究人员实验操作手册.md)。R13 旧批次使用 [原操作菜单](docs/R13旧TSP501-Mac独立菜单-20261118.md)。
