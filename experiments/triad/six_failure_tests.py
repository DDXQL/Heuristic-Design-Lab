#!/usr/bin/env python3
"""Audit-transition regression; synthetic owned files only, never old R11."""
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha,digest
from experiments.triad import six_ops,runtime
from experiments.triad.parallel_tests import fixture,deny


def main():
    (ROOT/'plans').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='OFFLINE-six-failure-',dir=ROOT/'plans') as tmp:
        root=Path(tmp);p=fixture(root,'fjsp-eoh','known',False);m=read(p)
        ledger=read(p.parent/'gate/ledger.json');uid=digest({'member':m['members'][0]['run_id'],'key':'attempt1'})
        for i,row in enumerate(m['members']):
            d=Path(row['run_dir']);runtime.prepare(d,row['config'],engineering=True)
            s=read(d/'checkpoint.json');s['phase']='paused'
            if i==0:s.update(cursor=2,tasks={'slot1':{'id':'slot1','status':'completed'},'slot2':{'id':'slot2','status':'completed'}},u_rng=['SYNTHETIC_CURRENT_RNG'],population=['SYNTHETIC_PARENT'])
            write(d/'checkpoint.json',s);write(d/'Run_clock.json',{'start':time.time(),'deadline':time.time()+3600})
            attempts={'attempt1':{'id':'attempt1','number':1,'status':'failed','send_confirmed':True,'finished_at':time.time(),'metadata':{'send_status':'confirmed','http_status':522,'failure_stage':'http_receive'},'usage':None}} if i==0 else {}
            if i==0:attempts['attempt2']={'id':'attempt2','number':1,'status':'failed','send_confirmed':False,'finished_at':time.time(),'metadata':{'send_status':'not_sent','failure_stage':'shared_admission'},'usage':None}
            write(d/'API_attempts.json',{'halt_reason':None,'api_attempts':attempts})
            ledger['jobs'][row['run_id']]={'SYNTHETIC_TERMINAL':True}
        ledger['requests'][uid]={'member':m['members'][0]['run_id'],'key':'attempt1','state':'failed_or_unknown'};ledger['active'][uid]=m['members'][0]['run_id']
        write(p.parent/'gate/ledger.json',ledger);write(p.parent/'gate/STOP.json',{'reason':'SYNTHETIC522'})
        files=[Path(row['run_dir'])/n for row in m['members'] for n in ('checkpoint.json','API_attempts.json','Protocol.json','Run_clock.json')]
        original={str(f):sha(f) for f in files}
        with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(six_ops,'manifest',return_value=p),patch.object(six_ops,'scheduler',return_value=[{'state':'COMPLETED','fixture':True}]*2):
            journal=Path(m['members'][0]['run_dir'])/'API_attempts.json';known=read(journal);unknown=copy.deepcopy(known)
            unknown['api_attempts']['attempt1'].update(send_confirmed=False,metadata={'send_status':'unknown','failure_stage':'wire'})
            write(journal,unknown)
            before=sha(p.parent/'gate/ledger.json')
            try:six_ops.settle_known('fjsp503',True)
            except PermissionError:pass
            else:raise AssertionError('unknown send accepted')
            assert sha(p.parent/'gate/ledger.json')==before and (p.parent/'gate/STOP.json').exists()
            write(journal,known)
            result=six_ops.settle_known('fjsp503',True)
            assert result['charged_retained']==2 and result['journal_only_not_sent_preserved']==1 and result['refunds']==0 and result['phase_or_rng_writes']==0
            assert all(sha(Path(f))==h for f,h in original.items())
            after=read(p.parent/'gate/ledger.json');assert len(after['requests'])==2 and not after['active'] and not after['jobs'] and after['requests'][uid]['state']=='reconciled_failed'
            assert not (p.parent/'gate/STOP.json').exists() and len(list((p.parent/'known-failures').glob('*/Original-STOP.json')))==1
    out={'passed':True,'unknown_send_refused_before_writes':True,'known_HTTP522_audited_and_archived':True,'journal_only_not_sent_charge_preserved':True,'budget_phase_rng_population_clock_unchanged':True,'requests_refunded':0,'API_requests':0,'actual_solves':0,'Slurm_submitted':False}
    write(ROOT/'reports/six-groups-20261116/OFFLINE_FAILURE.json',out);print(json.dumps(out))


if __name__=='__main__':main()
