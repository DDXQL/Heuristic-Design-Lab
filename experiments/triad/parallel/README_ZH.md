# 两个独立种子同时运行：R6准备交付

本版从R5p1源码7edeeb9建立，公共`code/`与冻结U入口不变。当前仅本地离线准备；没有上传、真实模型请求、真实求解或Slurm提交。616362仍使用原部署，不能接入这个批次，也不更换它的源码、配置或门禁。其最新远端进度仍未知。

## 三层并发与接入位置

每批明确选择两个新种子502／503，各对应一个独立sbatch作业。每搜索模型并发1，共享API总并发1；一个搜索做CPU评价时，另一搜索可以请求模型。EoH每搜索评价并发1，U每搜索保留原评价并发2。不同搜索不共享父代、种群、随机状态、检查点或预算；各自的原生反馈和U同批结算顺序不变。

`shared_admission.py`复用已有probe的O_EXCL声明、互斥事务及双作业文件系统检查，增加固定成员、FIFO请求队列、逐种子／累计硬上限和可恢复的批次账本。`entry.py`实际选择受控EoH传输；冻结U通过`shared_frozen.py`进程内包装原`routing_transport.StrictNonstreamTransport`，原协调器、实际Prompt与求解器保持原样。Mock也经过同一准入层。`Shared_execution.json`绑定配置、原协议、共享清单和叠加源码；缺少原清单的调用会被拒绝。

批次必须先以O_EXCL取得原账户`generation.lock`，之后两个成员的内部运行锁只负责各自写入和恢复。全批仍排斥R5p1旧作业／旧probe。因此只能在616362等旧生成任务已确认结清、原账户锁正常释放后激活真实新批次，不能删锁让它们与旧作业混跑。Mac和其他设备仍靠操作者明确排他安排；本版没有全设备在线网关。

请求许可在完整响应返回后释放，评价不占API许可。FIFO在候选返回时间不同的情况下只决定请求先后，不改变各搜索的随机计划。取得空闲许可后用单调时钟等待全局最小间隔，避免依赖跨节点墙钟同步。默认间隔1秒是工程设置，不是供应商官方RPM／TPM。官方并发、RPM、TPM和金额硬上限仍未知；一次模型错误就停止新发送，既有在途仅结清，不重试或退款。

## 预算与资源

| 批次 | 研究采用状态 | 每种子初始化／演化／累计请求 | 两种子累计请求上限 | 资源建议合计 | 新版真实前缀验收上限 |
| --- | --- | --- | --- | --- | --- |
| EoH502＋503 | N10等研究参数已采用；新执行方式仍待集群验收 | ≤20／1000／1020 | 2040 | 4CPU、4096MiB | 每种子1次，合计2次请求、含首解和复核≤84次求解 |
| U502＋503 | 原501设置可兼容复用；新种子预算及研究采用仍为草案，入口拒绝 | 草案≤20／1000／1020 | 草案2040 | 6CPU、4096MiB | 采用后每种子首个整批2次，合计4次请求、含复核≤168次求解 |

EoH每作业2CPU、2048MiB；U每作业3CPU、2048MiB。单作业12小时、原累计窗口48小时，仍用128C_02／wz／normal。为覆盖共享队列等待，EoH排空1620秒，U排空1980秒；这些资源为待手动提交时确认的工程建议。单次排队等待最多360秒；超时保留预算并停止，不抢占旧许可。

满额真实求解理论上限每种子42840、每对85680；解析失败、重复或缓存命中会减少求解，不能当已发生次数。上表真实前缀全部计入同一次搜索的原1020，不是额外请求。失败、重复、排队预留、未知及未用完的初始化额度各自保留，不借给另一种子。历史H构建、既有210固定H结果和已关闭614258／614474不重跑。

## 本地检查与已知边界

本地执行：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-two-searches-20261114/experiments/triad/parallel_tests.py
```

检查两进程、两个原生协调器、每种子并行／单独轨迹一致、FIFO／间隔／预算、单独暂停恢复和未知保留。EoH用train21元数据与合成分数；U用一个训练实例的只读元数据与原有合成评价，覆盖一个完整原生代及下一代计划，不运行该实例的真实构造。U公共Mock在21个重复合成分数上有精确浮点均值校验问题，本轮不修改公共校验或将Mock成绩解释为真实成绩。

冻结U若在初始化批次中间用有限前缀截断，会遗留未执行的planned初始化槽，恢复轨迹不同。新版真实入口只允许初始化的“下一个完整批次”有限边界；首次为2次，拒绝前缀1。检测到旧的planned初始化遗留则拒绝恢复，不修账或跳过。正常暂停沿原执行器整批结清，离线比较使用U边界2；EoH边界1。公共代码问题另记，不改当前501或616362。

单个正常暂停只释放该搜索的活动登记，另一搜索可继续。单独恢复沿原目录、原种群、原随机状态、原累计请求和原Run_clock；批次共用账户锁保留。任一未知发送、提交或基础设施失败会保留许可／回执并停止全批新发送；另一个搜索可以结清已有评价，不能继续发新模型请求。没有TTL解锁或自动补跑。

`status`总是列出两个成员，包括未开始、失败和停止；不会只输出最好一次。最终三次研究汇总还需只读纳入已有501的对应记录。本版并行准备不代表三次都已启动或完成。

## 未来联网后的最短手动验证

以下远端路径是R6预定安装位置，当前未上传。网络恢复后先在Mac终端手动部署新目录；原R5p1不覆盖。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-two-searches-20261114/experiments/triad/cluster.py stage
```

在已登录的集群终端进入新目录。沿用原Python环境，不安装依赖。

```bash
cd /public2/home/qiuqian/hdl-deploy/triad-two-searches-20261114-r6
P=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
"$P" -s -B experiments/triad/parallel.py mock-plan --directory plans/two-search-mock-acceptance
"$P" -s -B experiments/triad/parallel.py activate --manifest plans/two-search-mock-acceptance/Shared.json
"$P" -s -B experiments/triad/parallel.py submit --manifest plans/two-search-mock-acceptance/Shared.json --submit --settled-prefix 1 --approve-segment-solves 0
```

这一对实际Slurm作业均为Mock：API0、求解0、不读取凭据；合计4CPU／2048MiB，每作业30分钟。使用私人Mock门禁，不占原真实账户门禁；资源允许时可与616362并存。先由两个实际作业检查同目录可见性、O_EXCL和未知锁保留，再运行原生Mock。不能把同节点双作业写成跨节点验证。

```bash
squeue -u qiuqian
"$P" -s -B experiments/triad/parallel.py status --manifest plans/two-search-mock-acceptance/Shared.json
"$P" -s -B experiments/triad/parallel.py certify --manifest plans/two-search-mock-acceptance/Shared.json
```

`certify`必须匹配两个真实数字作业ID、终态COMPLETED／0:0、两份已暂停前缀和实际主机信息。本地双进程不能签出真实Slurm证明。

## 未来独立EoH502／503的有限前缀与正式并发

先确认616362已安全结清且不再排队或运行，以及其他设备／脚本停止使用账户。下列配置生成和激活不请求模型。72小时排他只在操作者明确执行带确认的plan时生成新时段；恢复不延长它。

```bash
"$P" -s -B experiments/triad/review.py --review experiments/triad/parallel/profiles.review.json --output plans/parallel-profiles --groups fjsp-eoh fjsp-u
"$P" -s -B experiments/triad/parallel.py plan --spec experiments/triad/parallel/two-eoh-502-503.pending.json --directory plans/two-eoh-502-503 --confirm-exclusive-account --exclusive-hours 72
"$P" -s -B experiments/triad/parallel.py check-only --manifest plans/two-eoh-502-503/Shared.json
"$P" -s -B experiments/triad/parallel.py activate --manifest plans/two-eoh-502-503/Shared.json --confirm-exclusive-account
```

确认缺项为空后，以下手动提交会真实请求模型和评价，不能在本轮离线阶段执行。它确认每种子原1020、合计原2040；实际这一段仅每种子1次，含复核最多84次求解，解析失败时可为0。

```bash
"$P" -s -B experiments/triad/parallel.py submit --manifest plans/two-eoh-502-503/Shared.json --submit --allow-api --allow-solves --approve-requests 2040 --settled-prefix 1 --approve-segment-solves 84
"$P" -s -B experiments/triad/parallel.py status --manifest plans/two-eoh-502-503/Shared.json
"$P" -s -B experiments/triad/parallel.py certify --manifest plans/two-eoh-502-503/Shared.json
```

两段均结清且新路径有限验收通过后，下面手动恢复两个原目录，才开始余下搜索。两个独立搜索同时存活、共享API1，未开启API2。

```bash
"$P" -s -B experiments/triad/parallel.py resume --manifest plans/two-eoh-502-503/Shared.json --submit --allow-api --allow-solves --approve-requests 2040
```

单独暂停索引0，索引1可继续；只恢复索引0须等其Slurm段已结束、应用paused且无未知，仍用原总额度。初次有限验证必须两个作业共同启动以完成文件系统检查。

```bash
"$P" -s -B experiments/triad/parallel.py pause --manifest plans/two-eoh-502-503/Shared.json --member 0
"$P" -s -B experiments/triad/parallel.py resume --manifest plans/two-eoh-502-503/Shared.json --member 0 --submit --allow-api --allow-solves --approve-requests 2040
```

U的对应spec已提供，但采用草案前check-only／submit会报告协议待定；不能仅把EoH命令换成U来绕过采用。采用后U有限首段需前缀2、合计求解上限168；其余恢复机制相同。

## 查询、取回及吞吐

复用原Mac查询／取回工具。下面以EoH502为例；503只将seed改为503。批次Batch.json保留全部运行映射，单独作业及提交回执不混淆。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-two-searches-20261114/experiments/triad/cluster.py query --batch-name two-eoh-502-503 --experiment fjsp-eoh --seed 502
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-two-searches-20261114/experiments/triad/cluster.py fetch --batch-name two-eoh-502-503 --experiment fjsp-eoh --seed 502
```

fetch保留原ZIP／成员哈希核验，并附共享清单、账本、停止原因、提交及文件系统证据的时点快照；一个作业取回不表示整批完成。不得把本地Mock或短工程probe耗时外推正式吞吐。账本记录每次API等待、保守间隔与线耗时，原评价回执保留求解CPU／墙钟／内存；未来只用实际相同前缀做串行与并行对比，所有额外请求／求解须另行声明并获授权。
