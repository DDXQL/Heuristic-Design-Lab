# 实验协议与运行决定

更新本页时注明是正式采用、现场实测、工程默认值，还是待验证。研究定义、工程能力和一次运行的结果分别记录。2026-11-20 核对。

## 已采用的研究协议

| 决定 | 依据和范围 |
| --- | --- |
| R15 按成功返回计数 | 用户采用做法 B。每个真实种子的目标为 1000 个成功返回的演化候选。无效、重复及评价失败照计。初始化与 H 构建单列，物理发送和预留另计。旧 R13 仍按原 1000 次演化尝试解释。[计数实现](experiments/triad/runtime.py) · [边界验证](experiments/triad/candidate_runtime_tests.py) |
| U 每步选一条 H | 共同状态方案 A v3，14 项信息含逐 H 数组，保持 SELECT 语义。[状态定义](code/heuristic_design/core/state_a_v3.py) |
| TSP train20、冻结 10H、U5/EoH10 | 每组初始化最多 20 次。EoH 采用 native EoH 准入。D06 LKH 3.0.13 参照已完成并取回，候选源码与官方包的同一性仍未验证。[TSP 采用和资产](docs/TSP候选源码接入-20261117.md) |
| 冻结评价与选优 | FJSP train21、OBP train96、TSP train20 沿已采用口径，按最小训练 J 及固定 ID 选冠军。固定 H 是额外参照，holdout 在冻结后另行评价。[评分与数据](experiments/triad/problems.py) · [冠军与导出](experiments/triad/runtime.py) |

## 真实约束与工程默认值

| 项目 | 事实、来源及当前处理 |
| --- | --- |
| API 总并发 1 | 最初是 R6 在账户上限未知时采用的保守工程设置。R15 入口、清单校验和调度分支仍只接入宽度 1，同批最多两份搜索。CPU 评价可交错。旧代码的 API2 是两组 FJSP EoH 的有限验收分支，R15 搜索入口没有接通。2、4、8 均待验证，账户并发、RPM、TPM 及金额硬限未核实。[历史依据](experiments/triad/parallel/README_ZH.md) · [旧探针](experiments/triad/concurrency_probe.py) · [共享准入](experiments/triad/shared_admission.py) |
| 已有并发实测 | 历史记录中的 618876/618877 同节点真实有限前缀验证了两份作业共享 API1。它只支持这个范围内的可用性结论。当前 R15p3 现场作业 634046～634049 已提交，最终回执尚未核验。[历史回执导航](docs/六组实验按序运行.md) |
| 普通失败策略 | R13 首次传输故障或共享排队超时会写全批 STOP。R15 已放宽为就地结算可确认的失败，明确终态 HTTP 520/522/524 记账后可用新槽继续，明确未发出的本地超时可有限尝试，普通 429 使用共享冷却。账本冲突和真实未知沿下表处理。[策略](experiments/triad/candidate_policy.py) · [共享结算](experiments/triad/shared_admission.py) |
| 超时、重试和请求上限 | 默认 1 秒发送间隔、600 秒排队、300 秒 HTTP 超时、429 冷却 30 秒、每演化槽最多两次预留、连续 5 个失败槽暂停本种子、每种子 1100 次演化预留，均是样例工程参数。5 可改为 0，正式预算以批准的 JSON 为准。300 秒是 R15 当前锁定传输实现的配置上界。空/截断响应示例均排除，按正式批次确认。[样例 JSON](configurations/experiments/tsp-502.json) · [校验](tools/experiment.py) |
| 租约、时间和审批 | 案例的 12 小时单段、48 小时批次、72 小时账户排他、最多 4 段都是配置值。项目内部还有 10 秒共享账本锁等待、提交回执和 Slurm 会计可见性的有限等待。单段真实上限由 Slurm 分配并强制执行。R15 省去 R13 新批次启动时的有限前缀。普通时间暂停继承已批准预算，由依赖作业提交下一段。[样例](configurations/experiments/tsp-502.json) · [续跑代码](experiments/triad/campaign.py) · [Slurm 官方说明](https://slurm.schedmd.com/sbatch.html) |
| 集群和账户要求 | 实际分区配额、作业时限、依赖作业能否由计算节点提交、共享文件锁在计划节点上的行为，以集群现行规则和现场回执为准。鉴权、余额和真实 429 以账户与响应证据为准。Slurm `COMPLETED` 只表示作业进程正常退出，候选是否达标看应用报告。[Slurm 状态说明](https://slurm.schedmd.com/job_state_codes.html) · [现场验收](docs/研究人员实验操作手册.md#4-上线前现场验收) |

## 共享 STOP 触发与恢复

以下覆盖 R15 候选搜索能够写入本批 `gate/STOP.json` 的路径。共享 STOP 会阻止本批新发送，仍占用的账户租约可能让下一批无法激活。单种子的预算耗尽、达到连续失败阈值、主动暂停或定时保存可单独出现。

| 写入入口 | 条件与范围 | 恢复前核对 |
| --- | --- | --- |
| [Admission.verify](experiments/triad/shared_admission.py#L159) | 全账户租约缺失、归属改变或过期，停本批发送 | 核对原清单、租约归属、其他批次和原授权期限。期限已尽时按原记录收尾 |
| [Gate.transaction](experiments/triad/concurrency_probe.py#L43) | 共享账本锁在有限时间内无法取得。事务写入不确定也可能留下锁，随后由等待方触发 | 核对锁主机、PID/作业身份与账本原件。确认原写入进程终态后再处理 |
| [Admission.known_failure](experiments/triad/shared_admission.py#L287) | 账号鉴权、余额、模型或参数等永久错误，以及明确的协议硬停。发送/结果非终态或网络工作进程无法确认时也会停本批 | 对照原 HTTP/发送回执、工作进程状态和账号证据。已确认终态但用量缺失的请求保留未知用量 |
| [Admission.known_failure](experiments/triad/shared_admission.py#L310) | 已预留请求在共享账本中找不到且无法安全补记，成员/请求/状态/活动许可冲突、等待请求持有许可、外来发送锁、HTTP/发送证据冲突或释放锁时归属改变 | 对照种子账本、共享请求与许可、发送锁。保留原始记录和已消耗预算 |
| [Admission.session](experiments/triad/shared_admission.py#L350) | 计算节点启动自检失败，或退出时检查点、请求、进程/作业或锁未安全结算 | 核对 `preflight/`、作业终态、检查点、锁与在途请求 |
| [写锁](experiments/triad/entry.py#L37) · [凭据](experiments/triad/entry.py#L215) | 种子写锁归属在退出时消失或改变。凭据读取/校验失败也会写全批 STOP | 核对本批写锁归属或凭据文件元数据，保留密钥私密性 |
| [parallel.submit](experiments/triad/parallel.py#L195) | 一组 `sbatch` 提交失败或回执不明，可能已有部分作业提交 | 用 `squeue` / `sacct`、提交收据、作业名及配置指纹确认是否有作业。保留已占用名额 |

旧 R13 的首次故障/排队超时路径以及独立并发探针自身的宽度、异常、到期停止条件仍在原实现中。R15 的普通本地超时与终态 HTTP 错误已通过故障注入；共享 STOP 需核实原因和所有权后处置，普通 `resume` 只适用于已结算的原批次。

**未知发送的隔离边界。** 目前保留请求 ID、预留、发送状态、已知 token 和用量未知。发送层用本地子进程状态辅助分类，续跑前核查 Slurm 终态、锁和本地账本。确认本地进程结束仍不足以确认供应商是否收到、完成或收费。后续可单列估算输入 token 和配置允许的最大输出，实际用量仍须保留未知。取得可信终态后可以就地结算，真正未知的请求保留预留和已取得的许可。在 API1 下这可能是唯一许可。当前版本没有自动为真正未知请求放行其他种子的能力。[发送核查](experiments/triad/shared_admission.py#L441) · [账本字段](experiments/triad/candidate_policy.py) · [接续核查](experiments/triad/time_continuation.py)

## 待验证的并发方案

先取得账户或供应商能确认的上限及可用额度，与正式搜索分开申领一次测试窗口。用相同模型、相近输入长度和相同输出上限做短请求，每阶段保持相同的发送间隔设置，并核对真实观察到的重叠数。建议宽度 1／2 各最多 4 次，宽度 4 最多 8 次，宽度 8 最多 16 次。逐级授权与停止，整套最多 32 次物理发送，0 次求解，无自动重试。任一阶段遇到 429、鉴权/余额错误、未知发送或超过批准延迟界就停止升档。记录每级总耗时、成功吞吐、延迟、确认发送、未知用量与已知 token。这只给出小样本可行性，供应商上限和长实验加速仍需各自证据。现有旧探针仅做 1／2，4／8 的探针和生产接入均未实现。该测试与 TSP 首次小试分开，当前不作为启动 API1 的前置条件。

## 版本与下一步

- 主线为现有分支 `codex/successful-candidate-runtime-20261119`。后续提交继续在该分支，发布时加标签并用打包器的 `--version` 指明新版本。R15p3 固定 Git 标签 `r15p3` 指向 `d32de9973c052d814b20470c7b65022556faa4bc`，原 ZIP 的 SHA-256 为 `bccfa9eefdaaa676f7bb138bfc68695d81a839a0d5df3e4bd348b52f5de9a5c3`。从该标签的临时干净检出运行 `python3 -B tools/build_candidate_campaign_release.py --base <原R13.zip路径> --output <新ZIP路径>`。旁边须有原 R13 SHA-256 文件。可对照 `release.json` 的成员哈希重现内容，重打包的 ZIP 时间戳可能不同。
- 集群 R13 在 `triad-tsp-lkh-candidate-20261117-r13`，R15p3 在 `triad-candidate-runtime-20261119-r15p3`。各目录保有自己的计划、检查点和结果。恢复旧实验回原发布目录。回退新发布时从原 ZIP 建独立部署目录，只给之后的新批次选用。运行中的计划、账本和结果继续使用原版本。
- 最短路径为先读 634046～634049 的现场状态，三项通过后再批准同一 R15p3 的有限真实 TSP 小试。U/EoH 各 1 个初始化槽，最多 2 次发送、40 个候选–实例评价、80 次含复核求解。使用独立账本，不访问测试集。小试通过后再提交正式 1000 成功候选。三份入口交接文档不会改变或阻塞这条路线。
