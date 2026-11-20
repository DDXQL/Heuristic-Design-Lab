"""Offline contract tests for bounded API, TSP and OBP acceptance."""

import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
from threading import Barrier
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import r15_acceptance as a
from experiments.triad import assets, problems, runtime, six_ops
from fjsp_usage.research_real.real_transport import TransportError
from heuristic_design.core import execution
from heuristic_design.core.storage import read, write


def deny(*args, **kwargs):
    raise AssertionError('offline tests only')


class Reply:
    redact = staticmethod(str)

    def __init__(self, barrier=None, fault=None):
        self.barrier=barrier
        self.fault=fault

    def dispatch(self, key, prompt, *, kind, on_sent):
        on_sent()
        if self.barrier is not None:self.barrier.wait(timeout=15)
        if self.fault is not None:
            error=TransportError('offline response error')
            error.metadata={'http_status':self.fault,'send_status':'confirmed','failure_stage':'http_receive'}
            if self.fault==429:error.metadata['retry_after']='61'
            raise error
        text='OK'
        if kind=='U':text='Choose H0.\n```python\ndef use_heuristics(state):\n    return 0\n```'
        elif kind=='H':text='{Prefer lower distance}\n```python\ndef priority('+', '.join(problems.h_args('tsp'))+'):\n    return 0.0\n```'
        return {'text':text,'usage':{'input_tokens':7,'output_tokens':1},'metadata':{'http_status':200}}


def probes(temp):
    observed={}
    for width in a.WIDTHS:
        d=temp/f'api{width}';d.mkdir()
        barrier=Barrier(width)
        report=a.probe(d,width,lambda:Reply(barrier),wait=lambda _:None)
        assert report['confirmed_sends']==report['successful_responses']==width*2 and report['passed']
        assert report['peak_confirmed_in_flight']==width and report['known_tokens']['input_tokens']==width*2*7
        observed[width]=report['confirmed_sends']
    for code in (429,524):
        d=temp/f'api-fail-{code}';d.mkdir()
        report=a.probe(d,2,lambda:Reply(Barrier(1),code),wait=deny)
        assert not report['passed'] and report['confirmed_sends']==2 and report['usage_unknown']==2
        assert all(r['http_status']==code for r in report['errors'])
    args=SimpleNamespace(kind='api',width=2,approve_requests=3,approve_solves=0,confirm_exclusive_account=True)
    try:a.execute(args,temp/'no-approval',[],4)
    except ValueError as error:assert 'exact request/solve caps' in str(error)
    else:raise AssertionError('invalid approval passed')
    args=SimpleNamespace(kind='api',width=4,approve_requests=8,approve_solves=0,
                         confirm_exclusive_account=True,rpm=20,tpm=8192)
    with (patch.dict(os.environ,{'SLURM_JOB_ID':'1','SLURM_STEP_ID':'0','SLURM_CPUS_PER_TASK':'9'}),
          patch.object(a.entry,'allocation_deadline',return_value=time.monotonic()+900)):
        try:a.execute(args,temp/'api-4',[],8)
        except ValueError as error:assert 'preceding concurrency stage' in str(error)
        else:raise AssertionError('skipped API stage accepted')
        args.width=2;args.approve_requests=4
        with patch.object(a.six_ops,'config',return_value={**six_ops.config('tsp-eoh'),'account_gate':str(temp)}):
            write(temp/'generation.lock',{'protocol':'R13 in progress'})
            try:a.execute(args,temp/'fresh-api-2',[],4)
            except ValueError as error:assert 'account occupied' in str(error)
            else:raise AssertionError('probe interrupted an occupied account')
    return observed


def tsp_pilot(temp, reference):
    cfg=a.ROOT/'configurations/experiments/tsp-502.json'
    doc=read(cfg);doc['research']['reference']=str(reference)
    config=temp/'tsp-pilot-input.json';write(config,doc)
    planned=a.setup_tsp(config)
    assert len(planned)==2 and all(len(p['instances'])==20 for p,_ in planned)
    assert len(planned[0][0]['members'])==10 and not planned[1][0]['members']
    assert a.client(planned[0][0]['config'],short=False).provider.max_output_tokens==8192

    def evaluator(task,p):
        loc=Path(p['run_directory'])/'worker-receipts'/task['id']/'physical-solves.jsonl'
        loc.parent.mkdir(parents=True)
        loc.write_text(''.join('{"event":"started"}\n' for _ in range(len(p['instances'])*2)))
        return {'valid':True,'fitness':-0.1,'instances':p['instances'],'offline_fixture':True}

    folder=temp/'tsp-pilot';folder.mkdir()
    with patch.object(runtime.Adapter,'validate_result',lambda self,r,instances:len(r['instances'])==20):
        report=a.tsp(folder,planned,lambda _:Reply(),evaluate=evaluator)
    assert report['passed'] and report['confirmed_sends']==2 and report['peak_confirmed_in_flight']==1
    assert report['actual_solves']==80 and all(Path(row['path']).is_file() for row in report['results'])
    failed=temp/'tsp-pilot-failed';failed.mkdir()
    def crashed(*args):raise RuntimeError('synthetic worker termination')
    fault=a.tsp(failed,planned,lambda _:Reply(),evaluate=crashed)
    assert not fault['passed'] and fault['confirmed_sends']==1 and fault['results'][0]['evaluation_error']['type']=='RuntimeError'
    return {'mock_sends':report['confirmed_sends'],'mock_solve_events':report['actual_solves']}


def obp_build(temp):
    c=six_ops.config('obp-u')
    c.update(mode='mock',freeze_status='engineering_only',credential_file=None)
    path=temp/'H401-mock.json';write(path,c)
    directory=a.ROOT/'runs'/('offline-h401-'+uuid4().hex)
    try:
        p=runtime.prepare(directory,path,engineering=True,run_kind='h-build')
        assert len(p['instances'])==96 and p['config']['search_seed']==401
        with patch.object(execution,'sys',SimpleNamespace(platform='linux')):
            result=execution.start(directory,adapter=runtime.Adapter())
        assert result['phase']=='completed' and result['cursor']==40
        frozen=temp/'H401-mock-frozen.json'
        report=assets.freeze_h(directory,frozen)
        assert report['H_count']==10 and read(frozen)['engineering_only']
        c.update(mode='real',h_file=str(frozen))
        try:problems.load_inputs(c)
        except ValueError as error:assert 'engineering H asset' in str(error)
        else:raise AssertionError('Mock freeze passed the real asset gate')
        try:assets.fixed_from_h401(c,directory,temp/'invalid-fixed.json')
        except ValueError as error:assert 'completed real OBP H401' in str(error)
        else:raise AssertionError('Mock H-build results passed real fixed-H reuse')
        assert not (temp/'invalid-fixed.json').exists()
        return {'attempts':40,'selected':report['H_count'],'mock_cannot_be_real':True}
    finally:
        if directory.is_dir():shutil.rmtree(directory)


if __name__=='__main__':
    import sys
    ref=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else a.ROOT/'preparations/operations/tsp-reference-r15.json'
    with (tempfile.TemporaryDirectory() as tmp, patch.object(socket.socket,'connect',deny),
          patch.object(socket,'create_connection',deny), patch.object(a,'StrictNonstreamTransport',deny),
          patch.object(a.entry,'key',deny), patch.object(a.evaluation,'evaluate',deny),
          patch.object(a.entry.subprocess,'run',deny)):
        d=Path(tmp)
        print(json.dumps({'probe':probes(d),'pilot':tsp_pilot(d,ref),'OBP_H401':obp_build(d),
                          'real_API':0,'real_solves':0,'Slurm':0},indent=2))
