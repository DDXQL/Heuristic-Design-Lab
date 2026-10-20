# B2-1：固定H0/H1两代权重程序演化

**阶段B–E全部完成。** 原协议、H、七状态、Prompt、模型参数、21train及共享15秒期限均未改；未访问validation/test。

## 基线与新候选

|策略|Fitness|21实例Cmax合计（非优化目标）|首次求解秒|复检秒|首次h评分调用|
|---|---:|---:|---:|---:|---:|
|H0（缓存固定h）|-2.111804960626|4524|14.103|13.135|未知|
|人工等权／21点网格冠军|-1.983144294915|4047|10.446|10.440|1999648|
|最佳新动态U B/g0001/000000|-1.982226488242|4050|12.334|12.746|2065864|

21个静态点全部有效；新增16点，复用α=0、0.25、0.5、0.75、1的原成绩。全部点见Candidates.csv及Fixed_weight_curve.svg；所有逐实例makespan见Instances.csv，逐实例计时与h调用见Instance_costs.csv。

最佳新U的Fitness比等权高0.000917806673，即平均Cmax/LB降低约0.0463%。逐实例10胜、7负、4平；Cmax合计4050，反而比等权4047高3，因为既定目标按各实例LB归一化后取平均。

该程序在3800次实际决策中α范围为[0.262746, 0.539620]，每步实际启用H0/H1，主导成员切换83次，19/21个实例物理排程与等权不同。它读取progress、remaining_work_mean/std及machine_ready_mean/std；未读取candidate_pair_ratio和previous_heuristic。

本批19个新且完整评价的U均在实际轨迹中改变权重，没有新常量U冠军。重复槽位B/g0001/000008与B/g0001/000007源码键相同；不补发、不重评。另有源码不同但21train物理排程相同的程序：19个有效新U形成16组，详见Observed_physical_groups.json；这不是普遍程序等价证明。

## 实际冠军源码

```python
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    ready_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    alpha = 0.5 + 0.3 * work_dispersion - 0.2 * progress * (1.0 - work_dispersion) - 0.1 * ready_dispersion
    return (1, (alpha, 1.0 - alpha, 0, 0, 0, 0, 0, 0, 0, 0))
```

## 代际变化与谱系

|种群|最佳Fitness|平均Fitness|完整成员及Fitness|
|---|---:|---:|---|
|P0|-1.983144294915|-2.073590322686|MANUAL/init/alpha_050: -1.983144294915<br>MANUAL/init/alpha_075: -2.066604642453<br>MANUAL/init/alpha_025: -2.086415908698<br>MANUAL/init/alpha_100: -2.111804960626<br>MANUAL/init/alpha_000: -2.119981806737|
|P1|-1.983144294915|-1.994290586721|MANUAL/init/alpha_050: -1.983144294915<br>B/g0000/000008: -1.985820305266<br>B/g0000/000006: -1.989505154465<br>B/g0000/000004: -2.004589259822<br>B/g0000/000002: -2.008393919139|
|P2|-1.982226488242|-1.983572272131|B/g0001/000000: -1.982226488242<br>B/g0001/000007: -1.982858694373<br>MANUAL/init/alpha_050: -1.983144294915<br>B/g0001/000002: -1.984815941562<br>B/g0001/000003: -1.984815941562|

第一代10个子代全部有效，4个进入P1；冠军仍为人工等权，故第一代没有新冠军改进。第二代确从P1抽父代：5次交叉均包含全部4个第一代新成员，3次变异以第一代新成员为父代，共23个父代引用；其余7次引用人工等权。第二代9个有效、1重复，4个第二代子代进入P2，其中2个超过等权。完整20槽父子关系见Lineage.csv；P0/P1/P2全部成员见Population_members.csv。

全部20个实际Prompt已按真实父代源码重建并逐字节核对，seed501父代抽样及P1/P2生存选择已从原结果独立复核。父代Fitness只影响外部生存／种群，未显式发送给模型。跨代继承和本批改进已观察到，但不能据此证明显式数值反馈有效，也不能单独归因于多代优于等预算其他搜索。

## 预算、评价与成本

20个逻辑候选／20次真实API尝试／20份完整响应；重试0，pending0，接口失败0，非法源码0，评价失败0，源码重复1。合法生成率20/20=100%，新且完整有效率19/20=95%，重复率1/20=5%。实际完成35次新增完整训练评价（16静态＋19新U），735个候选—实例评价、1470遍求解，无重启、额外初始化、诊断回放或补发。

新增评价的首次求解合计452.547秒，复检453.510秒；h评分调用分别为78,116,600和78,116,600次。API输入Token 53,502、输出6,097，无未知usage。实际费用unknown/null，账户／价格／账单查询为0；未把未知费用填成0。

计时使用perf_counter，为求解／复检墙钟耗时，未采集CPU进程秒。H0端点复用历史固定h计时，不含U接口开销，h调用数未知；等权也是历史缓存。本批新U与缓存基线并非同期精确速度对照，不将秒数差直接解释为算法效率因果变化。冠军首次h调用比等权约多3.31%，两者每步都用两成员，调用量仍会随排程路径与合法动作数变化。

## 证据边界与下一步

本批证明：在固定H0/H1、原接口和21train条件下，真实LLM两代演化产生了动态权重程序，通过外部选择实现了子代继承，并有新动态U小幅超过人工等权和有限21点静态网格。人工等权相对固定h的主要收益是既有基线收益，不能记为LLM新发现。

尚未证明：超过所有可能固定权重、动态性本身的独立因果收益、稳定的多种子收益、泛化、七维状态的充分性，或两代演化比其他等预算搜索更优。未做新的消融、续排或独立评价；不由权重变化或主导切换数推断其更好。

下一步最值得验证：冻结本批动态冠军及α=0.5，在预先登记、未参与本批选择的独立数据上做配对评价，检验约0.0463%的微小训练优势是否保持，并继续完整披露退化实例。本轮不执行。

## 复现与原始证据

原始目录：`runs/h01-state-weight-search-seed501-batch-v3-20261020/`。请求尝试、完整响应、Prompt、执行授权、协议及事件的只读副本位于evidence/；全部原始评价、物理排程及checkpoint保留在原始目录并另作压缩备份。Original_result_hashes.json逐项绑定原始文件，Execution_audit.json记录核验结论。未复制任何凭证或原始账单。

唯一正式入口：`tools/h01_weight_local.py`。本次顺序运行`grid --run-dir runs/h01-state-weight-search-seed501-batch-v3-20261020`、`search --run-dir runs/h01-state-weight-search-seed501-batch-v3-20261020 --env-file <本机既有凭证路径>`，最后以文档Python运行同入口`report --run-dir ...`。既定恢复命令仍为同目录同一`search`；本批已完成，勿再次启动。
