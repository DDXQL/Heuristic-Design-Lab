"""No API, H execution, schedule construction or training reevaluation."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import importlib.util
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

    def test_explicit_bounded_initialization_uses_only_its_declared_cap(self):
        c=settings(initialization_request_cap=3,initialization_candidate_cap=3,api_attempt_cap=10,
                   mock_faults={'INIT-0000':'invalid'})
        c['execution_contract']['initialization_policy']='bounded_initialization_until_population'
        d,p,s=self.run_case('bounded-init',c)
        self.assertEqual((s['initialization_requests'],s['generation_requests']),(3,7))

    def test_bounded_user_validation_prefix_is_exact_and_resumes_same_budget(self):
        d=self.root/'finite-prefix';e.prepare(d,settings())
        with contextlib.redirect_stdout(io.StringIO()):r=e.run(d,max_tasks=3)
        self.assertEqual(r['phase'],'paused')
        self.assertEqual(r['completed_tasks'],3)
        self.assertEqual(r['initialization_requests']+r['generation_requests'],3)
        clock=read(d/'Run_clock.json')
        with contextlib.redirect_stdout(io.StringIO()):e.run(d)
        p,s=e.check(d)
        self.assertEqual(read(d/'Run_clock.json'),clock)
        self.assertEqual(s['initialization_requests']+s['generation_requests'],9)

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

    def test_hard_or_unknown_reply_prevents_later_reserved_request_in_same_wave(self):
        from heuristic_design.llm import routing_transport
        for name,value in (
            ('hard',{'sent':True,'text':None,'error':'HTTP401','metadata':{'http_status':401}}),
            ('unknown',{'sent':False,'text':None,'error':'uncertain send','metadata':{'send_status':'unknown'}})):
            d=self.root/name;e.prepare(d,settings());p,s=e.check(d)
            p['config']['api_mode']='real';gate=self.root/(name+'-gate');gate.mkdir()
            p['config']['execution_contract']['account_gate']=str(gate)
            tasks=[{'id':'INIT-'+str(i),'stage':'initialization','generation':0,'operator':'INIT',
                    'parents':[],'parent_records':[],'parent_keys':[],'status':'planned','valid':False,'fitness':None} for i in range(2)]
            s['tasks']={t['id']:t for t in tasks}
            with patch.object(routing_transport,'generate',return_value=value) as fake,contextlib.redirect_stdout(io.StringIO()):
                if name=='unknown':
                    with self.assertRaises(RuntimeError):e._execute_batch(d,s,p,tasks,e.mock_evaluate)
                else:e._execute_batch(d,s,p,tasks,e.mock_evaluate)
            self.assertEqual(fake.call_count,1)
            self.assertEqual(s['initialization_requests'],2)  # both reservations remain charged
            self.assertEqual(tasks[1]['send_state'],'not_sent')
            self.assertEqual(tasks[1]['failure'],'cancelled_before_dispatch')

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

    def test_v3_constructor_call_binding_without_solving(self):
        from types import SimpleNamespace
        from heuristic_design.problems import routing_fixtures as fixtures
        from heuristic_design.core import routing_state_a_v3 as language
        from heuristic_design.problems.fjsp import routing as fjsp
        from llm4ad.task.optimization.fjsp_set.scheduler import Schedule
        candidate={'code':'inert'}
        inert=SimpleNamespace(schedule=Schedule((),12),reference=10,score=.2,trace=(),
            h_calls=(1,0),member_sequence=(0,),observation_seconds=0)
        with patch.object(fixtures,'compile_members',return_value=[lambda:None,lambda:None]), \
             patch.object(fixtures,'decode_instance',return_value='inert-instance'), \
             patch.object(language,'checked',return_value='inert-candidate'), \
             patch.object(language,'compile_candidate',return_value='inert-U'), \
             patch.object(fjsp,'construct_state_a_v3',return_value=inert) as construct:
            result=fixtures.solve('fjsp',{'file':'inert'},[],candidate,trace=False,state_schema='common-state-a-v3-fjsp')
        self.assertEqual(construct.call_args.args[0],'inert-instance')
        self.assertEqual(construct.call_args.kwargs,{'trace':False})
        self.assertEqual((result['raw_cost'],result['reference'],result['score']),(12,10,.2))
        # Retain the repaired inherited result packet binding with v3 metadata.
        packet=fjsp.StateAResult(Schedule((),12),.2,(),(1,0),0.,(0,),reference=10,state_schema='common-state-a-v3-fjsp')
        self.assertEqual(packet.member_sequence,(0,))

    def test_slurm_command_matches_configuration_without_submission(self):
        spec=importlib.util.spec_from_file_location('single_submit',ROOT/'deploy/fjsp-long/submit.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        document=read(ROOT/'experiments/fjsp_long/mock.json')
        cfg=self.root/'mock.json';write(cfg,document)
        deploy=read(ROOT/'deploy/fjsp-long/deployment.pending.json')
        deploy.update(partition='MOCK',memory_mib=512,walltime_seconds=1800)
        path=self.root/'deployment.json';write(path,deploy)
        with patch.object(module.subprocess,'run',side_effect=AssertionError('NO SUBMISSION')):
            _,cmd=module.command(path,cfg,'run')
        self.assertIn('--cpus-per-task=3',cmd);self.assertIn('--mem=512M',cmd)
        self.assertIn('--time=00:30:00',cmd);self.assertIn('--no-requeue',cmd)
        self.assertIn('--signal=B:USR1@120',cmd)
        self.assertFalse(any('--array' in part for part in cmd))
        _,finite=module.command(path,cfg,'run',pause_after_attempts=1)
        self.assertEqual(finite[-1],'1')
        with self.assertRaises(ValueError):module.command(path,cfg,'run',pause_after_attempts=10)
        deploy['walltime_seconds']=1801;write(path,deploy)
        with self.assertRaises(ValueError):module.command(path,cfg,'run')

    def test_slurm_duplicate_and_unknown_submission_are_not_replayed(self):
        from types import SimpleNamespace
        spec=importlib.util.spec_from_file_location('submission_fixture',ROOT/'deploy/fjsp-long/submit.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        document=read(ROOT/'experiments/fjsp_long/mock.json');document['run_root']='runs'
        cfg=self.root/'launch.json';write(cfg,document)
        from experiments.common.run_frozen import configuration
        _,c,d,_=configuration(cfg);e.prepare(d,c)
        deploy=read(ROOT/'deploy/fjsp-long/deployment.pending.json')
        deploy.update(remote_root=str(self.root),partition='MOCK',memory_mib=512,walltime_seconds=1800)
        path=self.root/'deploy.json';write(path,deploy)
        calls=[]
        def fake(command,**kwargs):
            calls.append(command)
            return SimpleNamespace(stdout='12345|COMPLETED|\n' if command[0]=='sacct' else '12345\n')
        args=['submit.py','run','--deployment',str(path),'--config',str(cfg),'--submit']
        errors=io.StringIO()
        with patch.object(module,'ROOT',self.root.resolve()),patch.object(sys,'argv',args), \
             patch.object(module.subprocess,'run',side_effect=fake), \
             contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(errors):
            self.assertEqual(module.main(),0,errors.getvalue())
            self.assertEqual(module.main(),2)
        self.assertEqual(sum(cmd[0]=='sbatch' for cmd in calls),1)
        claim=next((d/'submissions').glob('*.json'));write(claim,{'state':'submission_reserved'})
        with patch.object(module,'ROOT',self.root.resolve()),patch.object(sys,'argv',args), \
             patch.object(module.subprocess,'run',side_effect=AssertionError('unknown submission must not dispatch')), \
             contextlib.redirect_stderr(io.StringIO()):self.assertEqual(module.main(),2)


if __name__=='__main__':unittest.main()
