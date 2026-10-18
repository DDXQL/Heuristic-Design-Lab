# 固定成员对与权重校准：训练网格及复现说明

本批为**人工预先规定的参数搜索**，不是LLM生成或演化。使用10条旧冻结H、七状态、原21train及原MIX执行规则。12候选未进入任何历史种群，不修改原始运行记录。最终机制结论单列在`Mechanism_note.md`，全部候选和失败见`Grid_summary.csv`。

## 结果入口

- [一页机制结论](Mechanism_note.md)：完整训练收益、代价、证据边界及唯一下一轮建议。
- [全部12格及表图](Results.md)、[机器可读汇总](Grid_summary.csv)、[252条实例成绩](Grid_instances.csv)。
- [对H0/两个组成成员/两成员事后参照的1008行配对](Instance_comparisons.csv)、[全部胜负平及实例名单](Win_loss_tie.csv)。差值Cmax=网格−参照，负值更好；score=网格−参照，正值更好。
- [权重间排程比较](Weight_schedule_comparisons.csv)、[12组汇总](Weight_schedule_summary.csv)。物理排程相同与Cmax相同分别判断。
- [最佳源码](Best_candidate.py)、[最佳完整评价及排程](Best_candidate_result.json)、[身份说明](Best_candidate_identity.json)、[最佳逐实例参照表](Best_candidate_instances.csv)。最佳文件是已评价候选的相同副本，不是追加评价。
- [历史组合/旧冠军参照表](Historical_comparison.csv)及[历史身份](Historical_references.json)，均不重评。
- [完成标记](Evaluation_complete.json)、[分析摘要](Analysis.json)、最终`Verification.json`及[results/](results/)原始本地评价输出。

## 冻结方案

- 成员对按顺序为(H0,H1)、(H0,H2)、(H0,H3)、(H3,H6)。前三对包含强固定参照；最后一对来自旧有效单编号冠军的成员使用线索，事先不认定互补或收益。
- 每对按(0.25,0.75)、(0.50,0.50)、(0.75,0.25)生成合法受限语言源码；其他八项权重为0。执行器按原规则归一化，对两条h当前全部合法动作分数分别min–max，再加权求和。
- 12候选的完整源码、AST代码键、源码SHA-256及顺序事先存入[sources/](sources/)和[Plan.json](Plan.json)；参数见[Config.json](Config.json)。U虽然接收七状态，此处输出为常量，不把任何状态值或成员编号解释为质量等级。
- 每候选最多一次原21train完整评价，最多252个候选—实例、成功时504遍排程；首次求解和确定性复检共用每实例15秒期限。任一失败则该候选完整fitness为null，保留成功前缀，不加时、不补跑。没有第三遍观察回放。
- 固定h参照只读复用H0/H1/H2/H3/H6的完整原评价，见[Fixed_H_reused.json](Fixed_H_reused.json)。没有再求解固定h、旧单编号冠军或B3/B5消融，也没有验证集/测试集访问、新实例或模型请求。

## 身份、数据及计分

H来源为`runs/v22-gpt61-select-mix-301-20261014-v1/H_frozen.json`及绑定的`Conditional_H_reassessment.json`。核对资产seal、原H引用、10条代码键/顺序和21个文件身份，保留原来源及审查；研究用途沿原固定H条件研究，不创建新的技术审查。

旧冠军只作为带来源标签的参照：`single-ID-gpt61-paired-training-20261014-v1`的`r201/INIT`、`INIT/init/000004`。核对其导出源码、checkpoint代码键、原21实例成绩及H顺序后保存[Historical_references.json](Historical_references.json)。历史组合参照来自已完成的`reports/usage-v22-mechanism-ablation-301-20261017-v1`；不拿不同批次的搜索冠军直接推断本次网格或LLM搜索的因果收益。

逐实例`score=-Cmax/LB`，`LB=max(max_j w_j, sum_j w_j/M)`、`w_j`为每个工序最短可选加工时间之和，LB不取整。fitness是完整21个score的均值，越大越好。每个组成成员单独评价的成绩与MIX进行共同口径比较。

`best_fixed_component`表示该对中**完整训练fitness较高的固定h**；`pair_envelope`表示事后逐实例选择两条固定h中Cmax较短者。后者是需要已知完整结果的描述性参照，不是当前U的可部署规则，也不是逐步组合上界。

## 排程与成本记录

已有主评价的结果哈希包含成员决策，不能用来直接判断不同权重是否产生相同排程。本批通过临时、仅在子进程内生效的记录适配，调用未改动的生产执行器两遍，将现有返回结果中的排程交给原worker验收；不修改原结果对象、不追加求解、不记录影子动作。

- `physical_schedule`：按(job,operation)排序的`[job,operation,machine,start,end]`，编号均从0开始，含makespan。
- `physical_schedule_sha256`：仅对上述机器分配及起止时间求哈希，不含权重或成员历史。
- `commit_sequence_sha256`：保留原排程提交顺序的独立哈希，便于区分“提交顺序不同”与“物理排程不同”。
- 两次既有求解的物理排程必须一致。序列化和哈希在求解计时结束后的发送阶段完成；主评价墙钟及实例期限仍包含收集和记录开销。
- 每实例记录首次求解、复检、组合处理、h评分时间及两遍认证h调用。失败实例未认证的部分计时和调用数保持未知；前缀调用不能当完整调用成本。历史固定h未记录调用数，保留NA。

本页训练在第一页`single-ID-gpt61-fair-seed201-v2`四组完成、阶段`SEARCH_COMPLETE`且无运行锁后启动；完成凭证和哈希事先冻结，并在每个候选前复核。不读取账户或账单。操作系统资源没有独占，历史参照计时与本轮时间仅作描述性比较，不给出精确速度倍数结论。

## 执行及观察

以下命令已按阶段执行；`prepare`要求新目录，`evaluate`通过独占启动标记阻止重复。**不要删除标记后重跑本批。**

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:tests:. .venv/bin/python -B -m unittest test_usage_mechanism_ablation test_fixed_mixture_grid -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/calibrate_fixed_mixtures.py prepare
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/calibrate_fixed_mixtures.py evaluate
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code:. .venv/bin/python -B tools/calibrate_fixed_mixtures.py report
```

这些是本地校验、训练求解和结果制表命令；不包含网络模型或账户查询。`results/*.started.json`表示该候选已进入执行，不可因结果暂缺而自动重复；`results/*.json`是完整结果或成功前缀/失败；`Evaluation_complete.json`标识12个候选均已尝试，不等于12个均有效。

表格及图的原始数据保留在本目录。绘图复用原ReportLab工具新增的目录参数：

```bash
PYTHONDONTWRITEBYTECODE=1 /Users/DDXQL/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -B tools/plot_usage_ablation.py --grid-directory reports/usage-fixed-pair-weight-grid-20261018-v1
```

它只读已保存的结果并输出SVG，不求解。PNG由现有本地sharp运行时从SVG转换，不安装网络依赖。报告、图及机器可读数据在最终复核后提交推送；不上传凭证或原始账单。
