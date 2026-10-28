#!/usr/bin/env python3
"""Deterministic Chinese report for a finished fixed pilot; no model or solver."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
import argparse,csv,json,math,shutil
from heuristic_design.core.storage import read,write,sha
from heuristic_design.problems.tsp.campaign import summary
from heuristic_design.problems.tsp.operations import Adapter


def table(headers,rows):
    return '\n'.join(['|'+'|'.join(headers)+'|','|'+'|'.join(['---']*len(headers))+'|']+['|'+'|'.join(str(x) for x in row)+'|' for row in rows])

def fmt(x):return 'null' if x is None else f'{x:.12f}'

def report(directory,out):
    f=summary(directory);assert f['state']['phase']=='completed';out.mkdir(exist_ok=True,parents=True)
    h=read(directory/'H_frozen.json');p0=read(directory/'P0.json');final=read(directory/'Final_frozen.json');validation=read(directory/'Validation_candidates.json')
    shutil.copyfile(directory/'H_frozen.json',out/'H_frozen.json');shutil.copyfile(directory/'P0.json',out/'P0.json')
    shutil.copyfile(directory/'Validation_candidates.json',out/'Validation_candidates.json');shutil.copyfile(directory/'Final_frozen.json',out/'Final_frozen.json')
    (out/'Frozen_final_U.py').write_text(final['final']['candidate']['code']);(out/'Frozen_train_static_U.py').write_text(final['static_reference']['candidate']['code'])
    groups=[]
    for name in ['IND_701','IND_702','EVO_801','EVO_802']:
        facts=f['stage_facts'][name];rows=facts['records'];initial=[r for r in rows if r['stage']=='p0' and r['valid']];new=[r for r in rows if r['stage']=='new'];valid=[r for r in new if r['valid']]
        counts=next(g for g in f['groups'] if g['stage']==name)
        groups.append({'method':name,'P0_best':max(r['fitness'] for r in initial),'valid_new':len(valid),'AST_duplicates':counts['duplicates'],
            'best_new':max((r['fitness'] for r in valid),default=None),'best_so_far':facts['best_so_far']['fitness'],'champion_id':facts['best_so_far']['id'],
            'API_attempts':counts['API_attempts'],'complete_responses':counts['complete_responses'],'failed':counts['failed_or_uncommitted_new']})
    write(out/'Search_comparison.json',groups)
    generated={}
    for name in ['IND_701','IND_702','EVO_801','EVO_802']:
        for row in f['stage_facts'][name]['records']:
            if row['stage']=='new' and row.get('candidate'):
                generated.setdefault(row['candidate']['key'],[]).append({'path':name,'id':row['id']})
    write(out/'Generated_U_AST_groups.json',{'scope':'all 40 generated U; reporting only, no cross-path refill or cache','unique_AST_keys':len(generated),'groups':generated})
    with (out/'Search_comparison.csv').open('w',newline='') as stream:
        w=csv.DictWriter(stream,fieldnames=list(groups[0]),lineterminator='\n');w.writeheader();w.writerows(groups)
    static=f['stage_facts']['static']['records'];hrows=h['dispositions'];order=h['selected_ids']
    htable=table(['TSP成员','来源id','来源','train Fitness'],[[i,name,'人工' if name.startswith('manual') else 'LLM',fmt(next(r['fitness'] for r in hrows if r['id']==name))] for i,name in enumerate(order)])
    static_table=table(['静态策略','完整train Fitness'],[[r['id'],fmt(r['fitness'])] for r in sorted(static,key=lambda r: (r['fitness'] is None,-(r['fitness'] or 0),r['id']))])
    search_table=table(['路径','新增逻辑','API尝试','完整有效新增任务','AST重复','新增最好','含P0最好'],[[g['method'],10,g['API_attempts'],g['valid_new'],g['AST_duplicates'],fmt(g['best_new']),fmt(g['best_so_far'])] for g in groups])
    valrows=f['stage_facts']['validation']['records'];valtable=table(['冻结候选id','validation Fitness'],[[r['id'],fmt(r['fitness'])] for r in valrows])
    comparisons=[]
    for split,city in [('confirmation',50),('transfer',100)]:
        r=f['comparisons'][split]
        comparisons.append([split,city,r['instances'],fmt(r['final_fitness']),fmt(r['static_fitness']),r['wins'],r['losses'],r['ties'],fmt(r['final_total_length']),fmt(r['static_total_length'])])
    comptable=table(['集合','城市数','实例数','最终U Fitness','静态参照 Fitness','胜','负','平','最终U总长度','静态总长度'],comparisons)
    audit=read(out/'Delivery_verification.json');old=read(ROOT/'reports/tsp-pilot-20261026-v1/Partial_closeout.json')
    selected_manual=sum(name.startswith('manual') for name in order)
    identical=final['final']['candidate']['key']==final['static_reference']['candidate']['key']
    interpretation=('最终U与最强train静态参照是同一份AST代码；确认及迁移中相同结果属于同一策略的重复标签，没有追加生成。' if identical else '最终U与最强train静态参照的AST不同；下表是冻结后完整实例配对结果，不能由代码不同推断机制或行为不同。')
    text=f'''# TSP固定预算迁移小试：完整交付

状态：completed。真实生成、冻结验证已按预定范围结束，没有追加预算。最终执行目录`{directory.relative_to(ROOT)}`；全部请求共用v1原API账本。主机文件夹/远端未改名，未推送。

## 工程与FJSP一致性

通用化提交c7402ca；TSP初始实现7056f18；包装解析与partial保全b4a078b；显式新窗口4c5b00c。FJSP的H0/等权×toy/已有认证Behnke1共4组完整动作轨迹、状态、排程、Fitness、首解复检及认证哈希相等；Behnke1为Cmax106/100，与历史证据一致。原h-usage-space四处未跟踪产物保留。

TSP使用同一core任务执行器和父代/保留逻辑，通过Adapter接独立TSP签名、状态、准入、评价。二维单位方形float64欧氏完整图、城市0起止、闭合边计入，无局部搜索。13项几何/AST/MIX/完整Fitness/预算/身份/新窗口检查通过；全流程Mock和边界暂停恢复通过。Mock不算真实LLM任务。

## 版本修订和预算继承

v1前10份H响应有代码但缺说明外层花括号，原严格解析全部失败。v1响应、错误、协议、旧H后备及源码快照保留。v2只兼容普通/花括号说明，不修改返回代码；原10份首个完整响应重新准入并评价，H没有重发。所有真实U均在v2准入下生成，没有混用两套U搜索结果。不能将修订称为未变更的v1身份。

原窗口到期后，用户明确批准“允许新窗口，预算不变”；v2首启形成新12小时回执，保留旧时钟，暂停恢复不重置。已用10逻辑/10尝试逐条继承，真实全程总量为 **{f['used']['logical']}逻辑任务／{f['used']['API_attempts']}API尝试**（上限50/75，每任务最多2次）。完整响应{f['used']['complete_responses']}，未知尝试{f['used']['unknown_attempts']}。未用预算不转组、不补员。

## 冻结H与静态投入

人工5条＋LLM首份响应10条，完整train评价后按规范AST首次去重、质量降序/id同分排序取前5。人工规则公式与特征定义见docs/TSP_ADAPTER.md。冻结H中{selected_manual}/5来自人工，{5-selected_manual}/5来自LLM；LLM候选未入选的原因和全部成绩在H_selection.json中。此处是LLM生成H池及质量筛选，没有复现EoH-S集合演化。

{htable}

冻结后仅在train评价全部5单成员及10双成员等权；最强train静态参照为`{p0['static_reference']['id']}`，Fitness **{fmt(p0['static_reference']['fitness'])}**。前5个有效AST独立静态策略组成共同P0，四路径best-so-far均包含该P0，只有EVO生成读取父代。

{static_table}

## 两次IND与两次EVO

IND独立上下文，不读父代/历史/成绩；EVO一代5 CROSS＋5 MUTATE，原版指令（问题术语适配），2父代/1父代，排名权重1/(N+rank)无放回，代内父代冻结、代末按Fitness/id保留N5。四路径均新增10任务，不加成绩反馈。

{search_table}

两次IND均未超过共同P0；EVO_801的新增冠军较P0提高约0.003744888的train Fitness，EVO_802未超过P0。AST重复列的范围是各自路径（包括其P0）；跨路径AST分组另保存在Generated_U_AST_groups.json。

完整有效任务数含AST重复/缓存命中，不能等同新程序数量。逻辑任务、尝试、完整响应、认证和AST重复分别保留。P0和静态筛选投入不是免费，也不把继承冠军算新增发现。

## 一次validation与冻结确认

四路径train冠军（含P0）＋train静态参照，AST去重后共{len(validation['candidates'])}份候选，在validation前冻结清单；按完整validation Fitness降序/id升序选择。没有根据confirmation或transfer回调参数。

{valtable}

EVO_801训练冠军在validation上为−0.981103901129，劣于静态参照−0.959063489657，所以按冻结规则选择静态U。该EVO冠军的实际代码在前半程且距离标准差大于0.12时混合H0/H2，否则只用H0；train20中980步有414步双成员、71次权重向量变化。这证明本批产生并执行了状态相关策略，不能证明其训练外收益。原响应说明把规则称作nearest-neighbor，但成员0实际是manual_far_early，机制解释以代码和冻结编号为准。

最终U来源id：`{final['final']['id']}`，validation Fitness **{fmt(final['final']['fitness'])}**。{interpretation}

{comptable}

胜负统计是最终U长度相对静态参照，绝对容差1e-12；逐实例原始长度、相对NN比例及差值保留。Fitness为`−mean(length/NN_length)`，越大越好，**不是最优性gap或LB**。同规模确认和跨规模迁移是两项不同结果。

## 成本、失败与证据

已知输入token：{f['usage']['known_input_tokens']}；已知输出token：{f['usage']['known_output_tokens']}；未知usage尝试：{f['usage']['unknown_usage_attempts']}。平台点数和实际币种费用无法核实，保持null，没有费用门禁或额外分析模型调用。

v2物理程序实例预留：{audit['physical_program_instances_reserved']}；实际回传完整首解/复检{audit['captured_solve_passes']}遍，记录求解＋复检时间{audit['recorded_solve_recheck_seconds']:.3f}秒。v1人工H工程评价另有{old['physical_program_instances']}程序实例/{old['captured_solve_passes']}遍，未藏入零成本。未回传的失败前缀不作为完整Fitness。

Raw_evidence.tar.gz及Raw_manifest.json保存本批数据、协议、原账本/响应、stage checkpoint、首解复检、候选及当前绑定源码；往返校验通过。旧v1解析失败与原源码还单独保存在前一份partial归档。附带只读核查独立重算了{audit['all_candidate_tours_checked_independently']}条已返回路径的闭合长度，复现H质量选择及validation选择，所有stage的NN分母向量一致，源/数据/冻结资产匹配。

## 能支持什么

当前框架已完成第二问题的真实生成、准入、求解、搜索、冻结选择和两类训练外评价，支持“通过清楚的问题适配复用同一执行/记录/恢复链路”。本次冻结H的来源须按上表说明，不能把人工入选集合包装成LLM集合演化成果。

每方法只有2次搜索重复；结果仅提供本条件下的初步质量证据，不能证明演化稳定占优、跨问题策略直接迁移或普遍泛化。FJSP策略未直接移植到TSP，迁移的是设计/执行方法。没有局部搜索和公开最优值比较。无论正负，本轮已结束，不追加研究。

## 操作和文件

定义/特征/修改地图：docs/TSP_ADAPTER.md；事前协议：docs/TSP_PILOT_PROTOCOL_V1.md；修订及原账本继承：docs/TSP_EXECUTION_REVISION_V2.md。冻结源码、路径级结果和预算分别在本目录JSON/CSV及原runs中。

```sh
.venv/bin/python -B experiments/tsp/manage.py summary --directory {directory.relative_to(ROOT)}
.venv/bin/python -B experiments/tsp/manage.py status --directory {directory.relative_to(ROOT)}
```

已完成run不得再次run/resume。复核/报告不调用API或重新求解。未来任何新实验需要独立授权，不继承本批未用预算。
'''
    (out/'REPORT_ZH.md').write_text(text)
    print(json.dumps({'report':str(out/'REPORT_ZH.md'),'frozen_H_manual':selected_manual,'final_same_AST_as_static':identical,'search':groups,'comparisons':f['comparisons']},ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--directory',required=True);p.add_argument('--out',required=True);a=p.parse_args();report(Path(a.directory).resolve(),Path(a.out).resolve())
