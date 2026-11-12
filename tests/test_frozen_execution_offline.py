"""No API, H execution, schedule construction or training reevaluation."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from heuristic_design.core import evolution_v1 as e
from heuristic_design.core import execution_contract as contract
from heuristic_design.core.execution_export import export
from heuristic_design.core.storage import read, write


ROOT=Path(__file__).resolve().parents[1]
BASE=read(ROOT/'experiments/fjsp_long/mock.json')['settings']


def settings(**updates):
    c=copy.deepcopy(BASE);c.update(updates)
    return c


def semantic(s):
    return {k:s[k] for k in ('population','rng','generations','seen','generation_requests',
            'initialization_requests','initialization_complete','completed_tasks')}


class Offline(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.environment=patch.dict(os.environ,{k:'1' for k in contract.THREAD_ENV})
        self.environment.start()
        self.network=patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK'))
        self.network.start()

    def tearDown(self):
        self.network.stop();self.environment.stop();self.temp.cleanup()

    def run_case(self,name,c,pause=False):
        d=self.root/name;e.prepare(d,c)
        with contextlib.redirect_stdout(io.StringIO()):
            if pause:
                result=e.run(d,max_tasks=4);self.assertEqual(result['phase'],'paused')
                clock=read(d/'Run_clock.json');before=e.check(d)[1]
                old_requests=before['initialization_requests']+before['generation_requests']
            result=e.run(d)
        self.assertEqual(result['phase'],'completed')
        p,s=e.check(d)
        if pause:
            self.assertEqual(clock,read(d/'Run_clock.json'))
            self.assertGreater(s['initialization_requests']+s['generation_requests'],old_requests)
        return d,p,s

    def test_parallel_serial_resume_prefix_milestones_and_process_receipts(self):
        a,pa,sa=self.run_case('serial',settings(api_concurrency=1,evaluation_concurrency=1))
        b,pb,sb=self.run_case('parallel',settings(api_concurrency=2,evaluation_concurrency=2,mock_reverse_delay=True))
        d,pd,sd=self.run_case('resume',settings(),pause=True)
        self.assertEqual(semantic(sa),semantic(sb));self.assertEqual(semantic(sa),semantic(sd))
        for folder,p,s in ((a,pa,sa),(b,pb,sb),(d,pd,sd)):
            self.assertEqual((s['initialization_requests'],s['generation_requests'],s['completed_tasks']),(2,7,9))
            self.assertEqual(len(list((folder/'responses').glob('*.json'))),9)
            self.assertFalse((folder/'.coordinator.lock').exists())
            for count in (3,7):
                mark=read(folder/f'milestones/attempt-{count:06d}.json')
                self.assertEqual(mark['checkpoint']['generation_requests'],count)
                self.assertTrue(all(t['status'] in ('planned','completed') for t in mark['checkpoint']['tasks'].values()))
            ev=[read(folder/v['path']) for v in s['evaluations'].values()]
            self.assertTrue(all(r['mock_worker']['pid']!=os.getpid() and r['mock_worker']['real_solves']==0 for r in ev))
            result=export(folder,p,s)
            self.assertEqual(result['request_reservations'],9)
            self.assertIsNone(result['actual_cost']);self.assertFalse(result['currency_hard_cap_verified'])
            self.assertTrue((folder/'exports/per_instance.csv').exists())

    def test_independent_seeds_and_exclusive_launch(self):
        _,_,a=self.run_case('seed-71',settings())
        _,_,b=self.run_case('seed-72',settings(search_seed=72))
        self.assertNotEqual(a['rng'],b['rng'])
        self.assertEqual(a['generation_requests'],b['generation_requests'])
        d=self.root/'locked';e.prepare(d,settings());(d/'.coordinator.lock').write_text('preserve')
        with self.assertRaises(FileExistsError):e.run(d)
        self.assertEqual((d/'.coordinator.lock').read_text(),'preserve')

    def test_unknown_reservation_config_and_checkpoint_tamper_block(self):
        for status in ('request_reserved','evaluation_reserved','unknown_send'):
            d=self.root/status;e.prepare(d,settings());p,s=e.check(d)
            s['tasks']['UNKNOWN']={'id':'UNKNOWN','status':status};e.save(d,s)
            with self.assertRaises(ValueError):e.run(d)
            self.assertEqual(len(list((d/'responses').glob('*.json'))),0)
        d=self.root/'changed';e.prepare(d,settings());p=read(d/'Protocol.json');p['config']['search_seed']=999
        write(d/'Protocol.json',p)
        with self.assertRaises(ValueError):e.check(d)

    def test_initialization_failure_does_not_refill_and_duplicate_spends_attempt(self):
        d=self.root/'init-failure';e.prepare(d,settings(mock_faults={'INIT-0000':'invalid'}))
        with contextlib.redirect_stdout(io.StringIO()):r=e.run(d)
        self.assertEqual(r['phase'],'initialization_incomplete')
        self.assertEqual(r['initialization_requests'],2);self.assertEqual(r['generation_requests'],0)
        self.assertEqual(len(list((d/'responses').glob('*.json'))),2)

    def test_failure_classes_unknown_and_hard_stop(self):
        p={'config':{'api_mode':'real'}}
        for metadata in ({'send_status':'unknown'},{}):
            s={};t={'id':'x'}
            with self.assertRaises(RuntimeError):contract.settle_api(s,p,[t],{'x':{'ok':True,'value':{'sent':False,'metadata':metadata}}})
            self.assertEqual(t['send_state'],'unknown')
        s={};t={'id':'auth'}
        contract.settle_api(s,p,[t],{'auth':{'ok':True,'value':{'sent':True,'text':None,'error':'HTTP401','metadata':{'http_status':401},'usage':None}}})
        self.assertTrue(s['hard_api_stop']);self.assertEqual(s['phase'],'paused')
        s={}
        for i in range(3):
            t={'id':str(i)}
            contract.settle_api(s,p,[t],{str(i):{'ok':True,'value':{'sent':True,'text':None,'error':'HTTP524','metadata':{'http_status':524}}}})
        self.assertEqual(s['phase'],'paused');self.assertEqual(s['transport_failure_streak'],3)

    def test_infrastructure_failure_retains_lock_and_reservation(self):
        d=self.root/'infra';e.prepare(d,settings())
        def fail(*a):raise RuntimeError('synthetic infrastructure uncertainty')
        with contextlib.redirect_stdout(io.StringIO()),self.assertRaises(RuntimeError):e.run(d,evaluate=fail)
        self.assertTrue((d/'.coordinator.lock').exists())
        with self.assertRaises(ValueError):e.run(d)
        self.assertTrue(any(t['status']=='evaluation_reserved' for t in read(d/'checkpoint.json')['tasks'].values()))

    def test_resources_and_staged_drain_math(self):
        c=settings();c['provider']={'total_timeout':300}
        self.assertEqual(contract.drain_bound(c,21),1237)
        with patch.dict(os.environ,{'SLURM_JOB_ID':'MOCK','SLURM_CPUS_PER_TASK':'2'}):
            with self.assertRaises(ValueError):contract.resources(c)
        with patch.dict(os.environ,{'SLURM_JOB_ID':'MOCK','SLURM_CPUS_PER_TASK':'3','SLURM_NTASKS':'1'}):
            self.assertEqual(contract.resources(c)['actual_cpus'],3)
        c['execution_contract']['allocated_cpus']=2
        with self.assertRaises(ValueError):e.config(c)

    def test_pool_limits_actually_apply(self):
        active=0;peak=0;lock=threading.Lock()
        def work(item):
            nonlocal active,peak
            with lock:active+=1;peak=max(peak,active)
            time.sleep(.03)
            with lock:active-=1
            return item['id']
        rows=[{'id':str(i)} for i in range(6)]
        for width in (1,2):
            peak=0;result=e._batch(work,rows,width)
            self.assertEqual(peak,width);self.assertEqual(set(result),{r['id'] for r in rows})

    def test_wave_budget_is_checked_before_any_reservation_or_dispatch(self):
        d=self.root/'budget';e.prepare(d,settings());p,s=e.check(d)
        p['config']['api_attempt_cap']=1
        tasks=[{'id':'B'+str(i),'stage':'initialization','status':'planned'} for i in range(2)]
        with patch.object(e,'_batch',side_effect=AssertionError('must not dispatch')):
            with self.assertRaises(ValueError):e._execute_batch(d,s,p,tasks,e.mock_evaluate)
        self.assertEqual(s['initialization_requests'],0)
        self.assertFalse((d/'responses').exists())

    def test_raw_cost_and_reference_receipt_cannot_be_replaced_by_partial_score(self):
        p={'config':{'execution_contract':{},'evaluation_mode':'mock'},'instances':[{'file':'a'}],
           'references':[{'file':'a','reference':10}]}
        bad={'valid':True,'mock':True,'fitness':-.2,'instances':[{'file':'a','score':.2,'raw_cost':11,'reference':10}],
             'behavior_sha256':'synthetic'}
        with self.assertRaises(ValueError):e._validate_result(bad,p)


if __name__=='__main__':unittest.main()
