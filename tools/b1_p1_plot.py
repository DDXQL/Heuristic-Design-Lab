"""Plot real B1 checkpoints only. Never dispatches a provider or scheduler."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    args=parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    available={f.name for f in font_manager.fontManager.ttflist}
    font=next((x for x in ('Arial Unicode MS','PingFang HK','Noto Sans CJK SC') if x in available),'DejaVu Sans')
    plt.rcParams.update({'font.family':font,'axes.unicode_minus':False,'svg.fonttype':'none',
        'font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    r=args.run_dir.resolve();out=args.out_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    summary=json.loads((r/'results/Summary.json').read_text())
    rows=list(csv.DictReader((r/'results/Candidates.csv').open()))
    fig,axes=plt.subplots(1,2,figsize=(13.6,6.5),gridspec_kw={'width_ratios':[1.5,1]})
    fig.suptitle('10成员自由选择与双成员融合搜索：真实训练结果',fontsize=19,fontweight='bold',y=.98)
    best=None; curve=[];valid_x=[];valid_y=[];failed=[];duplicates=[]
    for i,row in enumerate(rows,1):
        if row['status']=='valid' and row['fitness']:
            value=float(row['fitness']);valid_x.append(i);valid_y.append(value)
            best=value if best is None else max(best,value)
        elif row['status']=='duplicate':duplicates.append(i)
        else:failed.append(i)
        curve.append(float('nan') if best is None else best)
    ax=axes[0]
    ax.scatter(valid_x,valid_y,s=32,color='#4383b4',alpha=.7,label='完整有效候选',zorder=3)
    ax.plot(range(1,len(rows)+1),curve,color='#d77820',lw=2.5,label='截至该槽位的冠军',zorder=4)
    ax.axvline(9.5,color='#777777',ls='--',lw=1)
    if len(rows)>19:ax.axvline(19.5,color='#777777',ls='--',lw=1)
    floor=min(valid_y)-.05
    if failed:ax.scatter(failed,[floor]*len(failed),marker='x',color='#b34848',label='失败槽位（此位置无Fitness含义）')
    if duplicates:ax.scatter(duplicates,[floor]*len(duplicates),marker='D',facecolors='none',edgecolors='#37835f',label='代码重复（不重新求解）')
    ax.set(xlabel='累计逻辑候选槽位（含无效和重复）',ylabel='train21 Fitness（越高越好）',xlim=(.5,len(rows)+.5))
    ax.grid(axis='y',alpha=.18);ax.legend(loc='center',bbox_to_anchor=(.29,.18),
        bbox_transform=fig.transFigure,ncol=2,fontsize=9)
    ax.set_title('真实候选顺序与best-so-far',pad=28)
    ax.text(5,1.02,'初始化9槽',transform=ax.get_xaxis_transform(),ha='center',fontsize=10)
    ax.text(14.5,1.02,'第一代10槽',transform=ax.get_xaxis_transform(),ha='center',fontsize=10)
    if len(rows)>19:ax.text(24.5,1.02,f'第二代{len(rows)-19}槽',transform=ax.get_xaxis_transform(),ha='center',fontsize=10)
    p=summary['populations'];names=list(p)
    ax=axes[1]
    means=[p[n]['mean'] for n in names];bests=[p[n]['best'] for n in names]
    ax.plot(range(len(names)),means,'o-',color='#246d9b',lw=2.3,label='种群平均Fitness')
    ax.plot(range(len(names)),bests,'s--',color='#d77820',lw=2.3,label='种群冠军Fitness')
    for i,(mean,best_value) in enumerate(zip(means,bests)):
        ax.annotate(f'{mean:.6f}',(i,mean),xytext=(0,-20),textcoords='offset points',ha='center',color='#246d9b')
        ax.annotate(f'{best_value:.6f}',(i,best_value),xytext=(0,12),textcoords='offset points',ha='center',color='#a75b17')
    ax.set_xticks(range(len(names)),[{'P0':'初始种群 P0','P1':'第一代 P1','P2':'第二代 P2'}[n] for n in names])
    ax.set(ylabel='train21 Fitness（越高越好）',xlim=(-.3,len(names)-.7))
    ax.set_ylim(min(means)-.08,max(bests)+.08);ax.grid(axis='y',alpha=.18)
    ax.set_title('平均水平与冠军分开报告',pad=28);ax.legend(loc='lower right',fontsize=9)
    delta=bests[-1]-bests[0]
    note=f"P0→{names[-1]}：冠军ΔFitness={delta:+.9f}；均值ΔFitness={means[-1]-means[0]:+.9f}。"
    fig.text(.045,.085,note,fontsize=11,color='#203c50')
    fig.text(.045,.035,'固定H0–H9；train21 / seed501 / T15；均值改善不等于冠军改善。旧失败保留；此图不含预测。',fontsize=10,color='#555555')
    fig.subplots_adjust(left=.07,right=.98,top=.78,bottom=.30,wspace=.30)
    for suffix in ('png','svg','pdf'):fig.savefig(out/f'10H自由搜索_真实搜索与种群.{suffix}',dpi=200,bbox_inches='tight')
    plt.close(fig)
    paths=[r/'results/Summary.json',r/'results/Candidates.csv']
    (out/'图表来源.json').write_text(json.dumps({'inputs':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'predicted_data':False,'status':summary['status'],'populations':names},ensure_ascii=False,indent=2)+'\n')
    print(out/'10H自由搜索_真实搜索与种群.png')


if __name__=='__main__':main()
