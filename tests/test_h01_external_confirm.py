from copy import deepcopy
from dataclasses import asdict
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import h01_external_data as d
from tools import h01_external_confirm as c
from tools import ind_evo_h01 as old
from tests.test_baseline_supplemental import T30Tests

TOY = '2 2 2 2 0 2 1 3 1 1 4 2 1 0 3 2 0 2 1 1'


class Tests(unittest.TestCase):
    def setUp(self):
        guard=patch('socket.socket.connect',side_effect=AssertionError('offline no network'))
        guard.start();self.addCleanup(guard.stop)

    def test_zero_based_conversion_and_independent_LB(self):
        problem=d.parse_text(TOY);self.assertEqual(d.independent_lb(problem),6.)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'isolated_toy.fjsp';path.write_text(d.serialize(problem,'toy'))
            loaded=old.certified.s.v2.load_instance(path)
            self.assertEqual(d.from_instance(loaded),problem)
            self.assertEqual(old.certified.s.v2.lower_bound_v5(loaded),6.)

    def test_reject_duplicate_machine_and_bad_time(self):
        for raw in ('1 1 1 2 0 1 0 2','1 1 1 1 1 2','1 1 1 1 0 0','1 1 1 1 0 1 99'):
            with self.assertRaises((ValueError,IndexError)):d.parse_text(raw)

    def test_json_machine_numbering_same(self):
        value={'machines':2,'jobs':[[[{'machine':1,'processing':3},{'machine':0,'processing':2}]]]}
        self.assertEqual(d.from_json(value),d.parse_text('1 2 1 2 0 2 1 3'))

    def test_job_permutation_and_machine_label_invariants(self):
        problem=d.parse_text(TOY);swapped=(2,tuple(reversed(problem[1])))
        self.assertNotEqual(d.identities(problem)['ordered_content'],d.identities(swapped)['ordered_content'])
        self.assertEqual(d.identities(problem)['job_permutation_content'],d.identities(swapped)['job_permutation_content'])
        remap=(2,tuple(tuple(tuple(sorted((1-m,p) for m,p in op)) for op in job) for job in problem[1]))
        self.assertEqual(d.identities(problem)['machine_label_free_conservative'],d.identities(remap)['machine_label_free_conservative'])

    def test_fixed_strata_seed_and_no_shortfall_refill(self):
        rows=[{'source_path':f'{s}/{i:02d}','eligible':True,'stratum':s} for s in range(3) for i in range(10)]
        self.assertEqual(d.select(rows),d.select(list(reversed(rows))))
        self.assertEqual([sum(r['stratum']==s for r in d.select(rows)) for s in range(3)],[7,7,6])
        self.assertEqual(len(d.select([r for r in rows if r['stratum']!=2])),14)

    def test_exact_40_tasks_and_alternating_order(self):
        rows=[{'file':f'TOY{i}'} for i in range(20)];tasks=c.tasks(rows)
        self.assertEqual(len(tasks),40);self.assertEqual(len({r['task_id'] for r in tasks}),40)
        self.assertEqual([r['policy'] for r in tasks[:4]],['dynamic','equal','equal','dynamic'])

    def test_deadline_reserve(self):
        self.assertTrue(c.enough_time(10,100));self.assertFalse(c.enough_time(10.001,100))

    def test_frozen_policy_keys_and_H01_complement(self):
        s=old.read(old.RUN/'checkpoint.json');candidate=s['tasks']['r2_EVO_s16']['candidate']
        self.assertEqual(candidate['key'],'f5992550e506d4708c21b06595ecaa451095f5bf0d83ff9220cd9a88dc4bf215')
        equal=next(r for r in old.read(old.RUN/'P0.json') if r['id']=='MANUAL/init/alpha_050')['candidate']
        fn=old.certified.compile_candidate(old.checked_candidate(equal,'U'))
        self.assertEqual(fn(.25,.3,.2,.1,.1,.01,-1),(1,(.5,.5,0,0,0,0,0,0,0,0)))

    def test_classification_keeps_timeout_invalid_and_unknown_stop(self):
        result,kw=T30Tests().evidence()
        self.assertEqual(old.certified.certify(result,kw)['decision'],'accepted')
        bad=deepcopy(kw);bad['lifecycle']['alive']=True
        self.assertEqual(old.certified.certify(result,bad)['decision'],'stop')
        timed={'valid':False,'fitness':None,'instances':[],'error_type':'Timeout','error':'complete-instance result deadline exceeded','failed_instance':'MOCK'}
        kw['lifecycle'].update(rows_received=0,trigger='parent_complete_result_timeout',exitcode=-15,
            exit_grace_used=False,all_results_received=False,cleanup=['join_0.05','terminate'])
        self.assertEqual(old.certified.certify(timed,kw)['decision'],'candidate_invalid_continue')
        kw['lifecycle']['receiver_thread_stopped']=False
        self.assertEqual(old.certified.certify(timed,kw)['decision'],'stop')

    def test_two_policy_per_instance_certified_worker_toy_regression(self):
        binding=old.read(old.RUN/'Protocol.json');expected={**binding['source_files'],**binding['protected_files']}
        s=old.read(old.RUN/'checkpoint.json');dynamic=s['tasks']['r2_EVO_s16']['candidate']
        equal=next(r for r in old.read(old.RUN/'P0.json') if r['id']=='MANUAL/init/alpha_050')['candidate']
        members=tuple(old.checked_candidate(r['candidate'],'h') for r in old.read(old.RUN/'H_frozen.json')['members'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'isolated_toy.fjsp';path.write_text(d.serialize(d.parse_text(TOY),'toy'))
            instance=old.certified.s.v2.load_instance(path)
            for name,value in [('dynamic',dynamic),('equal',equal)]:
                folder=root/name;folder.mkdir();candidate=old.checked_candidate(value,'U')
                payload={'folder':str(folder),'binding':binding,'candidate':asdict(candidate),'train_paths':[str(path)]}
                rows,failure,life=old.certified.collect(mp.get_context('spawn'),old.certified.worker,payload,members,[instance],[path.name],30,(1,),lambda r:None)
                self.assertIsNone(failure);self.assertEqual(len(rows),1);self.assertEqual(life['exitcode'],0)
                result={'valid':True,'fitness':rows[0]['score'],'instances':rows,'total_instances':1}
                boundary=old.certified.certify(result,dict(before=old.read(folder/'before.json'),after=old.read(folder/'after.json'),
                    lifecycle=life,expected_identity=old.certified.witness(binding)['identity'],expected_files=expected,start_files=expected,end_files=expected,worker_failure=False))
                self.assertEqual(boundary['decision'],'accepted')
                old.validate_result(result,[{'file':path.name,'LB':6.}],'modern')
                direct=old.certified.construct_usage_schedule(instance,tuple(old.certified.compile_candidate(h) for h in members),old.certified.compile_candidate(candidate))
                self.assertEqual(direct.schedule.makespan,rows[0]['makespan'])
                self.assertEqual(direct.score,rows[0]['score'])


if __name__=='__main__': unittest.main()
