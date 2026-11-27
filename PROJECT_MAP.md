# 项目地图

R15 新实验从 [README](README.md) 进入。图中方括号标的是角色，路径与已有代码相对应。

```text
Heuristic-Design-Lab
├── tools/experiment.py                          [研究人员命令]
├── reports/EXPERIMENT_STATUS.md                  [按回执生成的状态矩阵]
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
| 固定 H 与 Ross-style | `tools/experiment.py fixed-plan` 读工作台配置。[assets.py](experiments/triad/assets.py)评价或复用固定 H 成本。Ross-style 用本项目中的 [prototype_hh.py](tools/prototype_hh.py) 和[三问题模板](configurations/prototype-hh/)，见[操作说明](docs/传统状态路由基线.md)。 |
| 状态矩阵与跨设备刷新 | `tools/experiment.py dashboard` 走[矩阵读取与生成](tools/experiment_dashboard.py)。读取原运行、导出和外评回执，派生 Markdown 及最后状态 JSON。没有新的运行账本。 |
| 科研汇报 | [科研实验进展汇报](reports/RESEARCH_PROGRESS.md)由 [research_progress.py](tools/research_progress.py)读取同一份状态快照生成。统计只纳入身份明确、完成预定留出评价的三种子结果。 |
| API 并发和 TSP 有限真实验收 | [r15_acceptance.py](tools/r15_acceptance.py)，逐请求和结果 JSON 放在 `reports/acceptance-<name>/` |
| 六组三种子长实验 | [正式配置与命令](docs/R15真实验收与六组.md#六组正式长实验)，每组一份 JSON，OBP U 共用 H401 的正式冻结资产 |
| 冻结后外评和论文表 | [post_evaluation.py](experiments/triad/post_evaluation.py) 复用各问题的 T30 评价器，由 [campaign.py](experiments/triad/campaign.py) 调度。外评记录位于批次计划及 `holdout/`。 |

## 出问题先看哪里

| 现象 | 先看 |
| --- | --- |
| 配置报错、字段不支持、资产缺失 | `prepare` 的 `pending` 和错误信息。[研究人员入口](tools/experiment.py) · [基础配置校验](experiments/triad/configuration.py) |
| 请求失败、预算和暂停 | 种子的 `API_attempts.json`、`Stop.json`、`checkpoint.json`，以及批次 `api-pacing/`。[批次限速](experiments/triad/batch_admission.py) · [计数与容错](experiments/triad/candidate_policy.py) · [请求账本](code/fjsp_usage/research_real/attempt_budget.py) · [故障例外和废弃限制](DECISIONS.md#待修复事项) |
| Slurm 提交、接续或暂停 | `logs/<实验ID>-<作业ID>.*`、`plans/<批次>/campaign-control/` 与 `Campaign_result.json`。审核时限从批次的 `execution.slurm.review_wall_seconds` 设置。[提交](experiments/triad/parallel.py) · [依赖作业](experiments/triad/campaign.py) · [续跑判断](experiments/triad/time_continuation.py) |
| 每种子的历史、图表或冠军 | `runs/<批次>/<实验ID>/` 下的 `Protocol.json`、`checkpoint.json`、`exports/` 和 `worker-receipts/`。[执行循环](code/heuristic_design/core/execution.py) · [导出](code/heuristic_design/core/execution_export.py) |
| R15 三种子训练结果汇总 | [r15_results.py](tools/r15_results.py) 读取现有导出 ZIP。[汇总命令和纳入条件](docs/R15减负设计与交接.md#结果汇总与未完成事项) |

默认批次目录名为 `candidate-lab-<name>`，实验 ID 另含组别和种子。新 R15 正式批次的激活锁位于该批次的 `batch-gate/`，种子写入锁继续使用 `run-gates/` 和各自的检查点目录。搜索日志和结果按发布目录、批次与种子独立保存。历史研究和模型传输证据在 `docs/`、`reports/`、`archives/` 及 Git 历史。旧首页导航可用 `git show r15p3:README.md` 查看。

开发主线的 `api-pacing/` 只保存并发许可与发送间隔状态。单种子的实际请求记录以该种子 `API_attempts.json` 为准。R15p3 的历史共享账本与 STOP 排查见该标签或 DECISIONS 所列历史提交。选择问题与终端命令见 [实验导航](docs/实验导航.md)。

## 版本库与实验归档

GitHub 的现有 R15 分支保存当前代码、配置模板、可公开的训练资产、汇总表、图和复绘程序。训练集以各配置引用的清单和 SHA-256 为准。正式种子、已绑定 H、部署身份与接续状态以各次运行的 `Protocol.json`、`checkpoint.json` 和 Slurm 回执为准。

| 本机或集群归档 | 内容和校验方式 |
| --- | --- |
| Mac 的 `~/Developer/transfer-outbox/r15-consolidation-20261127/` | `verified-asset-index.json` 列出已核验发布包与结果包的 SHA-256。Git bundle 保存本地分支和标签。旧工作树的未提交代码及部分关键资产另有 ZIP 和逐文件校验；完整历史运行仍以原目录为准。 |
| 同目录的 `ross-frozen-evidence-20261127.zip` | Ross-style 的旧基点、工作树补丁、冻结冠军、搜索记录、TSP confirm60 数据和专用评价脚本。用 ZIP 的逐文件清单和旁置 SHA-256 验证。预期基点在 `base-commit.txt`。还原时在独立目录检出该基点，应用补丁并按 ZIP 路径恢复未跟踪文件。旧冠军的复现依赖原源码。 |
| Mac 的 `~/Developer/transfer-outbox/` | TSP confirm60 的 D06 参照、冻结冠军与逐实例归档，FJSP／OBP 已导出的冻结冠军，TSP／OBP 固定 H 外评，以及当前使用的 Slurm 发布 ZIP。TSP／OBP 的独立固定 H 实验脚本随 Ross 证据包保留，主项目用 `fixed-plan` 和 `assets.py` 做固定 H 训练端核查。 |
| 集群的 `~/hdl-deploy/` | 真实作业原发布目录、检查点、导出、API 请求记录和原版恢复命令。已有批次继续使用各自的部署版本。GitHub 上的统一源码用于后续新发布。 |

本机主项目的 `preparations/operations/obp-H401/H_frozen.json` 从正式 H401 归档取回，使用 `obp-h401-fixed-inputs-20261126.zip` 核对。TSP 外评模板的本机清单与参照分别放在 `preparations/operations/confirm.manifest.json` 和 `preparations/operations/tsp-confirm60/confirm60-reference.json`。新机器需从对应归档还原这些输入。复绘还需要 Ross 归档中的协议、候选表和成本回执。它们可放在本项目的 `runs/prototype-hh/` 供只读报表读取。
