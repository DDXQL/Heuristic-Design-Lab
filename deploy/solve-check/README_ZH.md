# 有限集群真实求解验收：含复核最多16次

本轮只准备一个独立工程验收。公共执行器和真实评价器继续使用`923781f05686f1899c24fd7899fb3bc6b1df1562`原字节，复用614258已验收的集群环境与基础目录，不重部署或重跑Mock。Mac长实验、模型账户门禁、锁和检查点均不修改。实现与离线检查由代理完成，真实求解和Slurm提交由用户手动执行。

## 身份与输入

集中配置为[plan.json](plan.json)，身份`fjsp-two-U-two-I-serial-parallel-20261113-r1`。

- 基础目录：`/public2/home/qiuqian/hdl-deploy/fjsp-noapi-923781f-20261113-r1`，保持不动。检查其原release清单SHA及各文件哈希。
- 新验收目录：`/public2/home/qiuqian/hdl-deploy/fjsp-real-solve-923781f-20261113-r1`。
- 依赖环境：`/public2/home/qiuqian/hdl-envs/portable-v2/bin/python`，不重新安装。
- 新叠加包：`/Users/DDXQL/Developer/transfer-outbox/fjsp-real-solve-16-923781f-20261113-r1.zip`，只含本轮入口、配置和外壳，不复制公共执行器、数据、旧运行或Mac结果。
- 结果固定写入新验收目录的`run/`。该目录存在即拒绝再次运行，作业认领也只允许一次；新作业号不产生新预算。没有自动恢复、重试、补跑或requeue。

从原train21清单按声明顺序取前两项，不读取成绩或耗时作选择依据。只解析这两个实例和原冻结10H；不访问validation/test，不重评完整固定H基线。

| 实例 | 原文件SHA-256 | 静态LB_v5 |
|---|---|---|
| Behnke1.fjsp | d3902d14d6a27f0d335bbb556ee088ba9103e738dc3f20d6d3feb74eb42c2ad1 | 70.0 |
| Behnke2.fjsp | 5ac8ba43854c66383f0f0f5b72734766033bd3f7104fb99bff5995bf3e64ba6d | 75.0 |

两个U都是本次固定手写的工程输入，不是搜索冠军，也不根据已有成绩挑选：

- `constant_H0`：始终返回冻结编号0。
- `state_switch_H0_H1`：构造进度小于0.5时选H0；之后若H1累计使用次数少于H0则选H1，否则选H0。读取完整v3状态中的构造进度和逐H累计次数，纯选择语义不变。

状态为`common-state-a-v3-fjsp`、U ABI为`pure-routing-state-a-v3`，沿用10项共同状态及4类逐H历史信息；4类逐H信息各有K项，不把它误称为总共14个标量。没有增删字段、状态消融或离线成绩先验。

## 准确调用次数与停止规则

原`core/routing_evaluation.py`的`evaluate_task`为每个U启动一个spawn子进程，实例在该进程内串行。其`_worker`在每个实例上恰好调用两次`routing_fixtures.solve`：首解一次、独立复核一次。两遍及完整结果接收共同占用该实例的30秒期限；全部结果返回后另有2秒正常退出宽限。

| 模式 | U数 | 实例数 | 每实例实际求解 | 小计 |
|---|---:|---:|---:|---:|
| 串行，1个评价子进程同时在途 | 2 | 2 | 首解1＋复核1 | 8 |
| 并发，2个评价子进程同时在途 | 2 | 2 | 首解1＋复核1 | 8 |
| 总上限 | | | | **16** |

这里是4次完整候选评价、8个候选实例行、最多16次原生求解调用。没有在16次之外另加一次复核、预热、校准或补齐。两种模式不使用评价缓存，确保实际比较评价执行路径。每个新评价预留4次；并发波次先整体预留8次并同步落盘，再启动两个子进程。原生每个子进程最多4次调用，计量包装器在第5次调用进入原函数前拒绝，且不自行求解。

原评价器已经验证首解/复核一致与可行性。父协调者还对保存的排程调用独立合法性检查器；它只检查已存工序、前序和机器区间，不调用构造器或H，不增加求解次数。

任何候选非法、超时、复核不一致、源码变化、基础设施不确定或跨模式结果不一致，整个验收有限停止，不再开始后续波次。已预留的并发波次完成有限收尾，全部预留保留计账。确认开始、完整完成、失败与预留未核实分别记录；未知不填0、不释放成可重跑额度。停止后保留本轮锁和原始证据，不能删锁、换目录或重新提交来重置16次上限。

## 资源和观测

申请**3CPU、2GiB、10分钟、单作业、单任务、no-requeue**：控制进程及最多2个真实评价子进程，底层数值库线程均为1；`srun`显式取得3CPU。应用在300秒的接收窗口内按剩余最坏实例期限决定是否开始下一波次。单个完整U含两个T30实例及退出宽限，串行/并发的等待边界来自现有评价器，不以Mock耗时推断真实吞吐。

包装器只观察原生`solve`调用，记录每次首解/复核的PID、实例、U、开始/完成/失败时间、进程CPU和峰值RSS，不改变H、状态、排程或评分计算。使用原生命周期回执记录真实子进程同时在途的峰值，必须观察到串行峰值1、并发峰值2。保存控制进程CPU/RSS、实际Slurm资源及总墙钟。每个子进程的RSS峰值不是整作业总内存峰值；Slurm MaxRSS为空/0时照实保留，不据此声称真实峰值为0。

比较全部U/实例的合法性、原始Cmax、LB、J、排程序列及首解/复核语义哈希，逐项要求串行/并发相同。结果包括`acceptance.json`、`per-instance.csv`、`physical-solves/*.jsonl`、四份原生评价与生命周期回执、预算检查点和失败记录。原评价器保存的子集fitness属于工程回执，不作为正式train21成绩，不排名、不选冠军、不宣称算法收益。

本轮只验证**单实验内部**真实评价并发。多个独立作业、多个种子、Job Array和跨作业性能未由本轮验证。模型请求为0，不需要占用Mac生成型作业的账户排他门禁。专用API保护在父进程及spawn子进程中禁止客户端导入、网络及凭据读取。

## 最少命令：都在Mac终端执行

先上传这个小叠加包并作静态核验，不运行求解：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/solve-check/control.py stage
```

沿用之前的交互SSH连接方式，只核验既有基础版本、上传新叠加文件并运行check。check只验证输入/源码、U静态合法性和LB，实际求解0，不重新执行Mock。结果自动保存在`reports/cluster-solve-check-20261113/latest-stage.json`。

用户确认计划后，手动提交一次，显式批准含复核的完整16次上限：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/solve-check/control.py submit --partition 128C_02 --submit --approve-solves 16
```

查询：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/solve-check/control.py query
```

取回（自动读取本轮提交的作业号）：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/solve-check/control.py fetch
```

取回先确认队列与终态，再将本轮结果和日志打成一个ZIP下载，核验远端SHA、ZIP路径及逐文件清单。失败作业也可取回诊断，但不会标为验收通过；没有重求解或重提交。原614258记录和文件不动。

## 当前验证边界

已完成：静态调用链核查、两个U静态验证、两例身份/LB核验，以及合成回执的16次预算、同计划串行/并发比较、失败停止、重复身份拒绝、隐藏第5次调用拒绝、API/网络/凭据保护检查。合成回执显式标记`SYNTHETIC_OFFLINE_ONLY`，实际求解0。

尚未上传本轮叠加包、尚未提交真实验收、尚无实际求解或真实并发/耗时/内存结果。614258只作既有环境与部署基础，不冒充本轮真实求解通过。正式研究配置、正式长实验或多作业并发均未因本工程包获得授权。

ZIP附同名`.sha256`和`release.json`。Linux可用`sha256sum -c`核验；Windows可用`Get-FileHash -Algorithm SHA256`比较同名文件。已打包不等于已传输或已备份。
