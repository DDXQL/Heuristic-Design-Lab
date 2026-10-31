"""Offline shared-P0, pair configuration and gate checks; no solver or API."""
from copy import deepcopy
from contextlib import redirect_stdout,ExitStack
from pathlib import Path
import io,tempfile,unittest
from unittest.mock import patch
from dataclasses import asdict

from experiments.common import run_survival_ab as entry,_survival_ab as ab
from heuristic_design.core import evolution_v1 as e,routing
from heuristic_design.core.storage import read,digest


def plan():
    return ab.preview(entry.PARAMETERS,source=entry.P0_SOURCE,pair_directory=entry.PAIR_DIRECTORY,
                      root=entry.ROOT,entry=Path(entry.__file__),pair_attempt_cap=entry.PAIR_API_ATTEMPT_CAP)


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')), \
             patch('heuristic_design.problems.routing_fixtures.solve',side_effect=AssertionError('NO SOLVE')):
            cls.plan=plan()

    def test_actual_P0_is_shared_and_historical_cost_is_separate(self):
        p=self.plan;self.assertEqual(len(p['shared_p0']['imports']),10)
        self.assertEqual(p['shared_p0']['historical_initialization']['attempts'],23)
        self.assertEqual(p['shared_p0']['historical_initialization']['new_API_requests_for_reuse'],0)
        self.assertEqual(p['budget']['pair_API_attempt_cap'],2000)
        self.assertEqual(p['budget']['per_arm_P0_re_evaluations'],10)
        self.assertEqual(p['budget']['max_solve_passes_per_pair'],84840)
        a,b=p['arm_configs']['A'],p['arm_configs']['B']
        self.assertEqual({k for k in a if a[k]!=b[k]},{'survival_policy'})
        self.assertEqual((a['api_attempt_cap'],b['api_attempt_cap']),(1000,1000))
        self.assertFalse(a['real_requests_authorized']);self.assertFalse(b['real_requests_authorized'])
        self.assertIsNone(entry.AUTHORIZATION_FILE)
        self.assertLessEqual(set(p['shared_p0']['allowed_source_changes']),ab.SELECTOR_ONLY)

    def test_incompatible_seed_state_deadline_or_provider_is_rejected(self):
        for change in ({'search_seed':502},{'window':11},{'solve_seed':502},
                       {'instance_timeout_seconds':29},{'provider':{**entry.PARAMETERS['provider'],'model':'OTHER'}}):
            c=e.config(entry.PARAMETERS) if 'instance_timeout_seconds' not in change else deepcopy(entry.PARAMETERS)
            c.update(change)
            with self.assertRaises(ValueError):ab.shared_p0(entry.P0_SOURCE,c)

    def test_non_selector_source_change_is_rejected(self):
        sources=e.source_identity();sources['code/heuristic_design/core/routing.py']='0'*64
        with patch.object(e,'source_identity',return_value=sources),self.assertRaises(ValueError):
            ab.shared_p0(entry.P0_SOURCE,e.config(entry.PARAMETERS))

    def test_P0_receipt_change_is_rejected(self):
        # P000 is bound by content equality to the frozen G1 plan, not a standalone receipt;
        # changing the actual content must fail before acceptance.
        real_read=ab.read
        def corrupt(path):
            value=real_read(path)
            if str(path).endswith('/populations/P000.json'):value[0]['fitness']+=1
            return value
        with patch.object(ab,'read',side_effect=corrupt),self.assertRaises(ValueError):
            ab.shared_p0(entry.P0_SOURCE,e.config(entry.PARAMETERS))

    def test_wrong_budget_or_unknown_parameter_fails(self):
        for change in ({'generation_request_cap':1001,'api_attempt_cap':1001},{'unexpected':1}):
            with self.assertRaises(ValueError):
                ab.preview({**entry.PARAMETERS,**change},source=entry.P0_SOURCE,pair_directory=entry.PAIR_DIRECTORY,
                  root=entry.ROOT,entry=Path(entry.__file__),pair_attempt_cap=2000)

    def test_closed_or_missing_new_approval_never_prepares_or_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            p=deepcopy(self.plan);p['pair_directory']=str(Path(temp)/'pair')
            p['pair_fingerprint']=ab.fingerprint(p)
            with patch.object(e,'prepare',side_effect=AssertionError('NO PREPARE')),patch.object(e,'run',side_effect=AssertionError('NO RUN')):
                with self.assertRaises(PermissionError):ab.launch(p,'A',root=entry.ROOT,entry=Path(entry.__file__),authorization_file=None)
                self.assertFalse(Path(p['pair_directory']).exists())
                p['arm_configs']['A']['real_requests_authorized']=True
                with self.assertRaises(PermissionError):ab.launch(p,'A',root=entry.ROOT,entry=Path(entry.__file__),authorization_file=None)
                self.assertFalse(Path(p['pair_directory']).exists())

    def test_old_batch_approval_cannot_be_used(self):
        # Only an in-memory dictionary is supplied; no approval file is created.
        with patch.object(ab,'read',return_value={'stage':'b1','status':'approved','max_attempts':1050}),self.assertRaises(PermissionError):
            ab.approval(Path('UNIT_ONLY_NONEXISTENT'),self.plan,entry.ROOT)

    def test_preview_has_no_network_solve_prepare_or_directory_creation(self):
        with patch.object(e,'prepare',side_effect=AssertionError('NO PREPARE')),patch.object(e,'run',side_effect=AssertionError('NO RUN')), \
             patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')), \
             patch('heuristic_design.problems.routing_fixtures.solve',side_effect=AssertionError('NO SOLVE')):
            p=plan();self.assertEqual(p['API_requests_sent'],0);self.assertEqual(p['solves'],0)
        self.assertFalse(entry.PAIR_DIRECTORY.exists())

    def test_new_Protocol_records_policy_and_unique_identity_without_evaluation(self):
        imports=[{'source':'UNIT_ONLY','candidate':asdict(routing.validate(
          f'def use_heuristics(state):\n    tag = {i}\n    return {i}\n',member_count=10))} for i in range(10)]
        hs=[{'key':str(i)} for i in range(10)];data=[{'file':'UNIT_ONLY','split':'train'}]
        with tempfile.TemporaryDirectory() as tmp,patch('heuristic_design.core.terminal_ops.inputs',return_value=(None,None,{})), \
             patch('heuristic_design.problems.routing_fixtures.compile_members'), \
             patch('heuristic_design.problems.routing_fixtures.precheck_instances',return_value=[{'file':'UNIT_ONLY','reference':1}]), \
             patch.object(e,'run',side_effect=AssertionError('NO RUN')):
            ids=[]
            for arm in ('A','B'):
                path=Path(tmp)/arm
                e.prepare(path,self.plan['arm_configs'][arm],imports=imports,h_members=hs,instances=data)
                p=read(path/'Protocol.json');ids.append(digest(p))
                self.assertEqual(p['config']['survival_policy'],ab.POLICIES[arm]);self.assertFalse(p['config']['real_requests_authorized'])
            self.assertNotEqual(*ids)

    def test_resume_routes_to_frozen_pair_and_ignores_edited_top_parameters(self):
        with patch.dict(entry.PARAMETERS,{'generations':999,'real_requests_authorized':True}), \
             patch.object(entry,'existing_arm',return_value=0) as old,patch.object(entry,'preview',side_effect=AssertionError('NO NEW PARAMS')), \
             patch('sys.argv',['run_survival_ab.py','--resume','A','--pair-dir','UNIT_ONLY']),redirect_stdout(io.StringIO()):
            self.assertEqual(entry.main(),0)
        self.assertEqual(old.call_args.kwargs['resume'],True)

    def test_pair_fingerprint_binds_budget_and_P0_but_not_the_enable_switch(self):
        p=deepcopy(self.plan);original=ab.fingerprint(p)
        for c in p['arm_configs'].values():c['real_requests_authorized']=True
        self.assertEqual(ab.fingerprint(p),original)
        p['arm_configs']['B']['api_attempt_cap']+=1
        self.assertNotEqual(ab.fingerprint(p),original)
        p=deepcopy(self.plan);p['shared_p0']['imports'][0]['source']='changed'
        self.assertNotEqual(ab.fingerprint(p),original)

    def test_actual_import_recheck_does_not_seed_reference_fitness(self):
        from heuristic_design.core.storage import write
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);write(d/'checkpoint.json',{'generation':1})
            refs=self.plan['shared_p0']['reference_evaluations']
            pop=[{'candidate':{'key':r['candidate_key']},'fitness':r['fitness'],'behavior_sha256':r['behavior_sha256']} for r in refs]
            write(d/'populations/P000.json',pop);ab.certify_imported_p0(d,self.plan)
            self.assertTrue(read(d/'launch/p0-recheck.json')['passed'])
            pop[0]['fitness']+=1;write(d/'populations/P000.json',pop)
            with self.assertRaises(ValueError):ab.certify_imported_p0(d,self.plan)

    def test_arm_Protocol_cannot_be_swapped_between_pair_policies(self):
        p={'config':self.plan['arm_configs']['B'],'source_files':self.plan['source_files'],
           'imports':self.plan['shared_p0']['imports']}
        with patch.object(ab,'read',return_value=p),self.assertRaises(ValueError):
            ab.check_arm_binding(Path('UNIT_ONLY'),'A',self.plan)
        p['config']=self.plan['arm_configs']['A']
        with patch.object(ab,'read',return_value=p):ab.check_arm_binding(Path('UNIT_ONLY'),'A',self.plan)


if __name__=='__main__':unittest.main()
