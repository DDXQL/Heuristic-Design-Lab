# TSP迁移交付：实现已验收，真实小试partial

2026-10-27收尾。通用化与FJSP回归已完成；TSP实现、正确性、全流程Mock、暂停恢复和全局预算保护已完成。**真实小试未完成，不能报告IND/EVO或确认/迁移性能结论。**

## 实际实现与检查

- FJSP通用化提交c7402ca，原工作区仍为codex/h-usage-space；另建codex/tsp-pilot worktree继承该提交，没有复制整个项目。
- FJSP回归包括H0/等权×toy/已有认证Behnke1共4策略实例，完整动作、状态、排程、Fitness、首解复检及认证哈希一致；Behnke1 Cmax为106/100，与历史一致。
- TSP提交7056f18。二维单位方形欧氏完整图，城市0固定起止，闭合边计入，NN分母，五维动作/五维U状态；没有局部搜索。问题提示、准入和评价经Adapter接共享执行器。
- 初始11项、包装兼容修订后12项正确性/预算/身份检查通过。三角形、正方形、独立NN、同分、状态、MIX极值/常数列、完整Fitness、数据split及无重复均检查。
- 完整Mock跑通H→静态→IND2/EVO2→validation→confirmation/transfer。28条请求时安全暂停，恢复保留原时窗、全部响应和尝试。全局50/75边界测试含25次一次重试，总75次，重开账本后仍拒绝第51任务。
- 修订后的完整Mock续接重放50个已有任务，新增dispatch=0，旧账本条目和原时钟不变。

## 真实小试与修复

真实H池完成10逻辑任务/10尝试/10首份完整响应；模型都输出普通说明文字而非花括号说明，v1均记格式失败。原协议、响应、错误及当时人工后备H冻结保留。尚未发送任何U请求，也没有执行静态U筛选、validation、confirmation或transfer。

包装兼容修订只允许说明外层花括号可选，代码、AST语言、几何/评分/提示、选择机制不变。原10份响应离线重新解析均通过AST准入；**尚未进行这些LLM H的完整train评价，不能当成10份完整有效H。** 详见Parser_reassessment.json。没有重发H或补充预算。修订有新身份，不能伪称原协议未变。

原运行窗口截止于**2026-10-27 10:09:26（Asia/Manila）**；当前已过期，真实v2尚未创建/启动。未重置时钟或用新目录重开预算。保留剩余40逻辑任务和最多65次API尝试的原授权上限，未擅自消耗。

目前真实完成的求解仅5条人工H×20 train，共100程序实例、200首解/复检；LLM H只做离线AST准入。完整账本、Token及未知费用见Partial_closeout.json。实际平台点数、币种费用无法核实，保持null。

## 结果边界

框架的TSP接口、共享执行/记录/恢复链路已通过工程验收。当前真实证据不能回答生成U的质量或演化是否有效，不能给出最终静态表、两次IND/EVO结果或冻结确认成绩。没有强行选动态U，也没有因负向/缺失结果追加采样。

原FJSP四处未跟踪实验产物保留；GitHub名、远端和本地主目录未改，未推送。完整worktree检出发生mmap超时，改为稀疏检出代码；目录存在FileProvider标记，这与系统同步问题可能有关，不能据此推断代码损坏。

## 文件与操作

- docs/TSP_ADAPTER.md：定义、特征、代码地图、真实可执行命令。
- docs/TSP_PILOT_PROTOCOL_V1.md：事前固定协议；未覆盖。
- docs/TSP_EXECUTION_REVISION_V2.md：包装修订、原账本和时窗继承。
- Correctness_revision_v2_final.log、Continuation_acceptance.json：当前代码验收。
- Partial_closeout.json、Partial_raw_manifest.json、Partial_raw_evidence.tar.gz：真实partial、原始证据和往返校验。
- Real_pre_repair_source_snapshot.tar.gz：与原协议匹配的执行源码，当前源码不冒充旧绑定。

只读查看真实partial（不请求、不求解）：

```sh
.venv/bin/python -B experiments/tsp/manage.py summary --directory runs/tsp-pilot-20261026-v1
```

原窗口过期且旧源码绑定已变化，不应执行v1 resume。需要继续真实U小试时，须先明确新的时间窗口，并保留10/50逻辑、10/75尝试和全部原响应；不得仅改时钟、删锁或另开独立预算。当前没有后台进程继续调用模型。
