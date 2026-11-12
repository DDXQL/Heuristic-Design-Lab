# 方案A小规模完整流程准备｜2026-11-12

本次完成的是代码接入、参数冻结、纯离线检查和用户可启动的工程验证。**没有启动模型、构造求解、训练/正式评价或Slurm作业。** 前轮Mac与集群4次API验收保持关闭；本次真实请求预留0、确认发送0、构造求解0。

独立工作树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-flow-check-20261112`，分支 `codex/flow-check-20261112`。基于共同API交付 `ab45ead`，接入方案A交付 `dd28326`。原API、方案A、FJSP/TSP运行工作树、用户修改、原始回执、锁和恢复依赖均保留。

## 验证范围与预算

这不是1000次搜索，也不是正式方法优劣比较。用现有手写3H工程集合及一个3-job、4-machine、9-operation的合成开发实例，检查真实生成、解析、完整构造、首解/复检、检查点、暂停接续和导出。不会读取train21、test、holdout，不重算旧冠军，不建设新H集合或新增状态消融。

|阶段|实际执行的内容|新增模型请求上限|构造求解上限|
|---|---|---:|---:|
|Mac|固定H0；用原EoH长提示生成一个H样本；用完整方案A提示生成一个U；三者各做首解和复检|2|6|
|集群|导入Mac相同候选与已验收响应，再做相同三项首解/复检，比较完整语义结果|0|6|
|本次新计划累计|两端分别串行，无补员、重试或成功数补齐|**2**|**12**|

12次是6个“候选×实例”分别首解和复检的上限，不是12个训练候选。源代码中的单条H样本不等于完成EoH演化；手写3H不是正式EoH-S集合。CSV仅报告工程成本，不据此推断正式性能收益。

本次使用已冻结 `common-state-a-v2`、纯选择ABI `pure-routing-state-a-v2` 和全部10项状态，定义SHA `8eed0e3257cf0a9314ad6ea1d14ae2b5ca659d8ece80748efaeb4a1aa965c632`。没有给旧13项换名或删除重复字段。FJSP使用原未取整LB_v5，输出 `J=(Cmax-LB)/LB`、越小越好。为了复用现有执行器存储，内部utility字段为−J，但本流程没有搜索/生存选择；CSV保留原始Cmax、LB及J，不能混入旧负Fitness曲线。

研究依据：[共同状态信息、评分与对比实验](https://app.notion.com/p/41204e0510d781f3a328c11ed393a1b1)，以及本地 `docs/state-a-v2/共同状态定义.md`、`docs/state-a-v2/接入与交付说明.md`。本轮读取了Notion当前可取内容及方案A实际源码。TSP新评分要求有来源的冻结LKH参照，现有准备材料尚未提供；因此当前完整流程先做FJSP，不用NN或手写数字假冒LKH。TSP/OBP接口离线检查通过不代表它们的完整流程已运行。

## 实际代码接入

没有重写搜索框架。`core/flow_check.py` 是现有 `core/execution` 的小规模任务适配层，复用原API journal、V5 wire、严格调用方、T30完整接收与进程回收，以及现有方案A解析/构造器。两端导入同一版本；wire与严格调用方逐字节等同前轮验收版本，供应商、模型、传输和10/240/300秒超时没有改变。

- 固定三个任务顺序，无正式种群和演化。Mac最多两个物理请求；集群禁止API开关和登录节点评价。
- 已知结果先提交，再处理时钟异常；未知在途、未结算评价、Stop或残留writer锁拒绝恢复。失败不退回预留，不改目录重开。
- 正常计划在固定H0结算后暂停，核验原时钟/预算/完整前缀，再在同一用户启动命令里接续一次。手动停止、clock gap及任何失败均不会被当作这次预定暂停自动接续。
- 补上执行器返回后的信号处理器恢复，避免两次控制阶段之间Ctrl-C仍只设置旧控制器的标志。主机StateA结果补齐实际H序列元数据，不改状态公式或动作规则。
- 每个评价子进程禁止网络，收到完整首解/复检结果才通过；不完整结果不按前缀平均。完整trace和实际H序列、源指纹、worker生命周期及usage分别保留。
- 新Slurm脚本和提交命令均显式 `--no-requeue`，1CPU/1GB，15分钟。提交后立即结束的作业从记账读取，不为查询失败重投。排队不是API失败。

运行文件、输入、Prompt和脚本清单见 `deploy/flow-check/plan.json`、`plan.sha256`；冻结索引见本目录 `FREEZE.json`。已有旧API入口/配置仅作来源与兼容资料，不在此工作树启动它们或恢复旧运行。

## 已完成的离线检查

- 39项控制/脚本检查通过：用合成回执代替模型和评价器，网络/求解入口拦截；覆盖预算门禁、两端串行及累计上限、原期限暂停接续、手动停止、clock gap、首个失败关闭、未知在途保留、导出篡改、SSH前置门禁、密钥不传给SSH、快速终态不重投及新流程取回。见 `offline-tests.log`。
- 10项方案A检查通过：给定部分状态的算术/缺失、窗口、封闭U接口、提示和缓存绑定、静态动作/历史顺序。构造入口禁止执行，未跑旧mock演化。见 `state-a-offline.json` 与日志。
- 部署包在临时目录解压，用隔离解释器执行check-only通过；无环境隐式路径依赖，清单排除密钥、虚拟环境、runs和旧结果。见 `isolated-package-check.json`。
- 四份shell/Slurm脚本通过bash语法检查。没有执行SSH部署、sbatch或srun。

准备中发现的两个问题已修复并保留来源：系统Python生成的AST指纹与冻结3.12.10不同，新工程夹具已用3.12.10生成；Mac临时路径的 `/var` 别名导致恢复时路径校验不一致，已对新流程目录统一resolve。原记录为 `initial-fixture-python-mismatch.json`、`control-tests-initial-path-error.log`。未改任何旧实验指纹。合盖期间没有真实验证进程；本次不另外排查电源原因。

上述结果只证明代码门禁和控制逻辑通过离线检查。实际构造可行、完整结果一致及跨平台语义一致，仍要由下面的有限运行产生证据。

## 用户一次启动

在Mac终端执行；**执行即明确批准本次新的最多2次模型请求和12次小型构造求解**，不是前轮4次额度的继续使用：

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-flow-check-20261112
bash deploy/flow-check/start.sh --allow-api --approve-api 2 --allow-evaluation --approve-solves 12
```

环境没有可用密钥时，会先在终端隐藏输入LeafAPI密钥，仅传给Mac API进程，不落盘或传给SSH。SSH密码仍由终端处理，不从其它进程或密钥文件提取凭据。

顺序固定：本地check-only与包核验→上传冻结代码→远端check-only/依赖核验与个人队列检查→Mac完整流程→Mac导出验收→上传内容寻址的结果→再查队列→用户命令内提交一个集群回放评价作业。远端预检失败会停在Mac请求/求解之前；Mac失败或未完成不提交集群。已有个人作业不自动取消。

持续唤醒执行时，Mac两次模型等待最多10分钟，加三项T30评价及进程清理约12分钟；集群作业墙钟上限15分钟，通常只需三项T30评价。SSH认证、文件系统读取、传输及Slurm排队另计，不承诺排队结束时间。每端保留原始1小时执行窗口，暂停不重置或延长。

集群作业退出后，在同一Mac目录执行：

```sh
bash deploy/flow-check/fetch.sh
```

它自动读取本轮记录的作业号，只读收集状态、账本、响应/结果导出和日志；模型0、求解0、提交0。未启动的目录缺失如实记录，已完成作业查不到活跃ID时保留sacct结果。也可传入本轮明确作业号 `bash deploy/flow-check/fetch.sh JOBID`。完成后只需告诉本页“完成”或错误，不必整理日志。

## 状态、停止、恢复

以下命令均在新工作树运行。Mac根固定为 `~/hdl-flow-validation/fjsp-state-a-flow-20261112/mac`，集群个人HOME中同样路径的 `cluster`；复制源码或更换工作目录不能重新获得额度。

状态和请求停止，本身不请求模型/求解/提交作业：

```sh
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/flow_check.py status --site mac
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/flow_check.py stop --site mac
```

停止在候选边界排空；正在进行的请求/评价可能还需最多约300＋30秒及清理时间。只有phase=paused、前缀已结算、无Stop/锁/未知在途且原窗口有效时才接续，不强杀或删锁。

Mac安全暂停后，一条命令隐藏输入凭据、确认原预算并接续；成功后继续传输/提交集群，不重跑已结算任务：

```sh
bash deploy/flow-check/start.sh --resume --allow-api --approve-api 2 --allow-evaluation --approve-solves 12
```

如果Mac已completed，只是传输/SSH/排队门禁中断，使用下面的命令继续；它不发Mac模型请求或重复Mac求解，但可能提交一个集群回放作业，仍受剩余6次构造上限约束：

```sh
bash deploy/flow-check/submit_cluster.sh run --allow-evaluation --approve-solves 12
```

有submission claim则不重复提交。集群已明确paused、所有前缀已结算且原时钟有效时才使用 `submit_cluster.sh resume --allow-evaluation --approve-solves 12`；这由用户提交一个接续作业，不增加模型请求或求解额度。stopped/expired/未知在途不走这些命令。

用户已登录集群时，排队阶段用 `scontrol hold JOBID` 暂停调度；需要继续原作业时用 `scontrol release JOBID`。运行中的本轮作业可用 `scancel --signal=USR1 --batch JOBID` 请求排空后暂停；不要硬取消或把命令用于其它实验。release允许原有有限评价开跑，绝不等同于新预算。

## 返回后直接验收的文件与下一步

本页读取 `reports/flow-check-20261112/launch-*`、`transfer-*`、`submitted-jobs.txt`、新 `collected-*/remote.json`，以及Mac固定根的Protocol、Tasks、API_attempts、checkpoint、Run_clock、结果、worker生命周期和export。逐次核对预留/发送/usage/未知成本，不把集群回放重复计为Mac API用量。

通过要求：三任务各完成全部声明实例及确定性复检；H/U解析与方案A绑定正确；原时钟/游标/预算接续；两端完整语义哈希一致；新增API≤2、构造≤12，无未知在途。API完整性、候选静态合法、求解可行和跨平台一致分别判定，不把失败统称“生成无效”。输出含完整JSON与 `results.csv`。这里没有搜索，因此不生成伪搜索曲线或性能结论。

若全部通过，可继续准备正式方案A搜索与同条件EoH对照的来源绑定及预算。正式H集合、完整训练数据、EoH算法和H构建成本仍按独立研究协议处理；不能把这三项工程任务充作正式搜索。TSP还需冻结有来源的LKH参照；此轮不新增OBP任务。真实运行失败后先分析已有材料，不自动另开一轮。

源码包在 `/Users/DDXQL/Developer/transfer-outbox/fjsp-state-a-flow-20261112.zip`，附SHA-256；本轮仅已打包与本地核验，尚未上传或备份，也不删除源文件或运行依赖。Windows可用PowerShell `Get-FileHash` 与旁边的SHA文件核对；这个发布包不含未来运行结果，不能当作实验结果备份。
