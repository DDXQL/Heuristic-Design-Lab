# 构造型TSP：实现与操作

协议：[固定预算](TSP_PILOT_PROTOCOL_V1.md)。本轮在独立worktree `/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-tsp-pilot`、分支`codex/tsp-pilot`；继承通用化提交c7402ca。原h-usage-space不切分支、不移动历史资产。稀疏检出只减少本地展开的历史资产，仍属同一Git仓库；`.venv`符号链接复用原环境，不复制凭据。

## 问题与边界

二维[0,1]均匀坐标、float64未取整欧氏距离，对称完整图。固定城市0出发，每次从未访问城市中取最高动作分数，精确同分最小编号，最终返回0。闭合边计入长度，无2-opt/ACO等局部搜索。`solver.py::tour_length`核验所有城市恰好一次、0起止；NN也使用相同起点、距离和同分。

所有距离特征除以sqrt(2)。每次选择前令R为未访问集合，c为当前城市，j为候选，p=(已访问城市数−1)/(n−1)。H收到以下5个float：

|字段|定义|范围|
|---|---|---|
|distance_current|d(c,j)/sqrt(2)|[0,1]|
|distance_start|d(j,0)/sqrt(2)|[0,1]|
|mean_remaining_distance|j到R去除j后的城市平均距离/sqrt(2)，空集0|[0,1]|
|nearest_remaining_distance|j到R去除j后的最近距离/sqrt(2)，空集0|[0,1]|
|progress|p，选择前计算|[0,1)|

U独立收到5个标量，不收到动作列表/H分数：

|字段|定义|范围|
|---|---|---|
|progress|同上|[0,1)|
|current_to_start|d(c,0)/sqrt(2)，首步0|[0,1]|
|mean_distance_current|c到R全部城市归一化距离均值|[0,1]|
|std_distance_current|同一距离向量的总体标准差|[0,.5]|
|previous_heuristic|首步−1；此前最大实际权重成员，同权最低编号|−1或[0,K−1]整数|

H签名`priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress)`返回有限标量，越大越优先。U签名`use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic)`返回`(mode, K个数的tuple)`。SELECT=0允许任意有限选择分数；MIX=1非负且恰1或2正项，先按最大值再按总和归一化。一成员使用原始动作分数；双成员各列min-max，常数列0且不重分权重。范围/极端值语义与旧FJSP函数做过对比。TSP执行通过独立问题模块实现，不引用FJSP状态/排程。

`candidates.py`是TSP闭合数值AST准入：单函数、标量局部变量、if/else、受限算术和abs/min/max/int/float/round。禁止导入、属性、索引、列表、循环、递归、外部资源；U只有终端输出tuple。非有限或超过1e100失败，pow字面整数0..8。进程有T30完整回传期限；不是任意Python的通用OS沙箱。

人工池5条公式（本轮手工设计，无外部算法来源）：−dc；−dc−.25(1−p)ds；−dc+.25(1−p)ds；−dc−.2mr；−dc+.15(mr−nr)。分别是NN、回起点偏置、早期远起点偏置、剩余均距、剩余离散度；变量对应表中字段。LLM池只生成10条，不复现Tier1/EoH-S集合演化。

## 从命令到实现

|目标|文件/函数|
|---|---|
|实例和独立split seed|`problems/tsp/data.py::generate`|
|几何、状态、动作、闭合路径|`problems/tsp/solver.py`|
|H/U签名与AST准入|`problems/tsp/candidates.py`|
|H生成/独立U上下文|`problems/tsp/prompts.py::build`的h/I1分支|
|CROSS/MUTATE|`core/operators.py`原usage指令；TSP只将选择关系称利用关系、排程评价称tour评价；无成绩反馈|
|父代/保留|`core/search.py::select_parents/survive`|
|评价/完整Fitness/首解复检|`problems/tsp/evaluation.py`|
|预算/暂停恢复/任务执行|`core/execution.py`；TSP `operations.Adapter.journal`接campaign全局账本|
|阶段/冻结H/P0/验证候选|`problems/tsp/campaign.py`|
|摘要和逐实例CSV|`campaign.summary`，不调用模型|

Fitness为完整声明集合`−mean(length/NN_length)`，越大越好，保留逐实例长度和比例；不是最优性gap或LB。任何实例失败整候选null。首解复检的完整路径、状态、动作、决策在内存精确比较，落盘路径和轨迹哈希及逐成员调用；共享30秒回传期限和独立2秒退出宽限。

## 操作命令

从TSP worktree根执行。新环境按requirements安装；本机复用既有Python3.12.10虚拟环境。

```sh
cd '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-tsp-pilot'
.venv/bin/python -B experiments/tsp/manage.py doctor
.venv/bin/python -B experiments/tsp/manage.py test
.venv/bin/python -B experiments/tsp/manage.py check --config experiments/tsp/configs/pilot-real.json
.venv/bin/python -B experiments/tsp/manage.py plan --config experiments/tsp/configs/pilot-real.json
```

help/check/plan只读配置，无API/求解。test为本地几何、语言、预算和身份测试，无真实API。prepare生成/冻结数据与协议，不求解。下面Mock运行完整固定流程（会本地求解，不调用模型），目录必须全新：

```sh
.venv/bin/python -B experiments/tsp/manage.py prepare --config experiments/tsp/configs/pilot-mock.json --directory runs/my-tsp-mock
.venv/bin/python -B experiments/tsp/manage.py run --directory runs/my-tsp-mock --background
.venv/bin/python -B experiments/tsp/manage.py status --directory runs/my-tsp-mock
.venv/bin/python -B experiments/tsp/manage.py summary --directory runs/my-tsp-mock --write
```

真实示例`pilot-real.json`记录本次用户已授权范围，不应将其当作未来新批次的许可。下面是本轮实际命令；**run会发送真实请求**，H10+IND20+EVO20，全campaign最多75尝试。凭据只从已有环境或指定既有env文件读取，值不输出、不复制。不要对同一授权另开新目录重置预算。

```sh
.venv/bin/python -B experiments/tsp/manage.py prepare --config experiments/tsp/configs/pilot-real.json --directory runs/tsp-pilot-20261026-v1
.venv/bin/python -B experiments/tsp/manage.py run --directory runs/tsp-pilot-20261026-v1 --allow-api --env-file '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.env.leafapi.local' --background
.venv/bin/python -B experiments/tsp/manage.py status --directory runs/tsp-pilot-20261026-v1
.venv/bin/python -B experiments/tsp/manage.py summary --directory runs/tsp-pilot-20261026-v1 --write
```

run按固定顺序完成：人工H train评价→生成H10→仅train筛5H→全部单H/双H等权基线→共同静态P0→IND两次/EVO两次→冻结最多5份候选→一次validation选择→冻结最终U→confirmation和transfer两策略评价。基线、生成、演化、评价统一由run按冻结任务清单执行，无隐藏额外请求。不提供任意调参续跑。

```sh
.venv/bin/python -B experiments/tsp/manage.py stop --directory runs/tsp-pilot-20261026-v1
# 等到phase=paused且writer锁移除；保持原账本、窗口及响应
.venv/bin/python -B experiments/tsp/manage.py resume --directory runs/tsp-pilot-20261026-v1 --allow-api --env-file '/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.env.leafapi.local' --background
```

正常暂停可按原checkpoint恢复；源/配置/数据/冻结H等哈希变化拒绝恢复。断电、未知请求、stopped/partial或残留锁不自动清理和重发，须先核对原账本和落盘证据。12小时原时窗不重置。后台是独立进程/file日志；不安装服务、不改全局电源，不保证合盖/休眠/断电后继续。

## 证据位置与解释

campaign根`Protocol.json`、数据Manifest、全局`API_attempts.json`、`wire_responses`、`H_frozen.json`、`P0.json`、`Validation_candidates.json`、`Final_frozen.json`及Frozen_artifacts回执。每阶段位于同级`runs/<campaign>--<stage>`，各自任务/锁/checkpoint/实际prompts/responses/evaluations，所有阶段共用一个API账本。

`results/Summary.md/JSON`、Stages.csv和Per_instance.csv给事实；人工和静态/P0投入单列。逻辑任务、API尝试、完整响应、完整有效任务和AST独立程序数量不同。Token未知单列，平台点数与实际费用无法核实保持null。冻结确认和100城市迁移分别报告，只有两次搜索重复不证明稳定优势。

本轮因说明文字花括号解析发生[显式执行修订v2](TSP_EXECUTION_REVISION_V2.md)。拟用续接目录为`runs/tsp-pilot-20261026-v2`（尚未启动，原窗口已过期）；v1保存前10份响应和**全局**API账本，v2所有新请求继续追加同一账本。本轮真实partial汇总使用v1；若获新时间窗口并正式建立续接，再使用v2。原v1不能直接在新源码下resume。两版解析准入及额外离线评价投入分开披露，不合并成未变更协议。


## 2026-10-28 完整实跑结果

真实v2已按获批新窗口完成，50逻辑/50尝试、未知0，未追加预算。H原10响应重用；最终冻结H全部来自人工池。四路径U各10份完整有效任务，一条EVO训练冠军超过P0，但validation选择共同静态参照，最终U与参照同AST，confirmation20/transfer10分别全部平局。完整表、成本、候选、原始归档及限制见[最终报告](../reports/tsp-pilot-20261028-complete/REPORT_ZH.md)。

当前只读查看已结束批次：

```sh
.venv/bin/python -B experiments/tsp/manage.py status --directory runs/tsp-pilot-20261026-v2
.venv/bin/python -B experiments/tsp/manage.py summary --directory runs/tsp-pilot-20261026-v2
```

不要再次run/resume或用剩余25次尝试增加候选。2026-10-27的partial报告保留为当时快照，不代表当前终态。初次操作的Mock目录示例仍可用于独立工程验收，真实生成需要相应新授权。
