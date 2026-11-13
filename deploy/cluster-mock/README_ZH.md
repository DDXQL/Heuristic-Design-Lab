# 冻结执行器的无API集群验收

本轮只部署文件、核验环境，并准备一个由用户提交的CPU Mock作业。公共执行器及状态继续使用`923781f05686f1899c24fd7899fb3bc6b1df1562`的原字节，没有修改Mac运行中的工作树、检查点、锁或账户门禁。

原工程ZIP保留不动。精简包从该ZIP逐文件核验后生成，保留公共源码和23份冻结H/数据清单资产，移除历史报告、旧运行结果、旧正式入口及其余不需要的材料。正式`research.pending.json`逐字节保留、仍未授权。H_frozen中的来源信息是冻结资产的一部分，不改写。精简包不包含本地账户门禁文件、运行锁、真实凭据或虚拟环境。

真实路径：

- 本地部署树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113`
- 部署包：`/Users/DDXQL/Developer/transfer-outbox/fjsp-cluster-noapi-923781f-20261113-r1.zip`
- 包哈希：同目录`fjsp-cluster-noapi-923781f-20261113-r1.zip.sha256`
- 远端新目录：`/public2/home/qiuqian/hdl-deploy/fjsp-noapi-923781f-20261113-r1`
- 复用环境：`/public2/home/qiuqian/hdl-envs/portable-v2/bin/python`
- 本地返回材料：部署树的`reports/cluster-noapi-20261113/`

## 下一条命令：在Mac终端执行

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/cluster-mock/control.py stage
```

该命令首先建立一次交互SSH连接，经`custom@222.201.144.188`到`qiuqian@110.1.2.1`。需要用户输入密码/完成认证的位置就在这里；密码由SSH终端处理，不写入脚本或日志。后续检查和传输复用同一连接，不循环重试失败认证。

操作依次为：本地ZIP哈希检查→远端只读盘点→上传ZIP及SHA→核验并解压至新目录→登录节点轻量导入检查。默认不安装依赖、不提交Slurm、不执行Mock计算或正式求解。已存在且身份不同的远端目录/ZIP会拒绝覆盖。

结果自动写入`reports/cluster-noapi-20261113/latest-stage.json`，详细材料在其中的`local_evidence`路径。回来告知“stage完成”即可继续读取，无需手抄完整输出。中途失败也保留已完成步骤；`uploaded`、远端哈希和导入状态分别记录。

## 登录节点与计算节点边界

| 位置 | 允许的本轮操作 |
|---|---|
| 登录节点 | 身份、Python/依赖版本、glibc、目录权限、df/quota、当前分区、账户/QOS和本人队列资源盘点；ZIP/源码/输入哈希；轻量导入及未冻结协议门禁检查；用户提交和查询 |
| 计算节点 | 通过Slurm运行小型Mock的串行/并发对照、独立子进程回执、日志、检查点、固定前缀暂停和同预算恢复；CPU3、内存1GiB、10分钟、单任务、no-requeue |

盘点命令被拒绝、字段不支持、输出截断或配额为空时，保留未知，不解释为无限资源。队列实际CPU汇总与账户/QOS原始证据分别保存。Mock资源是本轮工程验收参数，不是正式长实验的批准资源；Slurm仍执行账户、分区和合计资源限制。历史可用的`128C_02`仅为候选，提交前检查其当前状态；若盘点显示不可用，先据实际证据调整提交参数。

## 用户手动提交、查询和取回

确认stage材料和分区/账户资源允许后，在Mac终端手动提交一次：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/cluster-mock/control.py submit --partition 128C_02 --submit
```

没有`--submit`只打印远端命令，不提交。实际脚本为`deploy/cluster-mock/mock.sbatch`，不是正式搜索的cluster.sbatch。只提交一个作业，无Job Array、无requeue、无自动补交。提交前持久认领，重复调用拒绝；未知提交保留认领，先查询，不删除认领或旧锁来重提。实际账户/QOS沿用已有默认关联，不重新安装环境或硬编码节点。

查询（作业号从本轮提交回执自动读取）：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/cluster-mock/control.py query
```

取回（同样无需手填作业号）：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/deploy/cluster-mock/control.py fetch
```

取回先查本人队列与`sacct`，确认本作业退出活跃队列且有终态记账，再复制本轮结果和stdout/stderr到新的本地目录。它不删除远端文件、不覆盖旧结果、不重求解；逐文件核验结果清单。只有Slurm为COMPLETED/0:0、应用回执中的job_id匹配且Mock与隔离检查通过，才标记`compute_node_verified=true`。队列中查不到作业号本身不代表成功或API失败。

## 验收内容与隔离

专用`accept.py`不提供真实模式或凭据参数。导入冻结执行器前安装`guard.py`；父进程和spawn子进程均使用禁用的模型客户端桩，禁止真实客户端/正式评价器导入，阻断网络、`.key`、`.env`、`.ssh`和账户门禁文件访问，并清除相关密钥环境变量。原公共源码只读，未做补丁。Mock采用内置合成实例与人工成本回执，不执行H或训练构造，不读取train21求解。

三种小型路径各为2次合成初始化＋7次合成演化尝试：串行、并发、暂停恢复。检查固定计划结果一致、评价调用实际重叠、独立子进程、检查点/日志/CSV/冠军/曲线导出、暂停时释放本轮工作锁、恢复继承原时钟与预算。所有分数均标记Mock，不是科研结果。分区信号或强制终止不冒充该内部安全暂停检查通过；若作业中断，保留材料并报告失败，不自动续交。

`research.pending.json`预期返回“协议未冻结”。专用check将其记录为`unfrozen_expected_rejection`，与Python/依赖/路径/源码错误分开。不会为了通过检查填入研究参数或打开正式请求开关。

Mac正在请求模型不会阻止文件部署或本轮CPU Mock；本轮不申请生成型作业账户排他权，也不访问/修改Mac门禁。未来提交独立正式实验仍须另行具备冻结配置、明确请求与评价额度、账户及全部同账户设备的API并发安排、新目录身份、实际集群资源和相应真实入口验收。当前Mock通过不等于正式搜索获准或可与Mac同时发请求。

## 当前证据阶段

本地：包清单/源码不变性、解压导入、无API负向检查、串行/并发/暂停恢复和取回模拟已检查。远端：此前非交互跳板认证失败，尚未上传或核验。计算节点：尚未由用户提交，本轮没有真实Slurm作业。实际变化以`latest-stage.json`、`latest-query.json`和`latest-fetch.json`为准，未发生的步骤不标完成。

Windows归档核验可运行`Get-FileHash`检查ZIP的SHA-256，并与同名.sha256比较；本地已打包不等于已传输、已备份。
