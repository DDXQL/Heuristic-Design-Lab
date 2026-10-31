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
    # Editable local launch switches/grant paths are not test prerequisites.
    return ab.preview({**entry.PARAMETERS,'real_requests_authorized':False},source=entry.P0_SOURCE,pair_directory=entry.PAIR_DIRECTORY,
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

    def _gate_state(self,ready=False):
        refs=self.plan['shared_p0']['reference_evaluations']
        pop=[{'id':f'INIT-{i:04d}','candidate':{'key':r['candidate_key']},
              'fitness':r['fitness'],'behavior_sha256':r['behavior_sha256']} for i,r in enumerate(refs)]
        return {'identity':'UNIT_ONLY','phase':'paused','generation':0,'population':pop,
                'initialization_complete':ready,'completed_tasks':10,'generation_requests':0,
                'initialization_requests':0,'plans':{},'pause_ack':0}

    def _run_gate(self,d,state):
        # Drive coordinator control flow using saved data only. No evaluator,
        # transport, synthetic search, prepare, or imported candidate executes.
        with patch.object(e,'check',return_value=({'config':self.plan['arm_configs']['A']},state)), \
             patch('heuristic_design.llm.routing_transport.preflight'),patch.object(e,'log_progress'), \
             patch.object(e,'_execute_batch',side_effect=AssertionError('NO GENERATE/EVALUATE')) as batch, \
             patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')):
            result=e.run(d,evaluate=lambda *a:None,before_evolution=lambda path:ab.p0_generation_gate(path,self.plan))
            batch.assert_not_called()
        return result

    def test_P0_mismatch_blocks_at_generation_zero_without_plans_reservations_or_lock(self):
        from heuristic_design.core.storage import write
        for ready in (False,True):
            for field,bad in (('fitness',100.0),('behavior_sha256','WRONG'),('candidate',{'key':'WRONG'})):
                with self.subTest(ready=ready,field=field),tempfile.TemporaryDirectory() as temp:
                    d=Path(temp);state=self._gate_state(ready);state['population'][0][field]=bad
                    if ready:write(d/'populations/P000.json',state['population'])
                    with patch.object(e,'plan_generation',side_effect=AssertionError('NO PLAN')) as planner:
                        result=self._run_gate(d,state)
                        planner.assert_not_called()
                    self.assertEqual(result['phase'],'blocked');self.assertEqual(result['generation_requests'],0)
                    self.assertEqual(state['plans'],{});self.assertFalse((d/'.coordinator.lock').exists())
                    self.assertFalse(read(d/'launch/p0-before-generation.json')['passed'])

    def test_missing_P0_is_fail_closed_before_generation(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp)
            with patch.object(e,'plan_generation',side_effect=AssertionError('NO PLAN')):
                result=self._run_gate(d,self._gate_state(True))
            self.assertEqual(result['phase'],'blocked')
            self.assertFalse(read(d/'launch/p0-recheck.json')['passed'])

    def test_matching_P0_gate_runs_before_first_plan_including_resume(self):
        import random
        from heuristic_design.core.storage import write
        class ReachedFirstPlan(Exception):pass
        for ready in (False,True):
            with self.subTest(ready=ready),tempfile.TemporaryDirectory() as temp:
                d=Path(temp);state=self._gate_state(ready);state['rng']=random.Random(501).getstate()
                if ready:write(d/'populations/P000.json',state['population'])
                def first_plan(*args):
                    receipt=read(d/'launch/p0-before-generation.json')
                    self.assertTrue(receipt['passed']);self.assertEqual(receipt['generation'],0)
                    self.assertEqual(receipt['generation_requests'],0)
                    raise ReachedFirstPlan()
                with patch.object(e,'plan_generation',side_effect=first_plan),self.assertRaises(ReachedFirstPlan):
                    self._run_gate(d,state)
                self.assertEqual(state['generation_requests'],0)

    def test_resume_entry_forwards_the_same_P0_gate(self):
        with patch.object(ab,'read_pair',return_value=self.plan),patch.object(ab,'check_arm_binding'), \
             patch.object(ab,'existing',return_value=0) as existing, \
             patch.object(ab,'certify_imported_p0',return_value=True),patch.object(ab,'p0_generation_gate',return_value=True) as gate:
            self.assertEqual(ab.existing_arm(Path('UNIT_ONLY'),'A',root=entry.ROOT,resume=True),0)
            callback=existing.call_args.kwargs['before_evolution']
            self.assertTrue(callback(Path('UNIT_ONLY/A')))
            gate.assert_called_once_with(Path('UNIT_ONLY/A'),self.plan)

    def test_blocked_resume_returns_without_export_or_postprocessing(self):
        from experiments.common import _real_run
        from heuristic_design.core.storage import write,sha
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);folder=d/'launch';folder.mkdir()
            helper=folder/'_search_reports.py'
            helper.write_text('def finish(*args):\n    raise AssertionError("NO POSTPROCESS")\n')
            write(folder/'baselines.json',{})
            write(folder/'postprocess.receipt.json',{'helper_sha256':sha(helper),
                'baselines_sha256':sha(folder/'baselines.json')})
            gate=lambda path:False
            with patch.object(e,'check',return_value=({}, {'phase':'paused'})), \
                 patch.object(e,'run',return_value={'phase':'blocked','generation':0}) as run, \
                 patch.object(_real_run,'export',side_effect=AssertionError('NO EXPORT')) as export,redirect_stdout(io.StringIO()):
                self.assertEqual(_real_run.existing(d,root=d,resume=True,before_evolution=gate),2)
                run.assert_called_once_with(d.resolve(),allow_api=True,before_evolution=gate)
                export.assert_not_called()

    def test_arm_Protocol_cannot_be_swapped_between_pair_policies(self):
        p={'config':self.plan['arm_configs']['B'],'source_files':self.plan['source_files'],
           'imports':self.plan['shared_p0']['imports']}
        with patch.object(ab,'read',return_value=p),self.assertRaises(ValueError):
            ab.check_arm_binding(Path('UNIT_ONLY'),'A',self.plan)
        p['config']=self.plan['arm_configs']['A']
        with patch.object(ab,'read',return_value=p):ab.check_arm_binding(Path('UNIT_ONLY'),'A',self.plan)


if __name__=='__main__':unittest.main()
