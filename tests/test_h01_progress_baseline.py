"""No train solves/API: synthetic lifecycle, pure outputs and toy schedules."""
from copy import deepcopy
from dataclasses import asdict
import math
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import h01_progress_baseline as b
from fjsp_usage.usage_v2.execution import decode_output, combine_scores, construct_usage_schedule
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule
from fjsp_usage.baseline_a.policies import policy
from fjsp_usage.offline_v2 import _SchedulingState
from fjsp_usage.research.candidates import validate_code, H_ARGS
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation


def toy():
    return FJSPInstance('progress-step-toy',2,(
        (Operation(((0,2),(1,3))), Operation(((0,5),(1,6)))), (Operation(((0,4),)),)))


class RuleTests(unittest.TestCase):
    def test_family_and_aliases(self):
        rs=b.rules(); aliases=b.aliases()
        self.assertEqual(len(rs),21); self.assertEqual(sum(r['dynamic'] for r in rs),18)
        self.assertEqual(len({r['candidate']['key'] for r in rs}),21)
        self.assertEqual(len(aliases),27); self.assertEqual(len({r['canonical_id'] for r in aliases}),21)
        self.assertEqual([r['id'] for r in rs], [r['id'] for r in b.rules()])

    def test_boundaries_weight_direction_and_legal_endpoints(self):
        for r in b.rules():
            u=b.compile_candidate(b.checked_candidate(r['candidate'],'U'))
            points=[0., .25, .5, .75, .999]
            if r['dynamic']: points += [math.nextafter(r['tau'],0.),r['tau'],math.nextafter(r['tau'],1.)]
            for p in points:
                output=u(p,.1,.2,.1,.2,.1,-1)
                a=r['alpha_before'] if not r['dynamic'] or p<r['tau'] else r['alpha_after']
                self.assertEqual(output,(1,(a,1-a,0,0,0,0,0,0,0,0)))
                d=decode_output(output,10); self.assertEqual(d['weights'][:2],(a,1-a))
                self.assertEqual(sum(d['weights']),1.)
                self.assertEqual(d['support'],(1,) if a==0 else (0,) if a==1 else (0,1))

    def test_progress_is_committed_operation_fraction(self):
        state=_SchedulingState(toy()); self.assertEqual(state.features().progress,0.)
        from llm4ad.task.optimization.fjsp_set.scheduler import ScheduledOperation
        state.scheduled.append(ScheduledOperation(0,0,0,0,999))
        state.cursors[0]=1
        self.assertEqual(state.features().progress,1/3)

    def test_static_endpoints_and_equal_v1_regression(self):
        hs=[lambda p,w,n,j,m,s,e:-e,lambda p,w,n,j,m,s,e:w-p]+[lambda *a:0.]*8
        for r in b.rules()[:3]:
            a=r['alpha_before'];u=b.compile_candidate(b.checked_candidate(r['candidate'],'U'))
            first=construct_usage_schedule(toy(),hs,u); second=construct_usage_schedule(toy(),hs,u)
            self.assertEqual(first,second)
            spec={'id':'H0_H1_WS','category':'A2','members':[0,1]} if a==.5 else {'id':'H'+str(0 if a==1 else 1),'category':'A1','members':[0 if a==1 else 1]}
            old=construct_fusion_schedule(toy(),hs,policy(spec))
            self.assertEqual(first.schedule,old.schedule); self.assertEqual(first.score,old.score)
        x,extra=combine_scores({0:(-3.,0.,3.),1:(50.,0.,25.)},(.5,.5)+(0.,)*8,(0,1))
        self.assertEqual(x,(.5,.25,.75))
        tied=construct_usage_schedule(toy(),[lambda *a:0.]*10,lambda *a:(1,(.5,.5)+(0.,)*8))
        self.assertEqual((tied.schedule.operations[0].job,tied.schedule.operations[0].machine),(0,0))

    def test_actual_worker_observation_is_passive(self):
        hs=[lambda p,w,n,j,m,s,e:-e,lambda p,w,n,j,m,s,e:w-p]+[lambda *a:0.]*8
        for r in b.rules()[3:]:
            u=b.compile_candidate(b.checked_candidate(r['candidate'],'U')); seen=[]
            def observed(*args):
                out=u(*args);seen.append([args[0],out[1][0],out[1][1]]);return out
            a=construct_usage_schedule(toy(),hs,u); c=construct_usage_schedule(toy(),hs,observed)
            self.assertEqual(a,c); self.assertEqual([x[0] for x in seen],[0,1/3,2/3])

    def test_unknown_reservation_budget_and_identity_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(b,'RUN',Path(tmp)), patch.object(b,'sha',lambda p:'x'):
            p={'rule_ids':['x'],'cache':{},'instances':[],'effective_new_evaluation_cap':399}
            state={'protocol_sha256':'x','strategies':{'x':{'status':'reserved'}}}
            with self.assertRaisesRegex(ValueError,'unknown reservation'): b.ledger(state,p)
            state['strategies']['x'].update(status='completed',reserved_instances=20,reserved_solves=42)
            with self.assertRaisesRegex(ValueError,'budget ledger'): b.ledger(state,p)
            state['protocol_sha256']='wrong'
            with self.assertRaisesRegex(ValueError,'checkpoint protocol'): b.ledger(state,p)

    def test_new_worker_identity_observation_and_normal_exit(self):
        origin=b.read(b.old.DEFAULT/'Protocol.json')
        p={'source_files':{**origin['source_files'],**{n:b.sha(b.ROOT/n) for n in b.EXTRA}}}
        hs=tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -'+H_ARGS[-1]+'\n',kind='h') for _ in range(10))
        spec=b.rules()[3];expected=b.witness(p)['identity']
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            rows,failure,life=b.collect(mp.get_context('spawn'),b.worker,
                {'protocol':p,'spec':spec,'folder':tmp,'train_paths':[]},hs,(toy(),),('toy.fjsp',),30,(0,1),lambda x:None)
            self.assertIsNone(failure); self.assertEqual(life['exitcode'],0)
            self.assertTrue(life['receiver_thread_stopped']);self.assertEqual(len(rows),1)
            row=rows[0];self.assertEqual(row['before_steps'],1);self.assertEqual(row['after_steps'],2)
            self.assertEqual(row['actual_weight_changes'],1)
            self.assertEqual(row['progress_weights_sha256'],row['recheck_progress_weights_sha256'])
            result={'valid':True,'fitness':row['score'],'instances':rows,'total_instances':1}
            kwargs=dict(before=b.read(folder/'before.json'),after=b.read(folder/'after.json'),lifecycle=life,
                expected_identity=expected,expected_files=p['source_files'],start_files=p['source_files'],end_files=p['source_files'])
            self.assertEqual(b.classify(result,**kwargs)['decision'],'accepted')
            b.validate_result(result,[{'file':'toy.fjsp','LB':row['lower_bound']}],'modern')

    def test_detached_launcher_keeps_files_and_no_implicit_relaunch(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp, patch.object(b,'RUN',Path(tmp)),patch.object(b,'check',lambda:None),patch.object(b.subprocess,'Popen',return_value=Mock(pid=123)) as popen:
            b.launch();self.assertTrue(popen.call_args.kwargs['start_new_session'])
            self.assertTrue(popen.call_args.kwargs['close_fds'])
            self.assertTrue((Path(tmp)/'Launch_identity.json').exists())
            with self.assertRaisesRegex(ValueError,'already started/unknown'):b.launch()


# Reuse only relevant existing synthetic tests (including real 30s silent process,
# no solver): complete-message deadline, normal exit grace, timeout termination,
# unknown identity/exit stops and no prefix Fitness. No formal run is imported.
def load_tests(loader, tests, pattern):
    from tests import test_baseline_supplemental as lifecycle
    suite=unittest.TestSuite([tests])
    for name in ('test_complete_message_wait_includes_blocked_deserialisation',
                 'test_real_spawn_normal_exit_grace',
                 'test_real_T30_timeout_termination_and_receiver_unblocks',
                 'test_timeout_cleanup_confirmed_and_no_exit_grace',
                 'test_identity_terminal_reader_and_late_results_stop',
                 'test_guard_negative_events_without_actual_network_or_data_access'):
        suite.addTest(lifecycle.T30Tests(name))
    return suite
