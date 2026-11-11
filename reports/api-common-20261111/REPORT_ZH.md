# Mac与集群共同API诊断交付｜2026-11-11

本轮新增真实模型请求0、策略求解0、训练评价0、Slurm提交0。所有改动在独立工作树 `/Users/DDXQL/Developer/Heuristic-Design-Lab-api-common-20261111`、分支 `codex/api-common-mac-cluster-v5`；基于FJSP已集成的 `ca94a63`，复用共同V4客户端、严格非流式调用方及既有Python诊断入口。没有重写搜索器，没有修改状态方案A、基线方法、数据、H或演化算子，也没有新增状态消融。

## 1. 真实故障清单与证据边界

|环境／运行身份|证据时点与源码|已确认情况|不能据此得出的结论|
|---|---|---|---|
|Mac FJSP EoH `fjsp-eoh-single-nonstream-20261104-01`|11-04 21:10至11-05 09:00；Protocol SHA `b65ae5ded17c9fab54c93121393470b0d2e79bc9617977e8d64bf69842ee1fef`，共同V4非流式＋严格调用方|上限1050，实际预留324、确认发送293；API完整响应290、失败34：连接超时31、524两次、200后超时1次。检查点提交323，最后H-0323尚未提交；候选提取/约束另有1次失败。|324不是1050；未确认发送不自动等于未发送。连接超时旧日志无法拆分DNS/TCP/TLS。完整响应不等于完整实验完成。|
|Mac最后一次停止|`Clock_quarantine.json`、`Stop.json`、`Run_clock.json`与本机pmset窗口|同一任务墙钟约103.94秒、单调钟约13.35秒，相差约90.590602秒。pmset记录08:58:27合盖睡眠、09:00:00唤醒，睡眠93秒。源码在结算任务之前因clock gap抛错，遗留未提交任务与锁。|电源证据支持本次gap与本地休眠相关，不能把103.94秒当供应商计算时间；也不能因此解释此前全部31次连接超时。旧48h窗口已经过期，不直接恢复或延长。|
|集群旧10H作业585019，本地两份取回副本|11-04历史收尾；科学源码9997ecd／部署d8c3e687；transport旧V1，Protocol SHA `d11774dd…`|本地completed_verified记录初始化10＋演化1000＝1010，确认发送1010；3次真实HTTP524、2次解析/约束失败、240次重复。两份副本为同一次实验。|这是旧10H历史运行，不能覆盖用户“当前1000次尚未验收”的现场，也不证明新版H、状态方案A或当前基线流程已跑通。原始stdout/stderr及旧诊断完整取回仍有缺口。|
|集群新版状态任务585597／其余五项|聊天《集群接入部署方案》11-11只读盘点；部署bb21b69/afeb29b|585597最后聊天记录为11-04 21:53 running、初始化2、演化0；本机未见取回的最新运行证据。其他五项不能仅凭发布文件判定已运行或未运行。|不能沿用历史running或发布时not_started作为当前状态；不能为补证据重投旧任务或清锁。|
|集群鉴权历史|577617／auth-followup-20261103摘要|历史曾收到HTTP401；与后续完整请求的成功记录分时段保留。|401不能单独区分无效令牌、权限、IP或账户限制；没有读取凭据、余额或提供方后台，不能断言具体原因。|
|旧流式诊断|11-04 HTTP200后第2个SSE数据事件id改变；模型前缀符合预期|真实存在响应身份一致性拒收；当前不能回放未保存的原始SSE字节。|尚无证据将其解释为合法协议差异或模型被替换。没有为了通过而忽略首帧、ID、stop、usage、DONE或截断。|

原始路径、大小与SHA见 `source-manifest.json`；本轮只读来源包括原Protocol/检查点/API账本、末段terminal.log、具体失败收据、原始Prompt、旧收尾JSON和两条相关聊天的最新记录。没有递归读取所有历史响应或holdout内容。选取的14份原始文件前后SHA一致。

### 请求分母与已知成本

|批次／身份|硬上限|实际预留／确认发送|完整响应成功／分类失败|usage边界|
|---|---|---|---|---|
|11-04 V3流式对照；计划SHA `159382f8…`|旧累计4|本批2／2|1／1（SSE id变化）|已知输入9690、输出310；未知1|
|11-04 V4非流式短检查；计划SHA `ca2f5d15…`|与上一批共用旧累计4；本批仅剩2|本批2／2；两批累计4／4|2／0|已知输入19380、输出712；未知0|
|Mac正式FJSP EoH|1050|324／293|290／34，失败分型见上表|已知输入1429457、输出99432；未知34，其中确认发送而usage未知3|
|集群旧10H 585019正式搜索|1050；计划生成1010|1010／1010|传输成功1007／HTTP524失败3；候选解析/约束2另算|历史失败具体usage及费用不以摘要补算；当前远端状态未知|
|本轮V5两端新计划|待用户显式批准累计4；每端2|0／0|0／0|尚无线上usage，费用未知|

前两行来源分别为 `/Users/DDXQL/Developer/Heuristic-Design-Lab-api-reliability/runs/api-reliability-diagnostic-20261104-01/ledger.json`、`/Users/DDXQL/Developer/Heuristic-Design-Lab-api-reliability-next/runs/api-reliability-nonstream-pair-20261104-01/ledger.json`。它们是两批、一个累计4次的旧授权；旧额度已耗尽。本轮4次是独立待批准上限，未计入已用或正式搜索。所有费用均未获得提供方账单，不能用token或发送确认冒充实际费用。

远端只读SSH实际结果为跳板 `Permission denied (publickey,password)`，不是已成功进入计算节点。未索取、提取或输出凭据，也未反复登录。后续启动脚本会由用户在自己的终端完成SSH认证，先只读收集Slurm/检查点/锁/最近失败收据，再决定是否执行本轮诊断。当前远端事实仍未知。

“平台正在修复”只保留为用户信息，不作为根治证明。未发现超时参数被覆盖；也没有证据支持换模型、供应商、代理或单纯增大超时。LeafAPI当前接口说明未在本环境成功取得，不能借官方OpenAI接口文档替LeafAPI承诺；本轮按已观察成功的非流式格式、既有严格验收与离线反例核对，没有放宽完整性要求。

## 2. 已落实的最小修复

唯一共同wire版本为 **bounded-wire-reliability-v5**，完整源码SHA、计划SHA及使用方清单见 `CLIENT_FREEZE.json`；可运行验证文件的逐字节绑定在 `deploy/api-common/plan.json` 和 `plan.sha256`。

|文件／项目|修改及原因|
|---|---|
|`real_transport.py`|保留原HTTPSConnection/TLS验证、SNI、地址顺序和直接连接路径；在标准DNS地址解析／TCP地址回退处记录dns/tcp/tls阶段和耗时。旧connect超时的歧义不再传给未来记录。低层候选IP连接回退不是重发HTTP请求。|
|同一transport|非流式记录完整收到正文的字节数／哈希；JSON损坏时保留有界脱敏样本并明确分类。保留V4 SSE有界摘要，兼容分类旧id-change证据；不拼接不一致流或残缺JSON。|
|`routing_transport.py`|新源码中非流式OpenAI-chat调用也经过既有StrictNonstreamTransport，与FJSP EoH统一HTTP200、精确模型、stop、非空文本及合法usage门禁。没有把候选非法计作API协议错误。|
|`core/execution.py`|请求/评价已明确返回时，clock gap先记录、结算该任务一次，再在边界安全暂停；保留原deadline、任务、种群/RNG和已用成本。异常或未知在途仍走原停止保护。只改变未来新源码，不修写旧H-0323检查点。|
|已有诊断入口 `tools/api_reliability_next.py`|扩展为check-only／回放／显式run／安全resume／status／stop／export／bundle。每次先以exclusive create写入不可覆盖的逐槽预留收据，再落盘账本；收据/账本/响应前缀不一致就停止，孤立预留保守计入未知成本，不补发；失败关闭，只有已结算成功前缀的主动/时钟暂停可以显式续接剩余槽位。|

旧正式运行仍使用其原绑定：Mac FJSP V4、旧集群搜索V1、新版状态套件V4。没有在其他工作树并行修改客户端。新Mac/集群验证实际导入同一份V5，check-only核对导入文件路径及SHA；未来正式接入需新客户端收据与来源绑定，不能只复制provider配置，也不能用新源码resume旧冻结运行。

## 3. 参数与新诊断预算

|项目|固定值／变化|
|---|---|
|模型、端点、输出上限|原LeafAPI Chat Completions、gpt-6.1-sol、8192，不变|
|连接／读取／单次总期限|10／240／300秒，不变；新加观测，未靠延长期限规避故障|
|传输／代理|非流式；直接HTTPS，不读取应用代理环境；系统TUN未观测|
|并发|两端分别API1；Mac终结导出后才允许集群阶段，不按CPU数增加API并发|
|新预算|需用户通过 `--allow-api --approve-total 4` 明确启用；Mac最多2、集群最多2，共最多4；旧已耗尽诊断批次不重开、不继承旧授权|
|每端用途|第1槽：原Mac真实FJSP EoH H-0323 Prompt，3154字节；第2槽：原集群真实完整状态U Prompt，14946字节。两端使用完全相同的两份冻结文本；不测试“你好”，不删减正式Prompt|
|停止|每端首个失败即关闭该端剩余槽位；明确拒绝/响应身份等硬错误阻止后续集群阶段。网络类失败后集群独立阶段是预先声明的跨平台取证，不是失败重试；不会补满成功数|
|其他成本|求解0、训练评价0、无正式种群；实际金额未知仍为null。Slurm仅提交本轮API诊断作业，不串联正式搜索|

两种候选接口用于工程接入覆盖，不是状态消融或方法比较。API诊断不执行代码函数，不评价train或confirm/test，不把静态合法当成求解可行。

## 4. 已完成的纯离线检查

- 17项V5专项单元检查通过：DNS/TCP/TLS分型、坏JSON哈希、严格usage统一、clock gap结算后暂停/同预算续接、两个控制器互斥、两端累计4次、先预留后发送、拒绝后全局停止、未知请求禁止重放、控制暂停/续接、导出篡改拒绝、已有发布包身份复核且不覆盖、候选提取/约束分层、默认入口不读密钥/不构造transport。
- 15项既有JSON/SSE/传输预算回归通过。组合日志为29项（当时新增14）通过，随后加入互斥及归档复用及丢失账本前缀拒绝补发场景的17项专项通过；合计32项不同单元检查，不把重复运行相加。见 `offline-tests.log`、`targeted-tests.log`。
- 5份已有真实响应/故障材料离线回放通过：H成功响应、U成功响应、524、SSE id变化、clock gap；不是原始网络重发。见 `replay.json`。
- 40文件最小发布包在临时目录解压，用隔离Python `-I`执行check-only和回放均通过，不依赖原工作树的隐式PYTHONPATH。见 `bundle-offline-check.json`。
- 四个shell/Slurm脚本通过bash语法检查。没运行sbatch，没在登录节点做诊断计算。
- 两次测试夹具问题及原失败日志保留：首次坏JSON夹具误用另一协议responder；旧slow-drip测试的0.45秒期限在spawn启动前终止，改为仅该测试夹具1.2秒以实际触发慢体条件。部署的10/240/300秒没有调整。
- 新增不可覆盖预留收据后，专项反例发现未知中断的resume先校验响应文件、后校验阶段，报错顺序不够明确；现先拒绝unknown/failed再核对成功前缀。原失败日志 `targeted-prefix-initial-error.log` 保留，最终17项通过；没有因此补发请求。

这里的单元测试只用合成回执、伪transport及localhost HTTP；未调用任何策略求解/训练评价。clock gap控制用固定失败回执模拟结算，不执行研究算法。

## 5. 用户最少操作

### 推荐一次启动

在Mac已有LEAFAPI_API_KEY环境变量的终端执行：

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-api-common-20261111
bash deploy/api-common/start.sh --allow-api --approve-total 4
```

这条命令的明确作用顺序：

1. 本地check-only与真实材料回放，模型0／求解0。
2. SSH只读采集集群作业、旧/新检查点、锁和最近失败，写 `remote-before.json`。若认证失败、查询不可靠或仍有个人排队/运行作业，停在发Mac请求之前；不自动停掉既有实验。
3. Mac串行最多2次模型请求，每条先预留；不求解。
4. Mac闭合导出通过来源/预算检查后，才在 `/Users/DDXQL/Developer/transfer-outbox` 生成最小ZIP及SHA。只传显式文件、Prompt和Mac收据，不含密钥、.venv或旧runs。仅已打包/上传不当作Windows备份。
5. 传输、核验新发布目录，不覆盖已有源/结果；再次只读查队列，空闲才提交一个 `hdl-api-v5` Slurm作业。集群串行最多2次，不在登录节点请求模型或求解。

SSH密码只由终端处理，脚本不读取密码；使用本轮独立SSH复用连接，减少反复提示。集群只在用户显式提交的计算节点阶段从原个人600权限密钥文件读取凭据，不输出或传回密钥。

等待估计：每端持续运行时最多约10分钟模型等待，进程清理另计；集群作业墙钟上限15分钟、1CPU/1GB，无GPU。Slurm排队、SSH认证/传输无固定等待上界；Mac合盖/睡眠也可能增加实际墙钟等待，并触发已结算后的暂停。没有把这些时间归因于提供方。

如只想先看计划：

```sh
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/api_reliability_next.py check-only
```

模型0、求解0、提交0，通常秒级，不读密钥值。`replay`同样纯离线。在线新预算实际预留/确认发送目前均为0；4是待用户明确批准的硬上限，不是已用次数。

### 状态、停止与安全接续

统一状态根：Mac为 `~/hdl-api-validation/mac-cluster-api-v5-20261111/mac/`，集群个人HOME下同样相对路径的 `cluster/`。文件`owner.lock`保留，活跃互斥用OS锁，不靠删文件恢复。

Mac查看／请求停止（模型0、求解0、提交0）：

```sh
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/api_reliability_next.py status --site mac
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -B tools/api_reliability_next.py stop --site mac
```

stop只请求当前有界请求排空后暂停；不强杀。安全`paused`且每个既有槽位均已结算通过时，显式接续同一计划、剩余槽位（不是再给4次）：

```sh
caffeinate -i /Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -u -B tools/api_reliability_next.py resume --site mac --allow-api --approve-total 4
```

`failed_closed`或`unknown_interruption`拒绝接续，不删除claim或重放。停止后若Mac已闭合、只是传输/SSH中断，使用下列命令只继续传输/提交，不重跑Mac模型阶段：

```sh
bash deploy/api-common/submit_cluster.sh run --approve-total 4
```

该命令可能提交一个最多2次请求的集群诊断；若已经有提交claim或现有排队/运行作业则停止，不能反复提交。已知安全暂停的集群阶段使用 `submit_cluster.sh resume --approve-total 4`，重新申请计算节点但仍沿同一账本，最多只发该端剩余槽位。队列、锁、来源和暂停状态必须符合门禁，不自动处理unknown。

集群上可在诊断发布根用下列命令只写停止请求，不调用模型/求解：

```sh
/public2/home/qiuqian/hdl-envs/portable-v2/bin/python -B tools/api_reliability_next.py stop --site cluster
```

也可对确认过的本轮JOBID发送 `scancel --signal=USR1 --batch JOBID`，触发同一停止请求；不要把它用于旧585597或其它实验。完成排空前不保证即时结束，不用硬取消冒充安全暂停。

### 导出与取回

每次请求落盘后自动导出完整stage export：账本、逐次响应、调用方拒收材料、发送未知、已知token及未知usage。`export --site mac|cluster`可重新导出纯文件，不新增请求。

集群作业退出后，在Mac执行：

```sh
bash deploy/api-common/fetch.sh
```

只取回本轮cluster状态、export/响应及日志，写新的时间戳目录；模型0、求解0、提交0，不修改远端运行。当前未自动上传或取回任何数据。

## 6. 返回后本页直接读取的材料

用户只需告知启动/完成或阻塞状态，不必重述项目或整理日志。本页将读取：

- `reports/api-common-20261111/remote-before.json`、`remote-inventory.json`：两次远端只读事实及585019/585597实际任务身份。
- 同目录`user-launch.log`、`user-transfer.log`、`user-submit.txt`：是哪一步停止、是否产生新Slurm作业号。
- Mac状态根的`ledger.json`、`export.json`、responses与caller_rejections。
- `returned-时间戳/cluster/`及`logs/`：集群逐次请求、真实导入路径/SHA、DNS/TCP/TLS及HTTP/正文时序、源码绑定、usage和Slurm结果。

不从密钥文件或其它进程提取凭据；后续失败先交证据，不自动重开一轮。两端各2次用满只是计划终点，不据短成功宣布长实验稳定。

## 7. 完整小流程的准入判断

**当前不启动或提交小规模完整求解流程。** 还缺：本轮两端真实在线回执、现有集群任务的当前状态、状态方案A/基线对应的新运行与共同V5绑定。旧Mac运行已过原窗口且有未提交任务，不能套用本轮resume命令或改写历史身份来恢复。

若两端均完成严格响应与静态解析，下一阶段才另行准备“生成→解析→有限评价→检查点→暂停接续→导出”的完整小流程。策略求解必须另列候选/实例数量、首解复检次数、独立启动开关与Slurm资源，由用户手动执行，不混入4次API诊断。本轮没有任何自动进入正式种群、训练评价或长搜索的路径。

如果出现拒绝、DNS/TCP/TLS、524/200超时、解析或本地生命周期失败，分别按对应证据处理；平台/网络原因只有日志能支持时才归因，不通过多跑种子、补齐候选或提高API并发掩盖问题。

写作依据为主项目《中文科研写作规范》和固定humanizer-zh；实验代码遵循用户明确授权下的ahd-experiment-copilot边界。本报告是本轮增量，不覆盖任何历史报告、协议或账本。

原始Prompt和电源日志保留源文件中的尾部空白以保持字节身份；源码/文档的空白检查将这两类受保护文本排除，不修剪真实Prompt来消除格式提示。
