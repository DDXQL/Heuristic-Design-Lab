"""Mock dispatch only: no provider/metadata calls, no benchmark evaluation."""
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.budget import (BudgetJournal, BudgetLedger, BudgetStop,
    REQUEST_BUDGET_VERSION, request_history)
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.real_transport import JsonCandidateTransport, TransportError
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research.candidates import Candidate, U_ARGS, validate_code
from fjsp_usage.research_real.search import V5BudgetedSearch


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LocalRequestBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'requirements.txt').write_text('# handwritten unit fixture\n')
        self.source = self.root/'runs'/'legacy-paused'
        self.source.mkdir(parents=True)
        self.prior_slots = 0
        self.make_history()
        manifest = self.root/'handwritten-manifest.json'
        manifest.write_text('{}')
        self.dataset = SimpleNamespace(path=manifest, metadata={'manifest_sha256':sha(manifest)})
        self.directory = self.root/'runs'/'new-local-protocol'
        for target in ('socket.socket.connect',
                'fjsp_usage.research_real.quota_guard.QuotaGuardedTransport.__init__',
                'fjsp_usage.usage_v2.billing.InvoiceTransport.__init__',
                'fjsp_usage.usage_v2.billing.query_invoices',
                'fjsp_usage.usage_v2.model_migration.check_live_tariff',
                'fjsp_usage.usage_v2.registration.SerialGuard.check'):
            p = patch(target, side_effect=AssertionError('NO NETWORK/METADATA IN THIS TEST'))
            p.start(); self.addCleanup(p.stop)
        p = patch('fjsp_usage.usage_v2.registration.worktree_roots', return_value=[self.root])
        p.start(); self.addCleanup(p.stop)
        p = patch.dict('os.environ', {'FJSP_HANDWRITTEN_TEST_KEY':'not-a-real-key'})
        p.start(); self.addCleanup(p.stop)

    def make_history(self):
        binding = seal({'kind':'Fair_history_binding', 'mode':'real', 'lifetime_request_cap':300,
            'historical_request_slots':self.prior_slots, 'historical_confirmed_sends':self.prior_slots,
            'real_budget_inventory':{}, 'retained_account_hold':24000000})
        protocol = {'config':{'conditional_research':{'history_binding':binding}}}
        atomic_json(self.source/'protocol.json', protocol)
        identity = digest({'config':protocol['config'], 'context':digest(protocol)})
        atomic_json(self.source/'budget.json', {'identity':identity, 'mode':'real', 'halted':True,
            'records':{'OLD/unknown':{'status':'failed', 'send_confirmed':True, 'usage':None,
                'reservation':{'input_tokens':65536, 'output_tokens':32768}}}})
        atomic_json(self.source/'platform_quota.json', {'halted':True,
            'records':{'OLD/unknown':{'status':'pending', 'reserved':12000000}}})
        atomic_json(self.source/'checkpoint.json', {'cursor':30, 'A':20, 'B':10})

    def config(self, **changes):
        return ExperimentConfig(provider=ProviderConfig('https://leafapi.cc/v1/chat/completions',
            'gpt-6.1-sol', api_key_env='FJSP_HANDWRITTEN_TEST_KEY', protocol='openai-chat-v1'),
            mode='real', real_requests_authorized=True,
            H_size=2, H_initialization_cap=3, population_size=3, cross_parents=2,
            attempts_per_generation=10, generations=1, initialization_cap=3, seeds=(1,),
            total_request_cap=3, request_budget={'version':REQUEST_BUDGET_VERSION,
                'lifetime_request_cap':300, 'history_source':{'directory':str(self.source),
                    'protocol_sha256':sha(self.source/'protocol.json'),
                    'budget_sha256':sha(self.source/'budget.json')}}, **changes)

    def flow(self, config=None, directory=None):
        return Workflow(directory or self.directory, config=config or self.config(),
            dataset=self.dataset, project_root=self.root)

    def journal(self, flow, cap=10):
        return BudgetJournal(flow.directory/'r1/P/requests.json', phase='r1/P', cap=cap,
            transport=flow.client(), ledger=flow.ledger)

    def mock_reply(self, usage=None):
        calls = []
        def dispatch(inner, key, prompt, *, kind, on_sent):
            calls.append((key, prompt, kind)); on_sent()
            return {'text':'HANDWRITTEN response; not an experimental candidate', 'usage':usage,
                    'metadata':{'gateway_request_id':'handwritten-request-id', 'response_model':'gpt-6.1-sol'}}
        return calls, patch.object(JsonCandidateTransport, 'dispatch', dispatch)

    def test_normal_path_no_metadata_response_usage_and_completed_resume(self):
        before = {p.name:(p.read_bytes(), p.stat().st_mtime_ns) for p in self.source.iterdir()}
        usage = {'input_tokens':31, 'output_tokens':17}
        calls, wire = self.mock_reply(usage)
        with wire:
            flow = self.flow(); journal = self.journal(flow)
            row = journal.request('U/000000', 'unaltered prompt')
            self.assertEqual(row['usage'], usage)
            self.assertEqual(row['response_metadata']['gateway_request_id'], 'handwritten-request-id')
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(self.journal(self.flow()).request('U/000000', 'unaltered prompt'), row)
        self.assertEqual(len(calls), 1)
        summary = flow.ledger.summary()
        self.assertEqual((summary['request_slots'], summary['lifetime_request_slots']), (1,2))
        self.assertEqual((summary['known_input_tokens'], summary['known_output_tokens']), (31,17))
        self.assertIsNone(summary['actual_cost'])
        self.assertFalse(summary['account_amount_limit_enforced'])
        saved = json.loads(next((flow.directory/'wire_responses').glob('*.json')).read_text())
        self.assertEqual(saved['reply']['usage'], usage)
        self.assertFalse((flow.directory/'platform_quota.json').exists())
        self.assertFalse((flow.directory/'billing').exists())
        self.assertEqual(before, {p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir()})

    def test_missing_usage_remains_unknown_and_hard_cap_stops(self):
        calls, wire = self.mock_reply()
        with wire:
            flow = self.flow(); journal = self.journal(flow)
            for i in range(3):
                self.assertIsNone(journal.request(str(i), 'prompt')['usage'])
            with self.assertRaises(BudgetStop): journal.request('extra', 'prompt')
        self.assertEqual(len(calls), 3)
        summary = flow.ledger.summary()
        self.assertEqual(summary['unknown_usage_requests'], 3)
        self.assertEqual(summary['confirmed_sends'], 3)
        self.assertIsNone(summary['actual_cost'])
        self.assertIsNone(summary['known_usage_cost_estimate'])

    def test_failure_timeout_and_uncertain_send_consume_slots_without_retry(self):
        calls = []
        def dispatch(inner, key, prompt, *, kind, on_sent):
            calls.append(key)
            if not key.endswith('uncertain'): on_sent()
            raise TransportError('timeout or ordinary request failure; usage unknown')
        with patch.object(JsonCandidateTransport, 'dispatch', dispatch):
            flow = self.flow(); journal = self.journal(flow)
            for key in ('failed', 'timeout', 'uncertain'):
                row = journal.request(key, 'prompt')
                self.assertEqual(row['status'], 'failed')
                self.assertIsNone(row['usage'])
                self.assertEqual(self.journal(self.flow()).request(key, 'prompt'), row)
            with self.assertRaises(BudgetStop): journal.request('fourth', 'prompt')
        self.assertEqual(len(calls), 3)
        self.assertEqual(flow.ledger.summary()['confirmed_sends'], 2)
        self.assertEqual(flow.ledger.summary()['request_slots'], 3)

    def test_duplicate_ids_changed_prompt_and_wire_identity_are_rejected(self):
        calls, wire = self.mock_reply()
        with wire:
            flow = self.flow(); journal = self.journal(flow)
            journal.request('same', 'original')
            with self.assertRaises(ValueError): journal.request('same', 'changed')
            with self.assertRaises(BudgetStop):
                flow.client().dispatch('r1/P/same', 'original')
        self.assertEqual(len(calls), 1)

    def test_interrupted_and_orphan_reservations_never_resend(self):
        flow = self.flow(); journal = self.journal(flow)
        pkey = digest({'prompt':'p', 'kind':'U'})
        for key in ('pending', 'orphan'):
            flow.ledger.reserve('r1/P/'+key, 'r1/P', pkey)
            flow.ledger.confirm_send('r1/P/'+key)
        journal.data['requests']['pending'] = {'status':'pending','prompt_key':pkey,'usage':None}
        atomic_json(journal.path, journal.data)
        with patch.object(JsonCandidateTransport, 'dispatch', side_effect=AssertionError('NO REPLAY')):
            restored = self.journal(self.flow())
            for key in ('pending', 'orphan'):
                self.assertEqual(restored.request(key, 'p')['status'], 'interrupted')
        self.assertEqual(flow.ledger.summary()['request_slots'], 2)
        self.assertIsNone(json.loads(flow.ledger.path.read_text())['records']['r1/P/pending']['usage'])

    def test_global_phase_and_lifetime_caps_are_distinct(self):
        self.prior_slots = 298; self.make_history()  # + one native unknown = 299
        c = replace(self.config(), total_request_cap=1)
        calls, wire = self.mock_reply()
        with wire:
            flow = self.flow(c); journal = self.journal(flow)
            journal.request('last', 'p')
            self.assertEqual(flow.ledger.summary()['lifetime_request_slots'], 300)
            with self.assertRaises(BudgetStop): journal.request('beyond', 'p')
        self.assertEqual(len(calls), 1)
        with self.assertRaises(BudgetStop): self.flow(self.config(), self.root/'runs/over-lifetime')
        self.assertFalse((self.root/'runs/over-lifetime/protocol.json').exists())

    def test_phase_cap_stops_without_extra_send(self):
        c = self.config(); caps = c.phase_caps()
        caps.update({p:1 for p in caps if p.endswith(('/P','/B0','/B1','/B2'))})
        c = replace(c, phase_request_caps=caps)
        calls, wire = self.mock_reply()
        with wire:
            journal = self.journal(self.flow(c)); journal.request('one', 'p')
            with self.assertRaises(BudgetStop): journal.request('two', 'p')
        self.assertEqual(len(calls), 1)

    def test_no_switching_old_directory_or_protocol_identity(self):
        old = (self.source/'protocol.json').read_bytes()
        with self.assertRaises(ValueError): self.flow(directory=self.source)
        self.assertEqual(old, (self.source/'protocol.json').read_bytes())
        flow = self.flow()
        with self.assertRaises(ValueError): self.flow(replace(flow.config, instance_timeout=16))
        with self.assertRaises(ValueError):
            BudgetLedger(flow.directory/'budget.json', replace(flow.config,total_request_cap=2), flow.context)

    def test_changed_or_unaccounted_local_history_stops_without_metadata(self):
        flow = self.flow()
        peer = self.root/'runs/peer'; peer.mkdir()
        atomic_json(peer/'budget.json', {'mode':'real','identity':'unaccounted',
            'records':{'one':{'send_confirmed':True}}})
        with self.assertRaises(BudgetStop): flow.client()
        (peer/'budget.json').unlink()
        (self.source/'budget.json').write_text('{}')
        with self.assertRaises(BudgetStop): flow.client()

    def test_next_new_directory_inherits_new_policy_without_resetting_counts(self):
        calls, wire = self.mock_reply()
        with wire:
            first = self.flow(); self.journal(first).request('first', 'p')
        policy = deepcopy(first.config.request_budget)
        policy['history_source'] = {'directory':str(first.directory),
            'protocol_sha256':sha(first.directory/'protocol.json'), 'budget_sha256':sha(first.directory/'budget.json')}
        c = replace(first.config, request_budget=policy)
        second = self.flow(c, self.root/'runs/next-independent')
        self.assertNotEqual(first.context, second.context)
        self.assertEqual(second.ledger.summary()['historical_request_slots'], 2)
        self.assertEqual(first.ledger.summary()['request_slots'], 1)

    def test_explicit_new_mode_cannot_migrate_legacy_config_or_change_science(self):
        c = self.config(); p = c.payload()
        p.pop('request_budget')
        legacy = ExperimentConfig.from_dict(p)
        self.assertNotIn('request_budget', legacy.payload())
        self.assertEqual(p, legacy.payload())
        self.assertEqual(c.provider, legacy.provider)
        self.assertEqual(c.u_search(1), legacy.u_search(1))
        self.assertEqual(c.phase_caps(), legacy.phase_caps())
        for changes in ({'platform_quota_ceiling':30000000, 'platform_quota_reservation':1000000},
                        {'development_continuation_source':{'not':'a migration'}}):
            with self.assertRaises(ValueError): replace(c, **changes)
        for policy in (None, {'version':'bad','lifetime_request_cap':300,'history_source':None}):
            if policy is None:
                b = deepcopy(c.request_budget); b['history_source'] = None
            else: b = policy
            with self.assertRaises(ValueError): replace(c, request_budget=b)

    def test_real_search_checkpoint_resumes_with_same_prompts_and_no_repeat_evaluation(self):
        """Real search/parse/survival code; all scores and replies are handwritten toy fixtures."""
        c = replace(self.config(), total_request_cap=10)
        flow = self.flow(c)
        args = ', '.join(U_ARGS)
        initial = []
        for i, body in enumerate(('return 0', 'return 1', 'return int(progress > 0.5)')):
            candidate = validate_code(f'def select_heuristic({args}):\n    {body}\n', kind='U',
                                      description='HANDWRITTEN unit fixture')
            initial.append({'id':f'INIT/init/{i:06d}', 'candidate':asdict(candidate),
                            'fitness':-2-i, 'scores':[-2-i]})
        members = [Candidate('HANDWRITTEN H fixture','fixture display only',str(i),'h') for i in range(2)]
        calls, evaluations = [], []
        def dispatch(inner, key, prompt, *, kind, on_sent):
            calls.append((key,prompt)); on_sent()
            i = int(key.split('/')[-1])+1
            code = f'def select_heuristic({args}):\n    return int(progress > {i/100})\n'
            return {'text':'{HANDWRITTEN UNIT FIXTURE, not model evidence.}\n```python\n'+code+'```',
                    'usage':{'input_tokens':2,'output_tokens':4}}
        def evaluate(candidate):
            evaluations.append(candidate.key)
            return {'valid':True,'total_instances':1,'fitness':-1.,
                    'instances':[{'file':'HANDWRITTEN_TOY','makespan':2,'lower_bound':2.,
                                  'score':-1.,'feasible':True}]}
        def engine(current):
            return V5BudgetedSearch(current.directory/'r1/P', arm='P', config=c.u_search(1),
                members=members, evaluator=evaluate, transport=current.client(), context=current.context,
                initial=deepcopy(initial), kind='U', init_phase='r1/init', search_phase='r1/P',
                ledger=current.ledger, experiment=c, training_names=('HANDWRITTEN_TOY',))
        with patch.object(JsonCandidateTransport, 'dispatch', dispatch):
            first = engine(flow); first.run(stop_after_attempts=4)
            checkpoint = digest(first.state)
            resumed = engine(self.flow(c))
            self.assertEqual(digest(resumed.state), checkpoint)
            resumed.run()
            final = digest(resumed.state)
            completed = engine(self.flow(c)); completed.run()
            self.assertEqual(digest(completed.state), final)
        self.assertEqual(len(calls), 10)
        self.assertEqual(len(set(k for k,p in calls)), 10)
        self.assertEqual(len(evaluations), 10)
        self.assertEqual(completed.state['phase'], 'completed')
        self.assertEqual([r['operator'] for r in completed.state['attempts']], ['CROSS']*5+['MUTATE']*5)
        self.assertEqual(len(completed.state['population']), 3)
        self.assertEqual(len(completed.export_rows()), 3)

    def usage_config(self):
        from fjsp_usage.usage_v2.config import UsageConfig, LOCAL_REQUEST_EXPERIMENT
        data=self.config().payload()
        data.update(population_size=5,cross_parents=5,initialization_cap=20,total_request_cap=40,
                    usage_experiment_version=LOCAL_REQUEST_EXPERIMENT)
        return UsageConfig.from_dict(data)

    def test_select_mix_clients_bypass_all_legacy_metadata_gates(self):
        from fjsp_usage.usage_v2.workflow import UsageWorkflow
        from fjsp_usage.usage_v2.registration import RegisteredUsageWorkflow
        config=self.usage_config()
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir()}
        flow=UsageWorkflow(self.directory,config=config,dataset=self.dataset,project_root=self.root)
        flow.client()  # No V22 binding, account or invoice evidence is required.
        registered=RegisteredUsageWorkflow(self.directory,config=config,dataset=self.dataset,project_root=self.root)
        calls,wire=self.mock_reply({'input_tokens':7,'output_tokens':3})
        with wire:
            journal=BudgetJournal(self.directory/'r1/B/requests.json',phase='r1/B',cap=10,
                transport=registered.client(),ledger=registered.ledger)
            journal.request('B/g0000/000000','exact original prompt')
            journal.request('B/g0000/000000','exact original prompt')
        self.assertEqual(len(calls),1)
        self.assertFalse((self.directory/'V22_binding.json').exists())
        self.assertFalse((self.directory/'platform_quota.json').exists())
        self.assertFalse((self.directory/'billing').exists())
        self.assertEqual(before,{p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in self.source.iterdir()})

    def test_usage_modes_prompts_and_evaluator_parameters_are_unchanged(self):
        from fjsp_usage.usage_v2.workflow import UsageWorkflow
        from fjsp_usage.usage_v2.config import UsageConfig, LOCAL_REQUEST_EXPERIMENT, protocol
        from fjsp_usage.usage_v2.prompts import build_prompt
        provider=ProviderConfig('http://localhost:9','handwritten-offline')
        old=UsageConfig(provider=provider,H_size=2,population_size=3,cross_parents=2,
            generations=1,attempts_per_generation=10,initialization_cap=20,seeds=(101,),total_request_cap=40)
        new=replace(old,
            usage_experiment_version=LOCAL_REQUEST_EXPERIMENT,
            request_budget={'version':REQUEST_BUDGET_VERSION,'lifetime_request_cap':300,'history_source':None})
        self.assertEqual(new.provider,old.provider)
        self.assertEqual(new.u_search(new.seeds[0]),old.u_search(old.seeds[0]))
        old_protocol=protocol(old,{},{});new_protocol=protocol(new,{},{})
        for key in ('prompt_pack','language','state_contract','u_interface','actions','fitness','evaluation_deadlines','arm_modes'):
            self.assertEqual(old_protocol[key],new_protocol[key])
        members=[Candidate('unchanged handwritten H fixture','unchanged code',str(i),'h') for i in range(2)]
        parents=[{'id':str(i),'candidate':{'description':'fixture','code':'unchanged parent source'}} for i in range(3)]
        self.dataset.names={'train':('HANDWRITTEN_TOY',)}
        flow=UsageWorkflow(self.directory,config=new,dataset=self.dataset,project_root=self.root)
        with patch.object(flow,'train_eval',return_value={'unit_fixture':True}) as evaluate:
            for arm,modes in (('A',(0,)),('B',(0,1))):
                engine=flow.search_engine('r101/'+arm,arm,members,new.u_search(101),'r101/init','r101/'+arm)
                self.assertEqual(engine._build_prompt(arm,'CROSS',parents,members),build_prompt(arm,'CROSS',parents,members))
                engine.evaluator(members[0])
                self.assertEqual(evaluate.call_args.kwargs['allowed_modes'],modes)

    def test_select_mix_local_preflight_is_offline_and_new_directory_only(self):
        from experiments.tier2.usage_v2 import run
        from contextlib import redirect_stdout,redirect_stderr
        import io
        config_path=self.root/'new-config.json'
        atomic_json(config_path,self.usage_config().payload())
        dataset=SimpleNamespace(path=self.dataset.path,metadata=self.dataset.metadata,opened=[])
        argv=['run.py','local-preflight','--run-dir',str(self.directory),'--config',str(config_path)]
        with patch.object(run,'ROOT',self.root.resolve()),patch.object(run,'StagedDataset',return_value=dataset),\
                patch('sys.argv',argv),patch.object(run.UsageWorkflow,'client',side_effect=AssertionError('no client')),\
                redirect_stdout(io.StringIO()) as stdout,redirect_stderr(io.StringIO()):
            run.main()
            result=json.loads(stdout.getvalue())
            self.assertEqual(result['metadata_queries'],0)
            self.assertEqual(result['model_requests'],0)
            with self.assertRaises(SystemExit):run.main()


if __name__ == '__main__':
    unittest.main()
