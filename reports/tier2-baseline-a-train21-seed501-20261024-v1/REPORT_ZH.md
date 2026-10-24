# Tier 2 Baseline-A 中文总报告

补充决策解读、便携数据复用及交付阶段发现的缓存语义别名边界见[DECISION_ZH.md](DECISION_ZH.md)；数据文件索引见[README.md](README.md)。以下定量主体由冻结报告工具生成。

完整有效单H 10/10；完整有效等权WS 39/45；已登记/覆盖成员对 45/45。
Best Single：H0，-2.111804960626。Best有效等权对：H0_H1_WS，-1.983144294915。
H0/H1在有效对中排名1。实例级Single-H Oracle：-2.032977256531。

## 协议与审计

固定当前H0–H9顺序、train21、seed501、原LB与mean(−Cmax/LB)。单成员SELECT沿用原始评分；双成员各自对全部合法动作min–max归一化，常量列零，再0.5/0.5加权；精确同分沿原动作顺序首最大值。
共预先冻结10个单H、45个无序双H等权WS。没有新权重、状态、算子、Prompt、LLM请求或演化，也没有访问validation11/test28。
审计复用10个单H和4个成员对，扣除294项/588遍。新批只评价其余41对，最多861项/1722遍；全部策略清单和缺失项在Protocol.json、Cache_audit.json。
旧单H来自封存的原生两遍结果及相同数据/执行器源码；旧额外成员对来自四对网格，逐实例物理复检一致。H01另有V2正常终态认证，并与早期网格全部21实例Cmax/score/物理哈希一致。
旧缓存没有全部保留现代PID/exit0回执，不追溯伪造。旧计划中的10个非评价链配置/工作流/传输模块已变化，核心排程、解释器、原生runtime和相关缓存工具未变；逐项差异及排除依据见Cache_audit.json。
缓存静态H/常量U和排程器不含随机行为；旧生成seed不被冒充为新seed501运行。新进程明确seed501。缓存成本为历史测量，不含当前进程认证开销。
新评价复用冻结V2内核、V4收集器：每实例两遍共享poll(15)，收齐全部结果后独立最多2秒正常退出宽限。完整成绩仍要求前后加载身份、全部文件边界、确认终态exit0。已确认普通超时整策略null并继续独立策略；未知身份/终态/账本即停止。
本轮不保存完整动作评分矩阵，不进行额外轨迹求解；所有物理排程和成本从原两遍求解留证。此留证负担与旧V2不同，不能由跨批耗时差异断言算法加速。

## A1：完整单H排序

|排名|单H|Fitness|来源|
|---:|---|---:|---|
|1|H0|-2.111804960626|cache|
|2|H1|-2.119981806737|cache|
|3|H2|-2.142188696710|cache|
|4|H3|-2.170288898659|cache|
|5|H4|-2.391583985708|cache|
|6|H5|-2.401071577675|cache|
|7|H6|-2.415857292821|cache|
|8|H7|-2.477265237832|cache|
|9|H8|-2.524607580906|cache|
|10|H9|-2.561149825665|cache|

## A2：45对完整结果表

|有效排名|成员对|Fitness|来源|完整实例|异常|
|---:|---|---:|---|---:|---|
|1|H0_H1_WS|-1.983144294915|cache|21/21||
|2|H0_H3_WS|-1.993659698983|cache|21/21||
|3|H1_H5_WS|-2.057292594879|new|21/21||
|4|H1_H4_WS|-2.060923722306|new|21/21||
|5|H3_H5_WS|-2.074533777089|new|21/21||
|6|H3_H4_WS|-2.076124528439|new|21/21||
|7|H1_H6_WS|-2.124057477050|new|21/21||
|8|H1_H3_WS|-2.124549102185|new|21/21||
|9|H1_H2_WS|-2.124674458180|new|21/21||
|10|H3_H6_WS|-2.132408992883|cache|21/21||
|11|H2_H3_WS|-2.136194450157|new|21/21||
|12|H1_H7_WS|-2.154948014859|new|21/21||
|13|H3_H7_WS|-2.166121595478|new|21/21||
|14|H0_H6_WS|-2.180888168363|new|21/21||
|15|H3_H9_WS|-2.194084587910|new|21/21||
|16|H1_H9_WS|-2.196740799415|new|21/21||
|17|H0_H5_WS|-2.201502078263|new|21/21||
|18|H0_H7_WS|-2.212355537932|new|21/21||
|19|H3_H8_WS|-2.225120423952|new|21/21||
|20|H1_H8_WS|-2.231940985310|new|21/21||
|21|H2_H6_WS|-2.238421171168|new|21/21||
|22|H2_H8_WS|-2.252245383752|new|21/21||
|23|H2_H7_WS|-2.280506308343|new|21/21||
|24|H0_H2_WS|-2.331453043177|cache|21/21||
|25|H0_H9_WS|-2.352611036054|new|21/21||
|26|H0_H8_WS|-2.369297989631|new|21/21||
|27|H2_H9_WS|-2.405107769549|new|21/21||
|28|H7_H9_WS|-2.413268296992|new|21/21||
|29|H6_H9_WS|-2.455191871820|new|21/21||
|30|H7_H8_WS|-2.461931568452|new|21/21||
|31|H6_H7_WS|-2.465743695704|new|21/21||
|32|H6_H8_WS|-2.513321624337|new|21/21||
|33|H2_H4_WS|-2.544435338087|new|21/21||
|34|H5_H8_WS|-2.575255866840|new|21/21||
|35|H2_H5_WS|-2.579608491174|new|21/21||
|36|H4_H8_WS|-2.580232644520|new|21/21||
|37|H5_H9_WS|-2.593204373084|new|21/21||
|38|H8_H9_WS|-2.598554877760|new|21/21||
|39|H4_H9_WS|-2.600866728012|new|21/21||
|—|H0_H4_WS|null|new|20/21|Timeout|
|—|H4_H5_WS|null|new|20/21|Timeout|
|—|H4_H6_WS|null|new|13/21|Timeout|
|—|H4_H7_WS|null|new|20/21|Timeout|
|—|H5_H6_WS|null|new|13/21|Timeout|
|—|H5_H7_WS|null|new|20/21|Timeout|

超过Best Single的有效对6个；超过H0/H1的0个；超过B2冠军的0个；超过Single-H Oracle的2个。

这里的最佳仅指完整有效、已评价固定策略中的最佳；超时对没有完整质量成绩，不参与排序。即使全部45项任务都覆盖，也不把含null的扫描称为全45对质量最优，更不是全部权重或动态U空间最优。

## A3：单H实例级事后Oracle

Oracle逐实例选10个认证单H中最小Cmax/LB；同实例LB相同，等价于最小Cmax。得到-2.032977256531，相对最佳固定单H差0.078827704095，在12个实例严格改善。
Oracle_instances.csv同时保留全部10H的Cmax、所有并列最佳成员及展示成员（并列取最小编号）。Oracle_member_counts.csv区分展示计数与并列参与计数，避免把同分偏好当成成员独占贡献。
这是使用结果标签的事后诊断，不可部署为在线U，也不是整个动态策略空间的理论上界；融合动作可产生任一单H未产生的完整排程。Pair_complementarity.csv另列每对相对最佳分量、两单H事后包络及全单H Oracle差值。

## 与已有LLM-U比较

|方法|Fitness|完成程度/搜索范围|
|---|---:|---|
|B1 B/g0000/000006|-2.115159624700|1代；19逻辑任务；非等预算|
|B2 B/g0001/000000|-1.982226488242|2代；20逻辑任务；非等预算|

B1核实为Recovery-B的P1完成、P2未运行：19次历史API尝试、14个完整有效新候选，最后一个候选超时后原协议因缺结束身份停止。旧初始化目录另有未完成inflight，本轮未恢复或改写。
B2为固定H01的两代动态权重搜索：20次历史API尝试，19个新且完整有效候选、1重复，另含16个新增静态权重点和人工初始种群。B1自由10H与B2固定H01的初始化、空间、父代和完成程度不同。
本轮55项静态覆盖、14项历史复用与41项新评价，不能与这些LLM搜索预算直接等同。最终策略质量比较不证明枚举搜索比LLM演化更高效。逐实例参照、差值与胜负平保留在CSV；原冠军未经重新求解。

## 成本、异常与完整性

`{'reserved_new_evaluations': 861, 'reserved_new_solve_passes': 1722, 'recorded_instance_start_markers': 847, 'recorded_first_start_markers': 847, 'recorded_recheck_start_markers': 847, 'certified_new_pairs': 841, 'new_strategies': 41, 'cached_strategies': 14, 'cached_evaluations_avoided': 294, 'cached_solve_passes_avoided': 588, 'new_API_requests': 0, 'new_evolution_runs': 0, 'new_primary_wall_seconds': 1523.1800552495988, 'new_certified_prefix_first_seconds': 707.0140961551806, 'new_certified_prefix_recheck_seconds': 705.2210512029706, 'cached_historical_first_seconds': 136.46997004572768, 'cached_historical_recheck_seconds': 134.64224475884112, 'new_confirmed_timeouts': 6, 'failed_instance_internal_cost': 'unknown when killed; not zero filled; included in parent wall time', 'comparison_scope': 'descriptive timing only; legacy caches and modern local evaluations nonconcurrent; no speed claim'}`

All_instances_1155.csv保留所有55×21行：成功、无效策略成功前缀、失败和未到达分别标记；后两类Cmax/score为null，整策略Fitness始终null。失败实例内部首解/复检完成量及H调用可能未知，不填成0。
所有缓存结果及新认证结果在certified_results/；新进程身份/生命周期在process_evidence/；Source_manifest.json给出本地原始证据路径和哈希。历史源及新源码身份均再次检查，旧冻结文件不改写。

## 后续基线建议

Budget-matched Static Search：预先固定与LLM-U相同的候选尝试、完整FJSP评价和时间上限，从45对中按预定随机顺序或随机无放回采样，比较相同已消耗预算下的best-so-far；本次全扫描冠军只作较充分覆盖参照。缓存命中也要区分逻辑评价预算与新增计算成本。
Random U：冻结合法程序生成分布、深度/长度、SELECT/MIX及支持集/权重分布，沿用同一语言、解释器、失败和重复规则；匹配尝试与FJSP预算并保留失败，不额外给一方强初始种群。
GP-U：使用相同七状态、H集合、SELECT/WS语义及大小限制，冻结初始化、变异/交叉、选择、重复和超时规则；匹配评价预算，另报程序执行成本。不要把Borda等新算子只开放给某一臂。
后续随机/搜索重复种子及评估口径需另行预注册；train21用于开发，当前排名和Oracle不是独立泛化验证。已有test28不充当新确认集。本轮没有执行这些后续搜索。

## 文件与复现

排名：Single_ranking.csv / Pair_ranking_45.csv；完整逐实例：All_instances_1155.csv；认证来源：Sources.csv / Source_manifest.json；Oracle：Oracle.json / Oracle_instances.csv；协议：Protocol.json；命令：Commands.md。
