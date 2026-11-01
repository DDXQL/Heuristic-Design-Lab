"""Plot ONLY supplied offline tables. No project imports, API or solver access."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    d=json.loads(a.data.read_text());a.output.mkdir(parents=True,exist_ok=True)
    available={f.name for f in font_manager.fontManager.ttflist}
    preferred=[x for x in ['PingFang SC','Arial Unicode MS','Noto Sans CJK SC','Microsoft YaHei','SimHei'] if x in available]
    plt.rcParams.update({'font.sans-serif':preferred+['DejaVu Sans'],'axes.unicode_minus':False,
        'svg.fonttype':'none','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
    blue='#2563EB';green='#059669';orange='#D97706'
    label='MOCK 工程验证 · 非科研成绩' if d['engineering'] else '真实落盘结果'
    suffix=f'{label} | {d["phase"]} | 截至 {d["as_of"]}'
    def save(fig,name):
        fig.text(.02,.015,suffix,fontsize=8,color='#475569');fig.tight_layout(rect=(0,.06,1,1))
        for ext in ('png','svg'):fig.savefig(a.output/f'{name}.{ext}',dpi=180,facecolor='white')
        plt.close(fig)
    def placeholder(title,notice,name):
        fig,ax=plt.subplots(figsize=(10,4.8));ax.set_axis_off();ax.set_title(title,loc='left',fontweight='bold')
        ax.text(.5,.5,notice,ha='center',va='center',wrap=True,transform=ax.transAxes,color='#64748B');save(fig,name)
    curve=[r for r in d['curve'] if r['best_fitness'] is not None]
    if curve:
        fig,ax=plt.subplots(figsize=(10,4.8));ax.step([r['requests'] for r in curve],[r['best_fitness'] for r in curve],where='post',color=blue)
        ax.set(xlabel='累计请求槽位（含初始化、失败、重复）',ylabel='最佳完整训练 Fitness ↑',title='已提交候选的最佳 Fitness')
        ax.grid(alpha=.15);save(fig,'01_best_fitness')
    else:placeholder('最佳 Fitness','尚无有效已提交候选；不生成虚构曲线','01_best_fitness')
    if d['kind']=='H':
        quality=d.get('quality',[])
        if quality:
            fig,ax=plt.subplots(figsize=(10,max(4.8,len(quality)*.19)))
            ax.barh([r['id'] for r in quality],[r['fitness'] for r in quality],color=blue);ax.invert_yaxis()
            ax.set(xlabel='完整训练 Fitness ↑',title='H候选质量（非仅最终入选者）');save(fig,'02_H_quality')
        else:placeholder('H质量','候选质量待产生','02_H_quality')
        matrix=d.get('matrix',[])
        if matrix:
            fig,ax=plt.subplots(figsize=(11,5.8));im=ax.imshow([r['scores'] for r in matrix],aspect='auto',cmap='viridis')
            ax.set(yticks=range(len(matrix)),yticklabels=[r['id'] for r in matrix],xlabel='固定顺序训练实例索引',title='最终冻结成员分数矩阵' if d['selection_final'] else '进行中：当前均值前10候选（展示，非冻结）')
            width=len(matrix[0]['scores'])
            ax.set_xticks(range(width),labels=[str(i+1) for i in range(width)])
            fig.colorbar(im,ax=ax,label='−length / NN_length');save(fig,'03_H_score_matrix')
        else:placeholder('逐实例互补性','完整分数矩阵待产生','03_H_score_matrix')
        comp=d.get('complementarity',[])
        if comp:
            fig,ax=plt.subplots(figsize=(10,4.8));ax.bar([r['id'] for r in comp],[r['leave_one_out_envelope_loss'] for r in comp],color=green)
            ax.scatter(range(len(comp)),[r['leave_one_out_envelope_loss'] for r in comp],color=green,s=22,zorder=3)
            ax.tick_params(axis='x',rotation=45);ax.set(ylabel='移除该成员的包络损失 ↑',title='单H逐实例包络诊断；不代表动态路由表现')
            ax.text(.98,.95,f'包络相对最佳单H增益：{comp[0]["envelope_gain"]:.6f}',transform=ax.transAxes,ha='right',va='top');save(fig,'04_H_complementarity')
        else:placeholder('互补性诊断','成员不足，保留占位','04_H_complementarity')
        placeholder('U搜索与基线比较','H构建阶段：U搜索、独立基线及训练外验证尚未运行','05_baseline_comparison')
    else:
        generations=d.get('generations',[])
        if generations:
            fig,ax=plt.subplots(figsize=(10,4.8));ax.plot([r['generation'] for r in generations],[r['behavior_groups'] for r in generations],marker='o',color=orange)
            ax.set(xlabel='已完成代数',ylabel='种群中不同H序列向量数',title='U种群行为多样性');ax.grid(alpha=.15);save(fig,'02_U_behavior_diversity')
        else:placeholder('U种群行为多样性','尚无完整代；不填补缺失代数','02_U_behavior_diversity')
        c=d.get('comparison',{})
        if c.get('status')=='compatible':
            fig,ax=plt.subplots(figsize=(10,4.8));ax.bar(['U训练冠军','最佳恒选H'],[c['U_fitness'],c['baseline_fitness']],color=[blue,green]);ax.set(ylabel='完整训练 Fitness ↑',title=f'同口径训练比较 · 胜/负/平 {c["wins"]}/{c["losses"]}/{c["ties"]}')
            save(fig,'03_baseline_comparison')
        else:placeholder('同口径基线比较','基线缺失或不兼容：'+c.get('status','missing'),'03_baseline_comparison')
    placeholder('训练外验证','尚未执行；不得将训练成绩解释为泛化收益','06_validation_placeholder')


if __name__=='__main__':main()
