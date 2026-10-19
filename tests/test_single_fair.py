"""Offline gate/transport fixtures; no HTTP, benchmark solves or genuine U generation."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'experiments/tier2/research_real_v1'))
from run_single_fair import prepare, check_preparation, register, execute, run_training
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.budget import BudgetJournal, BudgetLedger, BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.single_billing import InvoiceTransport
from fjsp_usage.research_real.single_fair import (AUTH_SCOPE, FairQuota, FairWorkflow, bind_history,
    file_sha, history_summary, pending_config, source_bundle)
from fjsp_usage.research_real.single_io import install_protections
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.workflow import Workflow


class FairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=pending_config(ROOT,'single-ID-gpt61-paired-training-20261014-v1')
        # Exercise the old registration under its archived implementation
        # identity. New-version config routing intentionally invalidates a live
        # old-run fingerprint; production gates are never relaxed for this.
        snapshot=json.loads((ROOT/'runs'/cls.config.conditional_research['source_run']/'protocol.json').read_text())['implementation']
        cls.source_snapshot_patch=patch('fjsp_usage.research_real.single_fair.fingerprint',return_value=snapshot)
        cls.source_snapshot_patch.start();cls.addClassCleanup(cls.source_snapshot_patch.stop)
        cls.dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        cls.docs,cls.members=source_bundle(ROOT,cls.config,cls.dataset)
        cls.expected=dict(cls.docs['Worktree_binding.json']['real_budget_inventory'])
        folder=ROOT/'runs'/cls.config.conditional_research['source_run']
        cls.expected[cls.docs['budget.json']['identity']]=file_sha(folder/'budget.json')

    def setUp(self):
        # Defense against accidental network paths, including in registration.
        self.no_network=patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK IN OFFLINE TEST'))
        self.no_network.start();self.addCleanup(self.no_network.stop)

    def binding(self,extra=(),expected=None):
        return bind_history(ROOT,self.config,self.dataset,extra,inventory=lambda:expected or self.expected)

    def authorized(self,binding=None):
        p=self.config.payload();p['real_requests_authorized']=True
        p['conditional_research'].update(history_binding=binding or self.binding(),authorization={
            'approved':True,'reviewer':'HANDWRITTEN TEST FIXTURE (not DDXQL approval)',
            'scope':AUTH_SCOPE,'pending_config_sha256':digest(self.config.payload()),
            'max_new_requests':60,'exclusive_caller_branch':'codex/u-single-experiments'})
        return ExperimentConfig.from_dict(p)

    def peer(self,folder,count=2,*,pending=False):
        folder=Path(folder);folder.mkdir()
        rows={str(i):{'status':'reserved' if pending else 'failed','send_confirmed':True,
            'usage':None,'reservation':{'input_tokens':65536,'output_tokens':32768}} for i in range(count)}
        atomic_json(folder/'budget.json',{'identity':'handwritten-extra-ledger','mode':'real','records':rows})
        accounts={k:{'status':'pending' if pending else 'settled','send_confirmed':True,
            'before_used':100,'after_used':107,'observed_account_delta':7,'started_at':1,'finished_at':3}
            for k in rows}
        atomic_json(folder/'platform_quota.json',{'observed_used':1700000,'records':accounts})
        (folder/'billing').mkdir()
        import hashlib
        for key in rows:
            invoice={'request_id':'fixture-'+key,'model_name':'gpt-6.1-sol','type':2,'quota':7,
                     'created_at':2,'group':'codex-deafult'}
            atomic_json(folder/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json'),{
                'status':'invoice_account_matched','before':{'success':True,'records':[]},
                'after':{'success':True,'records':[invoice]},'transport_status':'failed',
                'response_metadata':{'gateway_request_id':invoice['request_id']}})
        handoff={'real_caller_active':False,'quota_halted':False,'unknown_new_fee_keys':[],
            'unknown_new_fee_holds':0,'old_account_hold':24000000,'budget_identity':'handwritten-extra-ledger',
            'budget_sha256':file_sha(folder/'budget.json'),'summary':{'request_slots':count,'confirmed_sends':count},
            'latest_verified_used_points':1700000,'known_new_points':7*count}
        atomic_json(folder/'Final_budget_handoff.json',handoff)
        atomic_json(folder/'Metadata_global_pacing.json',{'last_finished_at':200})
        atomic_json(folder/'Invoice_query_pacing.json',{'last_finished_at':190})
        inventory={**self.expected,'handwritten-extra-ledger':file_sha(folder/'budget.json')}
        return (folder,folder/'Final_budget_handoff.json'),inventory

    def test_pending_source_evidence_without_eval_client_or_holdout(self):
        self.assertFalse(self.config.real_requests_authorized)
        self.assertEqual(self.config.total_request_cap,60)
        self.assertEqual(self.config.phase_caps()['r201/B0'],10)
        self.assertNotIn('r201/diagnostic',self.config.phase_caps())
        with tempfile.TemporaryDirectory() as tmp,patch.object(Workflow,'train_eval',side_effect=AssertionError('NO REEVALUATION')),\
                patch.object(FairWorkflow,'client',side_effect=AssertionError('NO CLIENT')):
            folder=Path(tmp)/'prepared'
            prepare(folder,self.config,self.dataset)
            c,_=check_preparation(folder)
            self.assertFalse(c.real_requests_authorized)
            self.assertFalse((folder/'budget.json').exists())
            self.assertFalse((folder/'protocol.json').exists())
            self.assertEqual(json.loads((folder/'H_source_binding.json').read_text())['code_keys'],
                             [m.key for m in self.members])
            self.assertEqual(json.loads((folder/'Preparation.json').read_text())['H_reevaluations'],0)

    def test_new_scope_does_not_allow_silent_scale_model_or_output_change(self):
        for field,value in [('seeds',[202]),('total_request_cap',61),('population_size',4)]:
            p=self.config.payload();p[field]=value
            with self.assertRaises(ValueError):ExperimentConfig.from_dict(p)
        changed=replace(self.config,provider=replace(self.config.provider,max_output_tokens=4096))
        with self.assertRaisesRegex(ValueError,'semantics differ'):source_bundle(ROOT,changed,self.dataset)
        caps=self.config.default_phase_caps();caps['r201/init']=10
        with self.assertRaises(ValueError):replace(self.config,phase_request_caps=caps)

    def test_old_identity_rejects_new_config_routing_without_snapshot_fixture(self):
        from fjsp_usage.research_real.config import fingerprint
        with patch('fjsp_usage.research_real.single_fair.fingerprint',return_value=fingerprint(ROOT)):
            with self.assertRaisesRegex(ValueError,'semantic change'):
                source_bundle(ROOT,self.config,self.dataset)

    def test_offline_registration_rebinds_H_but_does_not_copy_old_U_or_create_client(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(Workflow,'train_eval',side_effect=AssertionError('NO H REEVALUATION')),\
                patch.object(FairWorkflow,'client',side_effect=AssertionError('NO CLIENT')):
            folder=Path(tmp)/'prepared';prepare(folder,self.config,self.dataset)
            approval=Path(tmp)/'fixture-approval.json'
            atomic_json(approval,self.authorized().conditional_research['authorization'])
            with patch('run_single_fair.bind_history',return_value=self.binding()):register(folder,approval,[])
            c=ExperimentConfig.from_dict(json.loads((folder/'config.single.authorized.json').read_text()))
            flow=FairWorkflow(folder,config=c,dataset=self.dataset,project_root=ROOT)
            H,members=flow.h_asset()
            self.assertEqual(H['members'],self.docs['H_frozen.json']['members'])
            self.assertNotEqual(H['context'],self.docs['H_frozen.json']['context'])
            self.assertEqual([m.key for m in members],[m.key for m in self.members])
            self.assertEqual(flow.ledger.data['records'],{})
            self.assertFalse((folder/'r201/Shared_initial.json').exists())
            self.assertFalse((folder/'platform_quota.json').exists())
            with self.assertRaises(ValueError):register(folder,approval,[])

    def test_false_or_missing_authorization_cannot_reach_credential_or_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            atomic_json(folder/'config.single.authorized.json',self.config.payload())
            with patch('run_single_fair.load_local_key',side_effect=AssertionError('NO KEY READ')),\
                    patch.object(FairWorkflow,'client',side_effect=AssertionError('NO CLIENT')),self.assertRaises(ValueError):
                execute(folder,Path('nonexistent-secret'))
        with self.assertRaises(BudgetStop):history_summary(ROOT,self.config)
        p=self.config.payload();p['real_requests_authorized']=True
        with self.assertRaises(ValueError):ExperimentConfig.from_dict(p)

    def test_inherits_base128_without_double_count_and_keeps_unknown_charges(self):
        b=self.binding()
        self.assertEqual(b['historical_request_slots'],128)
        self.assertEqual(b['historical_confirmed_sends'],112)
        self.assertEqual(b['retained_account_hold'],24000000)
        self.assertEqual(len(b['historical_token_charges']),128)
        self.assertTrue(any(x['input_tokens']==65536 and x['output_tokens']==32768 for x in b['historical_token_charges']))

    def test_additional_final_ledger_counted_once_and_pacing_inherited(self):
        with tempfile.TemporaryDirectory() as tmp:
            peer,inventory=self.peer(Path(tmp)/'peer')
            b=self.binding([peer],inventory)
            self.assertEqual(b['historical_request_slots'],130)
            self.assertEqual(b['retained_account_hold'],24000000)
            self.assertEqual(len(b['historical_token_charges']),130)
            self.assertGreaterEqual(b['metadata_floor'],200)
            with self.assertRaises(BudgetStop):self.binding([peer,peer],inventory)
            (peer[0]/'budget.json').write_text('{}')
            with self.assertRaisesRegex(BudgetStop,'handoff/ledger changed'):history_summary(ROOT,self.authorized(b))

    def test_peer_pending_unknown_fee_writer_and_unregistered_consumption_reject(self):
        for kind in ('pending','unknown','writer','inventory'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as tmp:
                peer,inventory=self.peer(Path(tmp)/'peer',pending=kind=='pending')
                if kind=='unknown':
                    h=json.loads(peer[1].read_text());h['unknown_new_fee_keys']=['unknown'];atomic_json(peer[1],h)
                if kind=='writer':(peer[0]/'.writer.lock').write_text('{}')
                if kind=='inventory':inventory['unregistered']='different'
                with self.assertRaises(BudgetStop):self.binding([peer],inventory)

    def test_peer_claimed_zero_unknown_does_not_replace_actual_invoice_proof(self):
        for cause in ('missing_receipt','wrong_cost','wrong_group'):
            with self.subTest(cause=cause),tempfile.TemporaryDirectory() as tmp:
                peer,inventory=self.peer(Path(tmp)/'peer')
                bill=next((peer[0]/'billing').glob('*.json'))
                if cause=='missing_receipt':bill.unlink()
                if cause=='wrong_cost':
                    h=json.loads(peer[1].read_text());h['known_new_points']=0;atomic_json(peer[1],h)
                if cause=='wrong_group':
                    h=json.loads(bill.read_text());h['after']['records'][0]['group']='wrong';atomic_json(bill,h)
                with self.assertRaises((BudgetStop,FileNotFoundError)):self.binding([peer],inventory)

    def test_cumulative_cap_and_H_generation_are_not_released(self):
        with tempfile.TemporaryDirectory() as tmp:
            peer,inventory=self.peer(Path(tmp)/'peer',count=120)
            with self.assertRaisesRegex(BudgetStop,'cumulative slots'):self.binding([peer],inventory)
        from fjsp_usage.research_real.single_fair import budget_check
        config=self.authorized()
        ledger=SimpleNamespace(path=ROOT/'runs/fixture/budget.json',config=config,data={'records':{}})
        with self.assertRaises(BudgetStop):budget_check(ledger,'H/fixture','H/init')

    def test_driver_stops_all_arms_and_initial_shortage_without_refill(self):
        flow=SimpleNamespace(initialize_u=Mock(return_value={'status':'initialized'}),
            search_arm=Mock(return_value={'status':'budget_stopped'}),search_all=Mock())
        with self.assertRaises(BudgetStop):run_training(flow)
        flow.search_arm.assert_called_once_with(201,'B0');flow.search_all.assert_not_called()
        flow.initialize_u.return_value={'status':'initialization_failed'};flow.search_arm.reset_mock()
        with self.assertRaises(BudgetStop):run_training(flow)
        flow.search_arm.assert_not_called()
        flow.initialize_u.return_value={'status':'initialized'}
        flow.search_arm.return_value={'status':'completed'}
        run_training(flow)
        self.assertEqual([c.args[1] for c in flow.search_arm.call_args_list],['B0','B1','B2','P'])
        flow.search_all.assert_called_once()

    def test_reused_search_has_one_shared_initial_and_equal_four_arm_slots(self):
        """Handwritten in-memory evaluations, NOT measurements of train21."""
        from fjsp_usage.research_real.search import V5BudgetedSearch
        names=tuple('HANDWRITTEN_TOY_'+str(i) for i in range(21)); evaluated=[];calls=[]
        config=self.authorized()
        class Wire:
            identity=digest({'provider':config.payload()['provider'],'mode':'real'})
            redact=staticmethod(str)
            def preflight(self,prompt):pass
            def dispatch(self,key,prompt,*,kind,on_sent):
                calls.append(key);on_sent()
                number=int(key.split('/')[-1]) if key.startswith('r201/init/') else 9
                code='def select_heuristic(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):\n    return '+str(number)+'\n'
                return {'text':'{Handwritten unit-test fixture, not a model candidate.}\n```python\n'+code+'```',
                        'usage':{'input_tokens':2,'output_tokens':3}}
        def evaluate(candidate):
            evaluated.append(candidate.key);makespan=10+int(candidate.code.strip().split()[-1])
            return {'valid':True,'total_instances':21,'fitness':-makespan/10,
                    'instances':[{'file':n,'makespan':makespan,'lower_bound':10,'score':-makespan/10,
                                  'feasible':True,'single_solve_seconds':0,'deterministic_recheck_seconds':0} for n in names]}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);ledger=BudgetLedger(folder/'budget.json',config,'fixture')
            def engine(arm,initial=None):
                return V5BudgetedSearch(folder/arm,arm=arm,config=config.u_search(201),members=self.members,
                    evaluator=evaluate,transport=Wire(),context='HANDWRITTEN_FIXTURE',kind='U',initial=initial,
                    init_phase='r201/init',search_phase='r201/'+('B0' if arm=='INIT' else arm),ledger=ledger,
                    experiment=config,training_names=names)
            init=engine('INIT');self.assertTrue(init.initialize());shared=init.export_rows()
            self.assertEqual(len(shared),5);before=list(shared)
            for arm in ('B0','B1','B2','P'):
                search=engine(arm,shared);r=search.run()
                self.assertEqual(r['phase'],'completed');self.assertEqual(len(search.state['attempts']),10)
                self.assertEqual(len(search.export_rows()),5)
                self.assertEqual(len([k for k in calls if k.startswith('r201/'+arm+'/')]),10)
                self.assertEqual(shared,before)
            self.assertEqual(len(calls),45)  # fresh5 once, NOT five per arm
            self.assertEqual(len(evaluated),9)  # duplicates consume slots but never reevaluate

    def io_fixture(self,folder,*,before_failed=False,after_failed=False,preflight_invoice=False):
        config=self.authorized();clock=[1000.0];sent=[]
        def sleep(n):clock[0]+=n
        class Wire:
            identity=digest({'provider':config.payload()['provider'],'mode':'real'})
            secret='HANDWRITTEN-NOT-A-KEY';redact=staticmethod(str)
            def __init__(self):self.config=config
            def preflight(self,prompt):pass
            def dispatch(self,key,prompt,*,kind,on_sent):
                sent.append(key);on_sent()
                return {'text':'HANDWRITTEN IO FIXTURE, NOT A CANDIDATE','usage':{'input_tokens':2,'output_tokens':3},
                    'metadata':{'gateway_request_id':'fixture-id','model':'gpt-6.1-sol'}}
        quota=FairQuota(Wire(),folder/'platform_quota.json','fixture',query=lambda:{'quota':{
            'available':True,'unlimited_quota':False,'expires_at':0,'total_used':(u:=107 if sent else 100),
            'total_available':100000000-u,'total_granted':100000000}},
            clock=lambda:clock[0],sleep=sleep,retained_extra=24000000)
        # Cache the tariff fixture; production install still wraps every actual GET.
        quota._tariff_at=clock[0]
        invoices=iter([{'success':False,'http_status':429}] if before_failed else
                      [{'success':True,'records':[]},{'success':False,'http_status':429}])
        from fjsp_usage.research_real.single_fair import PreflightInvoice
        invoice=(PreflightInvoice if preflight_invoice else InvoiceTransport)(quota,folder/'billing',query=lambda:next(invoices))
        protected=install_protections(invoice,quota,folder,lambda:None,
            metadata_floor=1000,invoice_floor=1000,clock=lambda:clock[0],sleep=sleep)
        quota._tariff_at=100000  # keep fixture tariff valid as fake clock advances
        ledger=BudgetLedger(folder/'budget.json',config,'fixture')
        journal=BudgetJournal(folder/'journal.json',phase='r201/B0',cap=10,transport=protected,ledger=ledger)
        return quota,journal,sent,clock

    def test_pre_send_metadata_pause_preserves_init_cursor_and_resumes_same_identity(self):
        from fjsp_usage.research_real.search import V5BudgetedSearch
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);quota,journal,sent,_=self.io_fixture(folder,before_failed=True,preflight_invoice=True)
            config=self.authorized()
            engine=V5BudgetedSearch(folder/'INIT',arm='INIT',config=config.u_search(201),members=self.members,
                evaluator=Mock(side_effect=AssertionError('no valid fixture to evaluate')),transport=journal.transport,
                context='HANDWRITTEN_FIXTURE',kind='U',initial=None,init_phase='r201/init',search_phase='r201/B0',
                ledger=journal.ledger,experiment=config,training_names=self.dataset.names['train'])
            with self.assertRaises(BudgetStop):engine.initialize()
            self.assertEqual(engine.state['init_cursor'],0);self.assertEqual(journal.ledger.data['records'],{})
            identifier=engine.state['inflight']['id'];self.assertEqual(sent,[])
            self.assertFalse((folder/'Initialization_status.json').exists())
            # Healthy metadata now, same pending id. The intentionally invalid
            # handwritten reply is consumed ONCE, never turned into a valid U.
            journal.transport.inner.query=lambda:{'success':True,'records':[]}
            engine.initialize(stop_after_attempts=1)
            self.assertEqual(engine.state['init_cursor'],1);self.assertEqual(len(sent),1)
            self.assertTrue(sent[0].endswith('/'+identifier))

    def test_historical_missing_group_stays_unknown_but_wrong_group_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            peer,inventory=self.peer(Path(tmp)/'peer')
            bill=next((peer[0]/'billing').glob('*.json'));body=json.loads(bill.read_text())
            body['after']['records'][0].pop('group');atomic_json(bill,body)
            b=self.binding([peer],inventory)
            self.assertEqual(len(b['historical_invoice_group_missing_keys']),1)

    def test_full_chain_pre_dispatch_429_spends_one_unsent_slot_then_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);quota,journal,sent,_=self.io_fixture(folder,before_failed=True)
            one=journal.request('B0/g0000/000000','fixture')
            self.assertEqual(one['status'],'failed');self.assertEqual(sent,[])
            self.assertEqual(len(journal.ledger.data['records']),1);self.assertTrue(quota.data['halted'])
            with self.assertRaises(BudgetStop):journal.request('B0/g0000/000001','fixture')
            self.assertEqual(journal.calls,1)
            self.assertEqual(list((folder/'wire_responses').glob('*.json')),[])

    def test_full_chain_wire_retained_before_late_invoice_429_no_resend(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);quota,journal,sent,_=self.io_fixture(folder,after_failed=True)
            one=journal.request('B0/g0000/000000','fixture')
            self.assertEqual(one['status'],'failed');self.assertEqual(len(sent),1)
            wire=json.loads(next((folder/'wire_responses').glob('*.json')).read_text())
            self.assertEqual(wire['status'],'wire_completed_before_settlement')
            self.assertEqual(wire['reply']['text'],'HANDWRITTEN IO FIXTURE, NOT A CANDIDATE')
            self.assertEqual(wire['reply']['usage'],{'input_tokens':2,'output_tokens':3})
            self.assertEqual(journal.request('B0/g0000/000000','fixture'),one)
            self.assertEqual(len(sent),1)
            with self.assertRaises(BudgetStop):journal.request('B0/g0000/000001','fixture')


if __name__=='__main__':unittest.main()
