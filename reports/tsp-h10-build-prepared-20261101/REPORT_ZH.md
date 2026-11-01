# TSP专用10H构建与汇报交付

工作树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-eoh-tsp-prep`；分支`codex/eoh-tsp-prep-20261101`。本轮正式H构建、正式基线、真实U搜索均未启动，无真实API请求，无付费授权文件创建或复用，不访问Notion。原FJSP B及主工作区未修改。代码与证据均位于Developer，不写iCloud。

## 已实现

1. 从既有正式来源审计、映射和当前冻结元数据核清FJSP 10H的来源。记录为`FJSP_H_provenance_audit.json`，没有重复求解历史实例。
2. 新增薄入口`experiments/common/run_tsp_h10.py`与问题适配器`code/heuristic_design/problems/tsp/h_build.py`；复用原`core.execution`、请求账本/wire传输、TSP封闭AST、已有compact worker/T30生命周期和`complementary_survival`。只给现有执行器加可选的提交后快照回调，未复制项目或再造恢复执行器。
3. 完成独立生成Prompt、准入/AST去重、完整train20评价、预定CPM筛选、10H冻结与身份回执、H谱系与逐实例记录、不足10H的明确失败，以及后续恒选与U配置生成。
4. 完成离线汇总入口与中文报告/CSV/PNG/SVG模板。普通结束或安全暂停自动尝试汇总，失败不影响原始结果；可独立重跑。H没有演化，不制造H代际曲线。U保留真实代数、谱系、各代种群与预算节点。

研究协议、差异与固定公式见[协议V1](../../docs/TSP_H10_BUILD_PROTOCOL_V1.md)。本轮是独立I1池＋现有CPM一次筛选，无H演化，无人工H补员，不是正式EoH-S复现，不声称已做真人行为审查。

## 参数与推荐预算

|实验|参数位置|请求预算|最坏评价量|本轮是否运行|
|---|---|---:|---:|---|
|正式H构建|`experiments/common/configs/tsp-h10.real.pending.json`|40槽/40尝试，每槽1次|800程序×实例行；1600遍|否|
|H工程小试|`experiments/common/configs/tsp-h10.mock.json`|12个Mock槽，真实API=0|12×1×2=24遍，独立小型工程实例|仅Mock验证|
|冻结后恒选10成员|H运行目录`next/singles.fixed.json`|0|10×20×2=400遍|正式train20未运行|
|冻结后U待定模板|H运行目录`next/u-real.pending.json`|初始化≤20＋演化200＝≤220|220×20×2=8800遍|否，独立预算待用户核对|

H的10是最终保留数，不是请求次数。40个候选槽全部结束后再选：先按均值选首个，再按逐实例包络增益贪心，增益平局按训练均值/稳定ID；最后以均值/ID编号。解析失败、传输失败、重复、无效评价都占槽，不自动补预算。重复不重复求解；同分不作为源码重复。不足10个有效去重H时无冻结产物，退出码2。

固定T30、12小时持久窗口；恢复保留原预算/时窗。硬认证/余额/型号/参数错误、连续3个传输失败、未知发送/未提交记录、源码变化或哈希错误停止，不清锁和重发。每次发送最多1次尝试，早停不自动追加新实验。真实LLM能否生成足够合法且互补的H、服务可用性、描述语义和泛化均尚未验证。

H默认采用现有`gpt-6.1-sol`配置、非流式响应；只有环境变量名`LEAFAPI_API_KEY`进入配置，程序不输出或保存密钥。没有查供应商余额/费率或创建付费授权。40次是请求上限，不是货币硬封顶。

H预算节点在JSON的`milestone_requests`；U报告节点在`run_tsp_routing.py`顶部`REPORT_REQUEST_NODES`，新运行冻结后恢复不读取新值。将来若另行决定1000次级U搜索，应单独修改N/G、初始化/演化/总上限和报告节点；不能把1000次自动套到H或所有实验。

## 命令：check-only（不生成候选、不评价策略、不发请求）

以下命令均在本独立工作树执行。check-only会计算NN参考进行输入核查，不运行H候选评价。

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-eoh-tsp-prep
.venv/bin/python -B experiments/common/run_tsp_h10.py --check-only
```

默认配置`real_requests_authorized=false`。没有显式匹配预算参数，普通启动会在创建run前被拦截。不存在默认继承B授权的路径。

## 命令：工程小试（Mock生成＋真实小型求解，真实API=0）

```sh
.venv/bin/python -u -B experiments/common/run_tsp_h10.py --config experiments/common/configs/tsp-h10.mock.json
```

这会产生带`engineering_only=true`的10H工程产物。即使给真实U入口加启动开关，也拒绝用该Mock集合进行真实搜索。不要把其图表当作PPT科研成绩。

## 命令：正式H构建（本轮唯一建议立即核对的真实预算：40次）

请先在自己的终端准备好已有API环境变量；不把密钥复制到聊天或源码。下面是**由用户启动的正式实验**。输入`--approve-budget 40`表示仅核对并启用这一批H的总上限，不开启恒选或U阶段。

```sh
.venv/bin/python -u -B experiments/common/run_tsp_h10.py --run-dir runs/tsp-h10-real-20261101-01 --approve-budget 40
```

同名目录存在即拒绝新建，不会覆盖或自动重跑。该目录尚未由助手创建。正式参数改动时须同时修改candidate_cap/API_attempt_cap和预算节点，并在启动命令中写相同上限；不支持用原授权增加预算。

查看进度、暂停、恢复和离线汇总各一条命令：

```sh
# 查看进度：只读
.venv/bin/python -B experiments/common/run_tsp_h10.py --status runs/tsp-h10-real-20261101-01

# 安全暂停：提交请求，等当前候选及复检排空，看到phase=paused且writer_lock=false
.venv/bin/python -B experiments/common/run_tsp_h10.py --pause runs/tsp-h10-real-20261101-01

# 恢复：仅安全paused；40仍是原总上限，不是新增40次
.venv/bin/python -u -B experiments/common/run_tsp_h10.py --resume runs/tsp-h10-real-20261101-01 --approve-budget 40

# 离线汇总：可用于进行中/暂停/完成运行，不发API、不求解、不重选、不冻结
.venv/bin/python -B experiments/common/summarize_tsp.py --run-dir runs/tsp-h10-real-20261101-01
```

普通完成和安全暂停后会自动尝试同样的汇总。进行中只读取cursor/已结算批次内的结果，报告截至时间、已提交量、预留量、代数和暂停记录；不把未知在途任务算有效，不以检查点状态保证进程仍存活。

## 冻结后到U：只准备，不自动执行

正式H运行显示`freeze.status=frozen`、member_count=10后才执行后续命令。以下路径假定使用上面指定的H目录：

```sh
# check-only：核查冻结10H、恒选P0与完整train20
.venv/bin/python -B experiments/common/run_tsp_routing.py --check-only --config runs/tsp-h10-real-20261101-01/next/singles.fixed.json

# 正式基线评价：400遍，API=0；由用户终端启动
.venv/bin/python -u -B experiments/common/run_tsp_routing.py --config runs/tsp-h10-real-20261101-01/next/singles.fixed.json --run-dir runs/tsp-h10-singles-real-20261101-01

# check-only：核查U待定模板；不会发送220次请求
.venv/bin/python -B experiments/common/run_tsp_routing.py --check-only --config runs/tsp-h10-real-20261101-01/next/u-real.pending.json

# 正式U搜索：这是另一批≤220次，需用户届时独立核对，当前不执行
# .venv/bin/python -u -B experiments/common/run_tsp_routing.py --config runs/tsp-h10-real-20261101-01/next/u-real.pending.json --run-dir runs/tsp-u10-real-20261101-01 --allow-api --approve-budget 220

# 离线配对汇总：只有来源/协议兼容才计算差值；缺失或不兼容则导出占位
# .venv/bin/python -B experiments/common/summarize_tsp.py --run-dir runs/tsp-u10-real-20261101-01 --baseline runs/tsp-h10-singles-real-20261101-01
```

U进度/暂停/恢复复用`run_tsp_routing.py --status/--pause/--resume RUN_DIR`；真实恢复还需`--allow-api --approve-budget 原总上限`。不切换到B的恢复入口。当前U继续主项目Fitness生存逻辑，未移植B分支行为优先生存及实验性故障恢复。

## 输出与汇报模板

- 原始：Protocol、Tasks、checkpoint、API_attempts、wire响应、候选Prompt/响应、worker回执、开始/结束及执行段记录、暂停控制记录。
- H：H_frozen＋receipt、H_build_outcome、Population_snapshots、milestones预算节点；next目录含后续配置、恒选P0、冻结训练快照。
- `analysis/REPORT_ZH.md`：简短中文结论；`summary.json`：状态、实际预算/usage、有效/失败/重复、耗时及来源。
- CSV：requests、candidates、per_instance、best_fitness、lineage、generations、populations、budget_nodes、sessions、pauses；H另有质量、完整分数矩阵、互补性与最终清单；U另有基线汇总和逐实例胜负平。
- PNG/SVG：最佳Fitness、H质量/矩阵/互补性或U行为多样性/兼容基线、缺失验证占位。SVG文字可编辑；Mock显著标识；图表不补跑、不补值。
- 图表使用本机已有`/Applications/anaconda3/bin/python3`的matplotlib；未修改B共享虚拟环境。也可设置任务专用`HDL_PLOT_PYTHON`指向已有绘图解释器。绘图失败只记录错误；原始结果和CSV仍保留，可独立重导出。

## 验证与局限

50项相关离线检查通过，复现命令：`.venv/bin/python -B tools/check_tsp_h10.py`。覆盖正常冻结、恒选物理解一致、U衔接、失败/重复/无效求解计数、不足10H无补齐、暂停恢复预算不重置、三传输失败停止、硬认证错误不重试、未知保留不重发、进行中结果过滤、基线身份拒绝、预算节点实际越界记录、汇总失败原始回执不变，以及原通用路由/FJSP/TSP相关回归。`checks.log`为最终日志。首次聚合测试误用stdin入口与spawn不兼容；已提供正式文件入口修正，旧启动失败日志单独保留，不将其解释成候选质量失败。

实现提交为`90f2d04`；本目录保存最终核验记录`FINAL_VERIFICATION.json`及`engineering/H`、`engineering/singles`、`engineering/U`汇报产物。最终提交还包括实例索引整数刻度的图形修订，仅离线重画H图表，不增加求解或请求。

|最终工程演示|实际工作量|结果|
|---|---|---|
|H池|12个Mock候选×1个9城工程实例×2遍＝24遍|第4槽安全暂停，再沿原12槽预算恢复；冻结10H|
|恒选10H|10条固定U×同一工程实例×2遍＝20遍|完成，与H构建期恒选物理解一致|
|U流程|2个Mock初始化＋一代4个子代，共12遍真实工程求解|完成；同来源恒选基线兼容；汇报图表已生成|

所有首解/复检哈希相等，compact不保存动作大表；三个阶段真实API均为0。已查看H矩阵及U基线PNG，确认中文、标签和Mock标识正常；SVG保留可编辑文字。冻结H来自Mock，不能进入真实U。独立离线汇总完成且无追加求解。正式H40/完整train20基线/真实U未由助手运行，正式目录`runs/tsp-h10-real-20261101-01`尚未创建。

在线服务、真实候选合法率及质量收益尚未验证，这是本轮边界，不是可通过离线测试补造的结论。

没有剩余的已知工程阻塞。EoH同预算正式训练仍属于另一个待定协议，本轮没有把其预算或旧模型规则混入TSP H构建。未打包/传输/清理历史；未来按AGENTS在Developer/transfer-outbox生成ZIP，用户完成Windows核验后再讨论清理。
