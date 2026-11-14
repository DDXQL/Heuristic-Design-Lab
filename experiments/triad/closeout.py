#!/usr/bin/env python3
"""Read-only closeout of existing J exports. No executor, solver or client imports."""
import argparse
import ast
import collections
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[2]
VERSION='offline-closeout-v1'
SECRET_PATTERNS=[re.compile(x,re.I) for x in (
    rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    rb'\bsk-[a-z0-9_-]{20,}',
    rb'authorization[\s"\x27:=]+bearer\s+[a-z0-9._-]{16,}',
    rb'"(?:api_key|access_token|password)"\s*:\s*"[^"\s]{12,}"')]
FORBIDDEN={'.venv','venv','__pycache__','.git','.ssh','account-gate','node_modules'}


def read(path):return json.loads(Path(path).read_text())
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()
def table(path,rows,columns=None):
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=columns or list(rows[0]) if rows else columns or [],extrasaction='ignore');w.writeheader();w.writerows(rows)
def csvrows(path):
    with Path(path).open(newline='') as f:return list(csv.DictReader(f))
def number(v):
    if v in (None,''):return None
    value=float(v)
    if not math.isfinite(value):raise ValueError('nonfinite recorded numeric value')
    return value
def sequence(v):
    if isinstance(v,(tuple,list)):return list(v)
    if not v:return []
    value=ast.literal_eval(v)
    if not isinstance(value,(tuple,list)):raise ValueError('sequence must be a stored list/tuple')
    return list(value)
def git(*args):
    p=subprocess.run(['git','-C',str(ROOT),*args],text=True,capture_output=True)
    return p.stdout.strip() if p.returncode==0 else None


def outcome(row):
    failure=row.get('failure','')
    if 'duplicate' in failure.lower():return 'duplicate'
    if row.get('valid') in (True,'True','true','1'):return 'valid_unique'
    if 'parse' in failure or 'constraint' in failure:return 'parse_or_constraint_failure'
    if 'evaluation' in failure:return 'evaluation_failure'
    if 'transport' in failure or row.get('api_outcome') in ('transport_failed','response_rejected'):return 'transport_or_response_failure'
    return 'unknown_or_other'


def inspect(source,allow_incomplete=False):
    source=Path(source).resolve()
    p=read(source/'Protocol.json');s=read(source/'checkpoint.json');summary=read(source/'exports/summary.json')
    if p['version'] not in ('parent-coverage-routing-v1','triad-shared-native-adapter-v1'):raise ValueError('only explicit J protocol exports are supported; legacy Fitness is not reinterpreted')
    identity=sha(source/'Protocol.json')
    if s.get('identity')!=identity or summary.get('protocol_sha256',identity)!=identity:raise ValueError('protocol/checkpoint/export identity mismatch')
    receipt=source/'Protocol.receipt.json'
    if receipt.exists() and read(receipt).get('sha256')!=identity:raise ValueError('protocol receipt differs')
    receipt=source/'checkpoint.receipt.json'
    if receipt.exists() and read(receipt)!={'identity':identity,'sha256':sha(source/'checkpoint.json')}:raise ValueError('checkpoint receipt differs')
    locks=[n for n in ('.coordinator.lock','.execution.lock','Stop.json') if (source/n).exists()]
    unknown=[k for k,t in s['tasks'].items() if t.get('status') not in ('completed','planned') or t.get('send_state')=='unknown']
    safe=s['phase']=='completed' or allow_incomplete and s['phase']=='paused'
    if not safe or locks or unknown or summary.get('unknown_sends',0):raise ValueError('source is active, unknown or not safely settled; retain original evidence')
    rows=csvrows(source/'exports/candidates.csv')
    if len(rows)!=len([t for t in s['tasks'].values() if t['status']=='completed']):raise ValueError('candidate export does not cover settled tasks; export with its original frozen tool first')
    init=sum(r['stage']=='initialization' for r in rows);evo=sum(r['stage']=='evolution' for r in rows)
    if (init,evo)!=(summary['initialization_attempts'],summary['evolution_attempts']):raise ValueError('export/budget counters differ')
    if [int(r['evolution_attempt']) for r in rows if r['stage']=='evolution']!=list(range(1,evo+1)):raise ValueError('evolution axis drops or duplicates attempts')
    champion=read(source/'exports/champion.json') if (source/'exports/champion.json').exists() else None
    if champion and (champion['id']!=summary['champion_id'] or champion['J']!=summary['best_J']):raise ValueError('champion/summary mismatch')
    return {'source':str(source),'protocol':p,'checkpoint':s,'summary':summary,'candidates':rows,'champion':champion,'status':{
      'phase':s['phase'],'run_id':summary['run_id'],'problem':p['config']['problem'],'search_seed':p['config']['search_seed'],
      'protocol_sha256':identity,'initialization_attempts':init,'evolution_attempts':evo,'outcomes':dict(collections.Counter(outcome(r) for r in rows)),
      'locks':locks,'unsettled_tasks':len(unknown),'matplotlib_available':importlib.util.find_spec('matplotlib') is not None,
      'source_writes':0,'API_requests':0,'actual_solves':0,'test_dataset_opened':False,'writer_check':'settled phase + no locks + receipt identity; full build also checks before/after source bytes'}}


def analyse(info,out):
    p=info['protocol'];rows=info['candidates'];champ=info['champion'];out.mkdir(parents=True)
    attempts=[];changes=[];edges=[];best=None
    for row in rows:
        record={**row,'outcome':outcome(row),'dataset':'train','metric':'J-min-v1'};attempts.append(record)
        value=number(row.get('J'))
        if value is not None and row.get('valid') in ('True','true','1',True) and (best is None or value<best):
            best=value;changes.append({'id':row['id'],'stage':row['stage'],'evolution_attempt':int(row['evolution_attempt']),'attempt':int(row['attempt']),'J':best,'operator':row['operator']})
        parents=row.get('parents','')
        parents=sequence(parents) if parents.startswith('[') else parents.split(',') if parents else []
        edges += [{'parent':parent,'child':row['id'],'operator':row['operator'],'stage':row['stage'],'evolution_attempt':row['evolution_attempt'],'outcome':record['outcome']} for parent in parents]
    by_id={r['id']:r for r in attempts}
    for edge in edges:
        edge['parent_J']=number(by_id.get(edge['parent'],{}).get('J'));edge['child_J']=number(by_id[edge['child']].get('J'))
    table(out/'attempts.csv',attempts);table(out/'champion-changes.csv',changes,['id','stage','evolution_attempt','attempt','J','operator']);table(out/'parent-edges.csv',edges,['parent','child','operator','stage','evolution_attempt','outcome','parent_J','child_J'])
    counts=[{'stage':stage,'operator':op,'outcome':kind,'attempts':n} for (stage,op,kind),n in sorted(collections.Counter((r['stage'],r['operator'],r['outcome']) for r in attempts).items())]
    table(out/'outcome-counts.csv',counts)
    generations=[];genpath=Path(info['source'])/'exports/generations.csv'
    for row in csvrows(genpath) if genpath.exists() else []:
        generations.append({**row,'best_J':-number(row['best_fitness']) if number(row.get('best_fitness')) is not None else None,'population_mean_J':-number(row['population_mean']) if number(row.get('population_mean')) is not None else None,'metric_conversion':'internal fitness=-J; negate once'})
    table(out/'generations-J.csv',generations,['generation','generation_requests','planned_candidates','valid_unique_children','children_selected','best_J','population_mean_J','population_ids','metric_conversion'])
    instance_rows=[];selections=[];missing=[];splits={r['file']:r.get('split','unknown') for r in p['instances']}
    if champ:
        key=champ['candidate']['key'];per=Path(info['source'])/'exports/per_instance.csv'
        if per.exists():
            with per.open(newline='') as f:
                for row in csv.DictReader(f):
                    if row['candidate_key']!=key:continue
                    if row.get('valid') not in ('True','true','1',True):continue
                    split=splits.get(row['file'],'unknown')
                    instance_rows.append({**row,'split':split,'metric':'J-min-v1'})
                    for i,member in enumerate(sequence(row.get('member_sequence',''))):
                        if type(member) is not int or not 0<=member<len(p['members']):raise ValueError('invalid stored member_sequence; h_calls is never substituted')
                        selections.append({'file':row['file'],'split':split,'step':i+1,'member':member})
        shutil.copyfile(Path(info['source'])/'exports/champion.py',out/'champion.py')
        write(out/'champion.json',champ)
    table(out/'champion-instances.csv',instance_rows,list(instance_rows[0]) if instance_rows else ['file','split','raw_cost','reference','J'])
    table(out/'H-selections.csv',selections,['file','split','step','member'])
    if not generations:missing.append('No stored generation rows; no population curve invented.')
    if not selections:missing.append('No stored champion member_sequence (or single-H method); no H-selection chart invented.')
    if not instance_rows:missing.append('No complete stored champion instance rows; no evaluation rerun.')
    ancestry={champ['id']} if champ else set();front=set(ancestry)
    for depth in range(2):
        front={e['parent'] for e in edges if e['child'] in front}-ancestry;ancestry |= front
    local=[e for e in edges if e['child'] in ancestry and e['parent'] in ancestry]
    table(out/'champion-local-edges.csv',local,['parent','child','operator','stage','evolution_attempt','outcome'])
    values=[number(r.get('J')) for r in instance_rows if r['split']=='train']
    if values and (len(values)!=len(p['instances']) or not math.isclose(sum(values)/len(values),info['summary']['best_J'],rel_tol=1e-12,abs_tol=1e-12)):raise ValueError('stored champion costs do not reproduce complete train J')
    return {'attempts':attempts,'counts':counts,'generations':generations,'instances':instance_rows,'selections':selections,'changes':changes,'local':local,'edges':edges,'missing':missing}


def render(info,data,out):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'svg.fonttype':'none','font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    figdir=out/'figures';figdir.mkdir();registry=[];status=info['status'];title=f"{status['problem'].upper()} / {info['protocol'].get('run_kind','U')} / seed {status['search_seed']} / TRAIN / J-min-v1"
    def save(fig,name,csvs,description):
        fig.suptitle(title,fontsize=11);fig.tight_layout(rect=(0,0,1,.95))
        for ext in ('png','svg','pdf'):fig.savefig(figdir/(name+'.'+ext),dpi=170)
        plt.close(fig);registry.append({'name':name,'source_csv':csvs,'description':description,'formats':['png','svg','pdf']})
    attempts=data['attempts'];init=[r for r in attempts if r['stage']=='initialization'];evo=[r for r in attempts if r['stage']=='evolution']
    fig,axes=plt.subplots(1,2,figsize=(11,4),gridspec_kw={'width_ratios':[1,4]})
    axes[0].step(range(1,len(init)+1),[number(r['best_J']) for r in init],where='post');axes[0].set(xlabel='Initialization attempt',ylabel='Best training J',title='Separate initialization budget')
    axes[1].step([0]+[int(r['evolution_attempt']) for r in evo],[number(init[-1]['best_J']) if init else None]+[number(r['best_J']) for r in evo],where='post')
    axes[1].set(xlabel='Evolution generation attempt (all outcomes)',ylabel='Best training J',xlim=(0,max(1,len(evo))),title=f'{len(evo)} attempts; failures and duplicates retained')
    save(fig,'01-best-J',['attempts.csv'],'Initialization separated; evolution includes every reserved/settled attempt.')
    fig,axes=plt.subplots(2,1,figsize=(11,6))
    styles={'CROSS':('#2463a2','o'),'MUTATE':('#d37a12','^'),'INIT':('#555555','s')}
    parent_means=[]
    for row in evo:
        values=[e['parent_J'] for e in data['edges'] if e['child']==row['id'] and e['parent_J'] is not None]
        if values:parent_means.append((int(row['evolution_attempt']),sum(values)/len(values)))
    if parent_means:axes[0].scatter([x for x,y in parent_means],[y for x,y in parent_means],s=7,color='#aaaaaa',alpha=.3,label="Parents' mean J (guide only)")
    for operator in sorted({r['operator'] for r in evo}):
        selected=[r for r in evo if r['operator']==operator and r['outcome']=='valid_unique' and number(r['J']) is not None];color,marker=styles.get(operator,('#7755aa','o'))
        axes[0].scatter([int(r['evolution_attempt']) for r in selected],[number(r['J']) for r in selected],s=12,alpha=.5,label=operator,color=color,marker=marker)
    survivors={x for g in data['generations'] for x in sequence(g.get('children_selected',''))}
    selected=[r for r in evo if r['id'] in survivors and number(r['J']) is not None]
    if selected:axes[0].scatter([int(r['evolution_attempt']) for r in selected],[number(r['J']) for r in selected],s=32,facecolors='none',edgecolors='#333333',linewidths=.7,label='Entered survivor population')
    axes[0].set(ylabel='Complete candidate train J',xlabel='Evolution attempt',xlim=(0,max(1,len(evo))))
    if axes[0].get_legend_handles_labels()[0]:axes[0].legend()
    gens=[r for r in data['generations'] if r['best_J'] is not None and r['population_mean_J'] is not None]
    axes[1].plot([int(r['generation']) for r in gens],[r['best_J'] for r in gens],label='Population best J')
    axes[1].plot([int(r['generation']) for r in gens],[r['population_mean_J'] for r in gens],label='Population mean J')
    axes[1].set(xlabel='Generation (not attempt)',ylabel='J = - internal fitness');axes[1].legend()
    save(fig,'02-candidates-population',['attempts.csv','generations-J.csv','parent-edges.csv'],'New CROSS/MUTATE candidates, parent mean guide and survivor circles; negate population_mean/best_fitness once.')
    kinds=sorted({r['outcome'] for r in attempts});colors=plt.get_cmap('tab10');fig,axes=plt.subplots(2,1,figsize=(11,6),gridspec_kw={'height_ratios':[1,3]})
    axes[0].scatter([int(r['evolution_attempt']) for r in evo],[kinds.index(r['outcome']) for r in evo],c=[colors(kinds.index(r['outcome'])) for r in evo],s=12,marker='|');axes[0].set_yticks(range(len(kinds)),kinds,fontsize=7);axes[0].set(xlabel='Every evolution attempt',xlim=(0,max(1,len(evo))))
    groups=sorted({(r['stage'],r['operator']) for r in attempts});bottom=np.zeros(len(groups))
    for i,kind in enumerate(kinds):
        vals=[sum(r['outcome']==kind and (r['stage'],r['operator'])==g for r in attempts) for g in groups];axes[1].bar(range(len(groups)),vals,bottom=bottom,label=kind,color=colors(i));bottom+=vals
    axes[1].set_xticks(range(len(groups)),[' / '.join(g) for g in groups]);axes[1].set(ylabel='Attempts (exclusive categories)');axes[1].legend(fontsize=8)
    save(fig,'03-outcomes',['attempts.csv','outcome-counts.csv'],'Exclusive outcome categories cover all initialization and evolution attempts.')
    fig,ax=plt.subplots(figsize=(10,3.8));changes=data['changes'];ax.step([r['evolution_attempt'] for r in changes],[r['J'] for r in changes],where='post',marker='o');ax.set(xlabel='Evolution attempt (0 = initialization)',ylabel='Strictly improving train J',title='Champion improvements; equal-J ties are not new improvements')
    save(fig,'04-champion-changes',['champion-changes.csv'],'Only strict improvements; final champion identity is taken from frozen export.')
    if data['local']:
        fig,ax=plt.subplots(figsize=(11,5));edges=data['local'];champ=info['champion']['id'];nodes={e['parent'] for e in edges}|{e['child'] for e in edges};levels={champ:0}
        for _ in range(3):
            for e in edges:
                if e['child'] in levels and e['parent'] not in levels:levels[e['parent']]=levels[e['child']]+1
        positions={}
        for level in sorted(set(levels.values())):
            members=sorted(n for n in nodes if levels.get(n)==level)
            for i,n in enumerate(members):positions[n]=(i-(len(members)-1)/2,-level)
        for e in edges:
            ax.annotate('',xy=positions[e['child']],xytext=positions[e['parent']],arrowprops={'arrowstyle':'->','color':'#aaa'})
        for n,(x,y) in positions.items():ax.text(x,y,n,ha='center',va='center',fontsize=8,bbox={'boxstyle':'round,pad=.4','facecolor':'#f4b860' if n==champ else '#dbe9f6','edgecolor':'#888'})
        ax.set(xlim=(-max(2,len(nodes)/3),max(2,len(nodes)/3)),ylim=(-2.6,.5),title='Champion + two parent hops only; full graph is in CSV');ax.axis('off')
        save(fig,'05-champion-local-lineage',['champion-local-edges.csv','parent-edges.csv'],'Local parent ancestry only; not a model reasoning explanation.')
    if data['instances']:
        fig,ax=plt.subplots(figsize=(12,4.5));records=data['instances'];x=np.arange(len(records));ax.bar(x-.2,[number(r['raw_cost']) for r in records],.4,label='Champion raw cost');ax.bar(x+.2,[number(r['reference']) for r in records],.4,label='Frozen reference');ax.set_xticks(x,[r['file'] for r in records],rotation=60,ha='right',fontsize=7);ax.set(ylabel='Raw cost / reference',title='Recorded champion results only; no test evaluation or baseline overlay');ax.legend()
        save(fig,'06-champion-instances',['champion-instances.csv'],'Dataset split is retained per row; sample is train21 only.')
    if data['selections']:
        records=data['selections'];names=list(dict.fromkeys(r['file'] for r in records));sequences={name:[r['member'] for r in records if r['file']==name] for name in names};K=len(info['protocol']['members']);matrix=np.array([[v[min(len(v)-1,int(i*len(v)/200))] for i in range(200)] for v in sequences.values()]);fig,axes=plt.subplots(1,2,figsize=(12,5),gridspec_kw={'width_ratios':[3,1]});im=axes[0].imshow(matrix,aspect='auto',interpolation='nearest',cmap='tab10',vmin=-.5,vmax=K-.5,extent=(0,100,len(names)-.5,-.5));axes[0].set_yticks(range(len(names)),names,fontsize=7);axes[0].set(xlabel='Normalized construction progress (%)',title='Chosen H from member_sequence (categorical resampling)');bar=fig.colorbar(im,ax=axes[0],ticks=range(K));bar.set_label('Selected H index');counts=collections.Counter(r['member'] for r in records);axes[1].barh(range(K),[counts[i] for i in range(K)]);axes[1].set(ylabel='H index',xlabel='Actual selections',yticks=range(K),title='h_calls is not used')
        save(fig,'07-H-selections',['H-selections.csv'],'Heatmap resamples stored selected-H identities to 200 progress columns; counts use every real stored selection.')
    write(out/'figures.json',registry);return registry


def source_files(source):
    included={};excluded=[]
    for p in sorted(Path(source).rglob('*')):
        name=str(p.relative_to(source))
        if p.is_symlink():raise ValueError('source symlink requires explicit review: '+name)
        if not p.is_file():continue
        if any(x in FORBIDDEN for x in p.relative_to(source).parts) or p.name.startswith('.env') or p.suffix in ('.key','.pyc') or re.search(r'(?:credential|private[_-]?key)',p.name,re.I):excluded.append(name);continue
        included[name]=p
    return included,excluded


def checked_hash(path):
    h=hashlib.sha256();tail=b''
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            value=tail+chunk
            if any(p.search(value) for p in SECRET_PATTERNS):raise ValueError('possible secret detected; original preserved; review/redact a separate copy: '+str(path))
            h.update(chunk);tail=value[-512:]
    return h.hexdigest()


def reproduction(info):
    p=info['protocol'];source=Path(info['source']);runtime_root=source.parent.parent;files={};missing=[]
    for name,h in p.get('source_files',{}).items():
        pure=Path(name)
        if pure.is_absolute() or '..' in pure.parts:raise ValueError('unsafe frozen source manifest')
        path=runtime_root/name
        if path.is_file() and not path.is_symlink() and sha(path)==h:files['runtime-source/'+name]=path
        else:missing.append({'file':name,'expected_sha256':h,'reason':'runtime source absent or differs; no current source substituted'})
    # Protocol already contains exact parsed train data and H. Preserve raw bound assets when available.
    for field in ('data_manifest','h_file','p0_file'):
        value=p['config'].get(field)
        if not value:continue
        path=Path(value)
        if not path.is_absolute():path=(runtime_root/path).resolve()
        if path.is_file() and not path.is_symlink():
            files['bound-inputs/'+field+'/'+path.name]=path
            if field=='data_manifest':
                m=read(path)
                if m.get('split')!='train':raise ValueError('closeout never opens test/holdout input data')
                for i,row in enumerate(m['instances']):
                    item=(path.parent/row['path']).resolve()
                    if sha(item)!=row['sha256']:raise ValueError('bound raw training asset differs')
                    files[f'bound-inputs/train/{i:04d}-'+item.name]=item
        else:missing.append({'file':str(path),'reason':'raw bound input unavailable; exact parsed values remain in Protocol.json'})
    files['postprocessor/closeout.py']=Path(__file__).resolve()
    return files,missing


def backup(info,out,target):
    source=Path(info['source']);target=Path(target).resolve()
    if target.exists():raise FileExistsError('immutable full ZIP already exists')
    if target.is_relative_to(source) or target.is_relative_to(out):raise ValueError('backup must be outside source and slim output')
    raw,excluded=source_files(source);deps,missing=reproduction(info);files={'run/'+n:p for n,p in raw.items()};files.update(deps)
    for p in out.rglob('*'):
        if p.is_file():files['derived/'+str(p.relative_to(out))]=p
    before={name:{'sha256':checked_hash(p),'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns} for name,p in files.items()}
    write(out/'source-file-manifest.json',{'source':str(source),'files':{n:v for n,v in before.items() if n.startswith('run/')},'excluded':excluded,'missing_reproduction_assets':missing,'secret_scan':'patterns on all included bytes; not a public-release approval'})
    target.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for name,p in files.items():
            h=hashlib.sha256()
            with p.open('rb') as f,z.open(name,'w',force_zip64=True) as dst:
                for chunk in iter(lambda:f.read(1024*1024),b''):dst.write(chunk);h.update(chunk)
            if h.hexdigest()!=before[name]['sha256']:raise ValueError('source changed during backup; retain incomplete ZIP and investigate')
        z.writestr('archive-manifest.json',json.dumps({'files':before,'excluded':excluded,'missing_reproduction_assets':missing,'source_protocol_sha256':info['status']['protocol_sha256']},ensure_ascii=False,indent=2))
    # Hash all archived members, not just the ZIP directory/CRC.
    with zipfile.ZipFile(target) as z:
        for name,meta in before.items():
            h=hashlib.sha256()
            with z.open(name) as f:
                for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
            if h.hexdigest()!=meta['sha256']:raise ValueError('archived member hash differs')
    after,after_excluded=source_files(source)
    if set(after)!=set(raw) or after_excluded!=excluded or any(p.stat().st_size!=before['run/'+n]['bytes'] or p.stat().st_mtime_ns!=before['run/'+n]['mtime_ns'] for n,p in after.items()):raise ValueError('source inventory changed during closeout')
    receipt={'path':str(target),'sha256':sha(target),'bytes':target.stat().st_size,'members':len(files)+1,'member_hashes_verified':True,'source_bytes_unchanged':True,'runtime_source_snapshot_complete':not missing,'missing_assets':missing,'packed':True,'transferred':False,'Windows_verified':False,'source_deleted':False}
    target.with_suffix('.zip.sha256').write_text(receipt['sha256']+'  '+target.name+'\n');write(out/'archive-receipt.json',receipt);return receipt


def report(info,data,out,figures,archive_path):
    s=info['summary'];p=info['protocol'];meta={'tool':VERSION,'run_code':p.get('git',{}),'run_source_files':p.get('source_files',{}),'postprocessing_code':{'git_commit':git('rev-parse','HEAD'),'file_sha256':sha(__file__),'python':sys.version,'tracked_changes':git('diff','--name-only','HEAD','--','experiments/triad/closeout.py')},'protocol_sha256':info['status']['protocol_sha256'],'source':info['source'],'source_phase':s['phase'],'data_use':'train only; no new validation/test evaluation','score':'J-min-v1; mean((cost-reference)/reference)','summary':s,'configuration':p['config'],'machine_at_run':p.get('machine'),'figures':figures,'limitations':data['missing'],'full_archive_requested':str(archive_path) if archive_path else None,'API_requests':0,'actual_solves':0,'source_writes':0}
    write(out/'reproduction.json',meta)
    meta['postprocessing_code']['matplotlib']=sys.modules['matplotlib'].__version__
    meta['postprocessing_code']['numpy']=sys.modules['numpy'].__version__
    write(out/'reproduction.json',meta)
    contents=f'''# {s['run_id']}：离线训练结果报告

本报告只整理已有导出，原运行未修改，模型请求、H/U执行、新增求解和测试集访问均为0。当前终态为{s['phase']}；这是单种子训练结果，不是泛化或因果证据。

| 项目 | 记录 |
| --- | --- |
| 冠军 | {s.get('champion_id')} |
| 完整训练J（越小越好） | {s.get('best_J')} |
| 初始化／演化尝试 | {s['initialization_attempts']}／{s['evolution_attempts']} |
| 预留／确认发送／未知发送 | {s['request_reservations']}／{s.get('confirmed_sends')}／{s.get('unknown_sends')} |
| 有效不同候选评价 | {s.get('valid_unique_evaluations',s.get('valid_candidates'))} |
| 已知token小计 | {s.get('known_usage_subtotal')} |
| 用量缺失条数／已核实费用 | {s.get('unknown_usage_attempts')}／{s.get('actual_cost')}（未知不等于0） |
| 历史H构建成本 | {s.get('source_H_cost','见原Protocol source_cost')}，不按种子重复相加 |
| 实际独占分类 | {info['status']['outcomes']} |

运行代码身份见reproduction.json的run_code及逐文件哈希；后处理代码身份另列，不能用后处理提交替代旧501运行版本。已有原始数据、真实Prompt、响应、检查点和日志放完整ZIP，精简目录只保存阅读与作图所需成果。完整包路径为{archive_path or '未请求'}，最终SHA见archive-receipt.json及旁边.sha256；未传输、未在Windows核验，原件保留。

图表的数据及生成方式见figures.json。横轴演化尝试保留全部失败和重复，初始化单列；种群best_fitness和population_mean只取一次负号得到J。分类互斥，不把有效候选数等同实际请求数。冠军图只取两层父代，完整关系见parent-edges.csv。H选择使用member_sequence逐步计数，不使用h_calls；热图按构造进度重采样，原步骤完整保存在CSV。

逐实例图仅展示已有冠军成本与固定参照，未叠加未经兼容核验的固定H基线，没有测试成绩。费用和物理求解次数未据候选数推算；批次共享耗时也不累加成墙钟时间。未知或缺少记录的项目继续保留未知。

'''
    contents+='\n'.join(f"![{fig['description']}](figures/{fig['name']}.png)\n\n来源：{', '.join(fig['source_csv'])}\n" for fig in figures)
    contents+='\n缺口：'+('；'.join(data['missing']) if data['missing'] else '所要求的单次训练展示图均有已有记录；多种子及测试对照须待实际完成后再汇总。')+'\n'
    (out/'REPORT_ZH.md').write_text(contents)
    shutil.copyfile(__file__,out/'plot_and_closeout.py')
    (out/'README.md').write_text('# 离线精简成果\n\n先读REPORT_ZH.md。图均有PNG、SVG、PDF及来源CSV；完整原始证据不在Git精简目录内。reproduction.json分开记录运行代码和后处理代码。archive-receipt.json记录完整包位置与SHA；不代表已传输。\n\n重画时用带Matplotlib的Python运行本目录plot_and_closeout.py build --run-dir 原运行路径 --output 新目录；不覆盖本目录。GitHub待推送清单见github-pending.json，所有公开上传仍待审阅。\n')


def finish(out):
    files=[p for p in sorted(out.rglob('*')) if p.is_file() and p.name not in ('files.sha256.json','github-pending.json')]
    manifest={str(p.relative_to(out)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in files};write(out/'files.sha256.json',{'files':manifest,'self_excluded':True})
    candidates=[str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p) for p in files]
    code_names=['experiments/triad/closeout.py','experiments/triad/closeout_tests.py','requirements-closeout.txt','docs/实验结束与归档.md','README.md']
    write(out/'github-pending.json',{'remote':git('remote','get-url','origin'),'branch':git('branch','--show-current'),'postprocessing_commit':git('rev-parse','HEAD'),'code_files':{n:sha(ROOT/n) for n in code_names if (ROOT/n).exists()},'remote_comparison':'not fetched; ahead/behind unknown','suggested_tag':'closeout-v1-'+out.name,'tag_created':False,'push_executed':False,'Release_uploaded':False,'public_upload_approved':False,'review_license_and_privacy':True,'selected_slim_files':candidates,'manifest_files':['files.sha256.json','github-pending.json'],'large_files_over_10MiB':[n for n,v in manifest.items() if v['bytes']>10*1024*1024],'excluded':['original runs/','full raw ZIP','credentials','virtual environments','other worktree modifications'],'note':'A branch push sends reachable commits, not just selected files; inspect the complete outgoing commit diff before any push. No force push.'})


def batch_report(path,out=None):
    """Render the existing batch summary; do not repeat selection/aggregation."""
    value=read(path)
    if not isinstance(value.get('all_runs'),list) or not isinstance(value.get('groups'),list):raise ValueError('existing batch.py summary JSON required')
    state={'declared_rows':len(value['all_runs']),'phases':dict(collections.Counter(r['phase'] for r in value['all_runs'])),'summary_sha256':sha(path),'API_requests':0,'actual_solves':0,'writes':0 if out is None else 'derived only'}
    if out is None:return state
    out=Path(out).resolve()
    if out.exists():raise FileExistsError('new batch derived directory required')
    out.mkdir(parents=True);write(out/'batch-summary-source.json',value)
    columns=['group','index','seed','run_id','phase','best_J','error','pending'];table(out/'all-runs.csv',value['all_runs'],columns)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    curves=[]
    for group in value['groups']:
        for point in group.get('J_curve_mean_sample_std',[]):curves.append({'group':group['group'],**point})
    table(out/'batch-curves.csv',curves,['group','evolution_attempt','observed_runs','mean_J','sample_std_J'])
    fig,ax=plt.subplots(figsize=(10,4.5))
    for group in value['groups']:
        points=group.get('J_curve_mean_sample_std',[])
        if not points:continue
        x=[p['evolution_attempt'] for p in points];y=[p['mean_J'] for p in points];line=ax.plot(x,y,label=group['group'])[0]
        for left,right in zip(points,points[1:]):
            if left.get('observed_runs',0)>=2 and right.get('observed_runs',0)>=2 and left.get('sample_std_J') is not None and right.get('sample_std_J') is not None:
                ax.fill_between([left['evolution_attempt'],right['evolution_attempt']],[left['mean_J']-left['sample_std_J'],right['mean_J']-right['sample_std_J']],[left['mean_J']+left['sample_std_J'],right['mean_J']+right['sample_std_J']],alpha=.15,color=line.get_color())
    ax.set(xlabel='Evolution attempt (existing observed points only)',ylabel='Mean training J',title='Existing batch summary; sample SD only where observed n >= 2')
    if ax.get_legend_handles_labels()[0]:ax.legend()
    fig.tight_layout()
    for ext in ('png','svg','pdf'):fig.savefig(out/('batch-mean-J.'+ext),dpi=170)
    plt.close(fig)
    seed_curves=[];missing=[]
    for row in value['all_runs']:
        source=Path(row['run_dir'])/'exports/candidates.csv' if row.get('run_dir') else None
        if source is None or not source.exists():missing.append({'group':row['group'],'seed':row.get('seed'),'phase':row['phase'],'reason':'stored candidate curve unavailable'});continue
        points={}
        for point in csvrows(source):
            if point.get('best_J') not in (None,''):points[int(point['evolution_attempt'])]=number(point['best_J'])
        seed_curves += [{'group':row['group'],'seed':row.get('seed'),'phase':row['phase'],'evolution_attempt':x,'best_J':y,'source_csv_sha256':sha(source)} for x,y in sorted(points.items())]
    table(out/'seed-curves.csv',seed_curves,['group','seed','phase','evolution_attempt','best_J','source_csv_sha256'])
    if seed_curves:
        groups=sorted({r['group'] for r in seed_curves});fig,axes=plt.subplots(len(groups),1,figsize=(10,3*len(groups)),squeeze=False)
        for ax,g in zip(axes[:,0],groups):
            for seed,phase in sorted({(r['seed'],r['phase']) for r in seed_curves if r['group']==g},key=str):
                points=[r for r in seed_curves if r['group']==g and r['seed']==seed];ax.plot([p['evolution_attempt'] for p in points],[p['best_J'] for p in points],label=f'{seed}: {phase}')
            ax.set(title=g+' / TRAIN / J-min-v1',xlabel='Evolution attempt (0 = init)',ylabel='Best J');ax.legend(fontsize=8)
        fig.tight_layout()
        for ext in ('png','svg','pdf'):fig.savefig(out/('seed-curves.'+ext),dpi=170)
        plt.close(fig)
    write(out/'missing-seed-curves.json',missing)
    text='# 批次离线成果\n\n读取既有batch.py汇总，不重新选冠军、不补跑、不补曲线。所有成功、失败、暂停及未启动运行见all-runs.csv；每个曲线点的有效数见batch-curves.csv。只有n≥2且已有样本标准差时画波动带。原始完整证据仍按每份运行分别执行build归档，本摘要不是全批原始备份。\n\n'
    text+='| 组 | 声明数 | 完成有效数 | 平均J | 样本标准差 |\n| --- | --- | --- | --- | --- |\n'
    for g in value['groups']:text+='| '+' | '.join(str(g.get(k)) for k in ('group','declared_runs','complete_valid_runs','mean_J','sample_std_J'))+' |\n'
    text+='\n![训练曲线](batch-mean-J.png)\n\n来源：batch-summary-source.json、batch-curves.csv。逐种子曲线见seed-curves.csv；图存在时为seed-curves.png，缺少的来源另列missing-seed-curves.json，不重跑补图。未运行测试评价。\n';(out/'REPORT_ZH.md').write_text(text)
    write(out/'batch-provenance.json',state);finish(out);return {**state,'output':str(out)}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['check-only','build','batch-report']);ap.add_argument('--run-dir',type=Path);ap.add_argument('--summary',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--archive',type=Path);ap.add_argument('--allow-incomplete',action='store_true');a=ap.parse_args()
    if a.summary is not None:
        if a.action not in ('check-only','batch-report') or a.run_dir is not None or a.archive is not None:raise ValueError('batch summary accepts check-only or batch-report; full archives are per run')
        if a.action=='batch-report' and a.output is None:raise ValueError('batch-report needs new --output')
        print(json.dumps(batch_report(a.summary,a.output if a.action=='batch-report' else None),ensure_ascii=False,indent=2));return 0
    if a.run_dir is None or a.action=='batch-report':raise ValueError('single-run check/build requires --run-dir; batch-report requires --summary')
    info=inspect(a.run_dir,a.allow_incomplete)
    if a.action=='check-only':print(json.dumps(info['status'],ensure_ascii=False,indent=2));return 0
    if not info['status']['matplotlib_available']:raise RuntimeError('Matplotlib absent in this Python; use the documented analysis environment; no automatic installation')
    if a.output is None:raise ValueError('explicit new derived --output directory required')
    out=a.output.resolve();source=Path(info['source'])
    if out.exists() or out.is_relative_to(source) or source.is_relative_to(out):raise ValueError('new derived output outside original run required; no overwrite')
    data=analyse(info,out);figures=render(info,data,out);report(info,data,out,figures,a.archive)
    archive=backup(info,out,a.archive) if a.archive else None;finish(out)
    print(json.dumps({'output':str(out),'figures':len(figures),'archive':archive,'API_requests':0,'actual_solves':0,'source_writes':0,'pushed':False},ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print(json.dumps({'error_type':type(e).__name__,'error':str(e),'automatic_retry':False},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
