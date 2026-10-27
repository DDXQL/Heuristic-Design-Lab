# 回应师兄上次建议：U的演进与真实代码示例

**回应要点：已经从“返回单个H编号”推进到“给10个H打分、按状态选成员、双成员动态加权、同一程序切换SELECT/MIX”。MAX/MIN/Borda则已做独立机制验证，尚未进入正式LLM-U闭合搜索语言。**

if/else是控制流写法，不是策略空间定义。一个没有if的函数可以连续调整两成员权重；一个有很多if的函数也可能在全部实际状态里只选同一个H。要看输出含义、执行器和实际轨迹，不数分支。

## 共同接口和执行语义

当前U的七维输入是`progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic`。进度为已调度工序数/总工序数；U不是动作评分函数，不能直接看到所有候选动作或调用H。

H收到每个合法工序-机器动作的加工时长、剩余工作量/工序数、作业/机器就绪、开始/结束时刻；返回动作分数。执行器枚举每个未完成作业下一工序的可选机器，不生成非法动作再惩罚。

- 旧`select_heuristic(...) -> int`：返回H编号，所选H按原始分数排序合法动作。
- 当前`use_heuristics(...) -> (0, ten_scores)`：对10个H给出成员选择分数，取最高者；**这些不是10个动作分数，也不是融合权重**。成员同分取较小编号。
- 当前`use_heuristics(...) -> (1, ten_weights)`：恰有1或2个正权重，非负有限；host归一化权重。只有1个活跃成员时按原始H分数，不做双成员min-max。
- 两成员WS：各自对当前全部合法动作的H评分独立min-max，常量列变0，再归一化加权相加，取最高动作；动作同分依原枚举顺序，即job/machine稳定顺序。
- 独立Fusion返回字符串算子和向量，由单独可信执行器解释；并非把字符串返回值塞进现有LLM闭合接口就能用。

代码入口：`code/fjsp_usage/usage_v2/execution.py::decode_output/normalize_scores/combine_scores/construct_usage_schedule`；旧索引兼容在`LegacyAdapter`。下面为原文源码，不是讲解伪代码；副本不作为独立实验入口。


## A_早期单成员索引：INIT/init/000003

- 实验：single-ID-gpt61-paired-training-20261014-v1 / seed201。
- 原始源码：[INIT_init_000003.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/runs/single-ID-gpt61-paired-training-20261014-v1/candidate_exports/INIT_init_000003.py>)，函数`select_heuristic`，原文件第1-2行。
- 本次原文副本：[A_早期单成员索引.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/A_早期单成员索引.py>)；源码SHA见`真实代码证据.json`。
- 原始LLM输出：[INIT_init_000003.response.txt](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/runs/single-ID-gpt61-paired-training-20261014-v1/candidate_exports/INIT_init_000003.response.txt>)；已核对代码AST一致，换行/括号排版不冒充算法变化。
- 实际行为证据：21完整实例；函数常量返回2，选择H2；不根据状态变化。
- 完整Fitness：-2.142188696710。行为扩展不等于质量改善。

```python
def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    return 2
```

## B_动态SELECT：B/init/000006

- 实验：B1-NS Recovery-B / train21 / seed501。
- 原始源码：[B_init_000006.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/b1-ns-recovery-B-execution-20261023/U_sources/B_init_000006.py>)，函数`use_heuristics`，原文件第1-8行。
- 本次原文副本：[B_动态SELECT.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/B_动态SELECT.py>)；源码SHA见`真实代码证据.json`。
- 原始LLM输出：[B_init_000006.txt](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/b1-ns-recovery-B-execution-20261023/responses/B_init_000006.txt>)；已核对代码AST一致，换行/括号排版不冒充算法变化。
- 完整train21实际行为：SELECT 3800步、MIX 0步、双成员 0步；实际成员[1, 5]；支持计数`{'1': 3762, '5': 38}`。
- 完整Fitness：-2.115159624700。行为扩展不等于质量改善。

```python
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if candidate_pair_ratio < 0.5 and remaining_work_mean < 0.25:
        return (0, (0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    if remaining_work_std > 0.2 and machine_ready_std < 0.1:
        return (0, (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    if progress > 0.75 and machine_ready_mean > 0.25:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))
    return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
```

## C_动态双成员MIX：B/g0000/000004

- 实验：B1-NS Recovery-B / train21 / seed501。
- 原始源码：[B_g0000_000004.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/b1-ns-recovery-B-execution-20261023/U_sources/B_g0000_000004.py>)，函数`use_heuristics`，原文件第1-6行。
- 本次原文副本：[C_动态双成员MIX.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/C_动态双成员MIX.py>)；源码SHA见`真实代码证据.json`。
- 原始LLM输出：[B_g0000_000004.txt](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/b1-ns-recovery-B-execution-20261023/responses/B_g0000_000004.txt>)；已核对代码AST一致，换行/括号排版不冒充算法变化。
- 完整train21实际行为：SELECT 0步、MIX 3800步、双成员 3800步；实际成员[5, 8]；支持计数`{'5,8': 3800}`。
- 完整Fitness：-2.466314273721。行为扩展不等于质量改善。

```python
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    readiness_dispersion = machine_ready_std / (machine_ready_mean + machine_ready_std + remaining_work_mean)
    workload_dispersion = remaining_work_std / (remaining_work_mean + remaining_work_std)
    weight_8 = 0.15 + 0.55 * readiness_dispersion - 0.1 * workload_dispersion
    weight_5 = 1.0 - weight_8
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, weight_5, 0.0, 0.0, weight_8, 0.0))
```

## D_SELECT_MIX切换：B/g0000/000007

- 实验：B1-NS Recovery-B / train21 / seed501。
- 原始源码：[B_g0000_000007.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/b1-ns-recovery-B-execution-20261023/U_sources/B_g0000_000007.py>)，函数`use_heuristics`，原文件第1-10行。
- 本次原文副本：[D_SELECT_MIX切换.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/D_SELECT_MIX切换.py>)；源码SHA见`真实代码证据.json`。
- 原始LLM输出：[B_g0000_000007.txt](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/b1-ns-recovery-B-execution-20261023/responses/B_g0000_000007.txt>)；已核对代码AST一致，换行/括号排版不冒充算法变化。
- 完整train21实际行为：SELECT 21步、MIX 3779步、双成员 1316步；实际成员[8, 9]；支持计数`{'8': 21, '8,9': 1316, '9': 2463}`。
- 完整Fitness：-2.549881652452。行为扩展不等于质量改善。

```python
def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    if previous_heuristic == -1:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0))
    if machine_ready_std > 0.2:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0))
    if remaining_work_std > 0.2:
        return (0, (0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0))
    weight_9 = min(1.0, max(progress / 0.75, (1.0 - candidate_pair_ratio) / 0.65))
    weight_8 = 1.0 - weight_9
    return (1, (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, weight_8, weight_9))
```

## B补充_连续成员打分：INIT/init/000005

- 实验：v22-gpt61-select-mix-301-20261014-v1 / seed301。
- 原始源码：[INIT__init__000005.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/docs/usage-space/real-gpt61-301/INIT__init__000005.py>)，函数`use_heuristics`，原文件第1-36行。
- 本次原文副本：[B补充_连续成员打分.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/B补充_连续成员打分.py>)；源码SHA见`真实代码证据.json`。
- 原始LLM输出：[INIT__init__000005.txt](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/docs/usage-space/real-gpt61-301/Actual_responses/INIT__init__000005.txt>)；已核对代码AST一致，换行/括号排版不冒充算法变化。
- 完整train21实际成员参与步数：`[919, 689, 0, 157, 2035, 0, 0, 0, 0, 0]`，合计3800步。
- 完整Fitness：-2.225194303278。行为扩展不等于质量改善。

完整函数较长，保存在上方源码/副本；现场不需要展示全部10个公式。以下仅为原文末行，不能作为独立可运行函数：

```python
    return (0, (s0, s1, s2, s3, s4, s5, s6, s7, s8, s9))
```

## E1_MAX_MIN固定策略：H0_H1_MAX / H0_H1_MIN

- 实验：独立Fusion V2/V3机制实验；人工固定策略，非LLM搜索。
- 原始源码：[execution.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/code/fjsp_usage/fusion_v2/execution.py>)，函数`fixed_policy`，原文件第69-75行。
- 本次原文副本：[E1_MAX_MIN固定策略.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/E1_MAX_MIN固定策略.py>)；源码SHA见`真实代码证据.json`。
- 实际行为证据：对应H01固定策略均完整train21；同状态机制记录见既有图07。

```python
def fixed_policy(pair, operator, size=10):
    if (type(pair) is not tuple or len(pair) != 2 or pair[0] >= pair[1]
            or any(type(i) is not int or not 0 <= i < size for i in pair)
            or operator not in OPERATORS):
        raise ValueError('ordered distinct in-range fixed pair and fusion operator required')
    vector = tuple(.5 if i in pair else 0. for i in range(size))
    return lambda *state: (operator, vector)
```

## E2_MAX_MIN动作融合：H0_H1_MAX / H0_H1_MIN

- 实验：独立Fusion V2/V3机制实验；人工固定策略，非LLM搜索。
- 原始源码：[execution.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/code/fjsp_usage/fusion_v2/execution.py>)，函数`fuse_scores`，原文件第37-66行。
- 本次原文副本：[E2_MAX_MIN动作融合.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/E2_MAX_MIN动作融合.py>)；源码SHA见`真实代码证据.json`。
- 实际行为证据：对应H01固定策略均完整train21；同状态机制记录见既有图07。

以下是函数末段原文，仅展示融合分支；完整校验仍在原模块：

```python
    if operator in ('MAX', 'MIN'):
        if weights[support[0]] != weights[support[1]]:
            raise UsageOutputError('unweighted extrema require equal indicators')
        operation = max if operator == 'MAX' else min
        scores = tuple(operation(info['normalized'][i][a] for i in support)
                       for a in range(length))
    return scores, info
```

## E3_Borda固定策略：H0_H1_BORDA

- 实验：独立Fusion V2/V3机制实验；人工固定策略，非LLM搜索。
- 原始源码：[execution.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/code/fjsp_usage/fusion_v3/execution.py>)，函数`fixed_borda`，原文件第40-45行。
- 本次原文副本：[E3_Borda固定策略.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/E3_Borda固定策略.py>)；源码SHA见`真实代码证据.json`。
- 实际行为证据：对应H01固定策略均完整train21；同状态机制记录见既有图07。

```python
def fixed_borda(pair,size=10):
    if (type(pair) is not tuple or len(pair)!=2 or any(type(i) is not int or not 0<=i<size for i in pair)
            or pair[0]>=pair[1]):
        raise ValueError('ordered distinct frozen member pair required')
    vector=tuple(.5 if i in pair else 0. for i in range(size))
    return lambda *state:('BORDA',vector)
```

## E4_Borda秩融合：H0_H1_BORDA

- 实验：独立Fusion V2/V3机制实验；人工固定策略，非LLM搜索。
- 原始源码：[ranking.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/code/fjsp_usage/fusion_v3/ranking.py>)，函数`borda_scores`，原文件第30-37行。
- 本次原文副本：[E4_Borda秩融合.py](</Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research-h-usage-space/reports/师兄讨论材料-20261027-v1/真实代码/E4_Borda秩融合.py>)；源码SHA见`真实代码证据.json`。
- 实际行为证据：对应H01固定策略均完整train21；同状态机制记录见既有图07。

```python
def borda_scores(columns, support):
    if len(support) != 2 or len(set(support)) != 2:
        raise ValueError('exactly two distinct members required')
    ranks = {i: borda_twice(columns[i]) for i in support}
    n = len(ranks[support[0]])
    if any(len(ranks[i]) != n for i in support):
        raise ValueError('aligned action columns required')
    return tuple(sum(ranks[i][a] for i in support) for a in range(n)), ranks
```

## 怎样解释这几段程序

- A：原始LLM函数只有`return 2`，虽然接收状态，但没有使用状态。旧批次不是当前10H自由搜索的重复。
- B：`B/init/000006`代码提到H1/H4/H9/H5，实际只用了H1与H5（3762/38步）。这既证明有动态成员选择，也暴露了“源码里有分支，不代表轨迹覆盖”。额外的v2.2程序确实输出10个连续成员分数，但最后仍只选一个H。
- C：`B/g0000/000004`没有if，按机器/工作离散度改变H5/H8权重，3800步都双成员，3779次相邻权重改变；Fitness−2.466314273721，质量并不好。可清楚展示“表达能力已经扩展，但搜索质量仍是问题”。
- D：`B/g0000/000007`首步SELECT H8，每实例一次模式切换；其余3779步MIX，其中1316步真双成员、2463步退化为H9单成员。H5/H6分支在已观测轨迹没有启用。不能把3779个MIX输出全部记成双成员融合。
- E：MAX/MIN先对各H列使用原V1归一化，再逐动作取极值；Borda对原始有限H分数取中秩整数点并相加，最终仍稳定argmax。Borda不是先min-max再依数值间距加权。V2/V3策略ID是固定机制实验标识，没有相应“LLM生成的MAX候选ID”。

## 能力对照与当前边界

|能力|早期U|当前正式LLM-U|独立机制实验|未来候选扩展，尚未证明|
|---|---|---|---|---|
|返回一个成员编号|支持旧int接口|用SELECT分数向量表达|兼容适配|无须仅为改写if/else另造机制|
|为多个成员打分，再选一个|旧int接口不直接表达|v2.2真实LLM程序已支持/执行|不依赖Fusion|需评估实际成员覆盖，而不只看向量长度|
|两个成员加权求和|旧单成员接口不支持|MIX真实生成并完整求解；可动态权重/成员|固定WS强基线已有|超过2成员不是本轮已实现能力|
|按状态切换SELECT/MIX|旧接口不支持|Recovery-B真实U已执行两模式|不等于动态切换MAX|不能把未访问分支当效果|
|MAX/MIN/Borda|不支持|当前闭合LLM-U未开放这些字符串算子|固定成员/算子及WS-Borda规则已评价|若进入LLM搜索，需要新接口/准入/等预算验证；不是已完成创新|
|更多状态、记忆、任意算子组合|不支持|本轮未实现|未认证|只列候选方向，不安排运行|

## 现场优先展示3段

1. A的两行常量SELECT：让师兄立即看到旧决策权限。
2. C的六行动态权重：没有if也能做状态相关融合；同时给出真实3800双成员步和较差Fitness，避免只展示“看起来合理”的代码。
3. D的SELECT/MIX切换：解释模式、成员、权重三个决策层次，并指出单成员退化和未启用分支。

连续成员打分的完整B补充和Fusion函数放附表，现场按追问打开。可追加最新冠军源码作质量线索，但不能拿其训练冠军地位替代训练外验证。
