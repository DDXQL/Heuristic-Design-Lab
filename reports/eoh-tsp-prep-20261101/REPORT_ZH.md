# EoH正式对照与TSP新版实验准备交付

2026-11-01。独立工作树：`/Users/DDXQL/Developer/Heuristic-Design-Lab-eoh-tsp-prep`；分支`codex/eoh-tsp-prep-20261101`，基于主项目已提交HEAD `0ce75da`。没有合并回主项目、推送、调用真实API、创建付费授权或启动正式搜索。

## 两份方案及结论

- [EoH精简方案](../../docs/EOH_COMPARISON_PREP_20261101.md)：历史canonical固定规则的当前train21重评已完成，Fitness **−2.012187450378091**、21例有效、API=0。原规则、协议与评价结果SHA已只读核验，证据见`eoh-check.json`。它源自DeepSeek-flash/40候选/validation选优，不能当当前模型同预算训练结果。
- [TSP精简方案](../../docs/TSP_ROUTING_PREP_20261101.md)：状态与纯路由已有；真正缺口是TSP的`member_sequence`、compact准入、任务Prompt、显式数据路径和可读导出。本轮已补齐这些缺口。

给定H的路由收益，应主要比较恒选各H、train最佳单H、简单/随机路由和状态消融；H生成成本作为共同沉没成本单列。端到端则须把H生成/筛选、U初始化/搜索全部计入同一预算，与重新训练单H的EoH比较，并统一选优和独立重复。等权MIX是历史附加参照，不再是纯路由最贴近的结构对照。预算和选优未定，EoH训练入口尚未改造，不可启动。

## 可修改位置

|文件|用途与主要参数|
|---|---|
|`experiments/common/run_tsp_routing.py`顶部|默认CONFIG、RUN_ROOT、RUN_PREFIX；默认是固定离线小试|
|`experiments/common/configs/tsp-routing-smoke.fixed.json`|3个固定手写U、train前2例、CPU=1、compact；无生成|
|`experiments/common/configs/tsp-routing-smoke.mock-solve.json`|Mock生成、真实求解；N=2/G=2，初始化最多4、演化8；并发2，仅工程验证|
|`experiments/common/configs/tsp-routing-singles.fixed.json`|5条恒选H，完整train20；API=0，由用户启动|
|`experiments/common/configs/tsp-routing-real.pending.json`|真实搜索待定模板：N/G、初始化/演化/总尝试上限、两个并发、seed、H/data、window、provider；`real_requests_authorized=false`|
|`experiments/common/configs/eoh-comparison.pending.json`|EoH总预算、H/U分配、seed、模型、表达空间和选优；未决定项为null，training_enabled=false|

配置中的H/data/P0相对**配置文件所在目录**解析。`state_schema`应与problem匹配；当前固定T30、每候选每实例首解+复检两遍。不更改B的入口参数、P0、授权或运行记录。运行后的resume读取原Protocol，忽略新顶部参数和配置；改配置只影响新运行。

## 终端命令

下面均在新工作树执行，使用现有共享虚拟环境的本地链接。无需访问iCloud或复制虚拟环境。

```sh
cd /Users/DDXQL/Developer/Heuristic-Design-Lab-eoh-tsp-prep

# 只读检查；不生成U、不评价候选、不发API。TSP会计算确定性NN参考。
.venv/bin/python -B experiments/common/check_eoh_comparison.py --check-only
.venv/bin/python -B experiments/common/run_tsp_routing.py --check-only
.venv/bin/python -B experiments/common/run_tsp_routing.py --check-only --config experiments/common/configs/tsp-routing-smoke.mock-solve.json
.venv/bin/python -B experiments/common/run_tsp_routing.py --check-only --config experiments/common/configs/tsp-routing-real.pending.json

# 固定路由小试：新建时间戳目录并自动导出；无搜索、无API。
.venv/bin/python -u -B experiments/common/run_tsp_routing.py

# 工程搜索小试：Mock生成+真实求解；不是LLM实验结果。
.venv/bin/python -u -B experiments/common/run_tsp_routing.py --config experiments/common/configs/tsp-routing-smoke.mock-solve.json

# 5个恒选成员的完整train20参照：固定求解，无API（本轮尚未代跑）。
.venv/bin/python -u -B experiments/common/run_tsp_routing.py --config experiments/common/configs/tsp-routing-singles.fixed.json
```

入口会打印实际运行目录，默认普通启动每次创建新目录；需要终端同时留存日志可使用`| tee`。查看、暂停、恢复和导出示例：

```sh
# 替换为入口打印的实际目录。检查已完成小试可直接使用下列路径。
TSP_RUN=runs/tsp-routing-offline-smoke-20261101
.venv/bin/python -B experiments/common/run_tsp_routing.py --status "$TSP_RUN"
.venv/bin/python -B experiments/common/run_tsp_routing.py --export "$TSP_RUN"

# 仅针对正在运行/已安全paused的将来运行：pause只提交控制请求，排空当前批次后再resume。
# .venv/bin/python -B experiments/common/run_tsp_routing.py --pause "$TSP_RUN"
# .venv/bin/python -u -B experiments/common/run_tsp_routing.py --resume "$TSP_RUN"
```

completed运行不得resume。发生未知在途请求或源码绑定变化时按原门禁停止，不能删除锁或换源码强行续跑。真实模板即使加`--allow-api`也会在创建运行目录前被当前false授权拦截。未来确定协议并明确授权后，新的真实启动命令形式如下；当前不可启动：

```sh
# 协议和授权尚未确定；不是当前可执行的付费指令。
# .venv/bin/python -u -B experiments/common/run_tsp_routing.py --config experiments/common/configs/tsp-routing-real.pending.json --allow-api
```

## 工作量与速度边界

|配置|候选上限|程序×实例行上限|首解+复检遍数上限|真实API|
|---|---:|---:|---:|---:|
|固定小试|3|6|12|0|
|Mock小试|初始化≤4+演化8|24|48|0|
|5单H/train20|5|100|200|0|
|真实待定模板|初始化≤20+演化200|4400|8800|≤220，未授权|

失败、重复消耗槽位，不自动补预算。Mock通常只需2个有效初始化，实际量可能小于上限。H生成不在此TSP模板中；H为历史给定资产。

实测固定小试6行、12遍：纯构造首解/复检累计 **0.144秒**，3候选串行评价累计 **0.613秒**（含进程/认证等）；不是整个CLI端到端计时。按此线性外推8800遍仅纯构造约106秒，不能据此承诺真实搜索耗时：API延迟、初始化有效率、进程/SHA/磁盘、并发及B占用均另计。每行T30是完整首解/复检生命周期上限，不能用这次快小试证明所有实例会在30秒内完成。

## 实际验证与交付

- 22项相关检查通过：新增6项TSP接入检查、既有5项路由、8项代际/预算、3项执行检查。包括full/compact物理解一致、城市同分、两种归一化、只调用选中H、n−1序列、无闭合边U调用、暂停恢复、并发一致、真实未授权拦截，以及FJSP相关回归。日志在本目录`checks.log`及`*-regression.log`。
- 实际train前2例的小试仅固定3条手写路由，**3候选/6行/12遍**，全部成功、首解复检哈希相等，compact不保存动作表和状态轨迹，每行保留49项H编号。没有正式搜索或API。结果只说明链路可运行，不是效果改善结论。
- 小试原始证据保存在本工作树`runs/tsp-routing-offline-smoke-20261101`；精简结果同步在本目录`smoke-per_instance.csv`、`smoke-summary.json`、`smoke-champion.py`。完整导出含candidates/generations/lineage/per_instance/champion，Protocol与worker回执继续用于恢复和认证。
- 新Prompt可读样本：`tsp-INIT-prompt.txt`。20个训练文件只从既有归档逐个提取并校验SHA，未解包全项目/全运行或提取训练外集合。复现输入准备可运行`tools/prepare_tsp_routing_inputs.py`，其输出已交付，无需每次重做。

## 实际阻塞与边界

1. EoH正式比较的预算、模型、表达空间、独立重复、选优协议仍未定；旧EoH入口不具备本轮要求的HTTP尝试预算/T30复检协议，尚不能视为正式对照训练入口。只读check可用，训练代码需协议确定后小范围适配。
2. TSP真实配置仅为可检查、默认拦截的参数模板，220次是示例上限，不是批准预算。下一轮还要决定是否重新生成H、完整研究规模及独立重复；当前5H全人工，不能包装成LLM集合演化产物。
3. 本轮以主项目`0ce75da`为基础，继续其Fitness生存逻辑；没有迁入B分支的行为优先生存、后续transport/恢复实验改动。若要求TSP复现B的完整协议，需另行迁入和专项验证，不能将本次结果当作B在第二问题上的重复。
4. 只准备历史train20和其前2例；训练外评价入口/新留出数据尚未准备。旧validation/confirmation/transfer已有使用史，不能称全新测试集。最终冻结和训练外选优不得通过修改train标签绕过。
5. 本工作树复用既有Python环境；EoH证据check默认只读主项目历史运行。新TSP资产已自足于本树，无需B路径。原主项目和B未切分支、未改文件、未暂停进程；不评价B此刻是否健康运行。

未进行传输打包、Windows传输或核验，也未清理任何历史资产。以后按AGENTS把ZIP放Developer/transfer-outbox，并在用户确认传输和Windows核验后才考虑对应清理。
