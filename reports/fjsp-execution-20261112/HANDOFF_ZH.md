# FJSP单次U长演化工程交付

交付日期：2026-11-13（Asia/Manila）。目标是现有10H、train21、原10项加4类逐H历史信息的一次U长演化。已接入完整状态v3并完成Mock/离线检查；尚未形成可批准启动的最终研究配置，没有模型请求、H执行、构造求解、训练重评或Slurm提交。

唯一工程工作树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-execution-20261112`，分支`codex/fjsp-execution-20261112`。执行层由本树维护，集群和TSP复用同一提交。主项目的用户修改、旧工作树、运行、预算、锁和历史结果均保留。`cluster-deployment`只是普通目录，未将其上溯发现的用户主目录Git作为项目。

## 来源与接入

- [共享工程约定](https://app.notion.com/p/41604e0510d781f3bbdbd540917022f2)与[研究决定](https://app.notion.com/p/41204e0510d781f3a328c11ed393a1b1)分开读取。研究参数没有从旧脚本的1050次授权、种群或种子继承。
- 基线是已验收流程工作树的`169a129fdde9c5d27d8f73f2361809c5e3644681`。V5 wire及严格调用方字节保持不变；没有重新开展API诊断。原API2/累计求解12额度已用足，本批不继承。
- 状态来源为唯一状态工作树的`2d36f37aeb8a953c0ed2f9c0d63f86e943de7e1e`，本树接入提交`c2cea61`。新状态与U模块等5个版本文件逐字节相同；合并保留了修复版结果的member_sequence，并在TSP结果中同时保留v3 schema。没有另写状态计算。
- 正式路径使用`common-state-a-v3-fjsp`、`pure-routing-state-a-v3`，定义SHA为`07592addf12a3a1fea9761dd648dcc50dab257daa6c9c615336b6a4b66eed3df`。Prompt、U解析/编译和评价构造均接入v3；旧v1/v2保持原身份。
- 写作规则、用户级实验技能及来源哈希见[source-registration.json](source-registration.json)。新工作树中AGENTS、中文科研写作规范和humanizer-zh均可发现。

## 有限核查结果与实际改动

| 项目 | 核查与当前交付 |
|---|---|
| Python候选并发 | 原执行器已有两个独立线程池；CPU任务通过线程池启动独立spawn求解进程，实例在候选进程内串行。复用该等效多进程方案，没有另建搜索框架。新增合成进程回执验证进程隔离；本批没有实际求解 |
| API与CPU并发 | 独立配置、分阶段执行；Mock实际宽度检查和乱序结算一致性通过。首轮真实模式强制API并发1，不按CPU核数放大 |
| 多种子 | 配置可显式声明种子并按index选择，各自初始化、目录、预算、随机状态和检查点隔离；Mock已检查。首轮真实配置限制一个种子，不自动扩展独立重复 |
| Slurm | 原脚本主要为单作业，未核实已有完整Job Array能力。本轮复用原信号/等待模式交付单作业外壳；今晚未实现或提交Array |
| 全局API限制 | 未发现可靠的跨设备账户级限流与全局金额硬上限。本轮采用一个生成型作业的替代：参与部署共用账户锁及run注册，另须人工确认Mac、集群和所有同账户设备停止其他请求。文件锁不能自动约束其他设备或旧入口 |
| 未取回与重复风险 | 612916的关闭验收已在用户指定本地证据中；旧585019/585597只引用既有库存快照。新远端查询在跳板认证失败后停止，当前队列/账户排他状态未知，不宣称无在途。提交前认领、终态查询及未知认领禁止重提已实现并用假回执检查 |

公共文件以原`core/evolution_v1.py`为协调者，新增`core/execution_contract.py`、`core/execution_export.py`和`experiments/common/run_frozen.py`作适配。原父代覆盖计划、CROSS/MUTATE、代末生存机制继续复用；1000次按固定计划的尝试前缀结算，最后一代可为预先声明的前缀。同批父代、随机状态和去重/提交顺序固定，不按响应到达顺序选择。

每次先预留整个波次，落盘并同步检查点后才发送。同波次首个硬错误、第三个连续临时传输错误或未知发送会阻止后续已预留请求发送；取消项保留预留并标明not_sent，API失败率不把它计作物理请求。重复、非法程序和失败消耗尝试；默认不重试，不补演化成功数，不循环启动、不requeue。初始化规则必须单独冻结：支持固定N个槽位、失败后不补员；也支持显式选择原有“在初始化上限内收集种群”规则，未选择时不得启动。

新评分保存逐实例原始成本、LB和J，内部明确使用`fitness=-J`复用最大化排序；导出及冠军使用最小J、固定ID升序，从全部完整有效前缀候选选择，不只查看最后种群。任一实例失败，整条候选J为空；成功前缀只作诊断。

累计账本随原运行恢复。检查点绑定配置、源码精确哈希、H/数据/参考值、状态/ABI、随机状态、游标和种群。请求未知或评价未结算时保留预留和锁并阻止重放；硬API错误暂停且禁止直接恢复；连续3次临时传输失败安全暂停，不补发。旧来源成本只在归属字段列一次，不在每次恢复重复相加。费用未知保留null，没有已验证的金额硬上限。

## 实际配置与待确定项

研究草案为[research.pending.json](../../experiments/fjsp_long/research.pending.json)，状态为`draft_NOT_AUTHORIZED`，真实请求开关为false。它不是正式批准配置。Mock参数在[mock.json](../../experiments/fjsp_long/mock.json)，只用于工程检查。

| 配置 | 当前身份 |
|---|---|
| 演化尝试 | 已确定1000；初始化另计，失败与重复也计数 |
| H与数据 | 现有10H及train21、原顺序；23个指定资产已复制到本树`preparations/fjsp-long`，不含旧runs |
| 状态/评分 | v3完整状态；`J=mean((Cmax-LB)/LB)`最小化；LB_v5不取整 |
| 独立重复 | 首轮一个搜索种子；具体整数待确定，不自动增加重复 |
| 种群/初始化 | 大小、初始化最多尝试数和初始化规则待确定；两个初始化上限字段须一致 |
| 完整请求上限 | 必须明确等于“初始化上限＋1000”，当前为null；例如20＋1000=1020仅是算例，不是批准 |
| API/CPU及资源 | API1是当前安全方案的实现限制；CPU评价并发、CPU/内存、分区、账户/QOS、请求间隔、每实例期限、段时限和总日历窗口待冻结。评价器当前支持已有T30首解/复检共享期限 |
| 保存节点 | 草案列220和1000；220仍是待确认建议，1000为预算终点，不增加一组实验 |
| 客户端 | 绑定已验收V5非流式、gpt-6.1-sol、8192输出上限、10/240/300秒和原端点；它是工程来源，不是本轮付费请求许可 |
| 账户排他 | 全部同账户设备的停止/排队确认及有效时间仍缺；无法由Mac文件锁证明远端排他 |

使用API1、CPU评价2及train21/T30时，分阶段波次含两次串行API等待，排空计算下限为`2×300＋21×30＋2＋5=1237秒`，另加冻结的请求间隔。不能照抄20分钟；入口根据声明实例数、两个池宽度和期限校验。至少控制进程加较大工作波次所需CPU，示例3CPU不是已批准资源。数值库线程在Python导入前设1；运行时核对Slurm实际CPU并记录实际资源。内存及train21峰值RSS尚无本轮实测。

单段暂停不延长原总日历窗口；恢复继承第一次启动时写入的截止时间。到段末前停止接收新波次，排空、导出后释放锁。强杀不等于安全暂停。

## 离线证据与固定H复用

- [持久Mock证据](offline-v3-20261113-03/acceptance.json)：串行、并发、暂停恢复均完成相同的2次初始化＋7次演化尝试，包含部分末代及3/7节点，语义哈希一致。候选评价使用真实子进程返回人工成本回执，未运行H或构造器。冠军、逐实例CSV、两种横轴曲线、日志、协议与节点检查点均在同目录中，明确标记`MOCK`，不能用于科研结论。
- [执行层测试](offline-v3-20261113-03/unit-tests.txt)：覆盖并发宽度、独立种子、预算、初始化不补员/显式有界初始化、精确有限前缀、未知在途、源配置/检查点篡改、失败留锁、v3调用绑定、资源与Slurm参数匹配、重复和未知提交防护。Slurm返回值全部是假回执。
- 状态检查另运行`tools/check_state_a_v3.py --check-only`，20项通过，模型请求/构造求解/正式评价均为0。继承的有限流程证据仍只证明9工序合成实例，未重新消耗其预算。
- [固定H兼容清单](fixed-H-reuse-v3/compatibility.json)与[210项派生J](fixed-H-reuse-v3/fixed-H-train21-J.csv)：逐项核对10H键/顺序、21实例内容哈希、重新计算的静态LB、完整有效标记、原始Cmax及原生复检哈希。新旧排名一致，H0的J为1.1118049606260487。仅读取已有成本并重表达评分，没有新增420次求解，也不把历史时间当作当前环境计时。
- 固定H动作输入、追加式调度、原动作枚举及精确同分规则继续复用；新增统计不额外执行未选H。最终v3接线经源码与惰性返回包检查，尚无本批真实train21执行证据。

最终状态、源码/规则身份、检查输出与打包回执以同目录文件为准。旧离线证据保留原时点，不覆盖成新版本通过。

## 最少命令与部署顺序

当前立即可执行的纯只读门禁检查：

```bash
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-execution-20261112
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B experiments/common/run_frozen.py check-only --config experiments/fjsp_long/research.pending.json
```

预期打印待定字段并退出2，不请求、不求解、不写运行目录，也不读取凭据。待用户确定参数后另存`research.frozen.json`，保留草案；同时冻结`deploy/fjsp-long/deployment.frozen.json`。当前这两个正式文件尚不存在，下面命令是条件交接，不是已经具备的批准启动命令。

包内有`release.json`文件清单/SHA；不含凭据、虚拟环境或历史runs。将ZIP及`.sha256`从Mac上传到新的远端目录后，在集群校验SHA和逐文件清单，再解压；使用已有`/public2/home/qiuqian/hdl-envs/portable-v2/bin/python`，不复制Mac环境。不固定node15。当前未上传、未提交、未在集群核验，不等于已备份。

Mac上传形式沿用既有跳板：

```bash
scp -o ProxyJump=custom@222.201.144.188 PACKAGE.zip PACKAGE.zip.sha256 qiuqian@110.1.2.1:/public2/home/qiuqian/hdl-deploy/
```

`PACKAGE`须替换成交付回执中的真实包名。本次BatchMode认证未通过，正常交互登录由用户处理；本任务不读取/改写SSH或API凭据。

集群解压后先运行`python -B deploy/fjsp-long/verify_release.py`核验文件清单；该检查不请求、不求解。待本轮参数另行冻结后，在新的release根目录中：

```bash
/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B experiments/common/run_frozen.py check-only --config experiments/fjsp_long/research.frozen.json
/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B experiments/common/run_frozen.py prepare --config experiments/fjsp_long/research.frozen.json
/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B deploy/fjsp-long/submit.py run --deployment deploy/fjsp-long/deployment.frozen.json --config experiments/fjsp_long/research.frozen.json
```

前两条仅校验/准备文件、静态解析数据及LB，不求解；第三条默认只打印将提交的命令。只有用户完成启动前核查和授权后，才为第三条追加`--submit`。每次提交先保留认领，收到作业号后记录；未知认领不自动重提。运行使用原有owner-only mode600凭据路径，只在明确的真实run/resume之后读取，不复制密钥。

查询：`bash deploy/fjsp-long/query.sh JOB_ID`。暂停：`python -B experiments/common/run_frozen.py pause --config experiments/fjsp_long/research.frozen.json`。须等检查点phase为paused、工作锁释放且原Slurm作业终态明确，再以同配置调用`submit.py resume ... --submit`；不新建目录重置预算、不删除锁或未知提交认领。

Mac取回：`bash deploy/fjsp-long/fetch.sh JOB_ID ABSOLUTE_REMOTE_RUN NEW_LOCAL_DIRECTORY`。脚本要求该作业已离开活跃队列且有终态记账，复制到新目录，核验结果哈希；没有`--delete`，不会重求解。取回后仍需检查检查点、锁和未知状态，文件复制不是恢复许可。

## 由用户启动的有限真实验收方案

优先把有限验收作为同一正式运行的初始化前缀，不隐藏额外请求。冻结完整参数及授权后，用户可在已有准备目录运行：

```bash
python -B experiments/common/run_frozen.py run --config experiments/fjsp_long/research.frozen.json --allow-api --allow-evaluation --pause-after-attempts 1
```

这一条应在计划正式运行的同一环境执行，最多保留并发送第1个初始化尝试，不自动重试；成功解析后最多评价1条候选，train21首解/复检最多42遍，失败前缀照实保留。它计入原初始化上限和完整请求上限，后续恢复仍是同一运行，不再加“验收预算”。集群采用同一外壳的现成控制参数：`submit.py run --deployment deploy/fjsp-long/deployment.frozen.json --config experiments/fjsp_long/research.frozen.json --pause-after-attempts 1`，先审阅打印命令，再由用户追加`--submit`。不在登录节点请求或求解，不把Mac运行搬去集群重置身份。本任务未启动该方案。

核对完整响应、v3候选/Prompt身份、21行可行性及首解复检、检查点/预算/费用未知项后，用户决定是否继续同一预算。若候选非法或初始化失败，不补发伪装通过；若另需独立小批验收，必须先另行明确其请求与求解额度，不使用已关闭的API2/求解12。

仍缺的启动条件集中为：最终种子及种群/初始化规则与上限、完整请求上限、资源/期限/账户排他配置，当前远端访问与资源/作业状态确认，以及用户启动后的真实新入口验收。新版状态代码已交付，不再是缺口。单种子train21长运行及跨平台长流程尚未执行，不能据Mock、旧有限验收或固定H静态复用宣称正式实验完成。
