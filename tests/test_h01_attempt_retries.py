"""B2-0.1 hand-written responses/scores ONLY. No network or FJSP solving."""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import Candidate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.attempt_budget import AttemptJournal, failure_policy, VERSION
from fjsp_usage.research_real.budget import BudgetStop, BudgetLedger
from fjsp_usage.research_real.real_transport import TransportError, network_failure_metadata
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.usage_v2.access import WireRecorder
from tools import h01_weight_local as local
from tools import h01_weight_search as old


def fault(status=None,code=None,message='UNIT temporary service failure'):
    e=TransportError(message);e.metadata={'http_status':status,'error_code':code};return e


class Inner:
    identity='MOCK-ONLY-WIRE';secret='';redact=staticmethod(str)
    def __init__(self,config,outcomes):self.config=config;self.outcomes=list(outcomes);self.sent=[]
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind='U',on_sent):
        self.sent.append((key,prompt));on_sent()
        answer=self.outcomes.pop(0) if self.outcomes else {'text':'UNIT complete response','usage':None}
        if isinstance(answer,BaseException):raise answer
        return answer


class AttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.sleep_calls=[]
        original=old.common.read(local.LEGACY/'config.pending.json')
        b20=old.common.read(local.DEFAULT/'config.pending.json')
        self.config=local.Config.from_dict({**b20,'experiment_version':local.BATCH_VERSION,
            'request_budget':dict(local.BATCH_POLICY),'real_requests_authorized':True})
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect','tools.h01_weight_local.audit_peer',
                     'tools.h01_weight_local.request_history','fjsp_usage.research_real.budget.request_history',
                     'fjsp_usage.usage_v2.registration.inventory','fjsp_usage.usage_v2.registration.worktree_roots',
                     'fjsp_usage.research_real.leafapi.query_status','fjsp_usage.usage_v2.billing.query_invoices',
                     'fjsp_usage.usage_v2.model_migration.check_live_tariff',
                     'fjsp_usage.research_real.conditional_research.history_summary',
                     'fjsp_usage.research_real.runtime.evaluate','tools.h01_weight_search.evaluate_weight',
                     'fjsp_usage.research_real.staged_evaluation.StagedDataset.load'):
            self.stack.enter_context(patch(name,side_effect=AssertionError('NO NETWORK, HISTORY GATE OR FJSP EVALUATION')))
        self.assertEqual(local.science(self.config.payload()),local.science(original))

    def journal(self,outcomes=(),directory=None):
        directory=directory or self.root
        inner=Inner(self.config,outcomes)
        wire=WireRecorder(inner,directory/'wire_responses')
        j=AttemptJournal(directory/'requests.json',config=self.config,context='UNIT',phase='r501/B',
                         transport=wire,sleep=lambda s:self.sleep_calls.append(s))
        return j,inner

    def test_first_success_and_accepted_response_never_resends(self):
        j,i=self.journal([{'text':'UNIT first','usage':{'input_tokens':2,'output_tokens':3},'metadata':{'id':'provider-unit'}}])
        r=j.request('B/g0000/000000','UNIT prompt')
        self.assertEqual(r['text'],'UNIT first');self.assertEqual(j.attempt_count,1)
        self.assertTrue(r['response_id'].endswith('/attempt/01/response'))
        self.assertEqual(r['response_metadata']['id'],'provider-unit')
        j.request('B/g0000/000000','UNIT prompt');self.assertEqual(len(i.sent),1)
        self.assertFalse(self.sleep_calls)

    def test_timeout_then_success_same_logical_prompt_and_backoff(self):
        j,i=self.journal([TimeoutError('UNIT timeout'),{'text':'UNIT retry success','usage':None}])
        r=j.request('B/g0000/000000','UNIT unchanged prompt')
        self.assertEqual(r['status'],'completed');self.assertEqual(len(i.sent),2)
        self.assertEqual({p for _,p in i.sent},{'UNIT unchanged prompt'})
        self.assertEqual([a['number'] for a in j.data['api_attempts'].values()],[1,2])
        self.assertGreater(self.sleep_calls[0],1)

    def test_three_connection_failures_then_next_candidate(self):
        j,i=self.journal([ConnectionError('UNIT disconnected') for _ in range(3)])
        r=j.request('c0','p');self.assertEqual(r['status'],'failed');self.assertEqual(len(i.sent),3)
        j.request('c0','p');self.assertEqual(len(i.sent),3)
        self.assertEqual(j.request('c1','p')['status'],'completed');self.assertEqual(len(i.sent),4)

    def test_temporary_http_allowlist(self):
        for status in (429,502,503,504):
            with self.subTest(status=status):
                d=self.root/str(status);d.mkdir();j,i=self.journal([fault(status),{'text':'UNIT','usage':None}],d)
                self.assertEqual(j.request('c','p')['status'],'completed');self.assertEqual(len(i.sent),2)

    def test_auth_quota_model_and_parameter_failures_not_retried(self):
        for status,code in [(401,'invalid_api_key'),(429,'insufficient_quota'),(404,'model_not_found'),(400,'invalid_parameter')]:
            with self.subTest(status=status):
                d=self.root/str(status);d.mkdir();j,i=self.journal([fault(status,code)],d)
                self.assertEqual(j.request('c','p')['status'],'failed');self.assertEqual(len(i.sent),1)
                with self.assertRaises(BudgetStop):j.request('next','p')

    def test_thirty_attempts_exhaust_before_twenty_candidates(self):
        j,i=self.journal([TimeoutError('UNIT') for _ in range(30)])
        for n in range(10):self.assertEqual(j.request(str(n),'p')['status'],'failed')
        with self.assertRaises(BudgetStop):j.request('11','p')
        self.assertEqual((j.calls,j.attempt_count,len(i.sent)),(10,30,30))
        resumed,inner=self.journal()
        with self.assertRaises(BudgetStop):resumed.request('11','p')
        self.assertEqual((resumed.attempt_count,len(inner.sent)),(30,0))

    def test_twenty_logical_cap_no_extra_even_if_api_budget_remains(self):
        j,i=self.journal()
        for n in range(20):j.request(str(n),'p')
        with self.assertRaises(BudgetStop):j.request('extra','p')
        self.assertEqual((j.calls,j.attempt_count),(20,20))

    def test_unknown_send_restart_counts_attempt_and_resumes_within_cap(self):
        j,i=self.journal([KeyboardInterrupt('UNIT abrupt interruption')])
        with self.assertRaises(KeyboardInterrupt):j.request('c','p')
        self.assertEqual(j.attempt_count,1)
        j2,i2=self.journal([{'text':'UNIT second attempt','usage':None}])
        self.assertEqual(j2.request('c','p')['status'],'completed')
        self.assertEqual(j2.attempt_count,2);self.assertEqual(len(i2.sent),1)
        self.assertEqual(list(j2.data['api_attempts'].values())[0]['status'],'interrupted_unknown')

    def test_complete_wire_saved_before_journal_acceptance_is_recovered(self):
        j,i=self.journal([{'text':'UNIT first complete persisted reply','usage':None}])
        with patch.object(j,'_accept',side_effect=KeyboardInterrupt('UNIT crash after full wire save')):
            with self.assertRaises(KeyboardInterrupt):j.request('c','p')
        j2,i2=self.journal([{'text':'MUST NEVER REQUEST THIS','usage':None}])
        self.assertEqual(j2.request('c','p')['text'],'UNIT first complete persisted reply')
        self.assertEqual((j2.attempt_count,len(i2.sent)),(1,0))

    def test_pre_dispatch_orphan_is_charged_and_not_reused(self):
        j,i=self.journal()
        with patch.object(j.transport,'dispatch',side_effect=KeyboardInterrupt('UNIT crash before wire journal')):
            with self.assertRaises(KeyboardInterrupt):j.request('c','p')
        self.assertEqual(len(i.sent),0)
        j2,i2=self.journal()
        self.assertEqual(j2.request('c','p')['status'],'completed')
        self.assertEqual(j2.attempt_count,2);self.assertTrue(i2.sent[0][0].endswith('/attempt/02'))
        self.assertIsNone(j2.data['requests']['c']['elapsed_seconds'])

    def test_explicit_transient_failure_before_checkpoint_survives_restart(self):
        j,i=self.journal([TimeoutError('UNIT known timeout')])
        def crash_sleep(_):raise KeyboardInterrupt('UNIT stopped during backoff')
        j.sleep=crash_sleep
        with self.assertRaises(KeyboardInterrupt):j.request('c','p')
        j2,i2=self.journal([TimeoutError('UNIT timeout'),TimeoutError('UNIT timeout')])
        self.assertEqual(j2.request('c','p')['status'],'failed')
        self.assertEqual(j2.attempt_count,3);self.assertEqual(len(i2.sent),2)

    def test_orphan_reservation_and_separate_batch_and_stale_writer(self):
        j,i=self.journal()
        second,_=self.journal()
        j.request('c','p')
        with self.assertRaises(BudgetStop):second.request('different','p')
        other=self.root/'other';other.mkdir();j2,i2=self.journal(directory=other)
        self.assertEqual(j2.request('c','p')['status'],'completed');self.assertEqual(j2.attempt_count,1)
        self.assertNotEqual(j.identity,j2.identity)
        with self.assertRaises(ValueError):j.request('c','changed prompt')

    def test_no_history_policy_and_legacy_ledger_cannot_use_new_policy(self):
        self.assertNotIn('history_source',self.config.request_budget)
        self.assertNotIn('lifetime_request_cap',self.config.request_budget)
        with self.assertRaises(ValueError):BudgetLedger(self.root/'old-ledger.json',self.config,'UNIT')
        j,i=self.journal();j.request('c','p');s=j.summary()
        self.assertIsNone(s['actual_cost']);self.assertFalse(s['global_history_gate'])
        self.assertFalse(s['cross_worktree_lock_gate'])

    def test_network_evidence_and_unclassified_errors_fail_closed(self):
        self.assertTrue(network_failure_metadata(ConnectionResetError())['temporary_network_failure'])
        self.assertFalse(failure_policy('candidate text exceeds 32 KiB')[0])
        self.assertFalse(failure_policy('chat truncated or response model differs from locked model')[0])
        from fjsp_usage.research_real.real_transport import decode_stream
        class BrokenStream:
            def getheader(self,*args):return 'text/event-stream'
            def readline(self,*args):raise TimeoutError('UNIT stream timeout')
        with self.assertRaises(TransportError) as captured:decode_stream(BrokenStream(),self.config.provider)
        self.assertTrue(failure_policy(str(captured.exception),captured.exception.metadata)[0])

    def test_existing_local_run_lock_rejects_duplicate_cli_writer_only(self):
        with RunLock(self.root):
            with self.assertRaises(RuntimeError):
                with RunLock(self.root):pass
        unrelated=self.root/'other-worktree';unrelated.mkdir();(unrelated/'.writer.lock').write_text('UNIT ignored')
        j,i=self.journal();self.assertEqual(j.request('c','p')['status'],'completed')

    def test_twenty_slots_invalid_duplicate_evaluation_failure_and_two_generations(self):
        members=tuple(Candidate(**v) for v in old.common.read(local.LEGACY/'H_context.json'))
        initial=old.common.read(local.LEGACY/'Initial_population.json')
        atomic_json(self.root/'Initial_population.json',initial);atomic_json(self.root/'Plan.json',{'unit':True})
        plan={'names':['UNIT_NEVER_SOLVED']};evaluations=[]
        from fjsp_usage.research.candidates import U_ARGS
        good=lambda n:'{HANDWRITTEN MOCK ONLY}\n```python\ndef use_heuristics('+', '.join(U_ARGS)+'):\n    alpha = min(1.0, progress + '+str(n/1000)+')\n    return (1, (alpha, 1-alpha, 0,0,0,0,0,0,0,0))\n```'
        answers=[]
        for n in range(20):
            text='UNIT invalid code' if n==0 else ('{UNIT duplicate}\n```python\n'+old.constant(50).code+'```' if n==1 else good(n))
            answers.append({'text':text,'usage':None})
        inner=Inner(self.config,answers);wire=WireRecorder(inner,self.root/'wire_responses')
        def evaluate(c):
            evaluations.append(c.key)
            if len(evaluations)==1:return {'valid':False,'fitness':None,'total_instances':1,'instances':[]}
            span=190-len(evaluations)
            return {'valid':True,'fitness':-span/100,'total_instances':1,
                    'primary_evaluation_seconds':.002,
                    'instances':[{'file':'UNIT_NEVER_SOLVED','score':-span/100,'makespan':span,'lower_bound':100,
                        'single_solve_seconds':.001,'deterministic_recheck_seconds':.001}]}
        engine,j=local.make_search(self.root,self.config,plan,members,wire,evaluate)
        engine.run();self.assertEqual((len(inner.sent),j.attempt_count,j.calls),(20,20,20))
        self.assertEqual(engine.state['generation'],2)
        self.assertEqual(engine.state['attempts'][0]['status'],'parse_or_constraint_error')
        self.assertEqual(engine.state['attempts'][1]['status'],'duplicate')
        self.assertEqual(engine.state['attempts'][2]['status'],'invalid')
        self.assertTrue(all(len(r['attempt_ids'])==1 for r in j.data['requests'].values()))
        self.assertTrue(any('/g0000/' in p for a in engine.state['attempts'][10:] for p in a['parents']))
        engine,j=local.make_search(self.root,self.config,plan,members,wire,evaluate)
        engine.run();self.assertEqual(len(inner.sent),20)
        # Report consumes fictitious rows only; no scheduling or extra requests.
        p={**old.common.read(local.LEGACY/'Plan.json'),'names':['UNIT_NEVER_SOLVED'],'budget_policy':VERSION}
        (self.root/'results').mkdir()
        for v in p['versions']:
            atomic_json(self.root/'results'/f'{v["id"]}.json',{'valid':True,'fitness':-2.,'total_instances':1,
                'primary_evaluation_seconds':.002,'instances':[{'file':'UNIT_NEVER_SOLVED','score':-2.,
                'makespan':200,'lower_bound':100,'single_solve_seconds':.001,'deterministic_recheck_seconds':.001}]})
        atomic_json(self.root/'Budget_summary.json',j.summary())
        from tools.h01_weight_report import report
        with patch.dict('sys.modules',{'reportlab':object()}),patch('tools.h01_weight_report.plot'):
            report(self.root,out=self.root/'UNIT_REPORT',plan_reader=lambda _:p,version=local.BATCH_VERSION)
        evidence=old.common.read(self.root/'UNIT_REPORT/Evidence.json')
        self.assertEqual(evidence['api_attempts_consumed'],20)
        self.assertIsNone(evidence['actual_cost'])
        self.assertTrue((self.root/'UNIT_REPORT/API_attempts.csv').exists())
        self.assertIn('accepted_attempt_id',(self.root/'UNIT_REPORT/Requests.csv').read_text())

    def test_search_stops_at_thirty_attempts_without_inventing_remaining_tasks(self):
        members=tuple(Candidate(**v) for v in old.common.read(local.LEGACY/'H_context.json'))
        atomic_json(self.root/'Initial_population.json',old.common.read(local.LEGACY/'Initial_population.json'))
        atomic_json(self.root/'Plan.json',{'unit':True})
        inner=Inner(self.config,[ConnectionError('UNIT connection failure') for _ in range(30)])
        wire=WireRecorder(inner,self.root/'wire_responses')
        e,j=local.make_search(self.root,self.config,{'names':['UNIT']},members,wire,
            lambda _:self.fail('no complete response may reach evaluation'))
        j.sleep=lambda _:None
        with self.assertRaisesRegex(BudgetStop,'attempt cap'):e.run()
        self.assertEqual((len(e.state['attempts']),j.calls,j.attempt_count),(10,10,30))
        self.assertEqual(e.state['generation'],1)
        self.assertIsNone(e.state['inflight'])

    def test_saved_response_and_completed_evaluation_are_not_repeated(self):
        members=tuple(Candidate(**v) for v in old.common.read(local.LEGACY/'H_context.json'))
        atomic_json(self.root/'Initial_population.json',old.common.read(local.LEGACY/'Initial_population.json'))
        atomic_json(self.root/'Plan.json',{'unit':True})
        code=old.constant(10).code
        wire=WireRecorder(Inner(self.config,[{'text':'{UNIT complete}\n```python\n'+code+'```','usage':None}]),self.root/'wire_responses')
        evaluations=[]
        def evaluate(c):
            evaluations.append(c.key)
            return {'valid':True,'fitness':-1.,'total_instances':1,
                    'instances':[{'file':'UNIT','score':-1.,'makespan':1,'lower_bound':1}]}
        e,j=local.make_search(self.root,self.config,{'names':['UNIT']},members,wire,evaluate)
        e._prepare(initial=False)
        # Crash after evaluate_once persisted its result, before candidate commit.
        native=e._evaluate_once
        def after_evaluation(*args):
            result=native(*args);raise KeyboardInterrupt('UNIT completed evaluation not yet committed')
        with patch.object(e,'_evaluate_once',side_effect=after_evaluation):
            with self.assertRaises(KeyboardInterrupt):e._attempt()
        e2,j2=local.make_search(self.root,self.config,{'names':['UNIT']},members,wire,evaluate)
        e2._attempt();self.assertEqual((len(wire.inner.sent),len(evaluations)),(1,1))

    def test_new_approval_required_and_science_prompt_unchanged(self):
        for field,value in [('generations',1),('attempts_per_generation',20),('instance_timeout',30)]:
            with self.assertRaises(ValueError):replace(self.config,**{field:value})
        members=tuple(Candidate(**v) for v in old.common.read(local.LEGACY/'H_context.json'))
        initial=old.common.read(local.LEGACY/'Initial_population.json')
        for op,parents in [('CROSS',initial),('MUTATE',[initial[2]])]:
            self.assertEqual(old.build_prompt('B',op,parents,members),(local.LEGACY/'prompt_templates'/f'{op}.txt').read_text())
        with patch.object(local,'check',return_value=({},self.config,members)):
            with self.assertRaisesRegex(BudgetStop,'not authorized'):local.execute(self.root,'search')

    def test_batch_check_does_not_use_peer_history_or_foreign_locks(self):
        from fjsp_usage.usage_v2.fixed_h import wrapper
        plan={'dataset':{'UNIT':True},'H_order':['UNIT-H'],'version':local.BATCH_VERSION}
        dataset=SimpleNamespace(metadata=plan['dataset'])
        H={'member_count':1,'training_files':['UNIT'],'members':[], 'artifact_sha256':'unit','context':'unit'}
        member=SimpleNamespace(key='UNIT-H')
        atomic_json(self.root/'config.pending.json',self.config.payload())
        atomic_json(self.root/'H_source_binding.json',wrapper(self.config,digest(plan),H))
        (self.root/'foreign-worktree.writer.lock').write_text('UNIT ignored')
        with patch.object(local,'pins_check',return_value=plan),patch.object(old,'check_evaluation_runtime'),\
             patch.object(local,'data_and_h',return_value=(dataset,H,[member])):
            result=local.check(self.root)
        self.assertEqual(result[0],plan)

    def test_pinned_asset_reads_ignore_old_writer_only_in_new_policy(self):
        from fjsp_usage.research_real.conditional_research import pinned_bundle
        folder=self.root/'runs/source';folder.mkdir(parents=True)
        source=folder/'asset.json';atomic_json(source,{'UNIT':'unchanged'})
        (folder/'.writer.lock').write_text('UNIT historical writer')
        declaration={'source_files_sha256':{'source/asset.json':old.common.sha(source)}}
        with self.assertRaises(ValueError):pinned_bundle(self.root,declaration)
        self.assertEqual(pinned_bundle(self.root,declaration,check_writer=False)['source/asset.json'],{'UNIT':'unchanged'})
        atomic_json(source,{'UNIT':'tampered'})
        with self.assertRaises(ValueError):pinned_bundle(self.root,declaration,check_writer=False)

    def test_fixed_H_passes_new_policy_to_ancestral_asset_audit(self):
        from fjsp_usage.usage_v2.fixed_h import source_h
        from fjsp_usage.research_real.staged_evaluation import StagedDataset
        from fjsp_usage.research_real.config import fingerprint
        dataset=StagedDataset(local.ROOT/'data/fjsp_manifest.json',project_root=local.ROOT,mode='real')
        exists=Path.exists
        def locked(p):return True if p.name=='.writer.lock' else exists(p)
        with patch.object(Path,'exists',locked),patch('fjsp_usage.research_real.conditional_research.h_asset',return_value=('UNIT-H',())) as audit:
            self.assertEqual(source_h(self.config,dataset,fingerprint(local.ROOT))[0],'UNIT-H')
            self.assertFalse(audit.call_args.args[0].check_source_writer)
        prior=local.Config.from_dict(old.common.read(local.DEFAULT/'config.pending.json'))
        with patch.object(Path,'exists',locked):
            with self.assertRaisesRegex(ValueError,'writer lock'):source_h(prior,dataset,fingerprint(local.ROOT))


class LocalHTTPRetryTests(unittest.TestCase):
    def test_existing_transport_local_503_then_success(self):
        from fjsp_usage.research_real.config import ExperimentConfig,ProviderConfig
        from fjsp_usage.research_real.fixtures import fixture_server
        from fjsp_usage.research_real.real_transport import JsonCandidateTransport
        with fixture_server(script=[{'status':503},{}]) as (url,traffic),tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(url.startswith('http://127.0.0.1:'))
            cfg=ExperimentConfig(provider=ProviderConfig(url,'HANDWRITTEN-UNIT-ONLY'),
                total_request_cap=20,request_budget=dict(local.BATCH_POLICY))
            path=Path(tmp)
            wire=WireRecorder(JsonCandidateTransport(cfg),path/'wire_responses')
            journal=AttemptJournal(path/'journal.json',config=cfg,context='LOCAL-HTTP-MOCK',phase='UNIT',
                                   transport=wire,sleep=lambda _:None)
            result=journal.request('c','UNIT identical prompt')
            self.assertEqual(result['status'],'completed')
            self.assertEqual((journal.attempt_count,len(traffic['requests'])),(2,2))
            self.assertEqual(list(journal.data['api_attempts'].values())[0]['metadata']['http_status'],503)


if __name__=='__main__':unittest.main()
