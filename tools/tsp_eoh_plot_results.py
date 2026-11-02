"""Plot supplied offline EoH comparison data only; no project imports or solver."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();d=json.loads(a.data.read_text());a.output.mkdir(parents=True,exist_ok=True)
    names={f.name for f in font_manager.fontManager.ttflist}
    plt.rcParams.update({'font.sans-serif':[x for x in ('PingFang SC','Arial Unicode MS','Noto Sans CJK SC','Microsoft YaHei') if x in names]+['DejaVu Sans'],
                         'svg.fonttype':'none','axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    suffix=('MOCK工程验证，非科研成绩' if d['engineering'] else '真实落盘训练结果')+f' | {d["phase"]} | 截至 {d["as_of"]}'
    def save(fig,stem):
        fig.text(.02,.015,suffix,fontsize=8,color='#475569');fig.tight_layout(rect=(0,.06,1,1))
        for ext in ('png','svg'):fig.savefig(a.output/f'{stem}.{ext}',dpi=180,facecolor='white')
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(10,4.8));plotted=False
    for key,label,color in [('curve','EoH单H','#2563EB'),('previous_curve','已有U（横轴含H构建40槽）','#059669')]:
        rows=[r for r in d[key] if r['requests'] is not None and r['best_fitness'] is not None]
        if rows:ax.step([r['requests'] for r in rows],[r['best_fitness'] for r in rows],where='post',label=label,color=color);plotted=True
    ax.axvline(253,color='#64748B',linestyle='--',linewidth=1,label='已有方案实际253槽')
    ax.set(xlabel='累计请求槽位（含失败、重复及初始化）',ylabel='最佳完整train20 Fitness ↑',title='同260上限的端到端训练预算比较')
    if not plotted:ax.text(.5,.5,'尚无有效已提交候选；不补造曲线',transform=ax.transAxes,ha='center')
    ax.legend(fontsize=9);ax.grid(alpha=.15);save(fig,'01_budget_fitness')
    fig,ax=plt.subplots(figsize=(10,4.8));rows=[r for r in d['comparison'][:2] if r['fitness'] is not None]
    if len(rows)==2:
        ax.scatter([r['fitness'] for r in rows],range(2),s=90,color=['#059669','#2563EB'])
        for i,r in enumerate(rows):ax.annotate(f'{r["fitness"]:.9f}；{r["request_slots"]}/{r["request_cap"]}槽',(r['fitness'],i),xytext=(0,14),textcoords='offset points',ha='center')
        ax.set(yticks=range(2),yticklabels=[r['method'] for r in rows],ylim=(-.7,1.7),xlabel='完整train20 Fitness ↑',title='训练冠军；不同实际用量单列，非泛化结果')
        ax.margins(x=.4)
    else:ax.set_axis_off();ax.text(.5,.5,'EoH真实训练结果尚未产生；保留占位',ha='center',va='center',transform=ax.transAxes)
    save(fig,'02_final_comparison')
    fig,ax=plt.subplots(figsize=(11,4.8));paired=d['paired']
    if paired:
        vals=[r['relative_length_reduction_percent'] for r in paired]
        ax.bar(range(len(vals)),vals,color=['#2563EB' if v>=0 else '#D97706' for v in vals])
        ax.axhline(0,color='#64748B',linewidth=1);ax.set(xticks=range(len(vals)),xticklabels=[r['file'].replace('train_','').replace('.json','') for r in paired],
            xlabel='train实例',ylabel='EoH相对双层长度降低（%）',title='逐实例配对；正值EoH较优、负值双层较优')
    else:ax.set_axis_off();ax.text(.5,.5,'配对结果尚未产生；不补跑、不填值',ha='center',va='center',transform=ax.transAxes)
    save(fig,'03_instance_comparison')


if __name__=='__main__':main()
