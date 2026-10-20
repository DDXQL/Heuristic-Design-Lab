"""B2-0 engineering fixtures only: fake responses/scores; NO FJSP evaluation.

No fixture population/result is written to the actual preparation directory.
"""
from contextlib import ExitStack
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.candidates import Candidate
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.budget import BudgetStop, BudgetJournal, BudgetLedger
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from tools import h01_weight_local as local
from tools import h01_weight_search as old


class B2LocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.directory=self.root/'runs/new-unit-only';self.directory.mkdir(parents=True)
        self.peer=self.root/'runs/stopped-unit-peer';self.peer.mkdir()
        binding=seal({'kind':'Fair_history_binding','mode':'real','lifetime_request_cap':300,
            'historical_request_slots':201,'historical_confirmed_sends':185,'real_budget_inventory':{},
            'retained_account_hold':24000000})
        original=old.common.read(local.LEGACY/'config.pending.json')
        p={'config':{'conditional_research':{'history_binding':binding},'provider':original['provider']},'dataset':{'unit':'NO BENCHMARK'}}
        self.protocol=p;identity=digest({'config':p['config'],'context':digest(p)})
        ledger={'identity':identity,'mode':'real','halted':False,'records':{}}
        arms={}
        for arm,count in [('A',20),('B',10)]:
            folder=self.peer/f'r201/{arm}';folder.mkdir(parents=True);journal={};attempts=[]
            for n in range(count):
                cid=f'{arm}/g0000/{n:06d}';key=f'r201/{arm}/{cid}';prompt='EXPLICIT HANDWRITTEN UNIT RECORD '+cid
                usage=None if n==0 else {'input_tokens':1,'output_tokens':2}
                row={'status':'failed' if n==0 else 'completed','usage':usage,'global_key':key,
                    'prompt':prompt,'prompt_key':digest({'prompt':prompt,'kind':'U'})}
                journal[cid]=row;attempts.append({'id':cid})
                ledger['records'][key]={k:row[k] for k in ('status','usage','prompt_key')}
                ledger['records'][key].update(phase=f'r201/{arm}',send_confirmed=True)
            atomic_json(folder/'budgeted_evolution_requests.json',{'requests':journal})
            atomic_json(folder/'checkpoint.json',{'attempts':attempts,
                'inflight':{'id':'B/g0001/000000'} if arm=='B' else None})
            arms[arm]={'slots':count}
        atomic_json(self.peer/'protocol.json',p);atomic_json(self.peer/'budget.json',ledger)
        atomic_json(self.peer/'Update_status.json',seal({'kind':'Update_status','mode':'real','context':digest(p),
            'status':'stopped_or_not_started','stop_reason':'UNIT explicit stopped, no retry','arms':arms}))
        atomic_json(self.peer/'Final_budget_handoff.json',{'real_caller_active':False,'budget_identity':identity,
            'budget_sha256':old.common.sha(self.peer/'budget.json'),'summary':{'request_slots':30,'confirmed_sends':30}})
        self.config=local.Config.from_dict({**original,'experiment_version':local.VERSION,'real_requests_authorized':True,
            'platform_quota_ceiling':None,'platform_quota_reservation':None,
            'request_budget':{'version':'local-request-budget-v1','lifetime_request_cap':300,'history_source':{
                'directory':str(self.peer),'protocol_sha256':old.common.sha(self.peer/'protocol.json'),
                'budget_sha256':old.common.sha(self.peer/'budget.json')}},
            'fixed_h_source':{'version':'usage-frozen-H-source-v1','directory':str(old.common.RUN),
                'files_sha256':{n:old.common.sha(old.common.RUN/n) for n in ('protocol.json','H_frozen.json','Conditional_H_reassessment.json')}}})
        self.plan={'names':['UNIT_NO_SCHEDULE'],'dataset':p['dataset']}
        atomic_json(self.directory/'Plan.json',self.plan)
        initial=old.common.read(local.LEGACY/'Initial_population.json')
        atomic_json(self.directory/'Initial_population.json',initial)
        self.initial=initial
        self.before={str(f):(f.read_bytes(),f.stat().st_mtime_ns) for f in self.peer.rglob('*') if f.is_file()}
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('fjsp_usage.usage_v2.registration.worktree_roots',return_value=[self.root]))
        for name in ('socket.socket.connect','fjsp_usage.research_real.runtime.evaluate',
                     'tools.h01_weight_search.evaluate_weight','fjsp_usage.research_real.staged_evaluation.StagedDataset.load',
                     'fjsp_usage.research_real.conditional_research.history_summary',
                     'fjsp_usage.usage_v2.billing.InvoiceTransport.__init__',
                     'fjsp_usage.usage_v2.billing.query_invoices','fjsp_usage.research_real.leafapi.query_status',
                     'fjsp_usage.usage_v2.model_migration.check_live_tariff'):
            self.stack.enter_context(patch(name,side_effect=AssertionError('NO NETWORK / NO TRAIN / NO OLD FINANCE')))

    def unchanged(self):
        self.assertEqual(self.before,{str(f):(f.read_bytes(),f.stat().st_mtime_ns) for f in self.peer.rglob('*') if f.is_file()})

    def test_science_config_and_prompt_unchanged(self):
        original=old.common.read(local.LEGACY/'config.pending.json')
        self.assertEqual(local.science(self.config.payload()),local.science(original))
        for key,value in [('generations',1),('total_request_cap',21),('instance_timeout',30),('population_size',6)]:
            with self.assertRaises(ValueError):replace(self.config,**{key:value})
        members=tuple(Candidate(**v)
                      for v in old.common.read(local.LEGACY/'H_context.json'))
        for op,parents in [('CROSS',self.initial),('MUTATE',[self.initial[2]])]:
            prompt=old.build_prompt('B',op,parents,members)
            self.assertEqual(prompt,(local.LEGACY/'prompt_templates'/f'{op}.txt').read_text())
            self.assertNotIn('fitness:',prompt)

    def test_science_assets_and_data_pins_are_strict(self):
        plan=old.common.read(local.LEGACY/'Plan.json')
        changes=local.audit_legacy_inputs(plan)
        self.assertEqual({r['file'] for r in changes},set(local.REBIND)|{local.REPORT})
        sha=old.common.sha
        for target in ('code/fjsp_usage/usage_v2/execution.py','data/fjsp_manifest.json',
                       str((local.LEGACY/'Initial_population.json').relative_to(local.ROOT))):
            with patch.object(old.common,'sha',side_effect=lambda p: '0'*64 if str(p)==str(local.ROOT/target) else sha(p)):
                with self.assertRaisesRegex(ValueError,'scientific/input'):local.audit_legacy_inputs(plan)

    def test_stopped_30_handoff_and_readonly_history(self):
        audit=local.audit_peer(self.directory,self.config,self.plan)
        self.assertEqual(audit['native_slots'],30)
        self.assertEqual(audit['history']['historical_request_slots'],231)
        self.assertEqual(len(audit['prepared_only']),1);self.unchanged()

    def test_handoff_negative_native_and_live_writer(self):
        (self.peer/'.writer.lock').write_text('UNIT writer')
        with self.assertRaises(BudgetStop):local.audit_peer(self.directory,self.config,self.plan)
        (self.peer/'.writer.lock').unlink()
        p=self.peer/'r201/A/budgeted_evolution_requests.json';x=old.common.read(p)
        next(iter(x['requests'].values()))['usage']={'input_tokens':99,'output_tokens':1};atomic_json(p,x)
        with self.assertRaises(BudgetStop):local.audit_peer(self.directory,self.config,self.plan)

    def test_cumulative_limit_and_omitted_ledger(self):
        from fjsp_usage.research_real.budget import request_history
        foreign=self.root/'runs/foreign';foreign.mkdir()
        atomic_json(foreign/'budget.json',{'mode':'real','identity':'foreign','records':{'x':{}}})
        with self.assertRaises(BudgetStop):request_history(self.config,self.root,exclude=self.directory)
        (foreign/'budget.json').unlink()
        binding=self.protocol['config']['conditional_research']['history_binding']
        binding['historical_request_slots']=281
        self.protocol['config']['conditional_research']['history_binding']=seal({k:v for k,v in binding.items() if k!='artifact_sha256'})
        atomic_json(self.peer/'protocol.json',self.protocol)
        b=old.common.read(self.peer/'budget.json');b['identity']=digest({'config':self.protocol['config'],'context':digest(self.protocol)})
        atomic_json(self.peer/'budget.json',b)
        rb={**self.config.request_budget,'history_source':{'directory':str(self.peer),
            'protocol_sha256':old.common.sha(self.peer/'protocol.json'),'budget_sha256':old.common.sha(self.peer/'budget.json')}}
        with self.assertRaises(BudgetStop):request_history(replace(self.config,request_budget=rb),self.root,exclude=self.directory)

    def test_real_stages_require_new_approval(self):
        with patch.object(local,'check',return_value=(self.plan,self.config,())):
            for stage in ('grid','search'):
                with self.assertRaisesRegex(BudgetStop,'not authorized'):local.execute(self.directory,stage)
        self.unchanged()

    def test_no_child_survives_is_reported_without_model_gain(self):
        calls=[]
        def dispatch(inner,key,prompt,*,kind,on_sent):
            calls.append(key);on_sent()
            return {'text':'{HANDWRITTEN MOCK duplicate}\n```python\n'+old.constant(50).code+'```','usage':None}
        plan=old.common.read(local.LEGACY/'Plan.json');plan['budget_policy']='local-request-budget-v1'
        members=tuple(Candidate(**r) for r in old.common.read(local.LEGACY/'H_context.json'))
        (self.directory/'results').mkdir()
        for f in (local.LEGACY/'results').glob('*.json'):(self.directory/'results'/f.name).write_bytes(f.read_bytes())
        with patch.object(JsonCandidateTransport,'dispatch',dispatch),patch.dict('os.environ',{'LEAFAPI_API_KEY':'UNIT-NOT-A-KEY'}):
            t=local.client(self.directory,self.config,lambda:local.audit_peer(self.directory,self.config,self.plan))
            s,ledger=local.make_search(self.directory,self.config,plan,members,t,
                lambda _:self.fail('duplicate must not be evaluated'))
            s.run();self.assertEqual(len(calls),20)
            self.assertEqual({a['status'] for a in s.state['attempts']},{'duplicate'})
            from tools.h01_weight_report import report
            with patch.dict('sys.modules',{'reportlab':object()}),patch('tools.h01_weight_report.plot'):
                report(self.directory,out=self.directory/'UNIT_DUPLICATE_REPORT',plan_reader=lambda _:plan,version=local.VERSION)
            e=old.common.read(self.directory/'UNIT_DUPLICATE_REPORT/Evidence.json')
            self.assertIsNone(e['best_new'])
            self.assertEqual([g['new_children_survived'] for g in e['generation_rows']],[0,0,0])
            self.assertTrue(all(not g['champion_is_LLM_new'] for g in e['generation_rows']))
        self.unchanged()

    def test_two_generation_full_client_failure_duplicate_interrupt_resume(self):
        calls=[];evaluated=[];responses={};interrupted=[False]
        def dispatch(inner,key,prompt,*,kind,on_sent):
            self.assertEqual(kind,'U');calls.append(key);n=len(calls)
            if n==7:raise TransportError('UNIT failure before confirmed send')
            on_sent()
            if n==5:raise TransportError('UNIT sent timeout; unknown cost')
            if n==6 and not interrupted[0]:
                interrupted[0]=True;raise KeyboardInterrupt('UNIT process termination after send')
            if n==2:return {'text':'UNIT malformed','usage':None}
            if n==3:return responses[calls[0]]
            expression='0.123' if n==1 else f'min(1.0, progress + {n/1000})'
            code='def use_heuristics('+', '.join(old.U_ARGS)+'):\n    alpha = '+expression+'\n    return (1, (alpha, 1-alpha, 0,0,0,0,0,0,0,0))\n'
            reply={'text':'{HANDWRITTEN MOCK ONLY, NOT MODEL EVIDENCE}\n```python\n'+code+'```',
                   'usage':{'input_tokens':1,'output_tokens':2}}
            responses[key]=reply;return reply
        def evaluator(c):
            evaluated.append(c.key)
            if len(evaluated)==2:return {'valid':False,'fitness':None,'total_instances':1,'instances':[],
                'error_type':'UNITTimeout','failed_instance':'UNIT_NO_SCHEDULE','primary_evaluation_seconds':None}
            makespan=190-len(evaluated);score=-makespan/100
            return {'valid':True,'fitness':score,'total_instances':1,'primary_evaluation_seconds':.002,
                'instances':[{'file':'UNIT_NO_SCHEDULE','score':score,'makespan':makespan,'lower_bound':100,'feasible':True,
                    'single_solve_seconds':.001,'deterministic_recheck_seconds':.001,'single_h_calls':[1,1]+[0]*8,
                    'deterministic_recheck_h_calls':[1,1]+[0]*8,
                    'observed_alpha':[.123,.123] if 'alpha = 0.123' in c.code else [.2,.6]}]}
        with patch.object(JsonCandidateTransport,'dispatch',dispatch),patch.dict('os.environ',{'LEAFAPI_API_KEY':'UNIT-NOT-A-KEY'}):
            def engine():
                transport=local.client(self.directory,self.config,lambda:local.audit_peer(self.directory,self.config,self.plan))
                members=tuple(Candidate(**r) for r in old.common.read(local.LEGACY/'H_context.json'))
                return local.make_search(self.directory,self.config,self.plan,members,transport,evaluator)
            s,ledger=engine()
            with self.assertRaises(KeyboardInterrupt):s.run()
            self.assertEqual(len(calls),6)
            s,ledger=engine();s.run()
            self.assertEqual(s.state['phase'],'completed');self.assertEqual(len(calls),20)
            self.assertEqual(len(set(calls)),20);self.assertEqual(len(ledger.data['records']),20)
            self.assertEqual(len(s.state['attempts']),20)
            statuses={a['status'] for a in s.state['attempts']}
            self.assertTrue({'valid','invalid','duplicate','failed','interrupted','parse_or_constraint_error'} <= statuses)
            second=[a for a in s.state['attempts'] if '/g0001/' in a['id']]
            self.assertTrue(any('/g0000/' in p for a in second for p in a['parents']))
            for gen in (0,1):
                rows=[a for a in s.state['attempts'] if f'/g{gen:04d}/' in a['id']]
                self.assertEqual([a['operator'] for a in rows],['CROSS']*5+['MUTATE']*5)
                self.assertEqual(len(rows),10)
            s.run();self.assertEqual(len(calls),20)
            with self.assertRaises(BudgetStop):ledger.reserve('extra',old.PHASE,'unit')
            summary=ledger.summary();self.assertIsNone(summary['actual_cost'])
            self.assertEqual(summary['lifetime_request_slots'],251)
            self.assertGreater(summary['unknown_usage_requests'],0)
            self.assertFalse(ledger.data['records'][calls[6]]['send_confirmed'])
            self.assertTrue(ledger.data['records'][calls[4]]['send_confirmed'])
            atomic_json(self.directory/'Budget_summary.json',summary)
            self.assertFalse((self.directory/'billing').exists());self.assertFalse((self.directory/'platform_quota.json').exists())
            # Full report also consumes only explicit mock scores and never
            # invokes an evaluator. These fictitious grid rows live in temp.
            p={**old.common.read(local.LEGACY/'Plan.json'),'names':['UNIT_NO_SCHEDULE'],'budget_policy':'local-request-budget-v1'}
            (self.directory/'results').mkdir()
            for v in p['versions']:
                atomic_json(self.directory/'results'/f'{v["id"]}.json',{'valid':True,'fitness':-2.,'total_instances':1,
                    'primary_evaluation_seconds':.002,'instances':[{'file':'UNIT_NO_SCHEDULE','makespan':200,
                        'lower_bound':100,'score':-2.,'single_solve_seconds':.001,'deterministic_recheck_seconds':.001}]})
            from tools.h01_weight_report import report
            with patch.dict('sys.modules',{'reportlab':object()}),patch('tools.h01_weight_report.plot'):
                report(self.directory,out=self.directory/'UNIT_FULL_REPORT',plan_reader=lambda _:p,version=local.VERSION)
            evidence=old.common.read(self.directory/'UNIT_FULL_REPORT/Evidence.json')
            self.assertIsNotNone(evidence['best_new_constant']);self.assertIsNotNone(evidence['best_new_dynamic'])
            self.assertIsNone(evidence['actual_cost']);self.assertEqual(len(evidence['generation_rows']),3)
            self.assertGreater(evidence['generation_rows'][2]['parents_from_previous_generation_children'],0)
            self.assertGreater(evidence['generation_rows'][2]['parent_uses_of_previous_improving_children'],0)
            self.assertIn('survived_generation',(self.directory/'UNIT_FULL_REPORT/Lineage.csv').read_text())
        self.unchanged()

    def test_report_local_unknown_cost_and_initial_not_model_gain(self):
        from tools.h01_weight_report import report
        plan=old.common.read(local.LEGACY/'Plan.json');plan['budget_policy']='local-request-budget-v1'
        d=self.directory
        (d/'results').mkdir();(d/'sources').mkdir()
        for p in (local.LEGACY/'results').glob('*.json'):(d/'results'/p.name).write_bytes(p.read_bytes())
        with patch.dict('sys.modules',{'reportlab':object()}),patch('tools.h01_weight_report.plot'):
            out=d/'UNIT_REPORT';report(d,out=out,plan_reader=lambda _:plan,version=local.VERSION)
        e=old.common.read(out/'Evidence.json')
        self.assertIsNone(e['known_actual_platform_points']);self.assertIsNone(e['best_new'])
        self.assertEqual(e['initial_champion'],'MANUAL/init/alpha_050')
        self.assertFalse(e['fixed_grid_complete']);self.assertIn('unknown/null',(out/'Report.md').read_text())


if __name__=='__main__':unittest.main()
