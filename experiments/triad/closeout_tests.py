#!/usr/bin/env python3
"""Finite synthetic receipt checks for offline closeout; no model/H/U/solver."""
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from experiments.triad import closeout as c


def deny(*a,**kw):raise AssertionError('offline only')
def reject(fn,kind=Exception):
    try:fn()
    except kind:return
    raise AssertionError('refusal required')


def main():
    with tempfile.TemporaryDirectory(prefix='closeout-fixture-') as tmp,patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny):
        root=Path(tmp).resolve();run=root/'runs/synthetic';run.mkdir(parents=True)
        p={'version':'parent-coverage-routing-v1','config':{'problem':'fjsp','search_seed':7},'members':[{},{}],'instances':[{'file':'train-fixture','split':'train'}],'source_files':{},'git':{'commit':'SYNTHETIC NOT REAL'}}
        c.write(run/'Protocol.json',p);identity=c.sha(run/'Protocol.json');s={'identity':identity,'phase':'completed','tasks':{str(i):{'status':'completed'} for i in range(4)}};c.write(run/'checkpoint.json',s)
        summary={'phase':'completed','run_id':'SYNTHETIC','protocol_sha256':identity,'initialization_attempts':1,'evolution_attempts':3,'request_reservations':4,'unknown_sends':0,'champion_id':'G1','best_J':1.0};c.write(run/'exports/summary.json',summary)
        c.write(run/'exports/champion.json',{'id':'G1','J':1.0,'candidate':{'key':'fixture'}});(run/'exports/champion.py').write_text('# fixture source; never executed\n')
        rows=[]
        for i,(name,stage,op,J,valid,failure) in enumerate([('I0','initialization','INIT',2,True,''),('G1','evolution','CROSS',1,True,''),('G2','evolution','MUTATE','',False,'AST_duplicate'),('G3','evolution','CROSS','',False,'parse_or_constraint')]):
            rows.append({'id':name,'stage':stage,'operator':op,'J':J,'valid':valid,'failure':failure,'parents':'' if i==0 else 'I0','attempt':i+1,'evolution_attempt':i,'best_J':2 if i==0 else 1})
        c.table(run/'exports/candidates.csv',rows)
        c.table(run/'exports/generations.csv',[{'generation':1,'generation_requests':3,'best_fitness':-1.0,'population_mean':-1.5}])
        c.table(run/'exports/per_instance.csv',[{'candidate_key':'fixture','file':'train-fixture','valid':True,'raw_cost':2,'reference':1,'J':1,'member_sequence':'[1, 0, 1]','h_calls':'[999, 1000]'}])
        before={str(p.relative_to(run)):c.sha(p) for p in run.rglob('*') if p.is_file()}
        info=c.inspect(run);out=root/'slim';data=c.analyse(info,out)
        assert [r['evolution_attempt'] for r in data['attempts'] if r['stage']=='evolution']==['1','2','3']
        assert sum(r['attempts'] for r in data['counts'])==4
        assert data['generations'][0]['best_J']==1 and data['generations'][0]['population_mean_J']==1.5
        assert len(data['selections'])==3 and [r['member'] for r in data['selections']]==[1,0,1]
        figures=c.render(info,data,out);assert len(figures)==7
        c.report(info,data,out,figures,root/'full.zip');receipt=c.backup(info,out,root/'full.zip');c.finish(out)
        assert receipt['member_hashes_verified'] and receipt['source_bytes_unchanged']
        assert before=={str(p.relative_to(run)):c.sha(p) for p in run.rglob('*') if p.is_file()}
        reject(lambda:c.backup(info,out,root/'full.zip'),FileExistsError)
        (run/'.coordinator.lock').write_text('synthetic');reject(lambda:c.inspect(run));(run/'.coordinator.lock').unlink()
        (root/'secret.txt').write_text('sk-'+'X'*24);reject(lambda:c.checked_hash(root/'secret.txt'))
        batch={'all_runs':[{'group':'fjsp-u','seed':7,'phase':'completed','run_dir':str(run),'best_J':1},{'group':'fjsp-u','seed':8,'phase':'failed'},{'group':'fjsp-u','seed':9,'phase':'not_started'}],
          'groups':[{'group':'fjsp-u','declared_runs':3,'complete_valid_runs':1,'mean_J':1,'sample_std_J':None,'J_curve_mean_sample_std':[{'evolution_attempt':1,'observed_runs':1,'mean_J':1,'sample_std_J':None}]}]}
        c.write(root/'batch-summary.json',batch);check=c.batch_report(root/'batch-summary.json');assert check['declared_rows']==3 and check['phases']['not_started']==1
        c.batch_report(root/'batch-summary.json',root/'batch-report');assert len(c.csvrows(root/'batch-report/all-runs.csv'))==3
    proof={'passed':True,'checks':['all evolution attempts retained; init separate','exclusive outcome counts','internal -J converted once','H selections from sequence, not score-call counts','seven PNG/SVG/PDF charts','full ZIP/member hashes/source immutability','secret/lock/overwrite refusal','batch failures/unstarted retained and n=1 has no SD band'],'API_requests':0,'actual_solves':0,'H_U_executions':0}
    c.write(ROOT/'reports/triad-closeout-20261114/OFFLINE_CHECKS.json',proof);print(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
