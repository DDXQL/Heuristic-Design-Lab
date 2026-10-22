"""Recovery acceptance: synthetic replies/results only; no API/FJSP/data load."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop
from tools import b1_ns_recovery as recovery
from tools import b1_nonstream_local as ns
import test_b1_nonstream_local as ns_fixture
from test_b1_nonstream_local import mock_code


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        fixture = ns_fixture.NSTests(methodName='runTest'); fixture.setUp()
        self.addCleanup(fixture.doCleanups); self.fixture = fixture
        self.directory = fixture.path / 'recovery'; self.directory.mkdir()
        fixture.inner.answers = ['bad', mock_code(0), mock_code(1), 'bad', 'bad', mock_code(2)]
        def evaluate(candidate):
            physical = {'makespan':100, 'operations': []}  # SYNTHETIC; never a real schedule
            row = {'makespan':100,'lower_bound':10,'score':-10.0,'feasible':True,
                'deterministic_schedule_sha256':'MOCK-full', 'physical_schedule_sha256':digest(physical),
                'recheck_physical_schedule_sha256':digest(physical),'commit_sequence_sha256':'MOCK-commit',
                'captured_solves':2,'physical_schedule':physical}
            return {'valid':True,'fitness':-10.0,'total_instances':21,
                'instances':[dict(row,file=n) for n in fixture.names]}
        self.source = fixture.engine(evaluator=evaluate)
        self.source.initialize(stop_after_attempts=6)
        self.assertEqual(self.source.state['init_cursor'],6)
        inherited = self.directory / 'inherited/r501/B'; inherited.mkdir(parents=True)
        for name in ('checkpoint.json','batch_requests.json'):
            shutil.copyfile(self.source.directory/name,inherited/name)
        for folder in ('wire_responses','received_responses','send_times','r501/B/prompts'):
            (self.directory/'inherited'/folder).mkdir(parents=True,exist_ok=True)
        self.p = {'train_names':list(fixture.names),'H_order':[m.key for m in fixture.members],
            'revalidation_ids':list(recovery.CANDIDATES),'request_phase':ns.NSSearch.request_phase,
            'origin_files':{'r501/B/batch_requests.json':ns.sha(inherited/'batch_requests.json')},
            'comparison_fields':['makespan','lower_bound','score','feasible','deterministic_schedule_sha256',
                'physical_schedule_sha256','recheck_physical_schedule_sha256','commit_sequence_sha256','captured_solves']}
        atomic_json(self.directory/'Protocol.json',self.p)
        self.calls=[]
        self.by_key={r['candidate']['key']:r['id'] for r in self.source.state['population']}

    def recheck(self,candidate):
        self.calls.append(candidate.key)
        result=deepcopy(self.source.state['evaluations'][self.by_key[candidate.key]]['result'])
        evidence={'modules':{'synthetic_mock_only':True},'identity':digest({'synthetic_mock_only':True})}
        before=self.directory/'worker_evidence'/(candidate.key+'.before.json')
        after=self.directory/'worker_evidence'/(candidate.key+'.after.json')
        atomic_json(before,evidence);atomic_json(after,evidence)
        result['worker_identity']={'before_sha256':ns.sha(before),'after_sha256':ns.sha(after),'loaded_identity':evidence['identity']}
        return result

    def ready(self):
        return recovery.revalidate_saved(self.directory,self.p,self.recheck)

    def migrated_engine(self):
        f=self.fixture
        return ns.NSSearch(self.directory/'r501/B',experiment=f.config,training_names=f.names,
            arm='B',config=f.config.u_search(501),members=f.members,evaluator=f.evaluator,
            transport=f.transport,context=ns.sha(self.directory/'Protocol.json'))

    def test_three_rechecks_then_ready_old_results_unchanged(self):
        before=recovery.input_manifest(self.directory/'inherited')
        result=self.ready();self.assertTrue(result['ready']);self.assertEqual(len(self.calls),3)
        self.assertEqual(recovery.input_manifest(self.directory/'inherited'),before)
        self.assertEqual(len(self.fixture.inner.sent),6)

    def test_completed_rechecks_not_repeated_after_restart(self):
        self.ready();self.ready();self.assertEqual(len(self.calls),3)

    def test_saved_worker_evidence_change_stops_resume(self):
        self.ready()
        evidence=next((self.directory/'worker_evidence').glob('*.after.json'))
        evidence.write_text('{}')
        with self.assertRaises(ValueError):self.ready()
        self.assertEqual(len(self.calls),3)

    def test_failed_recheck_stops_before_other_candidates_and_cannot_repeat(self):
        def failed(c):
            value=self.recheck(c);value['instances'][0]['physical_schedule_sha256']='CHANGED';return value
        with self.assertRaises(BudgetStop):recovery.revalidate_saved(self.directory,self.p,failed)
        saved=ns.read(self.directory/'Revalidation.json')
        self.assertFalse(saved['ready']);self.assertEqual(len(saved['rows']),1)
        self.assertIn('result',next(iter(saved['rows'].values())))
        with self.assertRaises(BudgetStop):self.ready()
        self.assertEqual(len(self.calls),1)

    def test_interrupted_recheck_pending_is_not_repeated(self):
        with self.assertRaises(KeyboardInterrupt):
            recovery.revalidate_saved(self.directory,self.p,lambda c:(_ for _ in ()).throw(KeyboardInterrupt()))
        with self.assertRaises(BudgetStop):self.ready()
        self.assertEqual(self.calls,[])

    def test_incomplete_result_never_ready(self):
        def incomplete(c):
            value=self.recheck(c);value['instances'].pop();return value
        with self.assertRaises(BudgetStop):recovery.revalidate_saved(self.directory,self.p,incomplete)
        self.assertFalse(ns.read(self.directory/'Revalidation.json')['ready'])

    def test_full_result_failure_and_missing_worker_evidence_stop(self):
        old=next(iter(self.source.state['evaluations'].values()))['result']
        with self.assertRaises(ValueError):recovery.compare_results(old,deepcopy(old),self.p)
        failed={'valid':False,'fitness':None,'total_instances':21,'instances':[],'worker_identity':{'mock':True}}
        with self.assertRaises(ValueError):recovery.compare_results(old,failed,self.p)

    def test_native_result_saved_before_missing_identity_stops_acceptance(self):
        candidate=next(iter(self.source.members))
        raw=deepcopy(next(iter(self.source.state['evaluations'].values()))['result'])
        fake_data=SimpleNamespace(metadata={'synthetic':True},load=lambda split:[None]*21,verify=lambda split:None)
        p={**self.p,'dataset':fake_data.metadata}
        with patch.object(ns.b1.b2,'data_and_h',return_value=(fake_data,{},self.fixture.members)), \
                patch.object(recovery,'check',return_value=p), \
                patch('fjsp_usage.research_real.runtime.evaluate',return_value=raw):
            evaluate,_=recovery.evaluator(self.directory,p,self.fixture.config)
            with self.assertRaises(BudgetStop):evaluate(candidate)
        self.assertEqual(ns.read(self.directory/'evaluation_receipts'/(candidate.key+'.json')),raw)
        self.assertTrue((self.directory/'Identity_stop.json').exists())

    def test_install_before_ready_refused(self):
        atomic_json(self.directory/'Revalidation.json',{'ready':False,'rows':{}})
        with self.assertRaises(BudgetStop):recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        self.assertFalse((self.directory/'r501/B/checkpoint.json').exists())

    def test_inherit_six_records_rng_seen_and_never_resend_them(self):
        self.ready();recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        new=self.migrated_engine()
        self.assertEqual((new.ledger.calls,new.ledger.attempt_count),(6,6))
        self.assertEqual(new.state['seen'],self.source.state['seen'])
        self.assertEqual(new.state['rng'],json.loads(json.dumps(self.source.state['rng'])))
        self.assertEqual(new.state['init_cursor'],6);self.assertEqual(len(new.state['population']),3)
        for ident,r in self.source.ledger.data['requests'].items():
            self.assertEqual(new.ledger.request(ident,r['prompt']),r)
        self.assertEqual(len(self.fixture.inner.sent),6)
        new.initialize(stop_after_attempts=1)
        self.assertEqual(new.state['init_cursor'],7)
        self.assertEqual(self.migrated_engine().ledger.attempt_count,7)
        # Calling install again MUST NOT replace the progressed checkpoint or ledger.
        recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        self.assertEqual(self.migrated_engine().ledger.attempt_count,7)

    def test_interrupted_two_file_migration_finishes_without_reset(self):
        self.ready();original=recovery.atomic_json
        def interrupt(path,value):
            if Path(path)==self.directory/'r501/B/batch_requests.json':raise KeyboardInterrupt()
            original(path,value)
        with patch.object(recovery,'atomic_json',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        self.assertEqual(self.migrated_engine().ledger.attempt_count,6)

    def test_inherited_six_count_toward_forty_logical_cap(self):
        self.ready();recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        new=self.migrated_engine()
        for i in range(34):new.ledger.request('MOCK-extra/'+str(i),'SYNTHETIC '+str(i))
        self.assertEqual(new.ledger.calls,40)
        with self.assertRaises(BudgetStop):new.ledger.request('MOCK-extra/34','SYNTHETIC 34')
        self.assertEqual(len(self.fixture.inner.sent),40)

    def test_inherited_six_count_toward_sixty_api_attempts(self):
        self.ready();recovery.install_progress(self.directory,self.p,self.fixture.config,self.fixture.transport)
        new=self.migrated_engine();new.ledger.sleep=lambda seconds:None
        for i in range(18):
            self.fixture.inner.answers=[TimeoutError('MOCK'),TimeoutError('MOCK'),mock_code(i+10)]
            new.ledger.request('MOCK-retry/'+str(i),'SYNTHETIC '+str(i))
        self.assertEqual(new.ledger.attempt_count,60)
        self.assertTrue(all(len(r['attempt_ids'])<=3 for r in new.ledger.data['requests'].values()))
        with self.assertRaises(BudgetStop):new.ledger.request('MOCK-next','SYNTHETIC next')
        self.assertEqual(self.migrated_engine().ledger.attempt_count,60)

    def test_old_authorization_not_accepted_and_no_provider_or_evaluation(self):
        with patch.object(recovery,'check',side_effect=AssertionError('no asset reads before approval')):
            for stage in ('revalidate','continue'):
                with self.assertRaises(BudgetStop):recovery.require_execution(self.directory,stage)
        atomic_json(self.directory/'continue.Authorization.json',{'approved':True,'stage':'B1-NS'})
        with self.assertRaises(BudgetStop):recovery.require_execution(self.directory,'continue')

    def test_continue_without_revalidation_cannot_read_key_or_construct_evaluator(self):
        p={**self.p,'config':self.fixture.config.payload()}
        with patch.object(recovery,'require_execution',return_value=p), \
                patch.object(recovery,'evaluator',side_effect=AssertionError('must not construct evaluator')):
            with self.assertRaisesRegex(BudgetStop,'revalidation not ready'):
                recovery.execute(self.directory,'continue')

    def test_approved_stage_still_cannot_execute_from_shared_workspace(self):
        atomic_json(self.directory/'revalidate.Authorization.json',recovery.approval(self.directory,'revalidate',True))
        with patch.object(recovery,'check',return_value={'source_snapshot':str(self.directory/'mock-snapshot')}):
            with self.assertRaisesRegex(BudgetStop,'isolated source snapshot'):
                recovery.require_execution(self.directory,'revalidate')

    def test_loaded_function_identity_detects_live_code_difference(self):
        # Actual code identity, not a mocked disk hash or a real FJSP solve.
        namespace={};exec('def a(x):\n return x+1\ndef b(x):\n return x+2\n',namespace)
        a,b=namespace['a'],namespace['b']
        self.assertNotEqual(recovery.code_identity(a.__code__),recovery.code_identity(b.__code__))
        compiled=compile('def a(x):\n return x+1\n','MOCK','exec')
        code=next(x for x in compiled.co_consts if hasattr(x,'co_code'))
        self.assertEqual(recovery.code_identity(a.__code__),recovery.code_identity(code))

    def test_attestation_rejects_changed_loaded_code_even_if_disk_hash_matches(self):
        p={'source_snapshot':str(recovery.ROOT),'critical_modules':['tools.b1_ns_recovery'],
           'snapshot_files':{'tools/b1_ns_recovery.py':ns.sha(Path(recovery.__file__))}}
        def changed(*args):return 'SYNTHETIC CHANGED CODE'
        original=recovery.approval.__code__
        recovery.approval.__code__=changed.__code__
        try:
            with self.assertRaisesRegex(ValueError,'loaded function/source differs'):
                recovery.source_attestation(p)
        finally:recovery.approval.__code__=original

    def test_worker_records_before_after_without_any_fjsp_execution(self):
        class Pipe:
            def __init__(self):self.rows=[];self.closed=False
            def send(self,row):self.rows.append(row)
            def close(self):self.closed=True
        def mock_worker(pipe,*args):
            for name in args[3]:pipe.send({'file':name,'SYNTHETIC_ONLY':True})
            pipe.close()
        pipe=Pipe();identity={'identity':'MOCK-LOADED-SOURCE','modules':{},'synthetic_only':True}
        with patch.dict('os.environ',{'B1_NS_RECOVERY_RUN':str(self.directory),'B1_NS_RECOVERY_CANDIDATE':'MOCK'}), \
                patch.object(recovery,'source_attestation',return_value=identity), \
                patch('tools.usage_mechanism_ablation.schedule_recording_worker',side_effect=mock_worker):
            recovery.identity_worker(pipe,None,None,None,['MOCK_A','MOCK_B'],None)
        self.assertEqual(len(pipe.rows),2);self.assertTrue(pipe.closed)
        self.assertEqual(ns.read(self.directory/'worker_evidence/MOCK.before.json'),identity)
        self.assertEqual(ns.read(self.directory/'worker_evidence/MOCK.after.json'),identity)

    def test_worker_identity_change_is_reported_not_silently_accepted(self):
        class Pipe:
            rows=[]
            def send(self,row):self.rows.append(row)
            def close(self):pass
        def mock_worker(pipe,*args):pipe.send({'file':'MOCK_LAST'})
        pipe=Pipe()
        with patch.dict('os.environ',{'B1_NS_RECOVERY_RUN':str(self.directory),'B1_NS_RECOVERY_CANDIDATE':'MOCK-CHANGED'}), \
                patch.object(recovery,'source_attestation',side_effect=[{'identity':'BEFORE'},{'identity':'CHANGED'}]), \
                patch('tools.usage_mechanism_ablation.schedule_recording_worker',side_effect=mock_worker):
            recovery.identity_worker(pipe,None,None,None,['MOCK_LAST'],None)
        self.assertEqual(pipe.rows[0]['error_type'],'SourceIdentityError')
        self.assertTrue((self.directory/'worker_evidence/MOCK-CHANGED.failure.json').exists())

    def test_frozen_wrapper_cannot_be_excluded(self):
        p=ns.read(ns.DEFAULT/'Protocol.json')
        self.assertIn('tools/usage_mechanism_ablation.py',p['pins'])
        with patch.object(recovery,'sha',return_value='0'*64):
            with self.assertRaises(ValueError):recovery.verify_files(recovery.ROOT,{'tools/usage_mechanism_ablation.py':p['pins']['tools/usage_mechanism_ablation.py']})


if __name__=='__main__':unittest.main()
