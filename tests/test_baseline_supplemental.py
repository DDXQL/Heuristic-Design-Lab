"""T30 lifecycle, identity, budget, resume and frozen-kernel acceptance."""
from copy import deepcopy
import importlib
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fjsp_usage.baseline_supplemental import specs
from fjsp_usage.baseline_supplemental.lifecycle import receive_complete,collect,classify
from fjsp_usage.baseline_supplemental.validation import ledger,compare_historical
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.candidates import validate_code,H_ARGS
from fjsp_usage.research.events import atomic_json
from tools import baseline_a_supplemental as s
from tests.test_baseline_a import toy,synthetic_row

RECEIPTS=[]


def delayed_exit(pipe,*args):
    pipe.send({'file':'MOCK','value':7});time.sleep(.2);pipe.close()


def silent_worker(pipe,payload,*args):
    import os
    modules={'synthetic_mock':{'code':'no FJSP or API'}}
    atomic_json(Path(payload)/'before.json',{'pid':os.getpid(),'modules':modules,'identity':digest(modules)})
    time.sleep(60)
    pipe.close()


def guard_mock(pipe,*args):
    events=s.v2.local_guard([])
    for event,arguments in [('socket.connect',(None,('MOCK',0))),('open',('/MOCK/validation11.fjsp','r',0))]:
        try:sys.audit(event,*arguments)
        except RuntimeError:pass
    pipe.send({'file':'MOCK','simulated_blocked':events});pipe.close()


class Receiver:
    def recv(self):return {'file':'MOCK'}
    def close(self):pass


class Sender:
    def close(self):pass


class FakeProcess:
    pid=123
    def __init__(self,*a,**kw):self.exitcode=None;self.alive=True
    def start(self):pass
    def join(self,timeout):pass
    def is_alive(self):return self.alive
    def terminate(self):self.alive=False;self.exitcode=-15
    def kill(self):self.alive=False;self.exitcode=-9


class FakeContext:
    def Pipe(self,duplex=False):return Receiver(),Sender()
    Process=FakeProcess


class DoneThread:
    def join(self,timeout):pass
    def is_alive(self):return False


class T30Tests(unittest.TestCase):
    def evidence(self):
        modules={'a':{'sha':'dummy'}};w={'pid':123,'modules':modules,'identity':digest(modules)}
        l={'status':'terminal','alive':False,'exitcode':0,'pid':123,'receiver_thread_stopped':True,
           'deadline_seconds':30,'deadline_scope':'complete_recv_including_deserialisation','exit_grace_seconds':2.,
           'expected_rows':1,'rows_received':1,'trigger':None,'all_results_received':True,'exit_grace_used':True,
           'results_complete_monotonic':1.,'cleanup':['join_exit_grace_2.0'],
           'instance_receives':[{'file':'MOCK','timely':True,'finished':1.,'deadline':30.}]}
        result={'valid':True,'fitness':-1.,'instances':[{'file':'MOCK'}]}
        kwargs=dict(before=w,after=deepcopy(w),lifecycle=l,expected_identity=w['identity'],
                    expected_files={'p':'h'},start_files={'p':'h'},end_files={'p':'h'})
        return result,kwargs

    def test_exact_nine_H_identity_and_order(self):
        self.assertEqual([r['id'] for r in specs()],['H0_H1_WS','H0_H4_WS','H4_H5_WS','H0','H4_H6_WS','H4_H7_WS','H0_H3_WS','H5_H6_WS','H5_H7_WS'])
        h=s.v2.read(s.BASE/'H_frozen.json');keys=[m['candidate']['key'] for m in h['members']]
        self.assertEqual(len(set(keys)),10);self.assertEqual([m['member_id'] for m in h['members']],list(range(10)))
        for m in h['members']:self.assertEqual(s.v2.checked_candidate(m['candidate'],'h').key,m['candidate']['key'])

    def test_complete_message_wait_includes_blocked_deserialisation(self):
        release=threading.Event()
        class Partial:
            def recv(self):release.wait();return {'file':'MOCK'}
        start=time.monotonic();box,reader,timely=receive_complete(Partial(),.03)
        self.assertFalse(timely);self.assertTrue(reader.is_alive());self.assertLess(time.monotonic()-start,1.)
        release.set();reader.join(1.);self.assertFalse(reader.is_alive())
        self.assertGreater(box['finished'],box['deadline'])
        RECEIPTS.append({'mock':'partial complete-message delay','budget':.03,'timely':timely,'reader_stopped':True})

    def test_real_spawn_normal_exit_grace(self):
        rows,failure,life=collect(mp.get_context('spawn'),delayed_exit,None,(),(),('MOCK',),30,None,lambda x:None)
        self.assertEqual(rows,[{'file':'MOCK','value':7}]);self.assertIsNone(failure)
        self.assertEqual(life['exitcode'],0);self.assertFalse(life['alive']);self.assertTrue(life['receiver_thread_stopped'])
        self.assertTrue(life['exit_grace_used']);self.assertGreater(life['exit_wait_observed_seconds'],.1)
        self.assertLessEqual(life['instance_receives'][0]['finished'],life['instance_receives'][0]['deadline'])
        RECEIPTS.append({'mock':'real spawn delayed normal exit','lifecycle':life})

    def test_real_T30_timeout_termination_and_receiver_unblocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows,failure,life=collect(mp.get_context('spawn'),silent_worker,tmp,(),(),('MOCK',),30,None,lambda x:None)
            self.assertEqual(rows,[]);self.assertEqual(failure['error_type'],'Timeout')
            self.assertEqual(life['exitcode'],-15);self.assertTrue(life['receiver_thread_stopped'])
            before=s.v2.read(Path(tmp)/'before.json')
            decision=classify(dict(failure,valid=False,fitness=None,instances=[]),before=before,after=None,lifecycle=life,
                expected_identity=before['identity'],expected_files={'mock':'h'},start_files={'mock':'h'},end_files={'mock':'h'})
            self.assertEqual(decision['decision'],'candidate_invalid_continue')
            RECEIPTS.append({'mock':'real spawned no-result 30s timeout; no solves','lifecycle':life,'classification':decision})

    def test_timeout_cleanup_confirmed_and_no_exit_grace(self):
        def timedout(*args):return {'started':0.,'deadline':30.},DoneThread(),False
        rows,failure,life=collect(FakeContext(),None,None,(),(),('MOCK',),30,None,lambda x:None,wait_fn=timedout)
        self.assertEqual(rows,[]);self.assertEqual(failure['error_type'],'Timeout')
        self.assertEqual(life['cleanup'],['join_0.05','terminate']);self.assertEqual(life['exitcode'],-15)
        self.assertFalse(life['exit_grace_used']);self.assertTrue(life['receiver_thread_stopped'])
        result,kw=self.evidence();kw['lifecycle']=life;kw['after']=None
        decision=classify(dict(failure,valid=False,fitness=None,instances=[]),**kw)
        self.assertEqual(decision['decision'],'candidate_invalid_continue')
        with self.assertRaises(ValueError):collect(FakeContext(),None,None,(),(),('MOCK',),15,None,lambda x:None)
        RECEIPTS.append({'mock':'confirmed T30 timeout','lifecycle':life,'classification':decision})

    def test_identity_terminal_reader_and_late_results_stop(self):
        result,kwargs=self.evidence();self.assertEqual(classify(result,**kwargs)['decision'],'accepted')
        for field,value in [('exitcode',-15),('alive',True),('receiver_thread_stopped',False),('pid',999),
                            ('deadline_seconds',15),('all_results_received',False)]:
            kw=deepcopy(kwargs);kw['lifecycle'][field]=value
            with self.subTest(field=field):self.assertEqual(classify(result,**kw)['decision'],'stop')
        kw=deepcopy(kwargs);kw['after']['identity']='wrong';self.assertEqual(classify(result,**kw)['decision'],'stop')
        kw=deepcopy(kwargs);kw['end_files']={};self.assertEqual(classify(result,**kw)['decision'],'stop')
        kw=deepcopy(kwargs);kw['lifecycle']['instance_receives'][0]['finished']=31.
        self.assertEqual(classify(result,**kw)['decision'],'stop')
        kw=deepcopy(kwargs);kw['worker_failure']=True;self.assertEqual(classify(result,**kw)['decision'],'stop')

    def test_guard_negative_events_without_actual_network_or_data_access(self):
        rows,failure,life=collect(mp.get_context('spawn'),guard_mock,None,(),(),('MOCK',),30,None,lambda x:None)
        self.assertIsNone(failure);self.assertEqual(life['exitcode'],0)
        self.assertEqual(rows[0]['simulated_blocked'],{'network_attempts_blocked':1,'nontrain_opens_blocked':1})
        self.assertFalse(any(n in sys.modules for n in ['openai','fjsp_usage.research_real.real_transport']))
        RECEIPTS.append({'mock':'simulated audit events only; no real connect/open','blocked':rows[0]['simulated_blocked']})

    def test_spawn_two_pass_toy_identity_and_frozen_source_detection(self):
        sources=dict(s.v2.read(s.BASE/'Protocol.json')['source_files'])
        for name in s.MODULES:
            p=Path(importlib.import_module(name).__file__).resolve();sources[str(p.relative_to(s.ROOT))]=s.v2.sha(p)
        p={'source_files':sources,'instances':[{'relative_path':'inputs/train/toy.fjsp'}]}
        identity=s.witness(p)['identity']
        with patch('fjsp_usage.baseline_supplemental.validation.compare_historical',lambda *a:None):
            with self.assertRaisesRegex(ValueError,'loaded function mismatch'):s.witness(p)
        members=tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -earliest_finish\n',kind='h') for _ in range(10))
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);spec=specs()[0];folder=d/'evidence'/spec['id'];folder.mkdir(parents=True)
            rows,failure,life=collect(mp.get_context('spawn'),s.worker,{'directory':str(d),'protocol':p,'spec':spec},
                members,(toy(),),('toy.fjsp',),30,None,lambda r:atomic_json(folder/'lifecycle.json',r))
            self.assertIsNone(failure);self.assertEqual(life['exitcode'],0);self.assertEqual(len(rows),1)
            self.assertEqual(s.v2.read(folder/'before.json')['identity'],identity)
            self.assertEqual(s.v2.read(folder/'after.json')['identity'],identity)
            s.validate_result({'valid':True,'total_instances':1,'fitness':rows[0]['score'],'instances':rows},
                [{'file':'toy.fjsp','LB':rows[0]['lower_bound']}],'modern')
            RECEIPTS.append({'mock':'toy worker two passes/identity','lifecycle':life,'identity':identity})

    def test_ledger_reservations_and_no_duplicate_completed_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);atomic_json(d/'Protocol.json',{})
            row=synthetic_row('MOCK');result={'valid':True,'fitness':-1.,'total_instances':1,'instances':[row]}
            atomic_json(d/'result.json',result)
            p={'instances':[{'file':'MOCK','LB':1.}]};state={'protocol_sha256':s.v2.sha(d/'Protocol.json'),'phase':'prepared','strategies':{}}
            self.assertEqual(ledger(state,p,s.v2.read,s.v2.sha,d),0)
            state['phase']='running';id=specs()[0]['id']
            state['strategies'][id]={'status':'reserved','reserved_evaluations':21,'reserved_solve_passes':42}
            with self.assertRaisesRegex(ValueError,'unknown reservation'):ledger(state,p,s.v2.read,s.v2.sha,d)
            state['strategies'][id].update(status='completed',valid=True,result_path='result.json',result_sha256=s.v2.sha(d/'result.json'))
            self.assertEqual(ledger(state,p,s.v2.read,s.v2.sha,d),21)
            broken=deepcopy(state);broken['strategies'][id]['reserved_solve_passes']=40
            with self.assertRaises(ValueError):ledger(broken,p,s.v2.read,s.v2.sha,d)
            for spec in specs()[1:]:state['strategies'][spec['id']]=deepcopy(state['strategies'][id])
            state['phase']='completed';self.assertEqual(ledger(state,p,s.v2.read,s.v2.sha,d),189)
            atomic_json(d/'checkpoint.json',state)
            with patch.object(s,'check',return_value=p),patch.object(s.v2,'load_instance',side_effect=AssertionError('must not load/solve')):
                s.run(d)

    def test_historical_inconsistency_and_null_fitness_rejected(self):
        old={'instances':[{'file':'MOCK','makespan':1,'lower_bound':1.,'score':-1.,'commit_sequence_sha256':'a'}]}
        new={'instances':[dict(old['instances'][0])]}
        compare_historical('H0_H1_WS',new,old)
        new['instances'][0]['makespan']=2
        with self.assertRaisesRegex(ValueError,'scientific mismatch'):compare_historical('H0_H1_WS',new,old)
        row=synthetic_row('MOCK')
        with self.assertRaises(ValueError):s.validate_result({'valid':False,'fitness':-1.,'total_instances':1,'instances':[row]},[{'file':'MOCK','LB':1.}],'modern')


if __name__=='__main__':unittest.main()
