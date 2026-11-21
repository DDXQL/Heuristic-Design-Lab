# 项目地图

R15 新实验从 [README](README.md) 进入。图中方括号标的是角色，路径与已有代码相对应。

```text
Heuristic-Design-Lab
├── tools/experiment.py                          [研究人员命令]
├── configurations/experiments/                   [可编辑的批次 JSON]
├── configurations/six-groups-20261116/           [研究组基础配置]
├── preparations/                                [冻结 H、train 清单、参照和身份]
│   ├── eoh-gap/                                 [FJSP train21]
│   ├── triad/tsp/                                [TSP train20、冻结 H]
│   ├── triad/obp-official-20261115/                [OBP train96]
│   └── operations/                              [接入的参照和本地绑定]
├── code/
│   ├── heuristic_design/problems/{tsp,fjsp,obp}/  [问题代码]
│   ├── heuristic_design/core/                    [状态、U 演化、执行和导出]
│   └── fjsp_usage/research_real/                 [V5 传输、物理请求账本]
├── experiments/triad/                           [问题适配、方法接入和集群执行]
├── deploy/eoh-baseline/                         [EoH 原生搜索接入]
└── 部署目录的 plans/、runs/、logs/、reports/      [计划、实验、日志与验收]
```

## 问题与方法

| 找什么 | 代码 |
| --- | --- |
| 三个问题如何读数据、绑定 H、评分 | [problems.py](experiments/triad/problems.py)、[evaluation.py](experiments/triad/evaluation.py) |
| 方案 A、U 每步选 H、U 算子 | [state_a_v3.py](code/heuristic_design/core/state_a_v3.py)、[routing_state_a_v3.py](code/heuristic_design/core/routing_state_a_v3.py)、[evolution_v1.py](code/heuristic_design/core/evolution_v1.py) |
| U 与 EoH 如何进入同一执行器 | [runtime.py](experiments/triad/runtime.py)、[eoh_gap.py](deploy/eoh-baseline/eoh_gap.py)。R15 主线接入三类问题的 U/EoH。[run_frozen.py](experiments/common/run_frozen.py)用于原 FJSP U 身份 |
| 固定 H 或其他基准 | `tools/experiment.py fixed-plan` 解析工作台配置。[assets.py](experiments/triad/assets.py)负责评价或复用成本。传统 HH 尚未接入统一入口 |
| API 并发和 TSP 有限真实验收 | [r15_acceptance.py](tools/r15_acceptance.py)，逐请求和结果 JSON 放在 `reports/acceptance-<name>/` |
| 六组三种子长实验 | [正式配置与命令](docs/R15真实验收与六组.md#六组正式长实验)，每组一份 JSON，OBP U 共用 H401 的正式冻结资产 |

## 出问题先看哪里

| 现象 | 先看 |
| --- | --- |
| 配置报错、字段不支持、资产缺失 | `prepare` 的 `pending` 和错误信息。[研究人员入口](tools/experiment.py) · [基础配置校验](experiments/triad/configuration.py) |
| 请求失败、预算、共享 STOP | 种子的 `API_attempts.json`、`Stop.json`、`checkpoint.json`，以及批次 `api-pacing/`。[批次并发与限速](experiments/triad/batch_admission.py) · [计数与容错](experiments/triad/candidate_policy.py) · [请求账本](code/fjsp_usage/research_real/attempt_budget.py) |
| Slurm 提交、接续或暂停 | `logs/<实验ID>-<作业ID>.*`、`plans/<批次>/campaign-control/` 与 `Campaign_result.json`。[提交](experiments/triad/parallel.py) · [依赖作业](experiments/triad/campaign.py) · [续跑判断](experiments/triad/time_continuation.py) |
| 每种子的历史、图表或冠军 | `runs/<批次>/<实验ID>/` 下的 `Protocol.json`、`checkpoint.json`、`exports/` 和 `worker-receipts/`。[执行循环](code/heuristic_design/core/execution.py) · [导出](code/heuristic_design/core/execution_export.py) |

默认批次目录名为 `candidate-lab-<name>`，实验 ID 另含组别和种子。账户租约位于共享账户目录，搜索日志和结果按发布目录、批次与种子独立保存。历史研究和模型传输证据在 `docs/`、`reports/`、`archives/` 及 Git 历史。旧首页导航可用 `git show r15p3:README.md` 查看。

开发主线的 `api-pacing/` 只保存并发许可与发送间隔状态。单种子的实际请求记录以该种子 `API_attempts.json` 为准。R15p3 的历史共享账本与 STOP 排查见该标签或 DECISIONS 所列历史提交。选择问题与终端命令见 [实验导航](docs/实验导航.md)。
