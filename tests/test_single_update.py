"""Handwritten search/budget fixtures only; never real model/training evidence."""
from copy import deepcopy
from dataclasses import asdict,replace
import json
from pathlib import Path
import tempfile
import unittest
from fjsp_usage.research.candidates import validate_code,Candidate
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.assets import seal
from fjsp_usage.research_real.budget import BudgetLedger,BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.single_update import UpdateSearch,CYCLE

ROOT=Path(__file__).resolve().parents[1]
ARGS='progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic'

class UpdateTest(unittest.TestCase):
    def fixture(self,tmp,*,repeat=False,pause=False):
        payload=json.loads((ROOT/'experiments/tier2/research_real_v1/config.single.update-frequency.pending.json').read_text())
        payload['conditional_research']['history_binding']=seal({'kind':'Fair_history_binding','mode':'real',
            'files_sha256':{},'historical_request_slots':0,'historical_confirmed_sends':0,
            'historical_token_charges':[],'retained_account_hold':0,'lifetime_request_cap':300})
        c=ExperimentConfig.from_dict(payload);ledger=BudgetLedger(Path(tmp)/'budget.json',c,'HANDWRITTEN_FIXTURE')
        calls=[];fail=[pause]
        class Wire:
            identity='HANDWRITTEN_UNIT_FIXTURE_NOT_PROVIDER';redact=staticmethod(str)
            def preflight(self,prompt):
                if fail[0]:fail[0]=False;raise BudgetStop('handwritten pre-send metadata pause')
            def dispatch(self,key,prompt,*,kind,on_sent):
                calls.append((key,prompt));on_sent();parts=key.split('/')
                index=1 if repeat else 10*int(parts[-2][1:])+int(parts[-1])+1
                code=f'def select_heuristic({ARGS}):\n    if progress < {index/1000}:\n        return 5\n    return 6\n'
                return {'text':'{HANDWRITTEN UNIT FIXTURE, not model output.}\n```python\n'+code+'```',
                        'usage':{'input_tokens':2,'output_tokens':4}}
        names=tuple('HANDWRITTEN_TOY_'+str(i) for i in range(21))
        def result(makespan):
            return {'valid':True,'total_instances':21,'fitness':-makespan/100,
                'instances':[{'file':n,'makespan':makespan,'lower_bound':100,'score':-makespan/100,
                              'feasible':True} for n in names]}
        initial=[]
        for i in range(5):
            candidate=validate_code(f'def select_heuristic({ARGS}):\n    return {i}\n',kind='U',description='HANDWRITTEN fixture')
            initial.append({'id':f'INIT/init/{i:06d}','candidate':asdict(candidate),
                'fitness':-(1100+i)/100,'scores':[-(1100+i)/100]*21})
        def evaluate(candidate):
            n=round(float(candidate.code.split('progress < ')[1].split(':')[0])*1000)
            return result(1000-n)
        members=[Candidate('HANDWRITTEN H fixture','HANDWRITTEN source display only',str(i),'h') for i in range(10)]
        def engine(arm):
            cfg=replace(c.u_search(201),**c.conditional_research['arm_search'][arm])
            return UpdateSearch(Path(tmp)/arm,arm=arm,config=cfg,members=members,evaluator=evaluate,
                transport=Wire(),context='HANDWRITTEN_FIXTURE',initial=deepcopy(initial),kind='U',
                init_phase='r201/init',search_phase='r201/'+arm,ledger=ledger,experiment=c,training_names=names)
        return c,ledger,calls,initial,engine

    def test_parameter_route_and_legacy_configs(self):
        c=ExperimentConfig.from_dict(json.loads((ROOT/'experiments/tier2/research_real_v1/config.single.update-frequency.pending.json').read_text()))
        self.assertEqual(c.phase_caps(),{'r201/A':30,'r201/B':30});self.assertEqual(c.search_arms(),('A','B'))
        p=c.payload();p['conditional_research']['operator_cycle']=['CROSS']*15+['MUTATE']*15
        with self.assertRaises(ValueError):ExperimentConfig.from_dict(p)
        for name in ['config.single.fair.pending.json']:
            old=ExperimentConfig.from_dict(json.loads((ROOT/'experiments/tier2/research_real_v1'/name).read_text()))
            self.assertEqual(old.search_arms(),('B0','B1','B2','P'))

    def test_exact_order_pools_rng_and_lineage(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,l,calls,p0,engine=self.fixture(tmp);a,b=engine('A'),engine('B')
            self.assertEqual(a.state['rng'],b.state['rng'])
            for boundary in (10,20,30):
                a.run_until(boundary);b.run_until(boundary)
                ma=json.loads((Path(tmp)/'A'/f'Milestone_{boundary:02d}.json').read_text())
                mb=json.loads((Path(tmp)/'B'/f'Milestone_{boundary:02d}.json').read_text())
                self.assertEqual(ma['actual_survival_updates'],int(boundary==30))
                self.assertEqual(mb['actual_survival_updates'],boundary//10)
                if boundary<30:self.assertEqual(ma['actual_parent_pool'],p0)
            for arm,s in [('A',a),('B',b)]:
                self.assertEqual([x['operator'] for x in s.state['attempts']],CYCLE*3)
                for row in s.state['attempts']:
                    self.assertEqual(len(set(row['parents'])),5 if row['operator']=='CROSS' else 1)
            self.assertTrue(all(p.startswith('INIT/') for r in a.state['attempts'] for p in r['parents']))
            self.assertTrue(any(p.startswith('B/') for r in b.state['attempts'][10:] for p in r['parents']))
            self.assertEqual(a.state['rng'],b.state['rng']);self.assertEqual(len(calls),60)
            self.assertEqual([r['parents'] for r in a.state['attempts'][:10]],[r['parents'] for r in b.state['attempts'][:10]])
            prompts={k:p for k,p in calls}
            for i in range(10):self.assertEqual(prompts[f'r201/A/A/g0000/{i:06d}'],prompts[f'r201/B/B/g0000/{i:06d}'])
            a.run_until(30);b.run_until(30);self.assertEqual(len(calls),60)
            with self.assertRaises(BudgetStop):a.evolution_requests.request('EXTRA','fixture')

    def test_restart_does_not_replay_and_preserves_parent_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,l,calls,p0,engine=self.fixture(tmp);b=engine('B');b.run_until(10)
            before=deepcopy(b.state);b=engine('B');self.assertEqual(digest(before),digest(b.state))
            b.run_until(10);self.assertEqual(len(calls),10);b.run_until(20)
            self.assertEqual(len(calls),20);self.assertTrue(any(p.startswith('B/') for p in b.state['attempts'][10]['parents']))

    def test_pre_send_pause_does_not_consume_cursor_or_rng_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,l,calls,p0,engine=self.fixture(tmp,pause=True);a=engine('A')
            with self.assertRaises(BudgetStop):a.run_until(10)
            pending=deepcopy(a.state['inflight']);rng=deepcopy(a.state['rng'])
            self.assertEqual(l.data['records'],{});self.assertEqual(a.state['cursor'],0)
            a=engine('A');self.assertEqual(a.state['inflight'],pending);self.assertEqual(digest(a.state['rng']),digest(rng))
            a.run_until(10);self.assertEqual(len(calls),10)
            self.assertEqual(a.state['attempts'][0]['parents'],pending['parents'])

    def test_duplicates_use_slots_and_independent_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            c,l,calls,p0,engine=self.fixture(tmp,repeat=True);a,b=engine('A'),engine('B')
            a.run_until(10);b.run_until(10)
            for s in (a,b):
                self.assertEqual(len(s.state['attempts']),10)
                self.assertEqual(sum(r['category']=='valid' for r in s.state['attempts']),1)
                self.assertEqual(sum(r['category']=='code_duplicate' for r in s.state['attempts']),9)
            self.assertEqual(len(calls),20)
            with self.assertRaises(BudgetStop):l.reserve('bad','r201/init','fixture')

if __name__=='__main__':unittest.main()
