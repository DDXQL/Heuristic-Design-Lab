# 共同构造状态与纯路由 V1

日期：2026-10-29。来源：Notion《Heuristic-Design-Lab 改进执行清单》。
T09更新：独立终端、数据/H接入与受限真实传输见[终端独立运行实验](终端独立运行实验.md)。下文仅Mock的限制为T00—T08阶段记录；T09已提供受双重授权及固定预算保护的真实路径，尚未做线上验收。

本实现接续 `aa83cac`，不覆盖历史协议或启用旧 common-v0 草案。

## 冻结定义

规范源为 `core/constructive_state.py::SPEC`，包含13个数值字段和历史元信息。
FJSP：D=工序数，B=各工序最大加工时间之和，C=各job最大可选机器数之和。
TSP：D=n−1，B=n×Dmax，C=n−1。闭合回0是强制边，不调用U，也不写可选决策历史。
所有动作增量均为 `[C(s+a)−C(s)]/B`；它不是质量奖励。
FJSP只用已有ready时间规则算动作起止，不复制排程、不续排、不调用H。

历史默认W=10，动作提交后更新；最近窗口不足就用已有记录，单样本总体标准差=0。
首步历史字段为None，availability=false；单动作best_gap不可用，少于两条历史switch不可用。
可关action_cost/trajectory/usage组；关组字段仍在packet内但None+mask+原因，不填真实0。
construction组在本版本必须保留。类别编号仅在本问题冻结H顺序内有意义。
零尺度、空/非法实例预检拒绝，拒绝规则不依赖U或成绩。终态没有观察或U调用。

## 实现决策

V1.1实现细化：U签名为`use_heuristics(state)`，返回内置int的H编号。
state为递归只读映射、usage_fraction为不可变向量。AST只允许命名字面字段、
availability的命名字面字段及usage_fraction的范围内字面索引；无循环/属性/导入/任意容器访问。
元数据和missing_reason用于trace，不向U开放。缺失值由U先检查mask再使用，运行时错误按无效候选处理。
H评分和动作同分顺序沿用问题旧入口，旧SELECT/MIX及历史状态保持原样。

新入口、缓存和检查点独立版本化，不把common请求转交legacy求解器。
新评价身份须包含规范、特征组、W、H有序身份、数据、评价器源码、种子、超时、并发和机器。
具体运行证据及限制见本轮reports；Mock指标不得解释为算法收益。

V1.2执行细化：新评价采用现有通用生命周期的T30“首解+复检完整行接收”上限，
随后独立2秒退出宽限。它不是每次首解/复检各T15，也不与历史T15质量直接比较；
不会因机器繁忙临时改变上限。新协议显式记录该范围，正式质量实验前须重新冻结。
初始化前预检实例兼容性和LB/NN参考，不按候选结果筛实例。

API与CPU并发独立限额；单个协调者先预留一批逻辑请求，工作线程只返回结果，
再由协调者按任务顺序落盘、去重、提交。当前以有界批次分阶段生成/评价，
不宣称已经实现生成和评价的流水线重叠。CPU评价在独立spawn进程中执行；实例层保持串行。
安全暂停排空当前批次；硬崩溃留下锁/不确定预留，拒绝自动重发，需人工核验。
T00—T08交付阶段生成器只开放Mock。`initialization=llm`表示走请求→解析→评价的初始化机制，
本轮提供的是Mock transport；正式模型接入和付费预算留待另行授权。

## 可运行入口

在仓库根目录运行。以下命令均不创建真实API客户端。配置文件的20代是准备值，
`preview`不执行；只有显式`run`才运行Mock工程验证。

```sh
.venv/bin/python -B experiments/manage.py --problem fjsp --state-schema constructive-common-v1-fjsp doctor
.venv/bin/python -B experiments/manage.py --problem tsp --state-schema constructive-common-v1-tsp preview --config experiments/common/configs/tsp-n10-g20.mock.json
.venv/bin/python -B experiments/common/manage.py --problem fjsp prepare --config experiments/common/configs/fjsp-n5-g20.mock.json --run-dir runs/my-common-mock
.venv/bin/python -B experiments/common/manage.py --problem fjsp run --run-dir runs/my-common-mock --max-tasks 18
.venv/bin/python -B experiments/common/manage.py --problem fjsp resume --run-dir runs/my-common-mock
.venv/bin/python -B experiments/common/manage.py --problem fjsp export --run-dir runs/my-common-mock
```

另一终端可用`pause --run-dir ...`请求排空当前批次。`run`仅接受prepared，
`resume`仅接受安全paused；已有目录、来源变化、旧版本、残留锁或不确定在途均拒绝自动覆盖/重发。
暂停期间的等待不算算法工作；本轮验收脚本另记整个调用墙钟。

`initialization=import`时附`--p0-file`，要求恰好N条、每条有非空`source`和新版
`candidate={description,code,key,abi}`。可运行样例为
`experiments/common/configs/fjsp-n5-g20.import.json`与
`experiments/common/fixtures/p0-n5-handwritten.json`。
这5条仅对应默认3个手写H；替换H后必须重新校验key及评价，不能借旧Fitness。
导入和LLM初始化均使用当前状态重评；未满N明确报告initialization_incomplete。

```sh
.venv/bin/python -B experiments/common/manage.py --problem fjsp prepare --config experiments/common/configs/fjsp-n5-g20.import.json --p0-file experiments/common/fixtures/p0-n5-handwritten.json --run-dir runs/my-common-import
.venv/bin/python -B tools/common_routing_samples.py --output reports/my-common-samples
.venv/bin/python -B tools/verify_common_routing_v1.py --run-root runs/my-common-acceptance --report reports/my-common-acceptance
.venv/bin/python -B tools/common_routing_benchmark.py --output reports/my-common-benchmark
```

Mock演化默认`evaluation_mode=mock`，人工目标刻意推动代际更替以测试谱系。
设为`solve`则生成仍是Mock，但评价运行真实FJSP/TSP构造器和完整首解/复检。
固定工作量测速仅用手写U，不做搜索。默认数据仅合成开发实例；无确认集调试入口。
默认H是3个手写工程规则，按声明顺序冻结，绝非历史训练排名H0–H9。
Python适配接口`prepare(...,h_members=...,instances=...)`可显式传入符合当前合成预检协议的来源；
正式训练数据/模型的适配和预算属于下一版受控实验，不混入本轮验收。

API和CPU并发在配置中分别设置`api_concurrency`/`evaluation_concurrency`。
默认都为1；两池互不强制同宽。候选并发，实例不叠加并发。
`generation_request_cap=2*N*G`是演化请求上限，初始化候选/请求另计。
generation失败/重复不补生成，Fitness留空；初始化可在独立上限内继续收集。
导出`candidates.csv`、`generations.csv`、`lineage.json`、`summary.json`。
CSV中的batch耗时是共享批次耗时，不能逐候选累加当总墙钟；批次原始计时在batch-receipts。

## 代码边界

| 边界 | 文件 |
| --- | --- |
| 字段、缺失、历史与分组 | `core/constructive_state.py` |
| 命名状态AST、编译与Prompt | `core/routing.py` |
| 两问题只读动作观察 | `problems/{fjsp,tsp}/common_state.py` |
| 两问题纯路由求解 | `problems/{fjsp,tsp}/routing.py` |
| 合成数据、手写H与独立预检 | `problems/routing_fixtures.py` |
| 初始化、冻结计划、选择与账本 | `core/evolution_v1.py` |
| spawn评价与T30认证 | `core/routing_evaluation.py`，复用`core/lifecycle.py` |
| 科研结果导出 | `core/evolution_export.py` |

以上code路径均相对`code/heuristic_design/`。旧`core/execution.py`和B1循环原样保留。
新增文件通过新版本源码身份绑定；完成的运行不因后来改源码而悄悄续跑。
