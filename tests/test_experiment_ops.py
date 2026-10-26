"""Engineering-only acceptance. No real API or formal-instance solves."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import experiment_ops as o
from tools import experiment_ops_run as r
from tools.experiment_ops_prompts import build
from tools.experiment_ops_report import summary

CLI=o.ROOT/'experiments/tier2/manage.py'


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ops-test-config-',dir=o.ROOT/'runs')
        self.addCleanup(self.tmp.cleanup);self.base=Path(self.tmp.name)
        self.run_dir=self.base.with_name(self.base.name+'-run')
        self.addCleanup(lambda:shutil.rmtree(self.run_dir) if self.run_dir.exists() else None)
        self.guard=patch('socket.socket.connect',side_effect=AssertionError('NO REAL NETWORK'));self.guard.start();self.addCleanup(self.guard.stop)

    def config(self,name='ind-mock',**changes):
        c=o.read(o.ROOT/f'experiments/tier2/ops/configs/{name}.json');c.update(changes)
        path=self.base/'config.json';o.write(path,c);return path

    def call(self,*args,success=True):
        p=subprocess.run([str(o.ROOT/'.venv/bin/python'),'-B',str(CLI),*map(str,args)],cwd=o.ROOT,capture_output=True,text=True,timeout=40)
        if success:self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        return p

    def wait(self,phase):
        end=time.monotonic()+20
        while time.monotonic()<end:
            path=self.run_dir/'checkpoint.json'
            if path.exists() and o.read(path)['phase']==phase and not (self.run_dir/'.execution.lock').exists():return
            time.sleep(.05)
        self.fail('bounded engineering wait did not reach '+phase)

    def test_preview_is_readonly_no_provider_or_solver(self):
        c=self.config('evo-api')
        with patch.object(o.certified,'construct_usage_schedule',side_effect=AssertionError('NO SOLVE')),patch.object(r,'JsonCandidateTransport',side_effect=AssertionError('NO API')):
            d=o.describe(c)
        self.assertEqual(d['budgets']['logical_generation'],2)
        self.assertFalse(self.run_dir.exists())

    def test_full_rules_and_exact_existing_semantics(self):
        c=self.config('rules-toy',rule_filter={});d=o.describe(c)
        self.assertEqual(len(d['tasks']),21)
        for row in o.rules.rules():
            fn=o.certified.compile_candidate(o.checked_candidate(row['candidate'],'U'))
            for progress in (.0,.25,.5,.75,.99):
                expected=row['alpha_before'] if row['tau'] is None or progress<row['tau'] else row['alpha_after']
                self.assertEqual(fn(progress,.1,.1,.01,.1,.01,-1)[1][:2],(expected,1-expected))

    def test_config_identity_mismatch_and_unknown_reservation_refuse_resume(self):
        c=self.config();o.prepare(c,self.run_dir)
        value=o.read(c);value['search_seed']+=1;o.write(c,value)
        with self.assertRaises(ValueError):o.check_run(self.run_dir)
        value['search_seed']-=1;o.write(c,value)
        s=o.read(self.run_dir/'checkpoint.json');s['tasks']['uncommitted']={'status':'reserved'}
        with self.assertRaises(ValueError):r.ledger(self.run_dir,s,o.check_run(self.run_dir))
        self.assertFalse((self.run_dir/'API_attempts.json').exists())

    def test_real_API_gate_fails_before_launch_or_network(self):
        c=self.config('ind-api');o.prepare(c,self.run_dir)
        with self.assertRaises(PermissionError):r.start(self.run_dir)
        self.assertFalse((self.run_dir/'.execution.lock').exists())
        self.assertFalse((self.run_dir/'API_attempts.json').exists())

    def test_no_implicit_fee_or_account_gate(self):
        c=self.config();o.prepare(c,self.run_dir);p=o.check_run(self.run_dir)
        client=r.ClientConfig(p)
        self.assertNotIn('platform_quota_ceiling',client.payload())
        self.assertEqual(client.request_budget['per_candidate_attempt_cap'],2)

    def test_independent_template_no_parents_or_history_and_tenH_support(self):
        c=self.config();d=o.describe(c);members=[o.checked_candidate(v['candidate'],'h') for v in d['H']['members']]
        text=build(d['config'],{'operator':'I1'},[],members)
        from tools.ind_evo_h01 import independent_prompt
        self.assertEqual(text,independent_prompt(members));self.assertNotIn('PARENT 0',text)
        c=self.config(space='ten_h');d=o.describe(c)
        text=build(d['config'],{'operator':'I1'},[],members)
        self.assertIn('H MEMBER 9',text);self.assertIn('SELECT (0) OR MIX (1)',text)

    def test_mock_evolution_two_slots_and_generation_update(self):
        c=self.config('evo-api',api_mode='mock');o.prepare(c,self.run_dir)
        self.call('run','--run-dir',self.run_dir)
        s=o.read(self.run_dir/'checkpoint.json');facts=summary(self.run_dir)
        self.assertEqual(s['phase'],'completed');self.assertEqual(s['generation'],1);self.assertEqual(len(s['population']),5)
        self.assertEqual(facts['used']['logical_generation'],2);self.assertEqual(facts['used']['complete_responses'],2)
        self.assertEqual(facts['used']['certified_new_generation'],2)
        journal=o.read(self.run_dir/'API_attempts.json')
        self.assertTrue(all(q['global_key'].startswith('operations/'+s['identity']+'/') for q in journal['requests'].values()))
        self.assertEqual(facts['API_usage']['verified_currency_cost'],0)
        tasks=list(s['tasks'].values());self.assertEqual([v.get('operator') for v in tasks[-2:]],['CROSS','MUTATE'])
        self.assertEqual(len(tasks[-2]['parents']),5);self.assertEqual(len(tasks[-1]['parents']),1)

    def test_background_pause_resume_preserves_budget_clock_and_response(self):
        c=self.config(candidates=3,mock_delay_seconds=1.);o.prepare(c,self.run_dir)
        launched=self.call('run','--run-dir',self.run_dir,'--background')
        self.assertIn('pid',json.loads(launched.stdout))
        until=time.monotonic()+15
        while time.monotonic()<until and not (self.run_dir/'wire_responses').exists():time.sleep(.05)
        self.call('stop','--run-dir',self.run_dir);self.wait('paused')
        clock=o.sha(self.run_dir/'Run_clock.json');old=o.read(self.run_dir/'API_attempts.json')
        self.call('resume','--run-dir',self.run_dir,'--background');self.wait('completed')
        self.assertEqual(o.sha(self.run_dir/'Run_clock.json'),clock)
        new=o.read(self.run_dir/'API_attempts.json')
        for key,value in old['requests'].items():self.assertEqual(new['requests'][key],value)
        facts=summary(self.run_dir);self.assertEqual(facts['used']['logical_generation'],3)
        self.assertEqual(facts['used']['API_attempts'],3);self.assertEqual(facts['phase'],'completed')
        self.assertTrue((self.run_dir/'control/pause_0001.json').exists())

    def test_expired_deadline_and_unknown_lock_never_cleared(self):
        c=self.config('fixed-toy');o.prepare(c,self.run_dir)
        s=o.read(self.run_dir/'checkpoint.json');s['phase']='paused'
        clock={'start':time.time()-7200,'deadline':time.time()-3600};o.write(self.run_dir/'Run_clock.json',clock)
        s['clock_sha256']=o.sha(self.run_dir/'Run_clock.json');o.write(self.run_dir/'checkpoint.json',s)
        with self.assertRaises(ValueError):r.start(self.run_dir,resume=True)
        o.write(self.run_dir/'.execution.lock',{'pid':99999999,'state':'unknown'})
        with self.assertRaises(ValueError):r.start(self.run_dir,resume=True)
        self.assertTrue((self.run_dir/'.execution.lock').exists());self.assertEqual(o.read(self.run_dir/'Run_clock.json'),clock)

    def test_cross_ab_template_and_authentic_parent_binding_without_solves(self):
        c=self.config('cross-ab-api');d=o.describe(c)
        members=[o.checked_candidate(v['candidate'],'h') for v in d['H']['members']]
        byid={p['id']:p for p in d['parents']};parents=[byid[k] for k in d['config']['parent_pairs'][0]]
        from tools import b1_usage_prompts
        from fjsp_usage.cross_feedback_ab import feedback
        a=build(d['config'],{'operator':'CROSS','condition':'A'},parents,members)
        b=build(d['config'],{'operator':'CROSS','condition':'B'},parents,members)
        self.assertEqual(a,b1_usage_prompts.build_prompt('B','CROSS',parents,members))
        block=feedback(parents[0]['fitness'],parents[1]['fitness'])
        self.assertEqual(b.replace(block,''),a)
        self.assertEqual(d['budgets']['logical_generation'],2)

    def test_unknown_API_attempt_never_released_or_resent(self):
        c=self.config();o.prepare(c,self.run_dir);p=o.check_run(self.run_dir)
        j={'halt_reason':None,'requests':{'unknown':{}},'api_attempts':{'attempt':{'status':'interrupted_unknown'}}}
        o.write(self.run_dir/'API_attempts.json',j)
        with self.assertRaises(ValueError):r.ledger(self.run_dir,o.read(self.run_dir/'checkpoint.json'),p)
        self.assertEqual(o.read(self.run_dir/'API_attempts.json'),j)


if __name__=='__main__':unittest.main()
