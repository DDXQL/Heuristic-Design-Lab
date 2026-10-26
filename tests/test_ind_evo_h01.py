"""Synthetic/prompt/journal acceptance; no inference or formal FJSP solves."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import random
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import ind_evo_h01 as x
from tests.test_cross_feedback_ab_execute import MockTransport
from fjsp_usage.research_real.attempt_budget import AttemptJournal
from fjsp_usage.research_real.budget import BudgetStop


def population():
    return [{'id':f'MANUAL/init/alpha_{p:03d}','candidate':asdict(x.legacy.constant(p)),
             'fitness':-abs(p-50)-1.,'scores':[-abs(p-50)-1.]} for p in (0,25,50,75,100)]


class Tests(unittest.TestCase):
    def setUp(self):
        p=patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK'));p.start();self.addCleanup(p.stop)
        p=patch('fjsp_usage.research_real.real_transport.JsonCandidateTransport.dispatch',side_effect=AssertionError('NO API'));p.start();self.addCleanup(p.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.p={'provider':{'endpoint':'https://leafapi.cc/v1/chat/completions','model':'gpt-6.1-sol',
             'api_key_env':'LEAFAPI_API_KEY','protocol':'openai-chat-v1','max_output_tokens':8192,'temperature':None}}

    def test_plan_120_and_no_feedback_dependent_schedule(self):
        a=x.plan();self.assertEqual(len(a),120);self.assertEqual(a,x.plan())
        for r in (1,2,3):
            for arm in ('IND','EVO'):
                self.assertEqual([t['slot'] for t in a if t['repeat']==r and t['arm']==arm],list(range(20)))
        self.assertEqual(len({r['task_id'] for r in a}),120)
        self.assertNotEqual(x.SEEDS[0],501)

    def test_exact_legacy_EVO_common_and_IND_no_parent_no_feedback(self):
        frozen=x.read(x.baseline.RUN/'H_frozen.json')
        members=[x.checked_candidate(h['candidate'],'h') for h in frozen['members']]
        ps=population();ind=x.independent_prompt(members)
        for op,count in [('CROSS',5),('MUTATE',1)]:
            evo=x.legacy.build_prompt('B',op,ps[:count],members)
            self.assertTrue(evo.startswith(x.legacy.TASK+'\n'+x.context(members)+'\n'))
            self.assertTrue(ind.startswith(x.legacy.TASK+'\n'+x.context(members)+'\n'))
            changed=deepcopy(ps[:count])
            for p in changed:p['fitness']=123456789.123456
            self.assertEqual(evo,x.legacy.build_prompt('B',op,changed,members))
        self.assertNotIn('PARENT 0',ind);self.assertNotIn('123456789',ind)
        for p in ps:self.assertNotIn(p['candidate']['code'],ind)
        self.assertIn('No phase partition, switching, dynamic dependence, complexity or improvement is required.',ind)
        self.assertIn('Every return is exactly (1, (alpha, 1.0-alpha',ind)

    def test_P0_space_exact_keys_and_select_rejected(self):
        from fjsp_usage.research.candidates import compile_candidate
        for percent in (0,25,50,75,100):
            c=x.legacy.constant(percent);self.assertEqual(c,x.legacy.validate(c.code,c.description))
            f=compile_candidate(c);self.assertEqual(f(0,.2,.1,.1,.2,.1,-1)[1][:2],(percent/100,1-percent/100))
        code=x.legacy.constant(50).code.replace('return (1,','return (0,')
        with self.assertRaises(x.CandidateError):x.legacy.validate(code)

    def test_generation_frozen_parent_and_original_survival_with_failures(self):
        ps=population();unit=x.initial_unit(ps,123);reference=x.ranked(deepcopy(ps));rng=random.Random(123);children=[]
        for slot in range(20):
            before=[r['id'] for r in unit['population']]
            op,parents=x.parents_for(unit,slot)
            expected=x.select_parents(reference,5 if slot%10<5 else 1,rng)
            self.assertEqual([r['id'] for r in parents],[r['id'] for r in expected])
            child=None if slot in (0,1,11) else {'id':f'B/g{slot//10:04d}/{slot%10:06d}',
                'candidate':asdict(x.legacy.constant(25)),'fitness':float(slot),'scores':[float(slot)]}
            if child:children.append(child)
            update=x.advance(unit,{'task_id':str(slot),'arm':'EVO'},{},child)
            if slot%10!=9:self.assertEqual(before,[r['id'] for r in unit['population']]);self.assertIsNone(update)
            else:
                reference=x.ranked(reference+children)[:5];children=[]
                self.assertEqual([r['id'] for r in unit['population']],[r['id'] for r in reference])
            if slot==10:self.assertTrue(all(id.startswith('B/g0000') for id in before))
        self.assertEqual(unit['generation'],2);self.assertEqual(len(unit['population']),5)

    def journal(self,t):
        return AttemptJournal(self.root/'journal.json',config=x.config(self.p),context='mock',phase='mock',transport=t,sleep=lambda t:None)

    def test_complete_invalid_response_not_regenerated(self):
        t=MockTransport(self.root);j=self.journal(t)
        self.assertEqual(j.request('q','p')['status'],'completed');j.request('q','p')
        self.assertEqual(len(t.calls),1)

    def test_retry_twice_and_30_cap_not_20_valid_refill(self):
        t=MockTransport(self.root,failures=100);j=self.journal(t)
        for i in range(15):self.assertEqual(j.request(str(i),'p')['status'],'failed')
        self.assertEqual(j.calls,15);self.assertEqual(j.attempt_count,30)
        with self.assertRaises(BudgetStop):j.request('extra','p')
        self.assertEqual(len(t.calls),30)
        self.assertEqual(6*x.POLICY['api_attempt_cap'],180)

    def test_unknown_request_never_resent(self):
        t=MockTransport(self.root);j=self.journal(t);aid='mock/q/attempt/01';pk=x.digest({'prompt':'p','kind':'U'})
        j.data['requests']['q']={'status':'pending','prompt':'p','prompt_key':pk,'kind':'U','global_key':'mock/q','logical_id':'q','attempt_ids':[aid],'usage':None}
        j.data['api_attempts'][aid]={'id':aid,'logical_id':'q','number':1,'status':'pending','send_confirmed':False,'prompt_key':pk,'started_at':time.time(),'usage':None}
        j.save();j.request('q','p');self.assertEqual(t.calls,[])
        self.assertEqual(j.data['halt_reason'],'uncertain_dispatch_requires_review')

    def test_no_money_gate_shared_configuration(self):
        c=x.config(self.p);self.assertEqual(c.total_request_cap,20)
        self.assertIsNone(c.cost_cap_estimate);self.assertIsNone(c.platform_quota_ceiling)
        self.assertEqual(x.digest(c.payload()),x.digest(__import__('json').loads(__import__('json').dumps(c.payload()))))

    def test_unknown_evaluation_and_pending_task_stop(self):
        with patch.object(x,'sha',lambda p:'x'):
            with self.assertRaisesRegex(BudgetStop,'unknown evaluation'):
                x.ledger({'protocol_sha256':'x','cursor':0,'evaluations':{'k':{'status':'reserved'}}},{})

    def test_same_T30_runtime_invalid_and_exit_stop(self):
        from tests.test_baseline_supplemental import T30Tests
        result,k=T30Tests().evidence()
        self.assertEqual(x.certified.certify(result,k)['decision'],'accepted')
        k['lifecycle']['exitcode']=-15
        self.assertEqual(x.certified.certify(result,k)['decision'],'stop')

    def test_uncommitted_response_boundary_cannot_replay(self):
        with patch.object(x,'sha',lambda p:'x'),patch.object(x,'read',lambda p:x.plan()):
            with self.assertRaisesRegex(BudgetStop,'uncommitted task boundary'):
                x.ledger({'protocol_sha256':'x','cursor':0,'evaluations':{},'tasks':{'r1_IND_s00':{'status':'completed'}}},{})


if __name__=='__main__':unittest.main()
