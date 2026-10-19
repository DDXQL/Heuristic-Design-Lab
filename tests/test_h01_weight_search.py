"""Pure offline checks; no instance construction/solve or network transport."""
from dataclasses import replace
import json
from pathlib import Path
import random
import importlib.util
import tempfile
import unittest
from types import SimpleNamespace

from fjsp_usage.research.candidates import U_ARGS, Candidate, CandidateError, compile_candidate
from fjsp_usage.research.protocol import SearchConfig
from fjsp_usage.research_real.budget import BudgetLedger, BudgetStop
from tools.h01_weight_search import (Config, WeightSearch, constant, validate,
    checked_function, build_prompt, peer_history, PHASE)
from unittest.mock import patch


def source(body):
    return 'def use_heuristics('+', '.join(U_ARGS)+'):\n'+body+'\n'


class WeightChecks(unittest.TestCase):
    def test_frozen_grid_and_legal_dynamic(self):
        self.assertEqual(len({constant(i).key for i in range(0,101,5)}),21)
        for i in range(0,101,5):
            fn = checked_function(compile_candidate(constant(i)))
            self.assertEqual(fn(.4,.3,.2,.1,.2,.1,-1)[1][0],i/100)
        c = validate(source('    alpha = min(1.0, max(0.0, progress))\n'
            '    return (1, (alpha, 1.0-alpha, 0, 0, 0, 0, 0, 0, 0, 0))'))
        fn = checked_function(compile_candidate(c))
        self.assertEqual(fn(.2,0,0,0,0,0,-1)[1][:2],(.2,.8))

    def test_endpoint_raw_scores_and_ties(self):
        from fjsp_usage.usage_v2.execution import decode_output, combine_scores
        for percent, member in ((0,1),(100,0)):
            output=compile_candidate(constant(percent))(*([0.]*6+[-1]))
            decoded=decode_output(output,10,(1,))
            raw=(2.,-3.,2.,0.)
            scores,normal=combine_scores({member:raw},decoded['weights'],decoded['support'])
            self.assertEqual(scores,raw);self.assertEqual(normal,{})
            self.assertEqual(max(range(4),key=lambda i:scores[i]),0)
            self.assertEqual(decoded['dominant'],member)

    def test_spawn_wiring_with_zero_instances(self):
        # Compiles the actual adapter in a spawned process but never constructs
        # or schedules any FJSP instance, including toy/synthetic instances.
        import multiprocessing as mp
        from tools.h01_weight_search import weight_worker
        from fjsp_usage.research.candidates import H_ARGS, validate_code
        h=validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -processing_time\n',kind='h')
        context=mp.get_context('spawn');receive,send=context.Pipe(duplex=False)
        process=context.Process(target=weight_worker,args=(send,constant(50),(h,)*10,(),(),(1,)))
        process.start();send.close();process.join(10)
        if process.is_alive():process.terminate();process.join();self.fail('spawn wiring did not finish')
        self.assertEqual(process.exitcode,0)
        with self.assertRaises(EOFError):receive.recv()
        receive.close()

    def test_unknown_cost_is_not_zero(self):
        from tools.h01_weight_report import recorded_costs
        row=recorded_costs({'valid':False,'fitness':None,'instances':[]})
        self.assertIsNone(row['primary_wall_seconds'])
        self.assertIsNone(row['primary_h_calls'])
        self.assertTrue(row['failed_instance_h_calls_unknown'])

    @unittest.skipUnless(importlib.util.find_spec('reportlab'), 'plot-only check uses bundled artifact Python')
    def test_report_plot_does_not_need_matplotlib_or_solves(self):
        from tools.h01_weight_report import plot, alpha_profile
        result={'valid':True,'instances':[{'file':'unit-fixture','observed_alpha':[.2,.6,.5],
            'decision_support_weights':[[1,[0,1],[.2,.8],1],[1,[0,1],[.6,.4],0],[1,[0,1],[.5,.5],0]]}]}
        profile=alpha_profile(result)
        self.assertTrue(profile['training_alpha_varies']);self.assertEqual(profile['dominant_switches'],1)
        with tempfile.TemporaryDirectory() as d:
            plot(Path(d),[{'kind':'fixed_grid','alpha':.5,'valid':True,'fitness':-2.}],[],None,'alpha_050')
            self.assertIn('<svg',(Path(d)/'Fixed_weight_curve.svg').read_text())

    def test_constraints_all_paths(self):
        c = constant(50).code
        for bad in (c.replace('(1, (','(0, ('), c.replace('0.5, 0.5','0.5, 0.4'),
                    c.replace('0.0, 0.0','0.1, 0.0',1), c.replace('(1, (','(True, ('),
                    c.replace('0.5, 0.5','True, 0.0')):
            with self.assertRaises(CandidateError):validate(bad)
        with self.assertRaises(CandidateError):
            validate(source('    if progress < 0.5:\n        return (0, (1,0,0,0,0,0,0,0,0,0))\n'
                '    return (1, (0.5,0.5,0,0,0,0,0,0,0,0))'))
        # Invalid alpha on an unseen path is rejected when actually invoked,
        # never clipped into the legal search space.
        fn = checked_function(compile_candidate(validate(source('    alpha = progress * 2\n'
            '    return (1, (alpha, 1-alpha, 0,0,0,0,0,0,0,0))'))))
        with self.assertRaises(ValueError):fn(.8,0,0,0,0,0,-1)
        with self.assertRaises(ValueError):checked_function(lambda *a:(1,(float('nan'),0)+8*(0,)))(0)

    def test_real_constraints_do_not_loosen_old_config(self):
        from tools import usage_mechanism_ablation as common
        raw = common.read(common.ROOT/'runs/h01-state-weight-search-seed501-20261019-v1/config.pending.json')
        c = Config.from_dict(raw)
        self.assertEqual(c.u_search(501).generations,2)
        self.assertEqual(c.phase_caps(),{PHASE:20})
        for kwargs in ({'seeds':(502,)},{'total_request_cap':21},{'generations':3},
                       {'training_diagnostics':True},{'instance_timeout':20}):
            with self.assertRaises(ValueError):replace(c,**kwargs)

    def test_peer_active_stops_before_account_or_solver(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); (p/'.writer.lock').write_text('active')
            with patch('tools.h01_weight_search.PEER_RUN',p):
                with self.assertRaisesRegex(BudgetStop,'WAIT_PEER_WRITER_LOCK'):peer_history(p)

    def test_final_handoff_receipts_and_rejections(self):
        from tools import usage_mechanism_ablation as common
        from fjsp_usage.research_real.assets import seal
        from fjsp_usage.research.protocol import digest
        import hashlib
        # Entirely invented accounting UNIT fixtures, not new real records.
        with tempfile.TemporaryDirectory() as d:
            peer=Path(d)/'peer';own=Path(d)/'own';peer.mkdir();own.mkdir();(peer/'billing').mkdir()
            def save(path,value):path.write_text(json.dumps(value))
            pending=common.read(common.ROOT/'runs/h01-state-weight-search-seed501-20261019-v1/config.pending.json')
            save(own/'config.pending.json',pending)
            keys=[f'unit-H-{i}' for i in range(10)];dataset={'unit_fixture':True}
            save(own/'Plan.json',{'dataset':dataset,'H_order':keys})
            p={'config':{'provider':pending['provider'],'conditional_research':{'version':'single-ID-update-frequency-v1'}},'dataset':dataset}
            context=digest(p);identity=digest({'config':p['config'],'context':context})
            save(peer/'protocol.json',p)
            save(peer/'H_frozen.json',seal({'kind':'H_frozen','mode':'real','context':context,
                'members':[{'candidate':{'key':key}} for key in keys]}))
            old={'kind':'Fair_history_binding','mode':'real','files_sha256':{},'real_budget_inventory':{},
                'historical_request_slots':201,'historical_confirmed_sends':185,'historical_token_charges':[],
                'retained_account_hold':24000000,'metadata_interval':30,'invoice_interval':150}
            save(peer/'History_binding.json',seal(old))
            native={'identity':identity,'mode':'real','halted':False,'records':{}}
            quota={'identity':identity,'halted':False,'observed_used':600,'records':{},
                'latest_quota':{'total_used':600,'unlimited_quota':False,'total_available':39999400}}
            allkeys=[]
            for arm in ('A','B'):
                folder=peer/f'r201/{arm}';folder.mkdir(parents=True);journal={}
                for i in range(30):
                    n=len(allkeys);key=f'r201/{arm}/{arm}/g0000/{i:06d}';allkeys.append(key)
                    usage={'input_tokens':1,'output_tokens':1}
                    native['records'][key]={'phase':f'r201/{arm}','prompt_key':f'unit-prompt-{n}',
                        'send_confirmed':True,'status':'completed','usage':usage,'reservation':usage}
                    q={'status':'settled','send_confirmed':True,'reserved':1000000,'before_used':10*n,
                        'after_used':10*(n+1),'observed_account_delta':10,'started_at':100+10*n,'finished_at':108+10*n}
                    quota['records'][key]=q
                    invoice={'request_id':f'unit-request-{n}','created_at':105+10*n,'type':2,
                        'model_name':'gpt-6.1-sol','quota':10,'group':'codex-deafult'}
                    bill={'status':'invoice_account_matched','original_quota_record':q,'wire_usage':usage,
                        'transport_status':'completed','before':{'success':True,'records':[]},
                        'after':{'success':True,'records':[invoice]},'invoice':invoice,'actual_platform_units':10}
                    save(peer/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json'),bill)
                    journal[str(i)]={'global_key':key,'prompt_key':f'unit-prompt-{n}','status':'completed','usage':usage,
                        'response_metadata':{'model':'gpt-6.1-sol'}}
                save(folder/'budgeted_evolution_requests.json',{'requests':journal})
                save(folder/'checkpoint.json',{'phase':'completed','generation':3 if arm=='A' else 1,
                    'inflight':None,'attempts':[{}]*30})
            save(peer/'budget.json',native);save(peer/'platform_quota.json',quota)
            save(peer/'Update_status.json',seal({'kind':'Update_status','mode':'real','context':context,'status':'completed',
                'arms':{a:{'phase':'completed'} for a in ('A','B')}}))
            handoff={'real_caller_active':False,'budget_identity':identity,'budget_sha256':common.sha(peer/'budget.json'),
                'quota_halted':False,'registered_generation_phases_complete':True,'known_new_points':600,
                'unknown_new_fee_keys':[],'unknown_new_fee_holds':0,'latest_verified_used_points':600,
                'old_account_hold':24000000,'summary':{'request_slots':60,'confirmed_sends':60,
                    'lifetime_request_slots':261,'lifetime_confirmed_sends':245}}
            save(peer/'Final_budget_handoff.json',handoff)
            for name,interval in [('Metadata_global_pacing.json',30),('Invoice_query_pacing.json',150)]:
                save(peer/name,{'last_finished_at':1000,'interval':interval})
            expected={identity:common.sha(peer/'budget.json')}
            with patch('tools.h01_weight_search.PEER_RUN',peer),patch('fjsp_usage.usage_v2.registration.inventory',return_value=expected):
                result=peer_history(own)
                self.assertEqual(result['historical_request_slots'],261)
                self.assertEqual(result['retained_account_hold'],24000000)
                self.assertEqual(result['peer_receipt_audit']['actual_points'],600)
                # A trusted-looking total cannot conceal a changed receipt.
                file=peer/'billing'/(hashlib.sha256(allkeys[0].encode()).hexdigest()+'.json')
                bad=json.loads(file.read_text());bad['invoice']['quota']=11;save(file,bad)
                with self.assertRaises(BudgetStop):peer_history(own)
                bad['invoice']['quota']=10;save(file,bad)
                handoff['old_account_hold']=0;save(peer/'Final_budget_handoff.json',handoff)
                with self.assertRaises(BudgetStop):peer_history(own)

    def test_twenty_slot_parameter_flow_and_resume(self):
        # Scientific unit fixtures, NOT new FJSP instances or evaluated strategies.
        from tools import usage_mechanism_ablation as common
        config = Config.from_dict(common.read(common.ROOT/'runs/h01-state-weight-search-seed501-20261019-v1/config.pending.json'))
        members = tuple(Candidate(f'fixture member {i}','def priority(): pass',str(i),'h') for i in range(10))
        initial = [{'id':f'MANUAL/init/{i}','candidate':{'description':'manual fixture','code':constant(i).code,'key':constant(i).key,
            'kind':'U','interface_version':constant(i).interface_version,'member_count':10},
            'fitness':-100-i,'scores':[-100-i]} for i in (0,25,50,75,100)]
        class Transport:
            identity = 'offline-unit-fixture-no-network'
            calls = 0
            def redact(self,text):return text
            def preflight(self,prompt):pass
            def dispatch(self,key,prompt,*,on_sent,**kwargs):
                self.calls += 1; on_sent()
                code = source(f'    alpha = min(1.0, progress + {self.calls/1000})\n'
                    '    return (1, (alpha, 1-alpha, 0,0,0,0,0,0,0,0))')
                return {'text':'{Offline fixture}\n```python\n'+code+'```','usage':{'input_tokens':1,'output_tokens':1}}
        transport = Transport(); evaluations=[]
        def evaluator(c):
            evaluations.append(c.key); score=-99+len(evaluations)
            return {'valid':True,'fitness':score,'total_instances':1,
                'instances':[{'file':'unit-fixture','score':score,'makespan':int(-score),'lower_bound':1,'feasible':True}]}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d); ledger=BudgetLedger(p/'budget.json',config,'offline')
            kwargs=dict(arm='B',config=config.u_search(501),members=members,evaluator=evaluator,
                transport=transport,context='offline',initial=initial,init_phase='r501/init',
                search_phase=PHASE,ledger=ledger,experiment=config,training_names=['unit-fixture'])
            s=WeightSearch(p/'search',**kwargs)
            first=s.run(stop_after_attempts=10)
            self.assertEqual(first['attempts'],10)
            # End-of-generation selection occurs on the next run boundary.
            resumed=WeightSearch(p/'search',**kwargs); result=resumed.run()
            self.assertEqual(result['phase'],'completed'); self.assertEqual(transport.calls,20)
            self.assertEqual(len(evaluations),20); self.assertEqual(len(ledger.data['records']),20)
            attempts=resumed.state['attempts']
            for g in (0,1):
                rows=attempts[10*g:10*g+10]
                self.assertEqual([r['operator'] for r in rows],['CROSS']*5+['MUTATE']*5)
                for r in rows:self.assertEqual(len(set(r['parents'])),5 if r['operator']=='CROSS' else 1)
                if g==0:self.assertTrue(all(x.startswith('MANUAL/init/') for r in rows for x in r['parents']))
                else:self.assertTrue(any('/g0000/' in x for r in rows for x in r['parents']))
            resumed.run(); self.assertEqual(transport.calls,20)
            prompt=next((p/'search/prompts').iterdir()).read_text()
            self.assertIn('H MEMBER 0',prompt);self.assertIn('H MEMBER 1',prompt)
            self.assertNotIn('H MEMBER 2',prompt);self.assertNotIn('fitness:',prompt)


if __name__ == '__main__':unittest.main()
