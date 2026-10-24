"""Synthetic lifecycle regression and exactly six progress-policy tests."""
from copy import deepcopy
import importlib
import json
import math
import multiprocessing as mp
from pathlib import Path
import time
import tempfile
import unittest
from unittest.mock import Mock,patch

from fjsp_usage.fusion_v4 import lifecycle as new
from fjsp_usage.fusion_v4.policies import specs,progress_policy
from fjsp_usage.fusion_v3.execution import construct_rank_schedule,fixed_borda
from fjsp_usage.fusion_v2.execution import fixed_policy
from fjsp_usage.research.protocol import digest
from tools.b1_timeout_boundary import collect_with_lifecycle as old_collect
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance,Operation
from fjsp_usage.research.candidates import validate_code,H_ARGS
from tools import fusion_v4_experiment as batch


def delayed_cleanup_worker(pipe,*args):
    """No FJSP: all result rows returned, deterministic cleanup delay afterwards."""
    pipe.send({'file':'MOCK','value':7})
    time.sleep(.25)
    pipe.close()


class LifecycleTests(unittest.TestCase):
    def context(self,alive,exitcode,readable=True,row=None):
        worker=Mock(pid=123,exitcode=exitcode);worker.is_alive.side_effect=alive
        receive,send=Mock(),Mock();receive.poll.return_value=readable
        receive.recv.return_value=row or {'file':'MOCK'}
        context=Mock();context.Pipe.return_value=(receive,send);context.Process.return_value=worker
        return context,worker,receive

    def collect(self,context,persist=lambda x:None):
        return new.collect(context,None,None,(),(),('MOCK',),15,None,persist,clock=lambda:1.)

    def test_normal_grace_only_after_complete_results_preserves_poll15(self):
        context,worker,receive=self.context([False,False,False],0)
        rows,failure,life=self.collect(context)
        self.assertIsNone(failure);self.assertEqual(rows,[{'file':'MOCK'}])
        receive.poll.assert_called_once_with(15);worker.join.assert_called_once_with(timeout=2.)
        worker.terminate.assert_not_called();self.assertTrue(life['exit_grace_used'])
        self.assertTrue(life['all_results_received']);self.assertEqual(life['rows_received'],1)

    def test_timeout_uses_original_cleanup_no_normal_grace_or_retry(self):
        context,worker,receive=self.context([True,False,False],-15,readable=False)
        rows,failure,life=self.collect(context)
        self.assertEqual(rows,[]);self.assertEqual(failure['error_type'],'Timeout')
        receive.poll.assert_called_once_with(15);worker.start.assert_called_once()
        self.assertFalse(life['exit_grace_used']);self.assertFalse(life['all_results_received'])
        self.assertEqual(worker.join.call_args_list[0].kwargs,{'timeout':.05})
        worker.terminate.assert_called_once()

    def test_lingering_after_grace_is_terminated_not_promoted(self):
        context,worker,_=self.context([True,False,False],-15)
        _,_,life=self.collect(context)
        self.assertEqual(worker.join.call_args_list[0].kwargs,{'timeout':2.})
        worker.terminate.assert_called_once();self.assertEqual(life['exitcode'],-15)

    def test_kill_and_unknown_terminal_remain_visible(self):
        context,worker,_=self.context([True,True,True],None)
        _,_,life=self.collect(context)
        worker.kill.assert_called_once();self.assertTrue(life['alive']);self.assertIsNone(life['exitcode'])

    def test_eof_error_never_gets_normal_grace(self):
        context,worker,receive=self.context([False,False,False],0)
        receive.recv.side_effect=EOFError
        _,failure,life=self.collect(context)
        self.assertEqual(failure['error_type'],'WorkerExit');self.assertFalse(life['exit_grace_used'])
        worker.join.assert_called_once_with(timeout=.05)

    def test_persistence_failure_still_cleans_up(self):
        context,worker,_=self.context([True,False,False],-15)
        with self.assertRaises(OSError):self.collect(context,Mock(side_effect=OSError('MOCK disk')))
        worker.terminate.assert_called_once()

    def test_real_old_vs_new_delayed_cleanup_mock(self):
        records=[]
        rows,failure,old=old_collect(mp.get_context('spawn'),delayed_cleanup_worker,None,(),(),('MOCK',),15,None,records.append)
        self.assertIsNone(failure);self.assertEqual(len(rows),1);self.assertEqual(old['exitcode'],-15)
        records=[]
        rows,failure,life=new.collect(mp.get_context('spawn'),delayed_cleanup_worker,None,(),(),('MOCK',),15,None,records.append)
        self.assertIsNone(failure);self.assertEqual(len(rows),1)
        self.assertEqual(life['exitcode'],0);self.assertFalse(life['alive'])
        self.assertGreater(life['exit_wait_observed_seconds'],.05)
        self.assertLess(life['exit_wait_observed_seconds'],2.)

    def classify_fixture(self):
        w={'pid':123,'modules':{'synthetic':'pinned'}};w['identity']=digest(w['modules'])
        _,_,life=self.collect(self.context([False,False,False],0)[0])
        kwargs={'before':w,'after':w,'lifecycle':life,'expected_identity':w['identity'],
                'expected_files':{'x':'hash'},'start_files':{'x':'hash'},'end_files':{'x':'hash'}}
        result={'valid':True,'fitness':-2.,'instances':[{'file':'MOCK'}]}
        return result,kwargs

    def test_original_identity_and_normal_exit0_requirements_retained(self):
        result,kw=self.classify_fixture()
        self.assertEqual(new.classify(result,**kw)['decision'],'original_result_checks_required')
        changes=[{'after':None},{'before':None},{'after':dict(kw['after'],identity='wrong')},
                 {'end_files':{}},{'worker_failure':True}]
        for exitcode in (-15,1,None):changes.append({'lifecycle':dict(kw['lifecycle'],exitcode=exitcode)})
        for change in changes:
            with self.subTest(change=change):self.assertEqual(new.classify(result,**dict(kw,**change))['decision'],'stop')

    def test_new_receipt_fields_cannot_be_missing_or_forged(self):
        result,kw=self.classify_fixture()
        for change in ({'exit_grace_used':False},{'all_results_received':False},
                       {'deadline_seconds':16},{'exit_grace_seconds':3},
                       {'rows_received':0},{'expected_rows':2},{'cleanup':['join_0.05']}):
            self.assertEqual(new.classify(result,**dict(kw,lifecycle=dict(kw['lifecycle'],**change)))['decision'],'stop')

    def test_confirmed_timeout_remains_invalid_and_cannot_use_grace(self):
        result,kw=self.classify_fixture();_,failure,life=self.collect(self.context([True,False,False],-15,False)[0])
        result={'valid':False,'fitness':None,**failure}
        self.assertEqual(new.classify(result,**dict(kw,after=None,lifecycle=life))['decision'],'candidate_invalid_continue')
        self.assertEqual(new.classify(result,**dict(kw,after=None,lifecycle=dict(life,exit_grace_used=True)))['decision'],'stop')


class ProgressTests(unittest.TestCase):
    def test_real_spawned_worker_mock_full_recheck_and_identity(self):
        old=batch.v2
        paths={str(Path(importlib.import_module(n).__file__).resolve().relative_to(batch.ROOT))
               for n in old.MODULES+batch.v3.NEW_MODULES+batch.MODULES}
        p={'source_files':{n:old.sha(batch.ROOT/n) for n in paths},
           'instances':[{'relative_path':'inputs/train/toy.fjsp'}]}
        expected=batch.witness(p)
        members=tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -'+H_ARGS[-1]+'\n',kind='h') for _ in range(10))
        toy=FJSPInstance('switch-toy',2,((Operation(((0,2),(1,3))),Operation(((0,5),(1,6)))),(Operation(((0,4),)),)))
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);spec=specs()[0];folder=directory/'evidence'/spec['id'];folder.mkdir(parents=True)
            rows,failure,life=new.collect(mp.get_context('spawn'),batch.worker,
                {'directory':str(directory),'protocol':p,'spec':spec},members,(toy,),('toy.fjsp',),15,None,lambda r:None)
            self.assertIsNone(failure);self.assertEqual(life['exitcode'],0);self.assertFalse(life['alive'])
            self.assertEqual(rows[0]['physical_schedule_sha256'],rows[0]['recheck_physical_schedule_sha256'])
            self.assertEqual(rows[0]['captured_solves'],2);self.assertEqual(rows[0]['operator_switches'],1)
            self.assertTrue(all(rows[0]['operator_counts'].values()))
            self.assertEqual(old.read(folder/'before.json')['identity'],expected['identity'])
            self.assertEqual(old.read(folder/'after.json')['identity'],expected['identity'])
            self.assertEqual(rows[0]['network_guard'],{'network_attempts_blocked':0,'nontrain_opens_blocked':0})

    def test_unknown_reservation_stops_before_any_instance_or_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            state={'protocol_sha256':'bound','phase':'running','strategies':{specs()[0]['id']:{'status':'reserved'}}}
            (directory/'checkpoint.json').write_text(json.dumps(state))
            with patch.object(batch,'check',return_value={}),patch.object(batch.v2,'sha',return_value='bound'),\
                 patch.object(batch.v2,'load_instance',side_effect=AssertionError('unexpected load')) as loader,\
                 patch.object(batch,'collect',side_effect=AssertionError('unexpected solve')) as collector:
                with self.assertRaisesRegex(ValueError,'unknown reservation'):batch.run(directory)
                loader.assert_not_called();collector.assert_not_called()

    def test_exact_six_and_threshold_equality_is_late(self):
        self.assertEqual(len(specs()),6);self.assertEqual(len({s['id'] for s in specs()}),6)
        for spec in specs():
            u=progress_policy(spec)
            self.assertEqual(u(spec['threshold']-1e-9)[0],spec['first'])
            self.assertEqual(u(spec['threshold'])[0],spec['late'])
            self.assertEqual(u(0)[1],(.5,.5,0.,0.,0.,0.,0.,0.,0.,0.))
        with self.assertRaises(ValueError):progress_policy(dict(specs()[0],threshold=.4))

    def test_one_actual_operator_switch_and_both_operators_for_train_sizes(self):
        for n in (50,100,200,500):
            for spec in specs():
                sequence=[progress_policy(spec)(i/n)[0] for i in range(n)]
                self.assertEqual(set(sequence),{'WEIGHTED_SUM','BORDA'})
                self.assertEqual(sum(a!=b for a,b in zip(sequence,sequence[1:])),1)
                self.assertEqual(sequence.count(spec['first']),math.ceil(n*spec['threshold']))

    def test_kernel_unchanged_fixed_policies_and_repeat_dynamic_schedules(self):
        toy=FJSPInstance('switch-toy',2,((Operation(((0,2),(1,3))),Operation(((0,5),(1,6)))),(Operation(((0,4),)),)))
        rules=[lambda p,w,n,j,m,s,f:-f,lambda p,w,n,j,m,s,f:w-p]+[lambda *s:0]*8
        for spec in specs():
            states=[];a=construct_rank_schedule(toy,rules,progress_policy(spec),trace=states.append)
            b=construct_rank_schedule(toy,rules,progress_policy(spec))
            self.assertEqual(a,b)
            self.assertTrue(all(r['state']['previous_heuristic']==(-1 if r['step']==0 else 0) for r in states))
        for op in ('WEIGHTED_SUM','BORDA'):
            policy=fixed_policy((0,1),op) if op=='WEIGHTED_SUM' else fixed_borda((0,1))
            self.assertEqual(construct_rank_schedule(toy,rules,policy),construct_rank_schedule(toy,rules,policy))


if __name__=='__main__':unittest.main()
