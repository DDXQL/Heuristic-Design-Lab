# Baseline-A Supplemental T30 与静态基线定稿

九策略完整有效9/9；六个原超时组合补齐6/6；综合有效等权对45/45。
协议SHA256：`ea3c8f8d8005c5ceff5fc9c9e44b9c1270e7e88b6209b3ec5b47395eccd78e32`。原Baseline-A六个null及全部旧记录保持不变。

## 协议、验收与证据

依据df28b3d审计，冻结原九策略与顺序、H0–H9代码和排名编号、train21、seed501、未取整V5-LB和mean(−Cmax/LB)。仅SELECT及逐成员当前合法动作minmax后0.5/0.5 WS，原同分规则未变。
独立T30版本使用接收线程，对完整消息接收及反序列化执行30秒期限；首解、复检、结果写入/发送及最后after身份证据共用期限。该机制比原poll(15)后可能阻塞recv更严格，因此不是只改变15→30一个工程变量。阶段计时也增加少量开销。
接收完整21行后另等最多2秒正常退出，不接受迟到成绩；失败时按原0.05秒join、terminate/kill清理。必须PID与源身份对应、接收线程停止、明确终态；成功要求after匹配、exit0及完整复检一致，普通超时只认证无效。未知终态/身份/复检/历史输出/预算不一致立即Stop，不自动重试。
Offline_acceptance.json记录合成进程/部分消息/迟到/退出/身份/预算恢复Mock、V1兼容toy以及既存3800状态矩阵重放；正式评价前冻结全部源文件与旧证据SHA。未运行Tier 1/2演化、真实LLM或holdout。
新批九项全部从空排程完整重评，没有用旧成绩抵扣同期评价。所有完整成功及已认证超时都保留原始行、before/after（如存在）、lifecycle、boundary、进度和网络/数据守卫。已完成账本任务跳过，未知reservation或孤立证据停止，不重复消耗。

## 九策略结果

|策略|完整Fitness|原Baseline-A Fitness|完整实例|主评价墙钟秒|
|---|---:|---:|---:|---:|
|H0_H1_WS|-1.983144294915|-1.983144294915|21/21|23.146|
|H0_H4_WS|-2.191303992561|null|21/21|56.432|
|H4_H5_WS|-2.416265877110|null|21/21|55.330|
|H0|-2.111804960626|-2.111804960626|21/21|25.803|
|H4_H6_WS|-2.357833634962|null|21/21|81.956|
|H4_H7_WS|-2.349527485685|null|21/21|68.285|
|H0_H3_WS|-1.993659698983|-1.993659698983|21/21|27.051|
|H5_H6_WS|-2.352164384561|null|21/21|78.666|
|H5_H7_WS|-2.345892018761|null|21/21|66.008|

## 同期参照与历史一致性

对三个参照的63/63项进行了逐实例比较；Cmax、score与对应排程指纹一致性：True。另核对六对原成功前缀106项。所有共同历史行的结果和可比哈希在每个新策略结束后验证，不一致将停止后续正式评价。
H0历史原生结果的deterministic_schedule_sha256对应新commit_sequence_sha256（同为原Schedule的asdict摘要）；不将FusionResult容器摘要或不同物理序列化哈希混比。H0/H1及H0/H3另比物理排程和commit哈希。H0/H3与H0旧值来自认证历史缓存，不能称三条基线均曾同期重新跑过T15现代执行器；本节为科学输出一致性，不能归因期限改变导致提速。
Old_new_comparison.csv给出逐实例原新Cmax、哈希与两遍耗时；All_instances_189.csv包含对H0/H1、B2逐实例score差，Comparisons.csv列完整策略胜负平及delta_F。

## 45对综合质量排名

综合表保留原39个有效对，用本批结果补充六个原无效对；这是一张显式标注来源的质量表，不是全45对同期T30资源实验。原Baseline-A/T15新评价及历史缓存证据边界继续保留，新T30控制结果另表报告，不覆盖旧表。
|有效排名|成员对|Fitness|来源|
|---:|---|---:|---|
|1|H0_H1_WS|-1.983144294915|Baseline-A-original|
|2|H0_H3_WS|-1.993659698983|Baseline-A-original|
|3|H1_H5_WS|-2.057292594879|Baseline-A-original|
|4|H1_H4_WS|-2.060923722306|Baseline-A-original|
|5|H3_H5_WS|-2.074533777089|Baseline-A-original|
|6|H3_H4_WS|-2.076124528439|Baseline-A-original|
|7|H1_H6_WS|-2.124057477050|Baseline-A-original|
|8|H1_H3_WS|-2.124549102185|Baseline-A-original|
|9|H1_H2_WS|-2.124674458180|Baseline-A-original|
|10|H3_H6_WS|-2.132408992883|Baseline-A-original|
|11|H2_H3_WS|-2.136194450157|Baseline-A-original|
|12|H1_H7_WS|-2.154948014859|Baseline-A-original|
|13|H3_H7_WS|-2.166121595478|Baseline-A-original|
|14|H0_H6_WS|-2.180888168363|Baseline-A-original|
|15|H0_H4_WS|-2.191303992561|Supplemental-T30|
|16|H3_H9_WS|-2.194084587910|Baseline-A-original|
|17|H1_H9_WS|-2.196740799415|Baseline-A-original|
|18|H0_H5_WS|-2.201502078263|Baseline-A-original|
|19|H0_H7_WS|-2.212355537932|Baseline-A-original|
|20|H3_H8_WS|-2.225120423952|Baseline-A-original|
|21|H1_H8_WS|-2.231940985310|Baseline-A-original|
|22|H2_H6_WS|-2.238421171168|Baseline-A-original|
|23|H2_H8_WS|-2.252245383752|Baseline-A-original|
|24|H2_H7_WS|-2.280506308343|Baseline-A-original|
|25|H0_H2_WS|-2.331453043177|Baseline-A-original|
|26|H5_H7_WS|-2.345892018761|Supplemental-T30|
|27|H4_H7_WS|-2.349527485685|Supplemental-T30|
|28|H5_H6_WS|-2.352164384561|Supplemental-T30|
|29|H0_H9_WS|-2.352611036054|Baseline-A-original|
|30|H4_H6_WS|-2.357833634962|Supplemental-T30|
|31|H0_H8_WS|-2.369297989631|Baseline-A-original|
|32|H2_H9_WS|-2.405107769549|Baseline-A-original|
|33|H7_H9_WS|-2.413268296992|Baseline-A-original|
|34|H4_H5_WS|-2.416265877110|Supplemental-T30|
|35|H6_H9_WS|-2.455191871820|Baseline-A-original|
|36|H7_H8_WS|-2.461931568452|Baseline-A-original|
|37|H6_H7_WS|-2.465743695704|Baseline-A-original|
|38|H6_H8_WS|-2.513321624337|Baseline-A-original|
|39|H2_H4_WS|-2.544435338087|Baseline-A-original|
|40|H5_H8_WS|-2.575255866840|Baseline-A-original|
|41|H2_H5_WS|-2.579608491174|Baseline-A-original|
|42|H4_H8_WS|-2.580232644520|Baseline-A-original|
|43|H5_H9_WS|-2.593204373084|Baseline-A-original|
|44|H8_H9_WS|-2.598554877760|Baseline-A-original|
|45|H4_H9_WS|-2.600866728012|Baseline-A-original|

Best Single：H0，-2.111804960626；Best Equal-Weight Pair：H0_H1_WS，-1.983144294915；Single-H Oracle：-2.032977256531。
综合有效对中超过H0/H1的0个，超过历史B2的0个，超过Best Single的6个。
历史B2：-1.982226488242，两代20次逻辑请求/19个完整有效候选；历史B1已知P1最佳：-2.115159624700，19次逻辑尝试/14个完整有效候选，P2未完成。来源为原封存Historical_references；不追认缺失现代进程回执、不声称预算或策略空间完全匹配。
最佳仅限这10个固定单H与45个等权对，不是全部权重或动态U的最优。Oracle只用原10H逐实例事后最小Cmax，单H数据未变时Oracle不变；不可部署，也不是动态或融合空间理论上界。枚举最终质量不证明比LLM搜索更有效率。

## 成本与异常

|策略|两遍构造秒|主评价墙钟秒|最慢实例双解秒|退出等待秒|
|---|---:|---:|---:|---:|
|H0_H1_WS|22.596|23.146|4.939|0.0359|
|H0_H4_WS|55.857|56.432|14.975|0.0194|
|H4_H5_WS|54.706|55.330|15.834|0.0224|
|H0|25.202|25.803|5.884|0.0196|
|H4_H6_WS|81.434|81.956|22.479|0.0204|
|H4_H7_WS|67.708|68.285|18.909|0.0395|
|H0_H3_WS|26.492|27.051|5.746|0.0285|
|H5_H6_WS|78.105|78.666|21.420|0.0213|
|H5_H7_WS|65.452|66.008|18.080|0.0212|

预留189项／378遍；实际首解启动189、复检启动189；主评价合计482.677秒。额外诊断求解0、缓存抵扣0、API请求0、演化0。
Costs_9.csv列CPU、评分、融合、RSS与主墙钟；Phases_189.csv区分首解、复检、检查、写盘、after、发送与父接收，Lifecycle_9.csv单列退出等待和终态。构造时间已包含排程器内部合法性检查，不能把CPU/墙钟重叠分项相加成总时间。未完成失败内部耗时不得填零；只认原始启动标记与父等待。
九策略同期串行，描述其差异；跨历史批次的包装、监控和环境不同，不能把耗时变化全归于算子/H复杂度，也不对单次计时作显著性或普遍性能结论。

## 下一轮：只设计，不执行

Budget-matched Static Search最小协议、缓存与合法率计账、B1/B2公平性及独立编号置换敏感性方案见NEXT_STATIC_SEARCH_PROTOCOL_ZH.md。此处不启动搜索、不抽取任何新候选、不运行LLM演化。

## 复现

参见REPRODUCE.md。run目录保存原始证据，报告目录保存认证结果副本、逐实例表、来源清单与本报告。Protocol.sha256为正式评价前的冻结值；源码/旧记录受协议SHA清单保护。
