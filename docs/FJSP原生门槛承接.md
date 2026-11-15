# FJSP单规则EoH原生门槛承接

用户于2026-11-15明确将`native_N_finite_or_fail`改为`native_EoH`，用于全部三次独立重复501、502、503。目标种群仍为10；原生代码重复或均分相同的候选仍被置为负无穷，父代选择仍过滤负无穷并按秩有放回抽样。不额外生成来补齐10个有限成员。这项修订是在观察到初始化门槛失败后采用，报告应保留该时间顺序。

原作业618885、618886及旧协议保留`initialization_incomplete`、FAILED/2:0。新目录是同一次逻辑搜索的协议修订承接，不是新的独立重复。新协议包含父协议、原始检查点、请求身份、原时钟和变更记录。旧目录不写新phase；新目录通过显式导入形成`prepared`，游标已为10，首次新任务为E1。执行仍使用现有公共循环、原生种群、共享准入、V5客户端和真实评价器。

|项目|种子501|种子502|
|---|---:|---:|
|原生种群记录|10|10|
|当前可选有限父代|8|9|
|已用初始化请求|10|10|
|已用物理求解，含独立复核|378|420|
|原累计请求上限|1020|1020|
|账面未用请求槽|1010|1010|
|尚需演化尝试|1000|1000|
|本次最多新增请求|1000|1000|
|本次新增求解上限，含复核|42000|42000|

两份原时钟截止均为2026-11-17 18:59:15（UTC+08，原始小数秒分别保留），不会从承接时间重新计时。原账户排他确认到2026-11-18 18:57:54（UTC+08），不续期。初始化未用的10个请求槽不会被用来补成员或追加演化。每槽最多一次请求，失败、重复和未知发送均不退款，不自动重试。初始化最佳J仍只是初始化结果，不能作为已完成1000次演化的成绩。

旧终态的随机状态已前进两个父代抽样，但没有对应的请求或结算。`P000_initial.json`保存抽样前状态。离线重放这两个按秩选择后，与原终态随机状态逐项一致；承接使用抽样前快照，得到501的首对父代SLOT-0000001/0000004，以及502的SLOT-0000003/0000004。原生代数仍为2，不重复执行初始化后的生存选择。

离线检查用原始记录比较了64步算子、父代、随机状态及原生登记/生存选择，并检查序列化后继续的一致性。另以种子503的纯Mock核对从空种群独立初始化、10次初始化后进入12次演化、暂停恢复一致。它不执行H、不请求模型、不证明新版已在计算节点运行。原20次请求及798次求解与早先2次请求/84次有限前缀有包含关系，不重复加账。

## 上传与手动继续

下一条在**Mac终端**执行，只上传并核验R9包、检查登录环境导入；不读密钥值、不提交、不请求模型、不求解：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-native-continuation-20261115/experiments/triad/launch_native.py stage
```

上传成功后，如没有已登录的集群终端，在Mac终端登录一次：

```bash
ssh -J custom@222.201.144.188 qiuqian@110.1.2.1
```

然后在**集群终端**执行：

```bash
cd /public2/home/qiuqian/hdl-deploy/triad-fjsp-native-continuation-20261115-r9
bash experiments/triad/continue_native.sh --submit --allow-api --allow-solves --approve-requests 2040
```

此脚本遇错即停止：核验两份已结算父运行及全部提交回执，创建承接配置和新目录；使用原R8的`close`正常结束旧批次占用；登记一次性承接并激活新批次；复用`parallel.py`手动提交两个独立作业。无自动重新提交。任何错误都保留现场，不整段重复执行，也不删除账户门禁。若之前已关闭旧批次或已有未结算登记，需要先读取回执判断，不靠重试处理。

两份申请仍各为2CPU、2048MiB、12小时段，总计4CPU、4096MiB；数值线程1，每种子模型并发1、评价并发1。两个搜索共享整个账户API并发1，保留原排他范围和请求间隔，API2未采用。已有真实共享准入证据仅覆盖node15同节点，继续作业固定此节点，并在新路径首次计算节点运行时重新做文件系统前置检查；没有增加付费前缀验收。新`Acceptance.json`明确写为“继承原准入证据”，`real_dispatch_path_verified=false`，不冒充新的实际验收。

## 观察、暂停、恢复与取回

以下继续在**集群终端**，设置一次变量：

```bash
HDL_P=/public2/home/qiuqian/hdl-envs/portable-v2/bin/python
HDL_M=plans/native-eoh-501-502/Shared.json
"$HDL_P" -s -B experiments/triad/parallel.py status --manifest "$HDL_M"
```

返回的两份job_id是新的继续段，不能沿用618885、618886查询。`status`读取已结算计数；Slurm运行/排队状态用`squeue -u qiuqian`查看。报告同时显示原累计请求与本段新增请求，保留原成本和失败来源。

若需安全暂停两份运行：

```bash
"$HDL_P" -s -B experiments/triad/parallel.py pause --manifest "$HDL_M"
```

仅当两份都已`paused`、Slurm已终态且无未知请求、锁或STOP，才手动继续原预算：

```bash
"$HDL_P" -s -B experiments/triad/parallel.py resume --manifest "$HDL_M" --submit --allow-api --allow-solves --approve-requests 2040
```

如果一份已完成，另一份安全暂停，使用同条`resume`追加`--member 0`或`--member 1`，分别对应501/502；不得重跑已完成成员。截止时间仍不延长。未知提交或发送不能靠恢复命令跳过，保留现场后诊断。

两份最新作业均终态后，在**Mac终端**取回（复用既有导出、哈希核验和传输；查询全用户队列后精确筛选job_id，避免已结算ID退出squeue造成取回失败）：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-native-continuation-20261115/experiments/triad/launch_native.py fetch
```

结果保存于本树`reports/native-continuation-20261115/fetch-*`，不覆盖原失败取回目录。汇总须同时纳入两份及失败，并按新协议标记，不只报告最好一次。

## 准备状态与边界

当前仅完成本地实现、离线核对和冻结包。上传、远端承接核验、Slurm提交、新版计算节点运行均未发生。提交前仍需用户完成上述上传、确认其他设备继续遵守原账户排他安排，并通过远端原始字节、Slurm终态、无未知占用和原期限检查。没有待批准的算法参数；这些是执行前提，不能自动放宽。

种子503采用同一原生门槛，未来从空种群独立初始化；本次继续脚本仅承接501/502，不启动503，不共享它们的种群或检查点。三次重复的原总请求上限为3060；本次两份原上限为2040，已有20次包含其中。R9不启动其他问题、H构建或额外验收。
