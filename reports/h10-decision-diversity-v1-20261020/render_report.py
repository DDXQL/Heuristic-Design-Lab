#!/usr/bin/env python3
"""Render saved observations only; no scheduler, data-loader or API imports."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
from statistics import fmean

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
import pypdfium2 as pdfium

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
read = lambda p: json.loads(p.read_text())
metrics, plan = read(HERE/'Metrics.json'), read(HERE/'Plan.json')
rows = [json.loads(line) for line in gzip.open(HERE/'sampled_states.jsonl.gz','rt')]
labels = [f'H{i}' for i in range(10)]
tie_sensitivity = {}
for label in ('B3','B5'):
    tie_sensitivity[label] = {}
    for scope, subset in [('all',rows),('own',[r for r in rows if r['driver']==label])]:
        below = [[r['raw_scores'][i][r['choices'][label]['action_index']] < max(r['raw_scores'][i])
                  for i in range(10)] for r in subset]
        tie_sensitivity[label][scope] = {'n':len(subset),
            'strictly_below_both_constituent_maxima':sum(all(b[i] for i in r['choices'][label]['support']) for b,r in zip(below,subset)),
            'strictly_below_all_10H_maxima':sum(all(b) for b in below)}
with (HERE/'Tie_sensitivity.json').open('x') as stream:
    json.dump(tie_sensitivity,stream,indent=2)
    stream.write('\n')


def csv_write(name, headers, values):
    with (HERE/name).open('x',newline='') as stream:
        writer = csv.writer(stream,lineterminator='\n')
        writer.writerow(headers)
        writer.writerows(values)


def md_table(headers, values):
    return '\n'.join(['| '+' | '.join(map(str,headers))+' |',
                      '| '+' | '.join(['---']*len(headers))+' |']
                    + ['| '+' | '.join(map(str,row))+' |' for row in values])


for kind in ('agreement','spearman'):
    csv_write(f'{kind}_matrix.csv',['member',*labels],[[labels[i],*r] for i,r in enumerate(metrics[kind]['values'])])
def save_figure(drawing, name):
    renderSVG.drawToFile(drawing,str(HERE/f'{name}.svg'))
    document=pdfium.PdfDocument(renderPDF.drawToString(drawing))
    page=document[0]
    bitmap=page.render(scale=1.5)
    bitmap.to_pil().save(HERE/f'{name}.png')
    bitmap.close();page.close();document.close()


def shade(value):
    return colors.Color((247-239*value)/255,(251-203*value)/255,(255-148*value)/255)


fig=Drawing(1480,800)
fig.add(Rect(0,0,1480,800,fillColor=colors.white,strokeColor=None))
fig.add(String(55,765,'Frozen 10H: train only / 6 instances / 4 reachable paths / 384 sampled states',fontSize=20,fontName='Helvetica-Bold'))
fig.add(String(55,737,'Equal instance/path strata; highest score wins; original stable action ties. Color scale: 0 to 1.',fontSize=14))
for x,kind,title in [(80,'agreement','Same top action (%)'),(820,'spearman','Mean Spearman correlation (ties averaged)')]:
    data=metrics[kind]['values']
    fig.add(String(x,697,title,fontName='Helvetica-Bold',fontSize=17))
    for i in range(10):
        fig.add(String(x-32,632-58*i,labels[i],fontSize=12))
        fig.add(String(x+29+58*i,672,labels[i],fontSize=12,textAnchor='middle'))
        for j in range(10):
            value=data[i][j]
            xx,yy=x+58*j,610-58*i
            fig.add(Rect(xx,yy,58,58,fillColor=shade(value),strokeColor=colors.white,strokeWidth=.5))
            text=f'{100*value:.1f}' if kind=='agreement' else f'{value:.4f}'
            fig.add(String(xx+29,yy+24,text,fontSize=10,textAnchor='middle',fillColor=colors.white if value>.6 else colors.black))
    for i in range(6):
        fig.add(Rect(x+80*i,38,80,14,fillColor=shade(i/5),strokeColor=None))
        fig.add(String(x+80*i,20,f'{i/5:.1f}',fontSize=10))
save_figure(fig,'H10_similarity')

bins=metrics['bins']
fig=Drawing(1200,480)
fig.add(Rect(0,0,1200,480,fillColor=colors.white,strokeColor=None))
fig.add(String(45,444,'Distinct H top actions: descriptive associations in sampled train states',fontName='Helvetica-Bold',fontSize=18))
fig.add(String(45,415,'Progress, candidate count, instance structure and driver are confounded; no causal interpretation.',fontSize=12))
for x,keys,ticks,title in [
    (75,list(bins)[:5],['0-20','20-40','40-60','60-80','80-100'],'Scheduling progress (%)'),
    (695,list(bins)[5:],['2-9','10-49','50-199','200+'],'Number of legal actions')]:
    values=[bins[k]['mean_distinct'] for k in keys]
    plot=VerticalBarChart()
    plot.x,plot.y,plot.width,plot.height=x,90,440,260
    plot.data=[values]
    plot.categoryAxis.categoryNames=ticks
    plot.categoryAxis.labels.fontSize=11
    plot.valueAxis.valueMin,plot.valueAxis.valueMax,plot.valueAxis.valueStep=0,6,1
    plot.valueAxis.labels.fontSize=11
    plot.bars[0].fillColor=colors.HexColor('#3579a8')
    fig.add(plot)
    fig.add(String(x,378,title,fontName='Helvetica-Bold',fontSize=15))
    fig.add(String(x,52,'Mean distinct top actions; n = sampled states',fontSize=11))
    for i,k in enumerate(keys):
        xx=x+(i+.5)*440/len(keys)
        yy=90+values[i]*260/6
        fig.add(String(xx,yy+8,f'{values[i]:.2f}',textAnchor='middle',fontSize=11))
        fig.add(String(xx,yy-17,f'n={bins[k]["n"]}',textAnchor='middle',fontSize=10,fillColor=colors.white))
save_figure(fig,'Disagreement_by_state')

pair_rows=[]
for i in range(10):
    for j in range(i+1,10):
        different=[r for r in rows if r['top_actions'][i]!=r['top_actions'][j]]
        strict=sum(r['raw_scores'][i][r['top_actions'][j]]<max(r['raw_scores'][i]) and
                   r['raw_scores'][j][r['top_actions'][i]]<max(r['raw_scores'][j]) for r in different)
        pair_rows.append([labels[i],labels[j],metrics['agreement']['values'][i][j],
            metrics['spearman']['values'][i][j],len(different),strict,len(different)-strict,
            sum(r['actions'][r['top_actions'][i]][:2]==r['actions'][r['top_actions'][j]][:2] for r in different),
            metrics['unique_physical_agreement_micro'][i][j],metrics['at_least_10_actions_agreement']['values'][i][j]])
csv_write('Pair_details.csv',['h_a','h_b','top_agreement','spearman','top_differences',
    'both_strictly_prefer_own_top','at_least_one_indifferent','same_job_operation_but_different_machine',
    'unique_physical_micro_agreement','at_least_10_actions_agreement'],pair_rows)
policies=['H0','H1','B3','B5']
policy_agreement=[[fmean(r['choices'][a]['action_index']==r['choices'][b]['action_index'] for r in rows)
                   for b in policies] for a in policies]
csv_write('Common_state_policy_agreement.csv',['policy',*policies],[[a,*v] for a,v in zip(policies,policy_agreement)])
csv_write('Sample_index.csv',['id','driver','instance','step','progress','legal_actions','distinct_H_tops','physical_sha256'],
          [[r['id'],r['driver'],r['file'],r['step'],r['state']['progress'],len(r['actions']),
            r['distinct_top_actions'],r['physical_sha256']] for r in rows])
csv_write('State_bins.csv',['stratum','states','mean_distinct_tops','mean_pair_disagreement'],
          [[k,v['n'],v['mean_distinct'],v['mean_pairwise_disagreement']] for k,v in bins.items()])

example_ids=['Behnke19.fjsp/B3/0166','Behnke3.fjsp/H1/0045',
             'Behnke43.fjsp/H1/0009','Behnke3.fjsp/B3/0042','Behnke43.fjsp/H0/0049']
examples=[next(r for r in rows if r['id']==key) for key in example_ids]
text=['# 代表状态：完整评分见 sampled_states.jsonl.gz',
      '以下例子为采样完成后的说明性摘录；不是按成绩筛选的新样本。job/operation/machine/step均从0编号。',
      '表中排名按原精确分数递减；同分使用合法动作原枚举次序。这里只展示前三个，不能用四舍五入后的分数重新判同分。']
for r in examples:
    text += [f'\n## {r["id"]}',
        f'合法动作{len(r["actions"])}个，10H首选共{r["distinct_top_actions"]}种；七状态：`{json.dumps(r["state"],ensure_ascii=False)}`。',
        md_table(['H','前三动作(job,op,machine)','对应原始分数'],
            [[labels[i],'; '.join(str(tuple(r['actions'][a][:3])) for a in r['stable_rankings'][i][:3]),
              '; '.join(f'{r["raw_scores"][i][a]:.17g}' for a in r['stable_rankings'][i][:3])]
             for i in range(10)]),
        md_table(['同态策略','支持集/实际归一化权重','首选动作','是否本轨迹实际动作'],
            [[key,str([(i,round(value['weights'][i],6)) for i in value['support']]),
              str(tuple(r['actions'][value['action_index']])),key==r['driver']]
             for key,value in r['choices'].items()])]
(HERE/'Representative_states.md').write_text('\n\n'.join(text)+'\n')

# Reuse an existing fixed-weight reference only after binding H/data/semantics.
grid_dir=ROOT/'reports/usage-fixed-pair-weight-grid-20261018-v1'
grid_plan=read(grid_dir/'Plan.json')
assert grid_plan['names']==[s['file'] for s in plan['structures_train21']]
assert grid_plan['H_order']==[h['code_key'] for h in plan['H_order']]
extra_pins={}
for relative in ('runs/v22-gpt61-select-mix-301-20261014-v1/H_frozen.json',
                 'data/fjsp_manifest.json','code/fjsp_usage/offline_v2.py','code/fjsp_usage/usage_v2/execution.py'):
    assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==grid_plan['pins'][relative]
grid=read(grid_dir/'results/H0_H1_w50_50.json')
assert grid['valid'] and grid['total_instances']==21
for p in (grid_dir/'Plan.json',grid_dir/'results/H0_H1_w50_50.json'):
    extra_pins[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()

agreement=md_table(['%同首选',*labels],
    [[labels[i],*[f'{100*x:.1f}' for x in v]] for i,v in enumerate(metrics['agreement']['values'])])
neighbor=md_table(['成员对','首选相同','Spearman','不同首选：双向严格/涉及一方无差别'],
    [[f'H{i}/H{j}',f'{100*metrics["agreement"]["values"][i][j]:.2f}%',
      f'{metrics["spearman"]["values"][i][j]:.6f}',
      '/'.join(str(next(x for x in pair_rows if x[:2]==[f'H{i}',f'H{j}'])[k]) for k in (5,6))]
     for i,j in [(1,3),(4,5),(6,7),(8,9)]])
structures=md_table(['实例','J/M/Q','柔性：平均候选机器数/M','名义最大负荷份额'],
    [[s['file'],f'{s["jobs"]}/{s["machines"]}/{s["operations"]}',f'{s["flexibility"]:.3f}',
      f'{s["nominal_max_load_share"]:.3f}'] for n in plan['selected'] for s in plan['structures_train21'] if s['file']==n])
main=f'''# 固定10H决策多样性诊断 V1

**在本次384个可达状态中，10H具有明显但不均匀的行为差异：平均产生4.37个不同首选，最多8个；H4/H5最接近。现有数据不能判定Kmax=2是收益瓶颈，也不能证明更大K或扩展U状态会更好。**

## 前提与范围

原生 `usage_v2/execution.py` 已有完整合法动作枚举和只读trace入口。U每步先输出，执行器对全部当前合法动作评分，再按最大值和稳定枚举次序选动作；trace虽在提交后回调，保存的是提交前状态。本工具只在独立镜像中恢复这个状态，旁路评分不向原执行器提供动作。动作集合指**现有追加式构造器允许的全部“未完成作业下一工序×可选机器”**，不包含插空等其他调度动作。

H0/H1各对6个实例进行一次原生端点回放（复用既有alpha=1/0源码，不生成U），并与历史固定h完整Schedule哈希核对。B3/B5复用已保存的逐步动作，逐步检查合法性、七状态、U输出、动作数、行为哈希，最终重建的完整UsageResultV2哈希匹配原主评价。**24条路径全部通过**；B3/B5没有重新完整求解。观察器只在预定抽样步计算10H；所有样本原driver动作均匹配原生argmax/组合规则。

先读取21train结构，再用预定最远点覆盖规则选6个实例，规则与来源哈希在[Plan.json](Plan.json)，不使用策略成绩选样本。特征为log作业数/机器数/工序数、柔性、名义最大负荷份额；初始为最大工序数、同分按manifest顺序。名义负荷是各工序向候选机器均分的加工时间代理，**不是实际排程负荷**。这是有限结构覆盖，不是随机代表整个问题族；未覆盖全部训练结构极值。

{structures}

每实例固定H0、H1、真实B3（成员对2/4或4/7）、真实B5（成员对0/9）四条路径，各取`floor(t*(Q−1)/15), t=0..15`，共384状态、364不同物理状态、每状态4–1056个合法动作。这样避免只观察H0路径；四条路径仍不是全部可达状态分布。重复物理状态保留在分层主分析中，另给去重敏感性结果。

只打开21个train文件；没有holdout读取、LLM/LeafAPI/账单查询、新H/U、权重搜索、正式fitness评价或原记录写入。没有修改生产调度器。原公式及裁剪由原编译器执行；首选精确同分按作业、机器枚举先后，排名相关性按同分平均秩计算，常量列应为未知。本次所有384状态的各列相关性均可定义。

## 10H相似性

主表是同态首选动作一致百分比，先在每个实例×driver内平均，再等权平均24个分层。完整相关矩阵见[图](H10_similarity.png)及[Spearman CSV](spearman_matrix.csv)。状态间相关且来自训练，下面不作独立样本显著性检验。

{agreement}

![10H相似性矩阵](H10_similarity.png)

{neighbor}

H4/H5只有14/384个首选不同，且均为不同作业间的严格偏好翻转；H4比H5多一个依赖工序数和剩余工作的depth_bonus，整体排名极近也可能翻转头部。H1/H3有51个首选不同，其中20个涉及一方对两个动作同分，31个为双方严格偏好相反；16个差异仅换同一工序的机器。未丢弃这些同分造成的实际差异，也未把它们全部解释为强冲突。

在未触发裁剪的合法输入下，H1的估计量为`finish+w−w/n`，H3为`finish+w−min(p,w/n)`；H3会在`p<w/n`时抵消finish中的当前加工时间，造成某些机器同分。因此Spearman达0.999065仍不等于首选相同。H6/H7首选一致84.38%，H8/H9只有71.09%，后者不能仅因公式相似就当作等价成员。

H0/H1首选一致仅16.93%、Spearman约0.317；H1/H4与H3/H4也很不同（首选一致6.77%/5.73%），H2相对H0及H6同样不同。这些是可利用信息存在的候选线索，不是组合收益排名。

去重后H1/H3、H4/H5、H6/H7、H8/H9一致率分别86.26%、96.15%、84.62%、69.78%，与主表判断相近；排除不足10个动作的状态后分别85.62%、96.05%、84.54%、70.08%。不能根据近邻结果直接删除成员：单选首选相似不保证与第三条h组合后的min–max分数几何相同。组合还取决于归一化后的数值间距，仅凭排名相关性不能判断成员可互换。

## 状态、路径与真实动作例子

H0、H1、B3、B5路径的平均不同首选数分别4.47、3.28、4.77、4.97，说明只采H0会漏掉部分路径行为。进度20–40%平均5.125种、80–100%为3.11种；2–9个候选动作时为1.85种，200个以上为5.30种。**进度、动作数、实例结构、driver相互混杂**，不能解释为进度导致分歧或大实例更有组合收益。逐实例与各分层见[Metrics.json](Metrics.json)。

![分歧与状态](Disagreement_by_state.png)

三个可核查例子（编号从0开始，完整10H前三排名、原分数和七状态见[代表状态](Representative_states.md)；压缩原始文件保留全部动作、输入、分数、秩）：

- `Behnke3/H1/step45`：12个动作，H1选(job1,op3,m14)，H3选(job1,op3,m9)。H3对m9/m13/m14同分，按机器编号选m9；H1对m14严格更偏好。
- `Behnke43/H1/step9`：36个动作，H4选(job8,op0,m3)，分数28.768743；H5选(job2,op0,m3)，分数26.8125。不同H的原始分数不能直接跨列比较大小。
- `Behnke3/B3/step42`：B3实际以H4/H7权重0.602181/0.397819，选(job6,op4,m19,start79,end92)。该动作在H4/H7平均秩为2.5/2，**不是任何一条H的单独首选**。这是组合改变动作的直接行为证据，后续收益未知。

## 当前MIX利用了什么，尚不能说明什么

将已有B3/B5直接应用于全部384个共同状态（七状态及previous_heuristic来自原driver，不另滚动影子策略历史）：B3有95/384步、B5有72/384步选择了两个组成成员各自首选之外的动作；其中46/384、36/384步不是任何10H单独首选。在它们自己的96个抽样状态中，后一个计数分别24、21。这里首选包含原同分规则；更严口径下，所选动作严格低于两个组成成员各自最高分的计数为91/384、69/384，严格低于全部10H各自最高分的计数为42/384、32/384（其余可能涉及打破同分，见[Tie_sensitivity.json](Tie_sensitivity.json)）。B3/B5同态首选相同54.17%；全部共同策略一致率见[CSV](Common_state_policy_agreement.csv)。这些数字说明组合不是简单挑一个h，但不能说明折中动作更好。

完整排程性能只复用原21train：H0=−2.111805、B3=−2.424245、B5=−2.329617，两个真实动态组合都低于H0。另经H身份、train和执行语义绑定核对，既有H0/H1等权手工网格结果为{grid['fitness']:.6f}，高于H0；来源为`reports/usage-fixed-pair-weight-grid-20261018-v1/results/H0_H1_w50_50.json`，本轮未重评。这支持优先理解H0/H1这一已有训练获益的简单组合，不支持“分歧越大越好”，也不是独立验证或本轮LLM收益。单步排名和完整fitness不能互作正确成员标签。

## 科研判断与下一步

1. **10H确有明显排序差异，也有近似冗余**：优先区分H4/H5的细微头部翻转与H0/H1等跨偏好差异。保留公式、具体状态和同分机制，不能只按源码相似度划类。
2. **还没有证据表明两成员限制是明显瓶颈**。某状态有8个不同首选，不代表必须同时混8条；现有U本来可逐步从10条任选成员/成员对，两条也已能产生单h首选之外的动作。缺少“第三条评分对最终质量的边际价值”证据。
3. **目前不建议直接扩大到Kmax=2/3/5搜索**。先以H0/H1已有基线和冻结U补足成员选择/权重机制证据；若之后检验K，先做独立登记的2对3小对照，控制成员来源、初始策略、评价及计算预算，再决定是否加入5。本轮不修改接口、不执行该比较。
4. **七状态可能不足，但当前不能定论**。U只有进度、候选对数量比例、剩余工作均值/标准差、机器ready均值/标准差及上一主导成员，看不到当前合法动作及10H的分数/排名冲突。聚合量丢失了作业—机器对应信息，可能限制对分歧的感知；本样本未发现七输入完全相同而物理状态不同的精确碰撞，也不能由此证明七状态充分。尚缺与最终收益相关、受控且可部署的感知验证；本轮不扩展状态。

未解决：未采轨迹/实例能否保持上述相似性；微小排序翻转如何累积为排程变化；MIX折中何时带来收益或损害；动态权重相对合适常量是否有增益；增加成员的质量收益能否抵消评分成本；七状态对这些条件是否足够。均没有状态级正确成员标签或泛化/因果收益结论。

## 成本、核验与复现

原生H0/H1共12遍有限回放，新增原生h评分625,892次；样本旁路10H评分919,080次；本地诊断约20.20秒。时间包含镜像、旁路打分、压缩和统计，不是求解器速度比较，没有新增确定性复检或候选有效性判定。24条路径哈希全部匹配、全部输入pins前后不变；离线检查覆盖同分秩、常量相关性未知、动作数量和非法提交拒绝。未修改历史有效性、期限、checkpoint、资产或账本。

原采集命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=code .venv/bin/python -B tools/diagnose_h_decision_diversity.py`（目录已存在会拒绝重跑）；`--check`仅做离线前提检查、不求解。`render_report.py`仅读取派生诊断及已说明的旧网格参照，使用预装ReportLab生成表图，不运行调度器。已有计划、完整样本、路径核对、CSV与Completion共同构成本次证据；不要把本次局部观察当成新的训练搜索或独立验证。
'''
(HERE/'README.md').write_text(main)
(HERE/'Additional_reference_pins.json').write_text(json.dumps(extra_pins,indent=2)+'\n')
print('Rendered saved diagnostics, matrices, representative states and Chinese report.')
