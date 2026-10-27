#!/usr/bin/env python3
"""Incremental evidence-only discussion pack. No project imports/API/solvers."""
import argparse
import ast
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
TSP=ROOT.parent/'FJSP-Heuristic-Research-tsp-pilot'
OLD=ROOT/'reports/组会实验盘点-20261027-v1'
OUT=ROOT/'reports/师兄讨论材料-20261027-v1'
PINS={};CHECKS=[]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def pin(path):
    path=Path(path).resolve();PINS[str(path)]={'sha256':sha(path),'bytes':path.stat().st_size};return path
def read(path):return json.loads(pin(path).read_text())
def table(path):return list(csv.DictReader(io.StringIO(pin(path).read_text(encoding='utf-8-sig'))))
def check(ok,label):
    if not ok:raise AssertionError(label)
    CHECKS.append(label)
def save(name,data):
    p=OUT/name;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
def csvsave(name,rows):
    p=OUT/name
    with p.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader()
        for r in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in r.items()})
def link(path,label=None):return f'[{label or Path(path).name}](<{Path(path).resolve()}>)'
def md(name,text):(OUT/name).write_text(text.strip()+'\n')

def extract(path,function=None):
    p=pin(path);code=p.read_text();tree=ast.parse(code)
    f=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and (function is None or n.name==function))
    text='\n'.join(code.splitlines()[f.lineno-1:f.end_lineno])+'\n'
    return {'source':str(p),'source_sha256':sha(p),'function':f.name,'start_line':f.lineno,'end_line':f.end_lineno,'code':text,'code_sha256':hashlib.sha256(text.encode()).hexdigest()}
def response_matches(code,path):
    text=pin(path).read_text();blocks=re.findall(r'```python\s*\n(.*?)```',text,re.S)
    check(len(blocks)==1,'one Python block: '+str(path))
    check(ast.dump(ast.parse(blocks[0]),include_attributes=False)==ast.dump(ast.parse(code),include_attributes=False),'export matches raw response AST: '+str(path))

def evidence():
    OUT.mkdir(exist_ok=True)
    facts=read(OLD/'核实数值.json');cards=read(OLD/'实验登记说明.json')
    read(OLD/'Notion只读来源.json');pin(ROOT/'code/fjsp_usage/usage_v2/execution.py')
    behaviors=read(ROOT/'reports/b1-ns-recovery-B-execution-20261023/Behavior_profiles.json')
    cand=table(ROOT/'reports/b1-ns-recovery-B-execution-20261023/Candidates.csv')
    olddir=ROOT/'runs/single-ID-gpt61-paired-training-20261014-v1'
    oldcp=read(olddir/'r201/INIT/checkpoint.json');oldresult=oldcp['evaluations']['INIT/init/000003']['result']
    examples=[]
    a=extract(olddir/'candidate_exports/INIT_init_000003.py');response=olddir/'candidate_exports/INIT_init_000003.response.txt'
    response_matches(a['code'],response);check(oldresult['valid'] and len(oldresult['instances'])==21,'early SELECT complete21')
    a.update(label='A_早期单成员索引',id='INIT/init/000003',experiment='single-ID-gpt61-paired-training-20261014-v1 / seed201',response=str(response),fitness=oldresult['fitness'],observed='21完整实例；函数常量返回2，选择H2；不根据状态变化。');examples.append(a)
    for label,tid in [('B_动态SELECT','B/init/000006'),('C_动态双成员MIX','B/g0000/000004'),('D_SELECT_MIX切换','B/g0000/000007')]:
        p=ROOT/'reports/b1-ns-recovery-B-execution-20261023/U_sources'/(tid.replace('/','_')+'.py')
        e=extract(p);resp=ROOT/'reports/b1-ns-recovery-B-execution-20261023/responses'/(tid.replace('/','_')+'.txt')
        response_matches(e['code'],resp)
        row=next(r for r in cand if r['id']==tid);check(row['full_valid']=='True','B1 example full-valid '+tid)
        e.update(label=label,id=tid,experiment='B1-NS Recovery-B / train21 / seed501',response=str(resp),fitness=float(row['fitness']),observed=behaviors[tid]);examples.append(e)
    vector=extract(ROOT/'docs/usage-space/real-gpt61-301/INIT__init__000005.py')
    vresp=ROOT/'docs/usage-space/real-gpt61-301/Actual_responses/INIT__init__000005.txt';response_matches(vector['code'],vresp)
    vcp=read(ROOT/'runs/v22-gpt61-select-mix-301-20261014-v1/r301/INIT/checkpoint.json');vr=vcp['evaluations']['INIT/init/000005']['result']
    counts=[sum(r['member_usage']['participation_counts'][i] for r in vr['instances']) for i in range(10)]
    vector.update(label='B补充_连续成员打分',id='INIT/init/000005',experiment='v22-gpt61-select-mix-301-20261014-v1 / seed301',response=str(vresp),fitness=vr['fitness'],observed={'member_step_counts':counts,'steps':sum(counts),'complete_instances':len(vr['instances'])});examples.append(vector)
    for label,path,fn,tid in [
        ('E1_MAX_MIN固定策略',ROOT/'code/fjsp_usage/fusion_v2/execution.py','fixed_policy','H0_H1_MAX / H0_H1_MIN'),
        ('E2_MAX_MIN动作融合',ROOT/'code/fjsp_usage/fusion_v2/execution.py','fuse_scores','H0_H1_MAX / H0_H1_MIN'),
        ('E3_Borda固定策略',ROOT/'code/fjsp_usage/fusion_v3/execution.py','fixed_borda','H0_H1_BORDA'),
        ('E4_Borda秩融合',ROOT/'code/fjsp_usage/fusion_v3/ranking.py','borda_scores','H0_H1_BORDA')]:
        e=extract(path,fn);e.update(label=label,id=tid,experiment='独立Fusion V2/V3机制实验；人工固定策略，非LLM搜索',response=None,fitness=None,observed='对应H01固定策略均完整train21；同状态机制记录见既有图07。');examples.append(e)
    for e in examples:
        path=OUT/'真实代码'/f'{e["label"]}.py';path.parent.mkdir(exist_ok=True);path.write_text(e['code']);e['local_copy']=str(path)
    save('真实代码证据.json',examples)
    # Only a bounded read of the newly accessible TSP worktree.
    state=read(TSP/'runs/tsp-pilot-20261026-v1/Campaign_state.json')
    journal=read(TSP/'runs/tsp-pilot-20261026-v1/API_attempts.json')
    hcp=read(TSP/'runs/tsp-pilot-20261026-v1--H/checkpoint.json')
    manual=read(TSP/'runs/tsp-pilot-20261026-v1--manual-H/checkpoint.json')
    mock=read(TSP/'reports/tsp-pilot-20261026-v1/Mock_final_acceptance.json')
    correction=pin(TSP/'reports/tsp-pilot-20261026-v1/Correctness_revision_v2.log').read_text()
    prerepair=read(TSP/'reports/tsp-pilot-20261026-v1/Pre_repair_receipt.json')
    for p in ['docs/TSP_ADAPTER.md','docs/TSP_EXECUTION_REVISION_V2.md','docs/TSP_PILOT_PROTOCOL_V1.md']:
        pin(TSP/p)
    for p in ['code/heuristic_design/problems/tsp/solver.py','code/heuristic_design/problems/tsp/candidates.py']:pin(TSP/p)
    tsp={'worktree':str(TSP),'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=TSP,text=True).strip(),
        'branch':subprocess.check_output(['git','branch','--show-current'],cwd=TSP,text=True).strip(),
        'dirty_status':subprocess.check_output(['git','status','--short'],cwd=TSP,text=True),
        'state':state,'logical':len(journal['requests']),'API_attempts':len(journal['api_attempts']),
        'full_responses':sum(x['status']=='completed' for x in journal['requests'].values()),
        'H_valid':sum(x.get('valid') is True for x in hcp['tasks'].values()),'H_task_count':len(hcp['tasks']),
        'manual_H_valid':sum(x.get('valid') is True for x in manual['tasks'].values()),
        'real_U_requests':prerepair['new_U_requests'],'mock_all_stages':mock['final_source_full_mock_completed'],
        'revision2_tests_recorded_passed':'"passed": true' in correction,
        'v2_real_directory_exists':(TSP/'runs/tsp-pilot-20261026-v2').exists(),
        'real_stage_directories':[p.name for p in (TSP/'runs').iterdir() if p.name.startswith('tsp-pilot-')],
        'distribution':'合成二维单位正方形欧氏TSP，50城市；非TSPLIB四实例',
        'limits':'脏工作树；旧v1实际执行与未提交v2修订身份分开，不运行或宣称v2真实续接已完成。'}
    check(tsp['logical']==tsp['API_attempts']==tsp['full_responses']==10 and tsp['real_U_requests']==0,'TSP bounded journal10 H responses / zero real U')
    save('TSP增量核查.json',tsp)
    exposure=read(ROOT/'reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Holdout_exposure_metadata.json')
    validation_audit=read(ROOT/'runs/conditional-paired-research-20261011-v4/Dataset_usage_audit.json')
    # Existing file index suffices for result search; archive inventory only adds availability.
    archive=ROOT/'runs/h01-champion-hurink-rdata20-seed501-20261026-v1/source/SchedulingLab_ac4c340.tar.gz'
    with tarfile.open(archive) as t:names=[m.name for m in t if re.search(r'/brandimarte/mk(?:0[1-9]|10)\.(?:json|txt)$',m.name,re.I)]
    idx=table(OLD/'文件索引.csv');mk_result_paths=[r['path'] for r in idx if re.search(r'brandimarte|mk0[1-9]|mk10',r['path'],re.I)]
    save('数据与四项计划核查.json',{'validation11_exposure':exposure,'validation_audit_source':str(ROOT/'runs/conditional-paired-research-20261011-v4/Dataset_usage_audit.json'),
        'validation_audit_top_keys':list(validation_audit),'Brandimarte_archive':str(archive),'Mk01_Mk10_archived_paths':names,
        'Mk_result_paths_in_existing_index':mk_result_paths,'notes':'归档有数据不等于开展过评价；未重跑、未取出Mk实例。'})
    return facts,cards,examples,tsp,exposure

def code_document(examples):
    header='''# 回应师兄上次建议：U的演进与真实代码示例

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
'''
    lines=[header]
    for e in examples:
        lines+=['',f'## {e["label"]}：{e["id"]}','',f'- 实验：{e["experiment"]}。',
          f'- 原始源码：{link(e["source"])}，函数`{e["function"]}`，原文件第{e["start_line"]}-{e["end_line"]}行。',
          f'- 本次原文副本：{link(e["local_copy"])}；源码SHA见`真实代码证据.json`。']
        if e['response']:lines.append(f'- 原始LLM输出：{link(e["response"])}；已核对代码AST一致，换行/括号排版不冒充算法变化。')
        if isinstance(e['observed'],dict):
            o=e['observed']
            if 'SELECT_steps' in o:lines.append(f'- 完整train21实际行为：SELECT {o["SELECT_steps"]}步、MIX {o["MIX_steps"]}步、双成员 {o["dual_member_steps"]}步；实际成员{o["active_members"]}；支持计数`{o["support_counts"]}`。')
            else:lines.append(f'- 完整train21实际成员参与步数：`{o["member_step_counts"]}`，合计{o["steps"]}步。')
        else:lines.append('- 实际行为证据：'+e['observed'])
        if e['fitness'] is not None:lines.append(f'- 完整Fitness：{e["fitness"]:.12f}。行为扩展不等于质量改善。')
        if e['label']=='B补充_连续成员打分':
            lines+=['','完整函数较长，保存在上方源码/副本；现场不需要展示全部10个公式。以下仅为原文末行，不能作为独立可运行函数：','', '```python',e['code'].splitlines()[-1],'```']
        elif e['label']=='E2_MAX_MIN动作融合':
            start=e['code'].index("    if operator in ('MAX', 'MIN'):")
            lines+=['','以下是函数末段原文，仅展示融合分支；完整校验仍在原模块：','','```python',e['code'][start:].rstrip(),'```']
        else:lines+=['','```python',e['code'].rstrip(),'```']
    lines+=['''
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
''']
    md('回应师兄上次建议：U的演进与真实代码示例.md','\n'.join(lines))

def plans_document(tsp,exposure):
    md('上次四项实验计划完成情况对照.md',f'''# 上次四项实验计划完成情况对照

核查日期2026-10-27；当前FJSP HEAD 5f66f08，TSP工作树HEAD `{tsp['head']}`，后者有未提交修改。状态按承诺的原范围判断，不用其他实验数量替代。

|原计划|判断|已完成的对应证据|剩余/不能称完成之处|
|---|---|---|---|
|1 初始化多样性与策略检查|部分完成|v2.2/Recovery-B/IND-EVO有固定槽位、合法/重复计数；已有H10同状态多样性、U谓词覆盖、状态尺度审计和真实执行支持集|缺“仅改变初始化多样性”的等预算独立消融；若干源码分支未在轨迹启用，不能用静态AST去重代替行为覆盖。|
|2 相同条件下对照|部分完成|A1/A2/A3固定H基线；IND/EVO共同H01/P0/数据/20槽计划；CROSS A/B同父代且只增加真实成绩；固定规则族事前冻结|IND/EVO只有重复1双方20槽完整，503/524不平衡；B1/B2空间/先验不匹配；A4盲抽与强P0不同；这些不能合成一项公平胜出。|
|3 独立评价与FJSP扩展|部分完成；部分目标由Hurink迁移验证覆盖|Behnke train21已有；旧B2 test28完整；新冠军Hurink20冻结确认|validation11已用于历史选择，test28已暴露；Hurink是不同基准/尺度，不替代原计划Brandimarte Mk01-Mk10。归档有Mk数据，未找到正式结果。|
|4 TSP迁移及四个TSPLIB实例|工程部分完成，原四实例尚未开展|独立工作树有适配、正确性/Mock、5人工H求解和10真实H响应；未见真实U请求|当前是合成欧氏TSP50城市；不是berlin52/kroA100/ch150/kroA200；LLM-H旧准入0有效，静态U枚举/真实U生成/演化未完成。|

## 1：初始化、多样性、分支和尺度

|证据|实际数量|解释|
|---|---|---|
|v2.2共享初始化|8槽5完整有效，源码重复0|原SELECT-only初始化；接口放开MIX不等于初始化实际探索融合。|
|Recovery-B初始化|9次I1：5完整有效、4解析/约束失败；总体19槽14完整有效|不是20个有效程序预算；P0实际成员/H支持由Behavior_profiles给出。|
|Recovery-B成员覆盖|完整有效程序启用H0/H1/H5/H8/H9，实际7对组合，没有H0/H1双成员步|区分源码坐标覆盖和实际支持覆盖；缺覆盖不是因果证明。|
|旧B2|20次完整响应、19新有效、1源码重复；16组已观测完整排程|不是全部程序语义等价分类；另有强手工P0。|
|H多样性诊断|384状态，364不同物理状态|影子评分，不是新增完整Fitness评价，也不是384个独立实例。|
|分支覆盖示例|动态SELECT代码写H1/H4/H9/H5，实际只启用H1/H5；混合模式代码写H5/H6分支，实际只有H8/H9|已具备检查能力；缺失覆盖仍存在，不能直接标“初始化问题已解决”。|

原始位置：{link(ROOT/'reports/b1-ns-recovery-B-execution-20261023/Candidates.csv')}、{link(ROOT/'reports/b1-ns-recovery-B-execution-20261023/Behavior_profiles.json')}、{link(ROOT/'reports/u-state-behavior-v1-20261020/Predicate_coverage.json')}、{link(ROOT/'reports/h10-decision-diversity-v1-20261020/Metrics.json')}。

## 2：哪些算受控，哪些不算

- 固定策略质量：同H/同train/LB/动作语义可比较最终策略；Baseline-A/T30来源与时间包装不同，不能顺带比较速度。
- IND/EVO：共同P0和新增20槽计划一致，问题是完整演化流程是否比独立生成更有效；实际113/120，1个共同完整重复，另两组partial。不是分离CROSS/MUTATE/选择各自作用。
- CROSS反馈：A原提示、B只加两父代完整成绩/差值，同配对同顺序；30槽29完整响应，1个A HTTP524。小样本、5父代上下文，不代表多代演化反馈。
- 历史B1/B2：10H自由发现vs给定H01且强静态P0，预算和先验不同；不得称等条件控制实验。
- A4：93查询来自865静态空间，只有60+33；不是完整五重复，也不是单独H01的连续权重最优。

## 3：数据使用史和扩展目标

|数据|已有使用|本次应怎样说|
|---|---|---|
|Behnke train21|H生成/编号、U选择、网格和多数诊断|开发/选择数据，不能叫独立验证。|
|Behnke validation11|历史单规则通过11实例均值选择；已有暴露审计|已被使用，不因本轮未跑就恢复为未见；对后续设计影响程度未知。|
|Behnke test28|历史B2冻结配对验证，12胜14负2平，均值略好|当时冻结评价的历史证据；现在已暴露，不给新冠军当全新确认。|
|Hurink rdata20|r2_EVO_s16冻结后一次配对，2胜18负，平均比率退化13.44%|完成了跨基准/机器尺度确认；不是同分布验证，不能合并旧test28。|
|Brandimarte Mk01-Mk10|公开SchedulingLab归档内已有json/txt；当前既有结果索引及数据目录未见正式评测结果|数据可用≠实验完成；原承诺尚未完成，不在本轮补测。|

暴露来源：{link(ROOT/'reports/ind-vs-evo-h01-train21-seed501-20261026-v1/closeout-v1/Holdout_exposure_metadata.json')}。其中指向相邻EoH-S原validation及主项目历史单规则选择记录；本轮沿用已核查元数据，不重读全套留出轨迹。

## 4：TSP五层完成度

|层次|当前核实状态|证据和限制|
|---|---|---|
|接口实现|已实现|专用状态、H/U签名、候选准入、构造型执行器；复用通用调度/选择，未复用FJSP状态或冠军。|
|测试通过|既有测试/Mock有通过记录|Correctness_final记录11检查，修订v2记录12检查；Mock50任务全流程通过，但不是50真实请求。|
|静态求解|部分完成|5人工H在合成train20完整求解，NN参照已有；全部单H/双H静态U枚举阶段尚未开始。|
|真实LLM生成U|尚未开展|全局账本10请求全部属于H，10完整响应但v1旧准入0有效；新U请求0。|
|真实LLM演化U|尚未开展|未见IND/EVO正式阶段目录；不能把Mock演化当真实。|

实际campaign=`runs/tsp-pilot-20261026-v1`，状态paused，理由为进入static前暂停。文档已有v2续接说明，解析器/执行器有未提交修订；**当前没有v2真实目录，不能把命令草案当已恢复完成。** 两个解析版本不能当同一执行身份。

TSP实际位置：{link(TSP/'runs/tsp-pilot-20261026-v1/Campaign_state.json')}、{link(TSP/'runs/tsp-pilot-20261026-v1/API_attempts.json')}、{link(TSP/'docs/TSP_EXECUTION_REVISION_V2.md')}。本轮只读该工作树，不修改、提交其文件，不诊断恢复或发送请求。

原计划的berlin52、kroA100、ch150、kroA200四个TSPLIB实例，当前新框架协议未采用；旧Notion/EvoFlow TSP V0即使出现kroA100，也不是本轮H/U构造型迁移成果。
''')

def experiment_documents(cards,facts,tsp):
    selected=[('固定H与静态融合','H01'),('固定H与静态融合','S01'),('固定H与静态融合','A'),('固定H与静态融合','AT30'),
      ('初始化/覆盖','U02'),('初始化/覆盖','U03'),('LLM生成与演化','B1'),('LLM生成与演化','B2'),
      ('独立生成vs演化','IE'),('状态/融合消融','D01'),('状态/融合消融','D02'),('状态/融合消融','D03'),('状态/融合消融','D04'),
      ('状态/融合消融','F2'),('状态/融合消融','F3'),('状态/融合消融','F4'),('状态/融合消融','RULE'),
      ('反馈/传统基线','AB'),('反馈/传统基线','ABD'),('反馈/传统基线','A4'),('独立/跨基准评价','V01'),('独立/跨基准评价','EXT')]
    rr=[]
    for group,id in selected:
        c=next(x for x in cards if x['id']==id)
        rr.append({'类别':group,'实验':c['name'],'研究目的':c['question'],'主要设置':c['space']+'；'+c['dataset']+'；'+c['seed'],
          '实际完成状态':c['classification']+'；'+c['budget'],'主要结果':c['result'],'结论边界':c['limits'],'证据路径':str(ROOT/c['evidence'])})
    rr.append({'类别':'TSP迁移','实验':'新构造型TSP独立工作树','研究目的':'第二问题H/U接口和完整流程迁移','主要设置':'合成欧氏50城市；H10/IND20/EVO20计划，非TSPLIB',
       '实际完成状态':'部分完成：10真实H响应、旧准入0有效；5人工H评价；U0','主要结果':'接口/Mock通过；人工H可求解，尚无真实U质量结果',
       '结论边界':'脏工作树、v2仅修订/Mock；未见真实续接目录，不与FJSP Fitness混比','证据路径':str(TSP/'runs/tsp-pilot-20261026-v1/Campaign_state.json')})
    csvsave('重要实验详细附表.csv',rr)
    concise=[
      ('固定H/静态融合','A1/A2/A3＋21点网格','10单H，45等权对综合，H01静态21点','已完成质量覆盖','H0 −2.111805；等权 −1.983144；Oracle −2.032977','混合T15/T30/历史缓存；不是全权重最优','A'),
      ('初始化/覆盖','v2.2＋Recovery-B','固定请求槽位，合法/重复/状态诊断','部分完成','B1有效14/19，实际7对，无H01双成员步','未做纯初始化多样性消融','B1'),
      ('生成/演化','历史B2','共同5静态P0，2代20演化槽','完成','动态 −1.982226；相对等权+0.000918','另有网格/P0投入；训练内单重复','B2'),
      ('IND/EVO','近期3重复计划','H01，共同P0，各20新增槽','113/120，只有重复1双方完整','新EVO冠军 −1.975489；两重复突破','故障/partial不平衡，不能断言稳定胜出','IE'),
      ('融合/状态消融','V2-V4＋简单动态','固定算子/预定阈值，0模型搜索','V2/V3有失败隔离，V4/规则族完整','动作可不同；MAX/MIN/Borda/简单切换未超过WS','局部表达≠收益；未开放正式LLM算子搜索','F2'),
      ('反馈/传统基线','CROSS反馈＋A4','A/B只差父代成绩；865静态策略RS','A/B30槽；A4 93/300','B无改善迹象；A4冠军 −2.022083','5父代任务；非同预算因果对照','AB'),
      ('独立/跨族验证','旧test28＋新Hurink20','不同冻结冠军、不同分布分开评价','两批各自完成','旧12胜14负2平；新2胜18负','已暴露；Hurink不是原Mk计划','EXT'),
      ('TSP迁移','新H/U构造框架','合成欧氏50城市，独立工作树','接口/Mock/人工H求解，10 H响应；U0','尚无真实U生成/演化成绩','不是四个TSPLIB实例，也非旧EvoFlow','TSP')]
    lines=['# 近期实验总览与重要图表索引','',
      '以科研问题分组，不把同一实验的缓存、复检、导出或恢复副本算作额外实验。完整来源见详细附表和既有资产盘点；本材料只做增量。','',
      '|类别|实验|主要设置/目的|实际状态|主要结果|边界|证据|','|---|---|---|---|---|---|---|']
    for group,name,setting,status,result,boundary,id in concise:
        path=TSP/'runs/tsp-pilot-20261026-v1/Campaign_state.json' if id=='TSP' else ROOT/next(c for c in cards if c['id']==id)['evidence']
        lines.append(f'|{group}|{name}|{setting}|{status}|{result}|{boundary}|{link(path)}|')
    lines+=['','详细逐项：'+link(OUT/'重要实验详细附表.csv')+'；历史总目录：'+link(OLD/'实验资产总目录.md')+'。','',
      '## 现场建议只开4张图','',
      '|顺序|图|核查结论|要怎么讲|','|---|---|---|---|',
      f'|1|{link(OUT/"图表/最新训练质量比较.png")}|本轮只读取既有成绩补画；纵向各项为策略质量参照|单H→强静态→最新动态训练冠军。标清搜索预算/先验不同。|',
      f'|2|{link(OLD/"图表/09_IND_EVO探索性比较.png")}|逻辑预算横轴含失败，三重复完整/partial标注保留|两个EVO路径突破；只有重复1双方20/20。|',
      f'|3|{link(OLD/"图表/10_冻结冠军训练外验证.png")}|同一冻结r2_EVO_s16；train和Hurink均值分开|训练提高约0.386%，跨基准平均比率退化13.44%。|',
      f'|4|{link(OLD/"图表/07_融合表达与质量.png")}|机制取同一WS轨迹3800状态，质量来自各自完整排程|动作表达差异已观察到，新增算子不自动带来收益。|',
      '', '所有图的Fitness越高越好；逐实例贡献以正值为动态改善。已查来源、方向、标签；不重新运行旧绘图脚本或求解器。新图提供PNG/SVG/PDF，其他图直接链接既有文件，避免重复版本。',
      '', '备份：'+link(OLD/'图表/04_B1_B2搜索与种群.png')+'、'+link(OLD/'图表/06_B2逐实例收益与退化.png')+'、'+link(OLD/'图表/02_等权45对分布.png')+'。',
      '', '## 重要增量与未知',
      '', '- 旧资产盘点只证明当前FJSP工作树未见TSP正式目录。本轮经git worktree发现并只读访问TSP分支，补充了10真实H响应与暂停状态；没有追改旧盘点。',
      '- TSP文档宣称v2为实际续接目录，但现场该目录不存在；以账本和目录为准，v2只能说已有修订与Mock证据。',
      '- Brandimarte归档有数据，未见Mk01-Mk10评价结果；不把“数据已下载”写成“已验证”。',
      '- 源码、真实响应、完整评价、实际行为是四层证据；代码段与响应AST已核对，缺现代终态的legacy结果不升级。']
    md('近期实验总览与重要图表索引.md','\n'.join(lines))

def discussion():
    md('师兄讨论提纲：成果、瓶颈与三个问题.md','''# 师兄讨论提纲：成果、瓶颈与三个问题

## 建议10分钟讲述顺序

1. **先回应建议（2分钟）**：“我没有继续把U限定成if/else返回一个H。现在真实LLM程序可输出成员分数、动态双成员权重，并在SELECT/MIX间切换；MAX/MIN/Borda做了独立固定机制验证。”展示C、D短代码，区分正式语言与机制试验。
2. **讲最主要成果（2分钟）**：固定H上静态组合有显著幅度的训练改善；完整45对和21点网格让基线更可靠。用新图说明最新动态冠军训练更好，但不称搜索预算公平。
3. **讲最重要反证（2分钟）**：IND/EVO只有一个共同完整重复；最新冻结冠军在Hurink跨基准退化。主动讲出来，避免师兄以为已经证明泛化或演化机制优势。
4. **逐条核对承诺（1分钟）**：初始化/受控对照部分完成；旧Behnke留出已暴露，Hurink替代部分跨族目标但Mk尚未做；TSP是合成数据工程推进，真实U尚未开始，不是四个TSPLIB完成。
5. **请教研究取舍（3分钟）**：围绕以下最多三个问题，先约定下一轮要排除的解释，再谈方法复杂度。

## 问题一：先改善搜索，还是继续扩融合空间？

- 关键证据：B1有效14/19且实际未访问H01双成员；固定WS很强。MAX/MIN/Borda对同状态动作有区别，却都未超过WS。
- 目前结论：成员发现/搜索覆盖是可观察瓶颈，算子表达不是唯一缺口；“扩空间就会改善”没有证据。
- 还不能判断：B1/B2先验和预算不同；IND/EVO故障/partial，缺完整稳定受控重复，不能归因到某一个搜索组件。
- 可选方向：①先做共同先验、统一失败计账的完整搜索对照；②保留现有空间，只研究初始化/行为覆盖；③仅在具体状态机制证据支持时把一个独立算子开放给LLM，并用同预算消融。
- 面对面问法：**“现在已看到组合覆盖不足，而新算子主要增加行为、未增加质量，您更建议先把同预算搜索做扎实，还是挑一个有机制依据的算子进入U语言？”**

## 问题二：怎样验证状态依赖本身有价值？

- 关键证据：旧B2比21点网格最好仅提高约0.0463%；18个简单动态规则没有超过等权。真实MIX/模式切换并不保证更好。
- 目前结论：已有动态决策能力与训练内候选收益；还没有把“动态表达”与“搜索找到不同静态策略/更多参数”分离。
- 还不能判断：有限21点不是连续静态最优；改变权重的轨迹差异不是同状态因果收益；同一训练集选冠军有选择偏差。
- 可选方向：①冻结一个U，与其预先定义的常量/去状态版本做配对；②在预注册开发样本做同状态反事实，再与完整排程质量分开报告；③在同预算、同成员范围的静态/动态搜索中比较，并把确认数据放在最终冻结之后。
- 面对面问法：**“如果我要证明的是‘根据状态调整’而不只是‘找到了一个较好程序’，您认为最小而有说服力的静态对照或去状态消融应怎样定义？”**

## 问题三：训练提升、跨基准退化后，FJSP与TSP怎样排序？

- 关键证据：r2_EVO_s16训练相对等权改善约0.386%，Hurink20却2胜18负、平均Cmax/LB增加13.44%；确认是跨族/机器尺度迁移。TSP目前只有工程/Mock和H生成接入，真实U0，且数据不是原定TSPLIB。
- 目前结论：当前冠军没有得到这次迁移收益证明；FJSP的尺度/分布敏感性值得定位，TSP还不能提供另一问题上的收益证据。
- 还不能判断：退化可能来自状态尺度、成员适用性或训练选择，现有数据不能单独归因；也没有相同分布未见集与跨尺度集的干净分离。
- 可选方向：①优先厘清FJSP的同分布与跨尺度诊断，把状态量/行为记录和质量分开；②冻结FJSP现状，TSP只做最小端到端流程验证，不急于算法优越性；③先完成与原承诺一致的公开实例扩展方案，之后再决定双问题并行。
- 面对面问法：**“这次反例更像分布/尺度外推问题，TSP又尚未进入真实U阶段，您建议先把FJSP的失效边界讲清，还是先做TSP的最小完整闭环来检验框架通用性？”**

## 建议的开场和结束

开场：“上次您建议扩大U的利用方式，我已经把成员打分、动态两成员融合和模式切换做成真实生成/执行能力，也用固定实验检查了MAX等机制。但目前最大的证据是静态基线很强，训练提升还没有可靠迁移，所以这次主要想请您帮我确定下一轮要回答的研究问题。”

结束：“我想先确定一个最小对照，能够区分搜索覆盖、动态状态价值和跨分布退化，而不是再同时扩大状态、算子和演化系统。”

以上选项仅供讨论，不构成预算授权或新实验启动。正式数值与原始位置见《近期实验总览与重要图表索引》和详细附表。
''')

def chart(facts):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font='/System/Library/Fonts/STHeiti Medium.ttc';font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=font).get_name(),'axes.unicode_minus':False,'svg.fonttype':'none','pdf.fonttype':42,'font.size':12})
    latest=max(float(r['best_including_P0']) for r in facts['IND_EVO_completion'])
    rs=[('Best Single H0',facts['H0'],'固定10H基线'),('H0/H1 静态等权',facts['equal'],'45等权对/21点网格最好已测'),('历史B2动态冠军',facts['B2'],'强P0＋20演化槽，另有静态投入'),('最新EVO r2_s16',latest,'113/120部分campaign的训练冠军')]
    f,ax=plt.subplots(figsize=(11,6));colors=['#8291a3','#2563a6','#21896b','#d58a24'];ax.scatter([r[1] for r in rs],range(4),s=85,color=colors)
    for i,(_,v,_) in enumerate(rs):ax.text(v+.004,i,f'{v:.9f}',va='center',fontsize=11)
    ax.set(yticks=range(4),yticklabels=[r[0] for r in rs],xlabel='完整train21 Fitness = 平均 -Cmax/LB（越高越好）',xlim=(facts['H0']-.02,latest+.055));ax.invert_yaxis();ax.grid(axis='x',alpha=.15);ax.spines[['top','right']].set_visible(False)
    f.suptitle('从强静态基线到最新动态U：最终策略质量参照',fontsize=17)
    f.text(.035,.035,'固定H0/H1动态范围；新冠军来自partial搜索。初始化/查询/失败条件不同，不是搜索效率或同预算公平结论。',fontsize=9,color='#475569')
    f.subplots_adjust(left=.25,bottom=.19,top=.85)
    folder=OUT/'图表';folder.mkdir(exist_ok=True)
    for ext in ['png','svg','pdf']:
        p=folder/('最新训练质量比较.'+ext);f.savefig(p,dpi=200)
        if ext=='svg':p.write_text('\n'.join(x.rstrip() for x in p.read_text().splitlines())+'\n')
    plt.close(f);csvsave('最新训练质量图输入.csv',[dict(method=r[0],fitness=r[1],scope=r[2]) for r in rs])

def quick_content():
    return [
      ('现场速览 1/2：回应建议与完成度',[
        ('一句话主线','U已经具备多成员打分、动态双成员权重和SELECT/MIX切换；静态组合收益明确，动态训练改善尚未转成可信迁移收益。'),
        ('先回应师兄','展示真实LLM代码C（六行动态H5/H8权重）和D（SELECT/MIX切换）。if/else是写法；输出权限和实际执行才定义策略空间。MAX/MIN/Borda目前是独立固定机制，不是LLM已经会自由搜索这些算子。'),
        ('四个核心数值','train21：H0 -2.111804961；H01等权 -1.983144295；历史B2 -1.982226488；新r2_EVO_s16 -1.975488675。只比较最终策略质量，不称预算公平。'),
        ('最新反证','同一新冠军冻结后，Hurink rdata20动态 -1.635914532、等权 -1.442119623；2胜18负，平均Cmax/LB退化约13.44%。这是跨基准/机器尺度迁移，不能冒充同分布验证。'),
        ('原计划1：初始化检查','部分完成：有效/重复/覆盖/状态尺度证据已有；缺单独改变初始化的受控消融，部分代码分支未访问。'),
        ('原计划2：等条件对照','部分完成：静态基线完整；IND/EVO共同H/P0/预算计划已做，但只有重复1双方20/20，后两重复partial。'),
        ('原计划3：独立FJSP扩展','部分完成：旧test28已评价但现已暴露；validation11已有选择使用；Hurink覆盖部分迁移目标，Mk01-Mk10只有归档数据、无正式结果。'),
        ('原计划4：TSP迁移','工程部分完成：合成欧氏TSP接口/Mock和5人工H求解；10真实H响应旧准入均失败、U请求0。不是原四个TSPLIB实例；v2真实续接尚无目录。')]),
      ('现场速览 2/2：成果、边界、三问',[
        ('讲述顺序','回应建议和真实代码 → 静态基线与最新训练质量图 → IND/EVO搜索曲线 → Hurink反例 → 四项承诺和三个问题。重点图/原始位置见配套索引。'),
        ('必须保留的预算边界','IND/EVO：113/120逻辑、117尝试、108响应、107质量认证，7未启动；8次503和1次524。历史B1：19槽14有效，未访问H01双成员；历史B2另有5手工P0和静态网格投入。'),
        ('问题1：搜索还是空间','B1组合覆盖不足；MAX/MIN/Borda动作不同却未改善质量。先做完整同预算搜索、只改初始化/行为覆盖，还是有依据地开放一个算子？请师兄帮忙确定主要研究变量。'),
        ('问题2：状态依赖的增量','历史B2只比已测21点静态最好提高约0.0463%，18简单动态规则未超过等权。如何定义冻结U的去状态/静态对照，才能排除只是找到了更好的参数？'),
        ('问题3：失效与双问题顺序','新冠军训练改善约0.386%但跨基准退化。优先定位FJSP分布/尺度失效，还是先完成TSP最小真实H/U闭环？不同时换状态、算子、搜索和数据。'),
        ('现场可展示的事实','完整45等权对已覆盖、H01最好；真实LLM确实生成并执行动态权重和模式切换；新EVO有两条训练突破路径。行为相异、训练冠军和泛化收益是三层证据。'),
        ('尚不能说','不能说EVO稳定优于IND；不能说MAX等已纳入正式LLM演化；不能说Mk或四个TSPLIB完成；不能把TSP Mock当真实U实验，也不把旧留出重新称未见。'),
        ('来源与本轮边界','FJSP提交5f66f08的既有资产与closeout认证；TSP工作树7056f18含未提交修订，按现场账本而非文档命令判断。完整路径见详细附表和真实代码证据。此轮无生成API、无新求解、不推送。')])]

def pdf():
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    pdfmetrics.registerFont(TTFont('CJK_Embedded','/System/Library/Fonts/STHeiti Medium.ttc',subfontIndex=0))
    style=ParagraphStyle('body',fontName='CJK_Embedded',fontSize=10.5,leading=15.5,wordWrap='CJK',textColor=HexColor('#243447'))
    heading=ParagraphStyle('head',parent=style,fontSize=12,leading=17,textColor=HexColor('#2563a6'))
    p=OUT/'现场速览.pdf';c=canvas.Canvas(str(p),pagesize=A4);w,h=A4
    for page,(title,sections) in enumerate(quick_content(),1):
        c.setFillColor(HexColor('#173a5e'));c.rect(0,h-66,w,66,fill=1,stroke=0)
        c.setFont('CJK_Embedded',18);c.setFillColor(HexColor('#ffffff'));c.drawString(38,h-39,title)
        y=h-86
        for label,text in sections:
            a=Paragraph(label,heading);_,hh=a.wrap(w-76,h);a.drawOn(c,38,y-hh);y-=hh+4
            a=Paragraph(text,style);_,hh=a.wrap(w-76,h);a.drawOn(c,38,y-hh);y-=hh+12
        if y<40:raise ValueError('quick sheet page overflow; shorten text, do not shrink illegibly')
        c.setFont('CJK_Embedded',9);c.setFillColor(HexColor('#64748b'));c.drawString(38,24,'2026-10-27  |  师兄讨论材料  |  只读整理，非新实验');c.drawRightString(w-38,24,f'{page} / 2');c.showPage()
    c.save()
    from pypdf import PdfReader
    check(len(PdfReader(str(p)).pages)==2,'quick sheet exactly two PDF pages')
    print(str(p))

def build():
    facts,cards,examples,tsp,exposure=evidence()
    code_document(examples);plans_document(tsp,exposure);experiment_documents(cards,facts,tsp);discussion();chart(facts)
    text=[]
    for title,sections in quick_content():
        text+=['# '+title,'']
        for label,value in sections:text+=['## '+label,'',value,'']
    md('现场速览.md','\n'.join(text))
    md('README.md','''# 师兄面对面讨论材料

建议按以下顺序打开：

1. [现场速览](现场速览.pdf)：两页可打印；文字源见[现场速览.md](现场速览.md)。
2. [回应建议与真实代码](回应师兄上次建议：U的演进与真实代码示例.md)：A-E真实函数及运行边界。
3. [四项原计划核对](上次四项实验计划完成情况对照.md)：不以替代实验冒充完成。
4. [近期实验和图表](近期实验总览与重要图表索引.md)：简表、详细CSV、当前最重要4图。
5. [三个讨论问题](师兄讨论提纲：成果、瓶颈与三个问题.md)：10分钟讲述顺序及面谈问法。

历史完整目录/图表不复制，沿原路径引用。本目录补充可访问TSP工作树的实际状态，不修改此前盘点和科研记录。
''')
    subprocess.run([sys.executable,str(ROOT/'tools/discussion_visual_index.py')],check=True)
    save('来源SHA256.json',PINS)
    save('验收记录.json',{'source_count':len(PINS),'checks':CHECKS,'new_generation_API':0,'new_FJSP_TSP_solves':0,'other_worktree_writes':0,
       'FJSP_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'TSP_head':tsp['head'],
       'scope':'增量读取既有索引、代表性源码/响应/完整结果和可访问TSP阶段，不重扫全部历史。'})
    print(json.dumps({'output':str(OUT),'sources':len(PINS),'code_examples':len(examples),'checks':len(CHECKS)},ensure_ascii=False))

def verify():
    pins=json.loads((OUT/'来源SHA256.json').read_text());bad=[p for p,v in pins.items() if sha(Path(p))!=v['sha256']]
    check(not bad,'all read source files unchanged including TSP worktree')
    errors=[]
    for p in OUT.glob('*.md'):
        for target in re.findall(r'\]\((<?[^)]+>?)\)',p.read_text()):
            target=target.strip('<>')
            if '://' in target or target.startswith('#'):continue
            q=Path(target);q=q if q.is_absolute() else p.parent/q
            if not q.exists():errors.append([p.name,target])
    check(not errors,'all local document/source links exist')
    save('最终核对.json',{'source_files_unchanged':len(pins),'missing_links':errors,'new_API':0,'new_solves':0})
    print('verified',len(pins),'unchanged sources; local links valid')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['build','pdf','verify']);a=p.parse_args()
    {'build':build,'pdf':pdf,'verify':verify}[a.action]()
