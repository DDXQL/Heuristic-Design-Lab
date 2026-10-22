"""B1-NS engineering acceptance: synthetic replies/fitness, never FJSP or API."""
from contextlib import ExitStack
from dataclasses import replace
from itertools import count
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import Candidate
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real import real_transport as rt
from tools import b1_nonstream_local as ns
from tools.t1_d2_prompt_ab import TimedRecorder
from test_b1_usage_local import mock_code


class Inner:
    identity='B1-NS-MOCK-ONLY';secret='';redact=staticmethod(str)
    def __init__(self,config):self.config,self.sent,self.answers=config,[],[]
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind='U',on_sent):
        on_sent();index=len(self.sent);self.sent.append((key,prompt))
        answer=self.answers.pop(0) if self.answers else mock_code(index)
        if isinstance(answer,BaseException):raise answer
        raw=answer if isinstance(answer,dict) else {'id':'MOCK-'+str(index),'model':'gpt-6.1-sol',
            'choices':[{'message':{'content':'{Synthetic fixture only}\n```python\n'+answer+'```'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':10}}
        try:reply=rt.decode_chat(raw,self.config.provider)
        except Exception as exc:
            exc.metadata={'http_status':200,'failure_stage':'http_receive',**getattr(exc,'metadata',{})};raise
        reply['metadata'].update(http_status=200,http_content_type='application/json')
        return reply


class NSTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name);base=ns.pending_config()
        self.config=replace(base,mode='synthetic',provider=replace(base.provider,endpoint='http://localhost/mock',api_key_env=None))
        self.inner=Inner(self.config)
        self.profile=ns.CompleteNonstreamTransport(self.inner,self.path/'received')
        self.transport=TimedRecorder(self.profile,self.path/'wire')
        self.names=tuple('MOCK_'+str(i) for i in range(21));self.evaluated=[]
        self.members=tuple(Candidate('Synthetic fixture H','def priority(x):\n    return '+str(i)+'\n','MOCK_H'+str(i),'h') for i in range(10))
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for name in ('socket.socket.connect','fjsp_usage.research_real.real_transport.JsonCandidateTransport.dispatch',
                     'fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.runtime.evaluate','tools.usage_mechanism_ablation.evaluate_with_schedules',
                     'fjsp_usage.research_real.leafapi.load_local_key','fjsp_usage.research_real.leafapi.query_status',
                     'fjsp_usage.usage_v2.billing.query_invoices','fjsp_usage.research_real.conditional_research.history_summary'):
            self.stack.enter_context(patch(name,side_effect=AssertionError('NO REAL API, KEY, FJSP OR HOLDOUT')))

    def evaluator(self,c):
        self.evaluated.append(c.key);makespan=300-len(self.evaluated);score=-makespan/10
        return {'valid':True,'total_instances':21,'fitness':score,
                'instances':[{'file':n,'makespan':makespan,'lower_bound':10,'score':score} for n in self.names]}

    def engine(self,evaluator=None):
        return ns.NSSearch(self.path/'search',experiment=self.config,training_names=self.names,
            arm='B',config=self.config.u_search(501),members=self.members,
            evaluator=evaluator or self.evaluator,transport=self.transport,context=digest(self.config.payload()))

    def test_only_explicit_engineering_config_differences(self):
        original=ns.baseline()['config'];new=ns.pending_config().payload()
        keys={k for k in original if digest(original[k])!=digest(new[k])}
        self.assertEqual(keys,{'provider','request_budget','experiment_version'})
        self.assertEqual(new['provider'],{**original['provider'],'stream_response':False})
        self.assertEqual([new[k] for k in ('population_size','cross_parents','mutation_parents','generations','attempts_per_generation')],[5,2,1,2,10])
        for kwargs in ({'cross_parents':3},{'instance_timeout':16},{'generations':3},
                       {'provider':replace(ns.pending_config().provider,max_output_tokens=8191)}):
            with self.assertRaises(ValueError):replace(ns.pending_config(),**kwargs)

    def test_full_two_generations_initialisation_parent_pools_and_inheritance(self):
        e=self.engine();r=e.run()
        self.assertEqual(e.state['phase'],'completed');self.assertEqual(len(self.inner.sent),25)
        self.assertEqual(len(self.evaluated),25);self.assertEqual(len(e.export_rows()),5)
        self.assertEqual(r['initialization_requests'],5);self.assertEqual(r['evolution_requests'],20)
        self.assertIs(e.initial_requests,e.evolution_requests)
        self.assertEqual(e.ledger.policy,ns.POLICY)
        self.assertTrue(all(k.startswith(ns.VERSION+'/r501/B/') for k,_ in self.inner.sent))
        for gen in (0,1):
            rows=[x for x in e.state['attempts'] if x.get('generation')==gen and x['operator']!='I1']
            self.assertEqual([x['operator'] for x in rows],['CROSS']*5+['MUTATE']*5)
            pool={x['id'] for x in e.state['generation_parent_pools'][str(gen)]}
            for x in rows:
                self.assertTrue(set(x['parents'])<=pool)
                self.assertEqual(len(set(x['parents'])),2 if x['operator']=='CROSS' else 1)
                self.assertEqual(x['expected_children'],1)
        self.assertTrue(any('/g0000/' in p for x in e.state['attempts'] if x.get('generation')==1 for p in x['parents']))
        self.assertEqual(set(e.state['population_snapshots']),{'P0','P1','P2'})

    def test_prompt_semantics_all_h_no_manual_or_fitness_injection(self):
        e=self.engine();self.assertEqual(e.state['population'],[]);e.run()
        first=self.inner.sent[0][1];self.assertEqual(first.count('H MEMBER '),10)
        self.assertIn('SELECT (0) OR MIX (1)',first)
        cross=[r for r in e.state['attempts'] if r['operator']=='CROSS']
        self.assertGreater(len({tuple(sorted(r['parents'])) for r in cross[:5]}),1)
        for _,p in self.inner.sent:
            self.assertNotIn('-29.9',p);self.assertNotIn('alpha_050',p);self.assertNotIn('T1-D4',p)
        self.assertIn('AT LEAST TWO parents',self.inner.sent[5][1])
        self.assertEqual(self.inner.sent[5][1].count('\nPARENT '),2)

    def test_invalid_and_duplicate_do_not_retry_or_evaluate(self):
        self.inner.answers=['invalid code',mock_code(1),mock_code(1)]
        e=self.engine();e.initialize(stop_after_attempts=3)
        self.assertEqual([r['status'] for r in e.state['attempts']],['parse_or_constraint_error','valid','duplicate'])
        self.assertEqual(len(self.inner.sent),3);self.assertEqual(len(self.evaluated),1)

    def test_missing_description_like_D4_is_not_repaired_or_seeded(self):
        raw={'id':'MOCK','model':'gpt-6.1-sol','choices':[{'message':{'content':'Plain description\n```python\n'+mock_code(1)+'```'},'finish_reason':'stop'}],
             'usage':{'prompt_tokens':10,'completion_tokens':10}}
        self.inner.answers=[raw];e=self.engine();e.initialize(stop_after_attempts=1)
        self.assertEqual(e.state['population'],[]);self.assertEqual(len(self.evaluated),0)
        self.assertEqual(e.state['attempts'][0]['status'],'parse_or_constraint_error')
        self.assertEqual(len(self.inner.sent),1)

    def test_timeout_three_attempts_then_failed_no_evaluation(self):
        self.inner.answers=[TimeoutError('MOCK timeout')]*3;e=self.engine()
        e.ledger.sleep=lambda n:None;clock=count(0,100);e.ledger.clock=lambda:next(clock)
        e.initialize(stop_after_attempts=1)
        self.assertEqual(len(self.inner.sent),3);self.assertEqual(len(self.evaluated),0)
        self.assertEqual(e.ledger.attempt_count,3)

    def test_sixty_attempt_shared_limit_persists_across_restart(self):
        self.inner.answers=[ConnectionError('MOCK connection')]*60;e=self.engine()
        e.ledger.sleep=lambda n:None;clock=count(0,100);e.ledger.clock=lambda:next(clock)
        for i in range(20):e.ledger.request('B/init/'+str(i),'MOCK')
        self.assertEqual(e.ledger.attempt_count,60)
        with self.assertRaises(BudgetStop):self.engine().ledger.request('B/extra','MOCK')
        self.assertEqual(len(self.inner.sent),60)

    def test_forty_logical_tasks_shared_limit(self):
        e=self.engine()
        for i in range(40):e.ledger.request('B/'+str(i),'MOCK')
        with self.assertRaises(BudgetStop):e.ledger.request('EXTRA','MOCK')
        self.assertEqual(e.ledger.calls,40)

    def test_three_nonstream_protocol_errors_circuit_without_retry(self):
        bad={'id':'MOCK','model':'gpt-6.1-sol','choices':[{'message':{'content':'partial'},'finish_reason':'length'}],
             'usage':{'prompt_tokens':10,'completion_tokens':10}}
        self.inner.answers=[bad]*3;e=self.engine()
        with self.assertRaises(BudgetStop):e.run()
        self.assertEqual(len(self.inner.sent),3);self.assertEqual(len(e.state['attempts']),3)
        self.assertEqual(e.ledger.data['halt_reason'],'transport_protocol_circuit_open')
        with self.assertRaises(BudgetStop):self.engine().run()
        self.assertEqual(len(self.inner.sent),3)

    def test_model_mismatch_halts_at_safe_checkpoint(self):
        bad={'id':'MOCK','model':'wrong','choices':[{'message':{'content':'x'},'finish_reason':'stop'}],
             'usage':{'prompt_tokens':10,'completion_tokens':10}}
        self.inner.answers=[bad];e=self.engine()
        with self.assertRaises(BudgetStop):e.run()
        self.assertEqual(len(self.inner.sent),1);self.assertEqual(len(e.state['attempts']),1)
        self.assertEqual(e.ledger.data['halt_reason'],'response_model_identity_mismatch')
        self.assertEqual(self.evaluated,[])

    def test_missing_usage_profile_rejected_but_received_reply_saved(self):
        bad={'id':'MOCK','model':'gpt-6.1-sol','choices':[{'message':{'content':'x'},'finish_reason':'stop'}]}
        self.inner.answers=[bad];e=self.engine();e.initialize(stop_after_attempts=1)
        self.assertEqual(self.evaluated,[]);self.assertEqual(len(self.inner.sent),1)
        self.assertEqual(len(list((self.path/'received').glob('*.json'))),1)
        a=next(iter(e.ledger.data['api_attempts'].values()))
        self.assertEqual(a['metadata']['protocol_kind'],'nonstream_json');self.assertIsNone(a['usage'])

    def test_unknown_delivery_resume_never_resends_or_resets(self):
        self.inner.answers=[KeyboardInterrupt('MOCK unknown send')];e=self.engine()
        with self.assertRaises(KeyboardInterrupt):e.initialize()
        with self.assertRaises(BudgetStop):self.engine().run()
        self.assertEqual(len(self.inner.sent),1);self.assertEqual(self.engine().ledger.attempt_count,1)

    def test_reserved_but_unconfirmed_resume_charged(self):
        e=self.engine()
        with patch.object(self.transport,'dispatch',side_effect=KeyboardInterrupt('MOCK reserved before send')):
            with self.assertRaises(KeyboardInterrupt):e.initialize()
        with self.assertRaises(BudgetStop):self.engine().run()
        self.assertEqual(self.inner.sent,[]);self.assertEqual(self.engine().ledger.attempt_count,1)

    def test_complete_wire_and_evaluation_resume_no_duplicates(self):
        e=self.engine();e._prepare(initial=True);p=e.state['inflight']
        e.ledger.request(p['id'],p['prompt']);self.assertEqual(len(self.inner.sent),1)
        resumed=self.engine();resumed.initialize(stop_after_attempts=1)
        self.assertEqual(len(self.inner.sent),1);self.assertEqual(len(self.evaluated),1)
        resumed.run();n=len(self.evaluated);resumed=self.engine();resumed.run()
        self.assertEqual(len(self.evaluated),n);self.assertEqual(len(self.inner.sent),25)

    def test_initialisation_failure_twenty_slots_never_fills_with_old_U(self):
        e=self.engine(evaluator=lambda c:{'valid':False,'total_instances':21,'instances':[],'fitness':None})
        e.run();self.assertEqual(e.state['phase'],'initialization_failed')
        self.assertEqual(len(self.inner.sent),20);self.assertEqual(e.state['population'],[])

    def test_evaluation_full_result_failure_and_prefix_not_fitness(self):
        class Dataset:
            names={'train':tuple('MOCK_'+str(i) for i in range(21))}
            def load(self,split):self.loaded=split;return [object()]*21
            def verify(self,split):assert split=='train'
        data=Dataset();result={'valid':False,'total_instances':21,'instances':[],'fitness':None}
        with patch('tools.usage_mechanism_ablation.evaluate_with_schedules',return_value=result) as evaluate:
            f=ns.training_evaluator(data,self.members,self.names);self.assertEqual(f(object()),result)
            args,kwargs=evaluate.call_args;self.assertEqual(data.loaded,'train')
            self.assertEqual(kwargs,{'timeout':15,'diagnostics':False,'allowed_modes':(0,1)})
        with patch('tools.usage_mechanism_ablation.evaluate_with_schedules',return_value={**result,'fitness':-1}):
            with self.assertRaises(ValueError):ns.training_evaluator(data,self.members,self.names)(object())
        with self.assertRaises(ValueError):ns.training_evaluator(data,self.members,self.names[:-1])

    def test_saved_evaluation_incomplete_result_never_survives(self):
        def bad(c):return {'valid':True,'total_instances':21,'fitness':-1,'instances':[]}
        e=self.engine(evaluator=bad)
        with self.assertRaises(ValueError):e.initialize()
        resumed=self.engine();resumed.initialize(stop_after_attempts=1)
        self.assertTrue(all(r['fitness']!=-1 for r in resumed.state['population']))
        self.assertEqual(resumed.state['evaluations']['B/init/000000']['result']['error_type'],'InterruptedEvaluation')

    def test_authorization_before_evaluator_provider_or_key(self):
        with tempfile.TemporaryDirectory(prefix='b1-ns-mock-gate-',dir=ns.ROOT/'runs') as folder:
            with patch.object(ns,'check',side_effect=AssertionError('must not load assets')):
                with self.assertRaises(BudgetStop):ns.run(Path(folder),None)

    def test_receipt_namespace_differs_from_old_and_config_changed_resume_fails(self):
        e=self.engine();e.initialize(stop_after_attempts=1)
        self.assertNotEqual(ns.NSSearch.request_phase,ns.b1.B1Search.request_phase)
        with self.assertRaisesRegex(ValueError,'resume rejected'):
            ns.NSSearch(e.directory,experiment=self.config,training_names=self.names,arm='B',
                config=self.config.u_search(501),members=self.members,evaluator=self.evaluator,
                transport=self.transport,context='OTHER BATCH')

    def test_legacy_search_default_and_prompt_pack_unchanged(self):
        self.assertEqual(ns.b1.B1Search.request_phase,'r501/B')
        self.assertEqual(ns.prompts.manifest(),ns.baseline()['prompt_pack'])
        self.assertIsNone(self.engine().report()['api_attempt_budget']['actual_cost'])

    def test_actual_entry_run_and_report_with_mock_train21_only(self):
        directory=self.path/'MOCK_ENTRY';directory.mkdir()
        (directory/'Protocol.json').write_text('{"synthetic_only":true}')
        class Dataset:
            names={'train':self.names}
            metadata={'synthetic_only':True}
            def load(self,split):assert split=='train';return [object()]*21
            def verify(self,split):assert split=='train'
        data=Dataset();p={'train_names':list(self.names)}
        with patch.object(ns,'require_execution',return_value=(p,self.config,data,self.members)), \
             patch.object(ns,'check',return_value=(p,self.config,data,self.members)), \
             patch.object(ns,'JsonCandidateTransport',return_value=self.inner), \
             patch('fjsp_usage.research_real.leafapi.load_local_key',return_value='UNIT-NOT-REAL'), \
             patch.dict('os.environ',{}), \
             patch('tools.usage_mechanism_ablation.evaluate_with_schedules',side_effect=lambda c,*a,**k:self.evaluator(c)):
            ns.run(directory,ns.ENV_FILE)
            report=ns.report(directory)
        self.assertEqual(report['status']['phase'],'completed')
        self.assertEqual(len(self.inner.sent),25);self.assertEqual(len(self.evaluated),25)
        self.assertEqual(len(ns.read(directory/'Final_or_partial_population.json')),5)
        self.assertFalse(report['stream_response']);self.assertIsNone(report['actual_cost'])

    def test_old_stage_authorization_rejected_before_asset_reads(self):
        with tempfile.TemporaryDirectory(prefix='b1-ns-mock-approval-',dir=ns.ROOT/'runs') as folder:
            path=Path(folder);(path/'Protocol.json').write_text('{"synthetic_only":true}')
            auth=ns.approval(path,True);auth['stage']='B1-1'
            (path/'B1_NS_authorization.json').write_text(json.dumps(auth))
            with patch.object(ns,'check',side_effect=AssertionError('no asset reads')):
                with self.assertRaises(BudgetStop):ns.require_execution(path)


if __name__=='__main__':unittest.main()
