"""B1 engineering only: synthetic programs/fitness; no API or FJSP solving."""
from contextlib import ExitStack
from dataclasses import asdict, replace
import json
from itertools import count
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.candidates import Candidate, U_ARGS
from fjsp_usage.research.evolution import select_parents
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.usage_v2.access import WireRecorder
from tools import b1_usage_local as b1
from tools import b1_usage_prompts as prompts


def mock_code(index):
    # Handwritten fixture only, never persisted to any real population.
    vector=','.join(str(1 if i==index%10 else 0) for i in range(10))
    return f'def use_heuristics({", ".join(U_ARGS)}):\n    mock_marker = {index}\n    return ({index%2}, ({vector}))\n'


class Inner:
    identity='B1-SYNTHETIC-ONLY';secret='';redact=staticmethod(str)
    def __init__(self):self.sent=[];self.answers=[]
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind='U',on_sent):
        on_sent();index=len(self.sent);self.sent.append((key,prompt))
        answer=self.answers.pop(0) if self.answers else mock_code(index)
        if isinstance(answer,Exception):raise answer
        return {'text':'{Synthetic fixture only}\n```python\n'+answer+'```',
                'usage':{'input_tokens':1,'output_tokens':1}}


class B1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        self.config=b1.pending_config()
        provider=replace(self.config.provider,endpoint='http://localhost/mock',api_key_env=None,
                         model='MOCK-NOT-A-SCIENTIFIC-MODEL',expected_response_model=None)
        self.config=replace(self.config,mode='synthetic',provider=provider)
        self.inner=Inner();self.inner.config=self.config
        self.transport=WireRecorder(self.inner,self.path/'wire')
        self.members=tuple(Candidate('Synthetic H fixture',f'def priority(x):\n    return {i}\n',f'MOCK_H_{i}','h') for i in range(10))
        self.names=('MOCK_A','MOCK_B');self.evaluated=[]
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        for target in ('socket.socket.connect','fjsp_usage.research_real.runtime.evaluate',
                       'tools.usage_mechanism_ablation.evaluate_with_schedules',
                       'fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                       'fjsp_usage.research_real.leafapi.query_status','fjsp_usage.usage_v2.billing.query_invoices',
                       'fjsp_usage.research_real.conditional_research.history_summary',
                       'fjsp_usage.research_real.real_transport.JsonCandidateTransport.dispatch'):
            self.stack.enter_context(patch(target,side_effect=AssertionError('NO REAL API, SCHEDULING OR HOLDOUT')))

    def evaluator(self,c):
        self.evaluated.append(c.key);n=len(self.evaluated);score=-(201-n)
        return {'valid':True,'total_instances':2,'fitness':score,
                'instances':[{'file':name,'makespan':201-n,'lower_bound':1,'score':score} for name in self.names]}

    def engine(self,**kwargs):
        config=kwargs.pop('experiment',self.config)
        return b1.B1Search(self.path/'search',experiment=config,training_names=self.names,
            arm='B',config=config.u_search(501),members=self.members,evaluator=kwargs.pop('evaluator',self.evaluator),
            transport=self.transport,context=digest(config.payload()),**kwargs)

    def test_rank_weights_remove_selected_without_reranking(self):
        population=[{'id':str(i),'fitness':-i} for i in range(5)]
        class Rng:
            def __init__(self):self.weights=[]
            def choices(self,indices,weights,k):
                self.weights.append(list(weights));return [1 if len(self.weights)==1 else 2]
        rng=Rng();chosen=select_parents(population,2,rng)
        self.assertEqual([p['id'] for p in chosen],['1','3'])
        self.assertEqual(rng.weights[0],[1/5,1/6,1/7,1/8,1/9])
        self.assertEqual(rng.weights[1],[1/5,1/7,1/8,1/9])
        self.assertEqual(len(population),5)

    def test_two_generation_counts_diverse_pairs_frozen_pool_survival_and_inheritance(self):
        e=self.engine();result=e.run();lineage=e.state['attempts']
        self.assertEqual(len(self.inner.sent),25);self.assertEqual(len(self.evaluated),25)
        self.assertEqual(len(e.state['population']),5);self.assertEqual(e.state['generation'],2)
        self.assertEqual(e.initial_requests,e.evolution_requests)
        pairs=[]
        for gen in (0,1):
            events=[r for r in lineage if r.get('generation')==gen and r['operator']!='I1']
            self.assertEqual([r['operator'] for r in events],['CROSS']*5+['MUTATE']*5)
            pool={r['id'] for r in e.state['generation_parent_pools'][str(gen)]}
            for r in events:
                self.assertEqual(r['cross_parents'],2);self.assertEqual(r['expected_children'],1)
                self.assertTrue(set(r['parents'])<=pool)
                self.assertEqual(len(set(r['parents'])),2 if r['operator']=='CROSS' else 1)
                if r['operator']=='CROSS':pairs.append(tuple(sorted(r['parents'])))
            survivors=e.state['population_snapshots']['P'+str(gen+1)]
            self.assertTrue(all('/g'+f'{gen:04d}'+'/' in r['id'] for r in survivors))
        self.assertGreater(len(set(pairs[:5])),1)
        self.assertTrue(any('/g0000/' in p for r in lineage if r.get('generation')==1 for p in r['parents']))
        self.assertEqual(result['initialization_requests'],5);self.assertEqual(result['evolution_requests'],20)
        self.assertEqual(result['cross_parents'],2);self.assertEqual(len(e.export_rows()),5)

    def test_prompt_two_parents_one_child_no_fitness(self):
        parents=[{'id':str(i),'fitness':-900+i,'candidate':{'description':'MOCK parent','code':mock_code(i)}} for i in range(2)]
        p=prompts.build_prompt('B','CROSS',parents,self.members)
        self.assertIn('AT LEAST TWO parents',p);self.assertIn('Return one complete new U',p)
        self.assertEqual(p.count('\nPARENT '),2);self.assertNotIn('PARENT 2',p)
        self.assertNotIn('-900',p);self.assertNotIn('-899',p)

    def test_k3_k5_are_configurable_but_identity_changes(self):
        identities=[]
        for k in (2,3,5):
            c=replace(self.config,cross_parents=k);identities.append(digest(c.payload()))
            self.assertEqual(c.u_search(501).cross_parents,k)
        self.assertEqual(len(set(identities)),3)
        for k in (1,6):
            with self.assertRaises(ValueError):replace(self.config,cross_parents=k)

    def test_config_change_rejects_checkpoint_resume(self):
        e=self.engine();e.run(stop_after_attempts=1)
        with self.assertRaisesRegex(ValueError,'resume rejected'):
            self.engine(experiment=replace(self.config,cross_parents=3))

    def test_restart_keeps_rng_and_no_repeat(self):
        e=self.engine();e.run(stop_after_attempts=3);self.assertEqual(len(self.inner.sent),8)
        resumed=self.engine();resumed.run()
        self.assertEqual(len(self.inner.sent),25);self.assertEqual(len(self.evaluated),25)
        resumed.run();self.assertEqual(len(self.inner.sent),25)
        actual=[r['parents'] for r in resumed.state['attempts']]
        self.path=self.path/'uninterrupted_reference';self.inner=Inner();self.inner.config=self.config
        self.path.mkdir()
        self.transport=WireRecorder(self.inner,self.path/'wire');self.evaluated=[]
        reference=self.engine();reference.run()
        self.assertEqual(actual,[r['parents'] for r in reference.state['attempts']])

    def test_first_saved_response_not_requested_again(self):
        e=self.engine();e.initialize();e._prepare(initial=False)
        pending=e.state['inflight'];e.ledger.request(pending['id'],pending['prompt'])
        self.assertEqual(len(self.inner.sent),6)
        resumed=self.engine();resumed._attempt()
        self.assertEqual(len(self.inner.sent),6);self.assertEqual(len(self.evaluated),6)

    def test_invalid_code_and_duplicate_are_not_retried(self):
        self.inner.answers=['invalid Python',mock_code(1),mock_code(1)]
        e=self.engine();e.initialize(stop_after_attempts=3)
        self.assertEqual(len(self.inner.sent),3);self.assertEqual(len(self.evaluated),1)
        self.assertEqual([r['status'] for r in e.state['attempts']],['parse_or_constraint_error','valid','duplicate'])

    def test_failed_fitness_never_survives(self):
        def invalid(c):return {'valid':False,'total_instances':2,'fitness':None,'instances':[],'error_type':'MOCK_FAILURE'}
        e=self.engine(evaluator=invalid);e.run()
        self.assertEqual(e.state['phase'],'initialization_failed');self.assertEqual(len(self.inner.sent),20)
        self.assertEqual(e.state['population'],[]);self.assertEqual(e.state['generation'],0)

    def test_forty_logical_budget_shared_between_stages(self):
        e=self.engine()
        for i in range(40):
            e.ledger.request(('B/init/' if i<20 else 'B/g0000/')+str(i),'MOCK')
        with self.assertRaises(BudgetStop):e.ledger.request('B/extra','MOCK')
        self.assertEqual(e.ledger.calls,40);self.assertEqual(e.ledger.attempt_count,40)

    def test_sixty_attempt_budget_is_global_and_persists(self):
        e=self.engine();self.inner.answers=[ConnectionError('MOCK network')]*60
        e.ledger.sleep=lambda n:None
        # Advance the mock clock so retries incur no real waits.
        clock=count(0,100);e.ledger.clock=lambda:next(clock)
        for i in range(20):e.ledger.request('B/init/'+str(i),'MOCK')
        self.assertEqual(e.ledger.attempt_count,60);self.assertEqual(e.ledger.calls,20)
        resumed=self.engine()
        with self.assertRaises(BudgetStop):resumed.ledger.request('B/g0000/0','MOCK')
        self.assertEqual(len(self.inner.sent),60)

    def test_initialisation_all_h_modes_and_no_parent_injection(self):
        p=prompts.build_prompt('B','I1',[],self.members)
        self.assertEqual(p.count('H MEMBER '),10)
        self.assertIn('SELECT (0) OR MIX (1)',p);self.assertNotIn('PARENT ',p)
        self.assertNotIn('No H behavior',prompts.NOVELTY)
        e=self.engine();self.assertEqual(e.state['population'],[])

    def test_metadata_logs_report_k2(self):
        e=self.engine();e.run()
        events=[json.loads(s) for s in (e.directory/'events.jsonl').read_text().splitlines()]
        logged=[x for x in events if x['kind']=='b1_operator']
        self.assertEqual(len(logged),25);self.assertTrue(all(x['cross_parents']==2 for x in logged))
        self.assertEqual(e.report()['api_attempt_budget']['actual_cost'],None)
        self.assertFalse(e.report()['api_attempt_budget']['global_history_gate'])

    def test_old_arm_name_cannot_select_wrong_operators(self):
        with self.assertRaises(ValueError):prompts.build_prompt('B1','CROSS',[],self.members)

    def test_k3_k5_reach_actual_mock_requests(self):
        original=self.path
        for k in (3,5):
            self.path=original/f'k{k}';self.inner=Inner();self.inner.config=self.config
            self.path.mkdir()
            self.transport=WireRecorder(self.inner,self.path/'wire');self.evaluated=[]
            e=self.engine(experiment=replace(self.config,cross_parents=k));e.run()
            cross=[r for r in e.state['attempts'] if r['operator']=='CROSS']
            self.assertEqual(len(cross),10)
            self.assertTrue(all(len(set(r['parents']))==k for r in cross))
            self.assertEqual(len(self.inner.sent),25)

    def test_missing_authorization_blocks_before_check_or_loading(self):
        with patch.object(b1,'check',side_effect=AssertionError('must not reach H/data/provider')):
            with self.assertRaises(BudgetStop):b1.run(self.path,None)

    def test_missing_journal_or_checkpoint_never_resets_consumption(self):
        e=self.engine();e.run(stop_after_attempts=1)
        journal=e.directory/'batch_requests.json';raw=journal.read_bytes();journal.unlink()
        with self.assertRaisesRegex(ValueError,'missing batch journal'):self.engine()
        journal.write_bytes(raw);(e.directory/'checkpoint.json').unlink()
        with self.assertRaisesRegex(ValueError,'orphan batch journal'):self.engine()

    def test_model_parameters_and_budget_are_unchanged_by_k(self):
        base=b1.pending_config()
        for k in (3,5):
            c=replace(base,cross_parents=k)
            self.assertEqual(c.provider,base.provider);self.assertEqual(c.request_budget,base.request_budget)
            self.assertEqual(c.generations,2);self.assertEqual(c.attempts_per_generation,10)
        with self.assertRaises(ValueError):replace(base,provider=replace(base.provider,max_output_tokens=8191))


if __name__=='__main__':unittest.main()
