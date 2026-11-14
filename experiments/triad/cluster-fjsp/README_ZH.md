# FJSP优先：本次集群启动交付

先启动FJSP EoH seed501；FJSP U只读纳入旧501，新502／503随后准备。TSP LKH和OBP数据／H独立列缺，不阻塞FJSP。本轮代码与本地合成检查完成不等于已经部署、计算节点通过或RUN_READY。

## 已采用与仍缺什么

| 项目 | 当前状态 |
| --- | --- |
| 每组3次、501／502／503、每种子1000演化、初始化另计 | 用户已采用，不再询问 |
| 旧FJSP U501 | 已只读登记完成摘要／曲线；不复制checkpoint、不重跑；不代表批准新U预算 |
| FJSP EoH N10、初始化HTTP上限20、累计1020、每槽1次、无重试、同模型／V5 | 用户已采用；科学参数不再待定 |
| EoH初始化 | 原生有限初始化可能未用满20就结束；重复源码或同分按原生置−inf，项目新增恰N个finite成员门槛；不足10则停止，不继续补员。不称原版EoH必须如此 |
| 评分／来源 | 完整train21原始成本、LB_v5、J最小化及稳定ID选优；旧负Fitness保持历史身份；同演化尝试不等于包含H构建的等端到端成本 |
| 资源建议 | 首份EoH 2CPU／2048MiB，128C_02／wz／normal，12小时一段、1260秒排空、原窗口48小时。依据已验收旧快照，仍需当前inventory核对 |
| 凭据 | 已有集群路径/public2/home/qiuqian/.config/hdl/leafapi.key；只检查lstat所有者／600／普通文件，不读值。模型只在计算节点按明确授权读取 |
| 当前账户 | 用户确认仅本人使用；不自动推断本人其他设备／旧作业停止，不复制过期valid_until |
| 仍缺 | 当前远端环境／作业／配额／凭据元数据和部署核验；操作者明确的全设备排他时段；第一阶段用户手动4次验证结果 |

当前没有有效SSH复用会话，本轮尚未取得新远端inventory，不反复尝试失败的非交互登录。旧CPU32／normal和Python3.12.10快照只作推荐依据，不能当今天的空闲资源。查询失败、配额空白均为未知。

## 1. 一条检查，一次交互部署

Mac终端使用原portable Python3.12；画图用的Python3.13不用于冻结H身份校验。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py check-only
```

下一条集中一次SSH交互（仍可能依次提示跳板和个人账号密码），完成当前只读inventory、不可变R5包上传／哈希核验、现有环境导入、配置和训练资产准备、旧501回执导入及首份check-only。它不请求模型、不求解、不提交Slurm。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py prepare
```

如果操作者能够保证未来72小时本人其他设备及旧脚本都不请求同一账户，可在该prepare命令末尾显式加`--confirm-exclusive-account --exclusive-hours 72`。这只写新鲜的排他确认和配置，不发请求。不能保证时不加，部署仍可继续，正式启动保持拒绝。此时限为覆盖48小时原搜索窗口及排队余量的工程建议，不因恢复重新延长。

回执在reports/cluster-launch-20261114/prepare-*；latest-preparation.json保存精确remote_batch、batch_name、远端目录和凭据元数据。当前默认远端为/public2/home/qiuqian/hdl-deploy/triad-six-groups-20261114-r5p1，环境仍为/public2/home/qiuqian/hdl-envs/portable-v2/bin/python，不默认安装。

## 2. 第一阶段：两个独立作业共享API总并发1

本项是待用户手动批准的独立工程预算，当前没有真实发送许可。以下命令一旦由用户执行，才批准这一阶段最多4次物理发送：两个独立sbatch作业各最多2次，每槽1次、无重试，真实求解0。每个作业1CPU／1024MiB／30分钟，合计2CPU／2048MiB。先用两个实际作业检查同目录可见性、O_EXCL互斥及未知锁保留，再允许模型发送。实际若同节点，只报告同节点双作业；只有不同实际主机通过才报告本次跨节点结果。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py probe-submit --phase 1 --submit --approve-sends 4 --confirm-exclusive-account --exclusive-hours 2
```

上述2小时确认也须由操作者保证；排队过久导致不足以容纳300秒请求时，作业停止而不延长确认。提交回执未知保留预留，不自动重提；作业及文件都在集群，Mac合盖、SSH断开不影响已被Slurm接受的作业。

代表性输入分别是实际EoH I1 Prompt（823字节）与冻结U初始化Prompt（16750字节），不是hello；输出上限均8192 token、总超时300秒，模型／供应商／V5和研究一致。每作业重复两次相同类型负载，不做候选评价、不混入研究种群或冠军。每阶段费用未知，不宣称金额硬上限。保留请求预留、确认发送、响应时刻、共享账本事件顺序、在途峰值、用量／未知项、HTTP状态与现有V5可得网关信息；V5白名单不导出RPM／TPM头，缺失就写未知，不另发查询请求。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py probe-status --phase 1
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py probe-fetch --phase 1
```

通过要求：两个实际Slurm身份及提交回执对应、4次确认发送且无未知、共享峰值1、正常结束且无STOP／在途。首个429、鉴权、协议或未知错误即停止新分配，结算已在途；不重试、不补预算、不靠超时解锁。工程批次另持有同一集群账户generation.lock，防止与正式搜索交叠；只有全部成功已结清才释放自身锁，失败保留待核查。跨Mac／其他框架仍靠操作者排他安排，不宣称已实现全设备共享门禁。

## 3. 第一阶段通过后，启动首份FJSP EoH

确认prepare的首份缺项为空、现有集群凭据可读及账户时段仍覆盖原窗口。以下是用户手动提交命令，原累计上限1020；每候选21例、每例首解＋复核，因此全搜索理论求解上限42840，不是本轮额外执行量。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py submit-first --submit --allow-api --allow-solves --approve-budget 1020
```

若先做一次有限真实求解验收，可在同一命令末尾加`--pause-after-attempts 1 --approve-segment-solves 42`。它占这次EoH原初始化的第1次尝试，模型最多1次、首解和复核合计最多42次，结清后paused；解析失败时求解可为0。不新开实验，不把这1次藏到1020之外。继续时用原目录与原上限resume，不重新初始化。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py query
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py pause
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py resume --approve-budget 1020
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/launch_fjsp.py fetch
```

只有首次部署和手动提交需要Mac／SSH；作业本身、依赖、密钥引用、日志、预算、检查点和暂停控制均在集群。账户门禁是整个运行段排他，EoH仍串行反馈和原随机过程；没有为并发改成异步演化或多候选EoH。

## 4. 可选项与边界

第一阶段通过后，若确有需要才手动另批准第二阶段：把probe-submit／status／fetch的phase改为2，仍需显式approve-sends 4及新鲜排他确认。两轮各两个同时在途，最多另外4次；先前4次不重用或退款，总方案上限8次。未启动第二阶段不影响首份EoH。每批成功只支持指定负载、时段和实际拓扑，不推定供应商最大并发／RPM／TPM，不循环压测找上限。

当前正式搜索之间仍不并发：batch和slurm串行保护保留。shared_probe的准入只用于工程验证，尚未接入两个正式独立搜索。有限serial_queue.py／serial_queue.sbatch是单作业备用薄层：只调用原entry，只有上一个应用completed且无未知／writer才进下一个；退出码0或afterok不足。暂停、失败和未知停止，恢复沿原总预算及各运行原窗口。未获得当前集群实证，不作为首份启动前置；4CPU／4096MiB包含最大3CPU子运行及监督开销，条目最多5个且总额度须用户显式确认。新U配置尚未采用时队列会拒绝，不自动借EoH批准。

首批当前仅本地合成检查通过，实际远端、两个Slurm作业及真实发送均未发生。r3／r4p1原包和旧验收614258／614474保留，不重跑固定H基线，不把本地双进程Mock称作集群跨作业／跨节点通过。
