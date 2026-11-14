# 三问题、六组独立搜索准备包

本包新增批次薄层和问题适配，公共`code/`保持923781f逐字节不变。当前Mac U501的源码、实际Prompt、种群、检查点、账户门禁均不改。614258／614474已关闭，保留原证据，不追加请求或求解。

## 配置与当前状态

配置位于本目录`configs/`，分别为`fjsp-u.json`、`fjsp-eoh.json`、`tsp-u.json`、`tsp-eoh.json`、`obp-u.json`、`obp-eoh.json`。六组均声明每个独立种子1000次演化生成尝试；初始化及H构建另计。重复数、种子清单、未批准种群和初始化上限保持null。当前全部正式启动被协议缺口阻止，不能把结构化准备当作真实运行验收。

- FJSP U：通过`entry.py`委托原`experiments/common/run_frozen.py`，保留实际501算法、Prompt和客户端。新的资源与账户安排在独立子配置中绑定；科学参数不符合原501配置时拒绝同版重复。原正式入口的单种子限制不删除。每份子配置仅向它传一个种子。
- FJSP EoH：复用旧原生EoH的I1、E1、E2、M1、M2、按秩选父代、原生生存及同分重复惩罚。完整train21的J最小化；种群内部仅桥接为−J，最终按完整有效候选的J、稳定语义ID升序选优。旧负Fitness入口和记录保持原身份。
- TSP U／EoH：接现有固定起点构造器、H ABI及14项状态；U是父代覆盖的CROSS／MUTATE，EoH直接演化H。历史10H和train20按交付哈希导入，H顺序不改。没有LKH参照时拒绝真实评价，不调用NN兜底。
- OBP U／EoH：正式候选采用预设N个永久箱、先筛全部合法箱（保留全部空箱）、再调用一次被选向量H的v2接口。H只接收当前物品及合法箱剩余容量的只读tuple，局部argmax映射回永久箱号；不再传全部箱后过滤。新候选状态适配已交付并通过局部状态检查，仍需用户采用。资源统计只含已开箱（包括满箱），14项定义不变；R_code使用int64求和、float64除法加0.5、Python int截断，R≤0拒绝。旧两标量原型仅用于工程身份；r1／r2旧包保留，但不作为最终OBP交付。接口细节见[OBP说明](OBP_INTERFACE_V2_ZH.md)。

TSP H原件SHA为`f85c5cafb8d675ae0dbbe2f682fe5f61f7a2bda5490eb6f95d958256d3dcdb8e`，原训练清单SHA为`fa95ca6ac7dd7f3902ca693436ec63d6241b91c11c0b7708615f1f20b07d3ccb`。迁移后的清单只改相对路径，各实例原始文件哈希保留。该H集合来自历史候选事后筛选，不称正式EoH-S；holdout40已见，confirm60暴露未知。本轮只读取train。

## 入口

- `batch.py`：全批计划、独立子配置物化、指定实验／种子启动、状态、暂停／恢复、全量汇总。
- `entry.py`：单次独立运行；复用公共执行循环，不实现第二个调度器或客户端。
- `assets.py`：H静态检查、独立有界构建、按完整训练J筛选冻结、固定H兼容结果复用；LKH准备与导入。
- `slurm.py`与`cluster.sbatch`：单个运行分段提交。打印命令为默认行为，真实提交需明确`--submit`及原累计额度。
- `cluster.py`：复用已验收SSH连接／上传核验机制，准备、提交、查询、暂停、取回。每次操作集中一次交互认证，不反复尝试失败登录。
- `mac.sh`：Mac薄层，不启动后台服务。

## 当前可直接执行

在Mac终端，以下命令只读取配置并列出六组缺口，不读密钥、不请求模型、不求解：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/batch.py plan
```

`batch.py prepare`只物化批次清单及已明确种子的独立配置，不初始化种群或求解。正式输入改变后使用新的批次计划目录，已物化的清单／子配置不得覆盖。

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/batch.py prepare
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/batch.py check-only --all
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/batch.py summary
```

工程Mock是独立身份，配置、合成H／参照和结果写入`reports/triad-package-20261113`及独立`runs/triad-OFFLINE-*`，不得进入研究输入。需要重验本轮代码时运行`offline_tests.py`；它显式拦截网络、真实客户端、构造器、真实评价器和LKH调用，不等于计算节点真实验收。

## 协议冻结后的手动启动流程

先审阅[集中建议草案](REVIEW_DRAFT.md)；未批准值不自行补齐。每个种子的运行ID、配置哈希、目录、预算、日志和提交回执链独立。每次从空种群初始化，禁止导入其他种子的P0或检查点。`run`与`resume`均需明确原累计额度，不因分段增加预算；原日历窗口也不延长。

Mac单次运行接口为`entry.py run --config 子配置真实路径 --run-dir 独立目录 --allow-api --allow-solves --approve-budget 原累计上限`。`prepare`只有文件写入，真实模式仍要求显式原额度确认但不读密钥。状态／暂停／导出使用同一路径与`status`、`pause`、`export`。恢复使用`resume`并承认原额度。批次可用`batch.py run --all`依次推进已冻结运行；遇暂停、失败、未知请求或未知提交停止，不能跳过后自动补跑。用户可自行执行下一条状态或恢复命令，无需逐代向聊天报告。

本工作树r4集群独立根目录为`/public2/home/qiuqian/hdl-deploy/triad-six-groups-20261114-r4p1`，复用`/public2/home/qiuqian/hdl-envs/portable-v2/bin/python`，不默认安装依赖。包准备完成后用户可在Mac终端执行：

```bash
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/cluster.py stage
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/cluster.py inspect
/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python -s -B /Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-eoh-gap-20261113/experiments/triad/cluster.py prepare
```

以上上传与检查不提交Slurm。正式配置未冻结时，`submit`会拒绝。冻结后，`cluster.py submit`／`resume`选择`--experiment`、`--seed`，同时给出`--submit --allow-api --allow-solves --approve-budget`；`query`、`pause`、`fetch`使用同一实验与种子。`summary`取回全批状态。包中不预造一个已批准种子或额度作为示例。

登录节点仅做导入、静态数据／参照校验、文件物化、只读资源检查和提交／查询。真实生成、完整构造求解及复核在计算节点执行。TSP参照准备规格在`lkh.pending.json`；`assets.py lkh-prepare`要求已批准且可核验的二进制哈希、版本、参数和距离协议，生成用户手动运行的命令；`lkh-import`只读完整tour并用原始距离重算参照。准备与导入不运行LKH。用户未来可用`assets.py lkh-run --run-dir 准备目录 --allow-lkh --approve-lkh 实例进程数`手动执行；每个进程有明确超时、RUNS与MAX_TRIALS，先预留后执行，遇错停止不重试。导入要求完整执行回执与tour哈希，本轮未运行该命令。

## H与固定基线

`assets.py build-check`集中列出H构建缺口；`build-prepare`／`build-run`使用独立目录和独立H请求上限，`freeze`仅接受完成的H构建，按已声明策略筛选；OBP建议greedy-envelope-J-v1逐步最小化训练逐例包络J，平局按稳定ID，零增益仍补足目标数。完整有效且不同的H不足目标数则停止，不补额度。工程Mock生成的H带`engineering_only`，真实搜索拒绝该资产。

`fixed-import`接收已经完成兼容性核查的原始成本JSON和审计回执，保留原件、费用和旧Fitness身份，只生成兼容导入包，不重新求解。`fixed-plan`检查冻结H、实例、参照、求解限制、物理实现身份及完整成本矩阵；兼容时直接从原始成本派生J，新增求解为0。`fixed-run`仅在没有兼容结果、用户明确批准包含首解／复核的总次数时可用。FJSP已存在10H×train21基线，缺原始兼容包时要求导入，不能默认重评420次。

## 预算、资源与恢复

六组每种子演化为1000次尝试，初始化失败、无效和重复按原协议消耗槽位。真实确认发送、未知发送、token已知小计／未知条数分开；费用未知保持null。首解／复核分别记录started、completed、failed，保留未结算数，不以成功前缀当完整成绩。H构建成本及历史H成本单列，同一H资产按哈希去重一次，不随搜索重复次数重复计成新增请求。

同账户全设备当前只运行一个生成任务；本地文件门禁不声称跨Mac／集群共享。总规划已报告Mac501完成；本包不据此自动取得账户许可，真实生成仍须确认全设备账户排他安排。未知提交先写持久预留并保留回执，不能自动重提；未知发送、未结算评价、Stop或锁阻止续跑，不删锁、不退款、不重放。

同时运行数K、每次模型并发a、CPU评价并发e分别记录。当前生成a＝1；FJSP原冻结U保留e＝2，其余新接入保持原生串行e＝1。波次分阶段时每次CPU至少`1+max(a,e)`，数值线程固定1；内存及多个运行的资源须合计。单Array的百分比上限不等于账户限流；本包不以Array为前置，也不宣称多独立作业并发已验收。

## 报告与证据边界

单次报告保存原始实例成本、参照、J、参数／Prompt／数据／源码身份、CSV、冠军与曲线。选优仅使用完整训练评价；测试集不用于调试。批次汇总从冻结清单出发，包含全部成功、失败、暂停、未知和未启动运行；终值和共同演化尝试位置的均值／样本标准差均输出，曲线不在中止后的未观测区间填值；有效数明确列出，少于2次时样本标准差为null，失败中途最好值不当最终冠军。

目前状态：本地准备及合成回执检查；未上传本六组包，未在计算节点运行新版EoH、TSP或OBP真实验收。旧614258／614474只作既有基础机制证据，不能替代本包真实运行证据。


## r3交付与已有501

r3为本地代码交付（CODE_READY），六组正式配置仍非RUN_READY。ZIP包含根README、入门指南、本文、集中建议草案、资产命令及delivery/离线证据；不含密钥、账户门禁、锁或任何旧运行。版本标识保留20261113，最终收尾日期为2026-11-14。包尚未上传，未在计算节点验证新版六组真实搜索。后续输入由cluster.py prepare单独上传并核验，只允许preparations/内的绑定训练资产，不上传凭据、源树或检查点。

FJSP U501被entry和Slurm入口保护，不能重开；只有用户采用其纳入规则、配置同版且原运行完成结清后，才能用batch.py register-existing --experiment fjsp-u --seed 501 --accept-existing-completed登记。此操作只读来源，生成摘要与曲线回执，不复制检查点；集群prepare --existing-receipt接收该回执并核验。若不纳入501，应采用其他新种子。未登记不会假装本批已完成一次。

原始六组配置在configs/，建议配置在recommended.draft/，一次审阅文件为study-review.draft.json。实际资源、账户、LKH和OBP资产仍待绑定；推荐值不等于批准。完整的用户手动准备命令见[资产与启动命令](PREPARATION_ZH.md)。


## r4离线收尾

r3 ZIP保持原SHA不变。r4追加closeout.py、独立可选绘图依赖和[收尾操作说明](../../docs/实验结束与归档.md)，不改公共执行代码、正式参数或原501。现有cluster.py stage指向新的20261114-r4包及独立远端目录，不覆盖旧部署。check-only只读现有导出；build生成新图表／报告／清单，并在显式archive参数下创建完整证据ZIP。batch-report复用已有批次Summary。所有模式均不导入客户端、求解器，不执行H／U或自动推送。图形依赖不安装进原portable执行环境。r4工程包不包含原501的1.15GB运行；实际样例精简成果及完整证据ZIP分别交付。

最终默认包为r4p1（closeout-v1.1）：比r4初稿多核对明确的J-gap定义，防止同名旧协议被误标。r4初稿与r3均保留。实际501样例v1由e926be8生成，保留其当时脚本和哈希；新增严格门禁不改写样例或原运行。
