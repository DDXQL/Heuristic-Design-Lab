# Common routing V1：实现、离线验收与交接

日期：2026-10-29。工作区：`/Users/DDXQL/Developer/Heuristic-Design-Lab`。
分支：`codex/common-state-routing-v1`；起点：`aa83cac`，现场起始干净，未发现适用AGENTS。
本轮原型及T00—T08验收已完成；Notion同步完成状态以指定页面最新登记为准。

本轮真实生成API调用数为0；未启动正式搜索，未使用确认集。所有Mock分数均为工程测试的人工目标，不能说明优化质量提升。真实求解只使用手写H/U及合成开发实例。

## 实现结果

- 13项共同数值状态、历史类别/使用比例、可用性和缺失原因，FJSP/TSP分别提取。默认W=10，可关闭非construction特征组。
- 新ABI为`use_heuristics(state) -> int H token`，封闭AST、只读映射、命名字面字段和受限向量索引；每步先U，再仅由所选H评分，动作提交后更新历史，终态不调用U。
- 初始化区分LLM请求机制与导入P0。生成器本版只提供Mock；导入P0须恰好N条、代码去重、来源明确，并以当前接口重新评价。
- 每代固定父代和随机状态；每个父代一次交叉主体、一次独立变异；交叉伙伴从其余父代均匀抽取；有效唯一子代到代末统一参与精英选择。
- N/G、请求和CPU并发分别可配；提供两问题N5/N10、G20配置。单协调者持久化账本，工作线程不修改共享账本；CPU评价使用独立spawn进程，实例层串行。
- 有界批次分阶段生成/评价；支持安全暂停后恢复。不确定硬崩溃保留锁及预留，不自动重发；没有声称支持任意崩溃后的全自动恢复。
- 导出候选记录、历史最优、有效评价数、代末最优/均值、子代入选、行为组、父子关系和批次计时。失败/重复Fitness为空。

完整定义、命令和代码地图见[COMMON_ROUTING_V1.md](../../docs/COMMON_ROUTING_V1.md)。旧七/五参数、SELECT/MIX、单H和静态等权评价入口保留，旧common-v0仍禁用。新schema、ABI、协议、H顺序、数据、参考规则、种子、源码与执行设置进入独立身份；不升级或复用历史checkpoint。

## 逐项验收

| 任务 | 验收结果与证据 | 实现提交 |
| --- | --- | --- |
| T00 | 分支/基准/写入探针确认；起始无用户修改；ps受限，未认证机器空闲 | 起点aa83cac |
| T01 | 手算非对称FJSP及三角形TSP，尺度不变性、只读动作试算、缺失/窗口/终态边界；真实轨迹字段及相关/成本统计在samples | 91c1e3d |
| T02 | AST非法字段/写入/向量索引/返回类型拒绝；真实小例新旧单H完整解一致；身份隔离及重新评价测试通过 | b5cc6b3、5d750c9 |
| T03 | N3/N5/N10覆盖；交叉伙伴不同、变异不使用交叉子代；重复/无效/失败及初始化上限明确处理 | 5d750c9 |
| T04 | 3代及N5/N10×20代Mock完成；暂停恢复的任务、RNG、种群一致；G2子代实际进入G3父代 | 5d750c9、6683025 |
| T05 | 乱序响应实际发生但选择不变；API1/CPU4独立限额；在途安全暂停排空且不重复发送；真实求解串并一致 | 4c8209a |
| T06 | M1 Air/8GB/8核固定8候选、两问题各2实例，1/2/4并发均32遍首解/复检；零超时且语义一致 | 4c8209a；最终代码6683025 |
| T07 | candidates/generations CSV、lineage/summary JSON，Mock明确标注；旧入口回归；部分初始化冠军排序修复 | 5d750c9、6683025 |
| T08 | 综合70项测试通过；源码/协议/证据再核对；文档、配置、报告分步提交；Notion逐项登记 | 本报告所在文档提交及Notion登记 |

实现提交依次为：`91c1e3d`状态、`b5cc6b3`路由、`5d750c9`演化、`4c8209a`并发评价、`6683025`导出修复。报告提交不会改变已绑定源码。所有提交均在本地，未推送。

## 可核查的样例与谱系

| 证据 | 路径（相对本报告目录） |
| --- | --- |
| FJSP完整状态与U/H调用轨迹、动作及解 | `samples/fjsp-traces.json` |
| TSP完整状态与U/H调用轨迹、游程 | `samples/tsp-traces.json` |
| 13字段分布、缺失、常量、相关性及提取成本 | `samples/state-diagnostics.json` |
| Mock五份运行验收与原始运行路径 | `mock/acceptance.json` |
| 三代父子关系 | `mock/n5-g3-serial/lineage.json` |
| 冻结父代、伙伴、Prompt输入身份和RNG前后状态 | `mock/n5-g3-serial/plans/G003.json` |
| 实际乱序及稳定提交顺序 | `mock/reordered-batch-receipts.json` |
| N5/N10二十代曲线数据 | `mock/n5-g20/generations.csv`、`mock/n10-g20/generations.csv` |
| 固定测速输入/H/U/硬件 | `benchmark/fixed-inputs.json` |
| 最终测速及逐档语义摘要 | `benchmark/benchmark.json`、`benchmark/width-{1,2,4}.json` |
| 综合检查 | `verification.log` |

Mock正式证据运行目录为`runs/common-routing-v1-20261029-acceptance-final/`；含原始Prompt、响应、账本、checkpoint和评价。恢复连接后已逐份执行`evolution_v1.check`，五份均为completed，代数分别3/3/3/20/20，身份均通过。

N5×20：初始化5次Mock请求、演化200次；N10×20：初始化10次、演化400次。Mock目标有意使新代胜出，用于谱系流转验收，不能拿该最优/均值上涨证明演化有效。行为组在Mock为5个人工进度探针的所选H序列，在真实评价为声明实例上的所选H序列；不是完整动作等价类或互补收益证据。

## 固定工作量测速

Apple M1，MacBookAir10,1，8GB，8逻辑核，Python3.12.10，macOS15.3.2。
每档相同8个手写U、两问题各2个合成实例；FJSP每例90工序、TSP每例70城市。每候选每实例首解/复检各一次，合计32遍/档。没有API等待；墙钟包含spawn、接收和退出认证。

| CPU并发 | 墙钟秒 | 候选/秒 | 相对串行加速 | 单worker峰值MiB | 超时/无效 | 与串行完整语义 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 2.700 | 2.963 | 1.00× | 38.89 | 0/0 | 一致 |
| 2 | 1.548 | 5.167 | 1.74× | 36.44 | 0/0 | 一致 |
| 4 | 0.952 | 8.407 | 2.84× | 37.86 | 0/0 | 一致 |

单worker峰值为实际进程自报RSS；width×peak只是内存包络，不能称系统总峰值。`sysctl vm.swapusage`被权限拒绝；前后`vm_stat`原样保留，可观察全系统换页计数，不能把它归因于本任务。ps亦受限，因此未认证无其他负载。

较大测速实例上，状态提取占worker求解时间约40%；早期12规模样例每步约66–69μs，占比约64–68%。这提示需要评估状态成本，但不支持按这几个小例删特征。样例中字段没有全程常量；TSP动作比例与进度的冗余等相关关系已导出，不代表统计泛化结论。

建议本地日常CPU并发先用2，专门批任务可试4；4是本次最快档位，尚无长时稳定性结论。配置默认仍为1，以保持显式选择。当前工程验证无需集群；正式多问题×多方案×多种子的总工作量若长期占机，再根据真实train求解吞吐申请CPU服务器。这里的秒级合成耗时不能估计train21正式总时长，API并发收益本轮也未实测。

## 实际检查命令

```sh
PYTHONPATH=code:.:tests .venv/bin/python -B -m unittest test_common_state_v1 test_common_routing_v1 test_coverage_evolution_v1 test_common_execution_v1 test_state_contracts test_generic_search test_tsp_adapter test_tsp_integration test_fjsp_usage_v2 test_fjsp_usage test_problem_layout
# 70 tests / 16.616s / OK，见verification.log

.venv/bin/python -B tools/verify_common_routing_v1.py --run-root runs/common-routing-v1-20261029-acceptance-final --report reports/common-routing-v1-20261029/mock
.venv/bin/python -B tools/common_routing_benchmark.py --output reports/common-routing-v1-20261029/benchmark
.venv/bin/python -B experiments/manage.py --problem tsp --state-schema constructive-common-v1-tsp preview --config experiments/common/configs/tsp-n10-g20.mock.json
git diff --check
```

以上目录已存在，不要原样重跑覆盖；复现时更换输出目录。完整原始测速worker轨迹保存在本地`benchmark/workers-*/`，通过本目录.gitignore排除体积较大的重复副本；摘要和固定输入纳入Git，证据清单记录原始文件SHA。此前版本的运行与测速也保留在runs中，没有删除。

中途连接断开曾导致无法核实最终命令；本次恢复后读取实际日志确认70项及最终测速均完成，没有将不确定状态当通过。

## 限制与下一步

1. 生成只开放Mock，默认H是按声明顺序冻结的3个手写规则，绝非历史训练排序的10H。真实模型接入、正式H和训练数据接入须另行冻结并验证。
2. 新协议采用T30完整首解＋复检行接收、另2秒退出宽限。不是两次各T15；不与旧T15成绩直接比较，正式协议须明确选择。
3. 丰富状态有显著观测开销；动作增量不是因果奖励。共同字段不表示同一U已跨问题泛化。
4. 硬崩溃不确定在途不自动重发；API与CPU采用独立有界池但未做流水线重叠。
5. 后续先冻结正式H来源/顺序、训练划分、Prompt、共同P0、预算、种子、超时与并发，再做特征组对照、父代覆盖对照、演化对独立生成及独立重复。正式预算仍待另定。
