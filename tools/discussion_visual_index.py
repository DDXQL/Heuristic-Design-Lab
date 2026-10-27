#!/usr/bin/env python3
"""Add readable figures to the discussion index using existing records only."""
import csv
import hashlib
import json
import os
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/师兄讨论材料-20261027-v1'
OLD=ROOT/'reports/组会实验盘点-20261027-v1'

def build():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font='/System/Library/Fonts/STHeiti Medium.ttc';font_manager.fontManager.addfont(font)
    plt.rcParams.update({'font.family':font_manager.FontProperties(fname=font).get_name(),'axes.unicode_minus':False,'svg.fonttype':'none','font.size':11})
    paths=[ROOT/'reports/b1-ns-recovery-B-execution-20261023/Summary.json',ROOT/'docs/usage-space/real-gpt61-301/Complete_summary.json',OUT/'TSP增量核查.json']
    b1,v22,tsp=[json.loads(p.read_text()) for p in paths]
    init=next(g for g in v22['groups'] if g['arm']=='INIT')
    counts=[('v2.2初始化',init['complete_valid_new_candidates'],0,init['request_slots']-init['returned_text_responses'],0),
            ('B1初始化',b1['stage_outcomes']['I1']['valid'],b1['stage_outcomes']['I1']['parse_or_constraint_error'],0,0),
            ('B1交叉',b1['stage_outcomes']['CROSS']['valid'],0,0,0),
            ('B1变异',b1['stage_outcomes']['MUTATE']['valid'],0,0,b1['stage_outcomes']['MUTATE']['invalid'])]
    assert [sum(r[1:]) for r in counts]==[8,9,5,5]
    fig,(ax,bx)=plt.subplots(1,2,figsize=(14,6.5))
    bottom=[0]*4
    for col,label,color in [(1,'完整有效','#21896b'),(2,'解析/约束失败','#d58a24'),(3,'传输失败','#8291a3'),(4,'评价/身份证据失败','#c95555')]:
        values=[r[col] for r in counts];ax.bar(range(4),values,bottom=bottom,color=color,label=label)
        bottom=[a+b for a,b in zip(bottom,values)]
    for i,r in enumerate(counts):ax.text(i,sum(r[1:])+.15,f'有效 {r[1]}/{sum(r[1:])}',ha='center',fontsize=10)
    ax.set(xticks=range(4),xticklabels=[r[0] for r in counts],ylabel='逻辑候选槽位数',ylim=(0,11),title='初始化与后续候选准入：保留失败槽位');ax.legend(fontsize=9)
    pairs={tuple(map(int,p.split(','))) for p in b1['observed_dual_pairs']}
    for i in range(10):
        for j in range(i+1,10):
            bx.scatter(j,i,marker='s',s=145,color='#21896b' if (i,j) in pairs else '#e4eaf0')
    bx.scatter(1,0,marker='s',s=210,facecolor='none',edgecolor='#c95555',lw=2,label='H0/H1未观察到双成员执行')
    bx.set(xticks=range(10),yticks=range(10),xticklabels=[f'H{i}' for i in range(10)],yticklabels=[f'H{i}' for i in range(10)],title='B1完整有效候选的双成员组合覆盖',xlim=(-.5,9.5),ylim=(9.5,-.5));bx.set_aspect('equal');bx.legend(fontsize=8,loc='lower left')
    fig.suptitle('初始化有效率与实际覆盖：程序可生成，不代表组合已探索充分',fontsize=16)
    fig.text(.025,.025,'train21；不同批次/阶段仅作描述，不是初始化方法消融。绿色为已观测7对；灰色表示未观察到，不代表组合无效。',fontsize=9,color='#475569')
    fig.subplots_adjust(top=.83,bottom=.18,wspace=.32)
    folder=OUT/'图表';folder.mkdir(exist_ok=True)
    def savefig(fig,name):
        fig.savefig(folder/(name+'.png'),dpi=190);fig.savefig(folder/(name+'.svg'))
        p=folder/(name+'.svg');p.write_text('\n'.join(x.rstrip() for x in p.read_text().splitlines())+'\n');plt.close(fig)
    savefig(fig,'初始化与实际组合覆盖')
    fig,ax=plt.subplots(figsize=(12,6));ax.axis('off')
    entries=[('接口与执行器','已实现：TSP专用状态、H/U签名、构造与合法性检查','#21896b'),
             ('测试与Mock','已有通过记录；Mock全流程不等于真实生成','#21896b'),
             ('静态求解',f'部分完成：{tsp["manual_H_valid"]}个人工H有效；静态U枚举阶段未开始','#d58a24'),
             ('真实LLM生成U',f'尚未开展：U请求{tsp["real_U_requests"]}；10份H响应在v1旧准入下0有效','#8291a3'),
             ('真实LLM演化U','尚未开展：无真实IND/EVO阶段结果','#8291a3')]
    for i,(label,note,color) in enumerate(entries):
        y=.84-i*.155;ax.scatter(.025,y,s=130,color=color,transform=ax.transAxes);ax.text(.075,y+.018,label,transform=ax.transAxes,fontsize=13,va='center');ax.text(.075,y-.036,note,transform=ax.transAxes,fontsize=11,color='#475569',va='center')
    fig.suptitle('TSP迁移证据进度：已有工程实现，尚无真实U质量结果',fontsize=16)
    fig.text(.045,.045,'来源：2026-10-27既有核查快照，非实时状态。合成欧氏50城市，不是四个TSPLIB实例；没有U结果就不绘制U性能排名。',fontsize=9,color='#475569')
    fig.subplots_adjust(top=.86,bottom=.14);savefig(fig,'TSP迁移证据进度')
    index=OUT/'近期实验总览与重要图表索引.md';text=index.read_text()
    # Keep historical evidence links, but make figure navigation primary.
    mappings=[
        ('固定H/静态融合',[(OLD/'图表/01_单H排名.png','单H'),(OLD/'图表/02_等权45对分布.png','45对'),(OLD/'图表/03_H01静态权重曲线.png','权重曲线')]),
        ('初始化/覆盖',[(folder/'初始化与实际组合覆盖.png','有效率与组合覆盖')]),
        ('生成/演化',[(OLD/'图表/04_B1_B2搜索与种群.png','搜索与种群')]),
        ('IND/EVO',[(OLD/'图表/09_IND_EVO探索性比较.png','三重复搜索曲线')]),
        ('融合/状态消融',[(OLD/'图表/07_融合表达与质量.png','机制与质量'),(OLD/'图表/11_预定动态规则族.png','固定规则族')]),
        ('反馈/传统基线',[(OLD/'图表/12_CROSS成绩反馈分任务.png','反馈A/B'),(OLD/'图表/08_A4完整与部分路径.png','A4')]),
        ('独立/跨族验证',[(OLD/'图表/10_冻结冠军训练外验证.png','Hurink验证')]),
        ('TSP迁移',[(folder/'TSP迁移证据进度.png','迁移进度（不是质量成绩）')])]
    def rel(p):return os.path.relpath(p,OUT)
    lines=[]
    for line in text.splitlines():
        if line=='|类别|实验|主要设置/目的|实际状态|主要结果|边界|证据|':
            line='|类别|实验|主要设置/目的|实际状态|主要结果|边界|看图（PNG）|原始证据（可选）|'
        elif line=='|---|---|---|---|---|---|---|':line='|---|---|---|---|---|---|---|---|'
        for category,images in mappings:
            if line.startswith('|'+category+'|'):
                cells=line.split('|')
                if len(cells)==9:
                    image_links=' / '.join(f'[{label}](<{rel(p)}>)' for p,label in images);cells.insert(-2,image_links);line='|'.join(cells)
                break
        lines.append(line)
    text='\n'.join(lines)+'\n'
    notice='''## 怎样直接看图

JSON/CSV是原始数据或账本，不是图片；无法在当前界面打开它们，不代表没有图。**先点总表“看图（PNG）”列，或直接看下方图片预览。** VS Code中可按`Command+Shift+V`打开本文Markdown预览；Windows/Linux为`Ctrl+Shift+V`。原始证据列保留，供需要时核对，不要求先读大JSON。

'''
    if '## 怎样直接看图' not in text:text=text.replace('\n|类别|', '\n'+notice+'|类别|',1)
    text=text.split('\n## 各类实验图片预览')[0]
    text+='\n## 各类实验图片预览\n\n下面是已有结果的可视化；不重新调用API或求解。原图保留，只补充初始化覆盖与TSP证据进度两张图。TSP图仅反映先前核查快照，不把未执行阶段画成成绩。\n'
    captions=[('固定H与静态融合',OLD/'图表/02_等权45对分布.png','完整45对质量表，保留原批/T30来源。'),
              ('初始化与策略覆盖',folder/'初始化与实际组合覆盖.png','有效率分母是逻辑槽位，未观察到的成员对不等于无效。'),
              ('历史生成与演化',OLD/'图表/04_B1_B2搜索与种群.png','B1/B2空间和初始化不同，非公平消融。'),
              ('独立生成与演化',OLD/'图表/09_IND_EVO探索性比较.png','113/120部分完成，保留失败槽位和未启动范围。'),
              ('融合机制',OLD/'图表/07_融合表达与质量.png','同状态动作差异与完整排程质量分开。'),
              ('成绩反馈',OLD/'图表/12_CROSS成绩反馈分任务.png','A有一项HTTP524；按父代任务展示全部有效子代。'),
              ('跨基准验证',OLD/'图表/10_冻结冠军训练外验证.png','同一冻结新冠军在Hurink退化；不是同分布验证。'),
              ('TSP迁移',folder/'TSP迁移证据进度.png','工程/Mock与真实LLM实验分层，没有真实U质量数据。')]
    for title,p,note in captions:
        assert p.exists(),p
        text+=f'\n### {title}\n\n{note}\n\n![{title}](<{rel(p)}>)\n'
    index.write_text(text)
    manifest={'sources':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},'new_figures':['初始化与实际组合覆盖','TSP迁移证据进度'],
              'formats':['PNG','SVG'],'new_API':0,'new_solves':0,'TSP':'复用既有核查快照，未更新或接触原运行。','index':'近期实验总览与重要图表索引.md'}
    (OUT/'可视化补充验收.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print('Updated visual links and inline previews; generated two evidence-only figures; API=0, solves=0.')

if __name__=='__main__':build()
