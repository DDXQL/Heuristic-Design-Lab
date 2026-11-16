#!/usr/bin/env python3
"""Analyse fetched immutable exports only; no executor, model or evaluator calls."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import configuration


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--fetch-root',type=Path,required=True)
    a=ap.parse_args();stamp=str(time.time_ns());out=ROOT/'reports/six-groups-results'/stamp;out.mkdir(parents=True)
    observed={};errors=[]
    for status in sorted(a.fetch_root.glob('fetch*/status.json')):
        v=read(status)
        if not v.get('retrieved'):continue
        for member in v.get('members',[]):
            base=Path(member['result']);receipt=read(base/'retrieval-manifest.json')
            for n,h in receipt['files'].items():
                if Path(n).is_absolute() or '..' in Path(n).parts or sha(base/n)!=h:raise ValueError('retrieved member identity changed: '+n)
            protocols=[base/n for n in receipt['files'] if n.startswith('runs/') and n.endswith('/Protocol.json')]
            if len(protocols)!=1:raise ValueError('one exact run per fetched member required')
            p=read(protocols[0]);d=protocols[0].parent;s=read(d/'exports/summary.json')
            group=p['config']['problem']+'-'+('u' if p.get('run_kind')=='u' or p.get('version')=='parent-coverage-routing-v1' else 'eoh')
            seed=p['config']['search_seed'];key=(group,seed)
            candidate={**s,'group':group,'seed':seed,'run_dir':str(d),'source_protocol_sha256':sha(d/'Protocol.json'),'fetch_receipt':str(status)}
            prior=observed.get(key)
            if prior and prior['source_protocol_sha256']!=candidate['source_protocol_sha256']:raise ValueError('two distinct scientific identities for same group/seed; do not silently pick best')
            if prior and prior.get('evolution_attempts',0)>candidate.get('evolution_attempts',0):continue
            observed[key]=candidate
    old=read(ROOT/'preparations/triad/fjsp/existing501-registration.json')
    observed.setdefault(('fjsp-u',501),{**old['snapshot'],'group':'fjsp-u','seed':501,'run_dir':None,'registered_existing':True,'source_protocol_sha256':old['source_protocol_sha256']})
    rows=[]
    for g in configuration.GROUPS:
        for seed in (501,502,503):
            r=observed.get((g,seed),{'group':g,'seed':seed,'phase':'completed_evidence_not_registered' if g=='fjsp-u' and seed==502 else 'not_retrieved','run_dir':None,'best_J':None})
            rows.append(r)
            if r.get('run_dir') and r['phase'] in ('completed','paused'):
                name=g+'-'+str(seed);derived=out/name
                archive=Path('/Users/DDXQL/Developer/transfer-outbox')/('six-results-'+name+'-'+stamp+'.zip')
                cmd=[sys.executable,'-s','-B',str(ROOT/'experiments/triad/closeout.py'),'build','--run-dir',r['run_dir'],'--output',str(derived),'--archive',str(archive)]
                if r['phase']=='paused':cmd+=['--allow-incomplete']
                p=subprocess.run(cmd,text=True,capture_output=True)
                if p.returncode:errors.append({'group':g,'seed':seed,'error':p.stderr[-1500:]})
                else:r['derived_report']=str(derived)
    groups=[]
    for g in configuration.GROUPS:
        all_rows=[r for r in rows if r['group']==g]
        complete=[r for r in all_rows if r['phase']=='completed' and r.get('evolution_attempts')==1000 and r.get('best_J') is not None]
        vals=[r['best_J'] for r in complete];curves=[]
        for r in complete:
            points={}
            if r.get('run_dir'):
                for line in csv.DictReader((Path(r['run_dir'])/'exports/candidates.csv').open()):
                    if line.get('best_J') not in ('',None):points[int(line['evolution_attempt'])]=float(line['best_J'])
            elif r['group']=='fjsp-u' and r['seed']==501:
                for point in old['curve']:points[point['evolution_attempt']]=point['best_J']
            curves.append(points)
        mean_curve=[]
        for i in sorted({i for c in curves for i in c}):
            v=[c[i] for c in curves if i in c]
            mean_curve.append({'evolution_attempt':i,'observed_runs':len(v),'mean_J':statistics.mean(v),'sample_std_J':statistics.stdev(v) if len(v)>1 else None})
        groups.append({'group':g,'declared_runs':3,'complete_valid_runs':len(vals),'mean_J':statistics.mean(vals) if vals else None,'sample_std_J':statistics.stdev(vals) if len(vals)>1 else None,
            'excluded_from_mean':[{'seed':r['seed'],'phase':r['phase']} for r in all_rows if r not in complete],'J_curve_mean_sample_std':mean_curve})
    summary={'all_runs':rows,'groups':groups,'actual_cost':None,'API_requests':0,'actual_solves':0,'postprocessing_errors':errors}
    write(out/'all18.json',summary)
    with (out/'all18.csv').open('w',newline='') as f:
        cols=['group','seed','phase','evolution_attempts','initialization_attempts','request_reservations','best_J','run_dir'];w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(rows)
    subprocess.run([sys.executable,'-s','-B',str(ROOT/'experiments/triad/closeout.py'),'batch-report','--summary',str(out/'all18.json'),'--output',str(out/'batch')],check=True)
    print(json.dumps({'output':str(out),'all18_retained':True,'postprocessing_errors':errors,'API_requests':0,'actual_solves':0,'pushed':False},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
