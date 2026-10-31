"""Scoped offline checks for formal entry; no real transport or train21 solves."""
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import asdict
import errno
import io
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from experiments.common import run_b1_v6 as entry, _real_run as launch, _search_reports as reports
from heuristic_design.core import evolution_v1 as e, routing, routing_evaluation as evaluation
from heuristic_design.core.storage import read, write, sha, digest
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.problems import routing_fixtures as fixtures


class Tests(unittest.TestCase):
    def test_disk_observation_does_not_block_when_threshold_is_none(self):
        from types import SimpleNamespace
        parameters={**entry.PARAMETERS,'real_requests_authorized':False}
        args=dict(root=entry.ROOT,stage='b1',run_root=entry.RUN_ROOT,r1_runs=entry.R1_RUNS,
                  pilot_run=entry.R3_RUN_DIR,r3_compatibility_file=entry.R3_COMPATIBILITY_FILE)
        with patch.object(launch.shutil,'disk_usage',return_value=SimpleNamespace(free=1)):
            _,plan,_=launch.preflight(parameters,min_free_gib=None,**args)
            self.assertEqual(plan['blocking'],[])
            self.assertFalse(plan['disk_space_gate_enabled']);self.assertIsNone(plan['required_free_GiB'])
            self.assertFalse(plan['real_requests_authorized']);self.assertEqual(plan['total_attempt_cap'],1050)
            _,limited,_=launch.preflight(parameters,min_free_gib=20,**args)
            self.assertTrue(limited['disk_space_gate_enabled'])
            self.assertTrue(any('磁盘' in reason for reason in limited['blocking']))

    def test_exact_new_budget_and_parent_coverage_without_execution(self):
        c=e.config(entry.PARAMETERS)
        self.assertEqual((c['population_size'],c['generations'],c['initialization_request_cap'],
            c['generation_request_cap'],c['api_attempt_cap']),(10,50,50,1000,1050))
        self.assertTrue(c['real_requests_authorized'])
        self.assertEqual((c['api_concurrency'],c['evaluation_concurrency']),(2,2))
        pop=[{'id':str(i),'candidate':{'key':str(i)}} for i in range(10)]
        before=deepcopy(pop);rng=random.Random(501);total=0
        for g in range(1,51):
            plan=e.plan_generation(pop,g,rng);total+=len(plan)
            for parent in pop:
                pair=[t for t in plan if t['subject']==parent['id']]
                self.assertEqual({t['operator'] for t in pair},{'CROSS','MUTATE'})
                cross=next(t for t in pair if t['operator']=='CROSS')
                self.assertEqual(cross['parents'][0],parent['id'])
                self.assertNotEqual(cross['parents'][0],cross['parents'][1])
                self.assertTrue(set(cross['parents'])<=set(str(i) for i in range(10)))
        self.assertEqual(total,1000);self.assertEqual(pop,before)
        for change in ({'milestone_generations':[20,10]}, {'milestone_generations':[51]},
                       {'recording_mode':'small'}, {'ignored_parameter':1}):
            with self.assertRaises(ValueError):e.config({**entry.PARAMETERS,**change})

    def test_full_compact_same_schedules_routing_h_calls_and_scores(self):
        c=e.config(entry.PARAMETERS);members,_,_=inputs(c)
        data=fixtures.instances('fjsp',size=6,count=1)
        pilot=read(entry.ROOT/entry.R3_RUN_DIR/'checkpoint.json')
        candidates=[t['candidate'] for t in pilot['tasks'].values() if t['valid']]
        self.assertGreaterEqual(len(candidates),2)
        for candidate in candidates:
            a=fixtures.solve('fjsp',data[0],members,candidate,trace=True)
            b=fixtures.solve('fjsp',data[0],members,candidate,trace=False)
            for key in ('score','solution','h_calls','member_sequence'):self.assertEqual(a[key],b[key])
            self.assertEqual(a['member_sequence'],[t['member_id'] for t in a['trace']])
            self.assertTrue(a['trace']);self.assertEqual(b['trace'],[])

    def test_compact_worker_two_pass_receipts_and_behavior(self):
        c=e.config(entry.PARAMETERS);members,_,_=inputs(c)
        data=fixtures.instances('fjsp',size=6,count=1)
        candidate=asdict(routing.validate('def use_heuristics(state):\n    return 0\n',member_count=10))
        with tempfile.TemporaryDirectory() as temp:
            p={'run_directory':temp,'config':c,'source_files':e.source_identity(),'members':members,'instances':data}
            r=evaluation.evaluate_task({'id':'UNIT_ONLY','candidate':candidate},p)
            self.assertTrue(r['valid']);self.assertEqual(r['recording_mode'],'compact')
            row=r['instances'][0];self.assertEqual(row['captured_solves'],2)
            self.assertEqual(row['semantic_sha256'],row['recheck_semantic_sha256'])
            self.assertEqual(r['behavior'],[row['member_sequence']]);self.assertEqual(row['trace'],[])
            self.assertEqual(r['lifecycle']['cleanup'],['join_exit_grace_2.0'])
            self.assertFalse(r['lifecycle']['alive'])

    def test_compact_hardlink_fallback_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);result={'valid':True};task={'id':'unit'}
            origin=d/'worker-receipts/unit/result.json';write(origin,result)
            path,method=e.store_evaluation(d,task,'one',result,'compact')
            self.assertEqual(method,'hardlink');self.assertEqual(path.stat().st_ino,origin.stat().st_ino)
            with self.assertRaises(FileExistsError):e.store_evaluation(d,task,'one',{'changed':True},'compact')
            with patch.object(e.os,'link',side_effect=OSError(errno.ENOTSUP,'unit FS fallback')):
                path,method=e.store_evaluation(d,task,'two',result,'compact')
            self.assertEqual(method,'copy');self.assertEqual(read(path),result)

    def test_milestone_receipts_preserve_cumulative_budget_and_reject_change(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);state={'generation':10,'identity':'unit','generations':[{'generation':10}],
                'population':[{'candidate':{'key':'k'}}],'evaluations':{'k':{'sha256':'evaluation'}},
                'initialization_requests':17,'generation_requests':200}
            e.save_milestone(d,state,{'config':{'milestone_generations':[10,20,30,40,50]}})
            value=read(d/'milestones/G010.json');self.assertEqual(value['generation_requests'],200)
            self.assertEqual(read(d/'milestones/G010.receipt.json')['sha256'],sha(d/'milestones/G010.json'))
            state['generation_requests']=201
            with self.assertRaises(FileExistsError):e.save_milestone(d,state,{'config':{'milestone_generations':[10]}})

    def test_actual_R1_reuse_no_solves_or_network(self):
        c=e.config(entry.PARAMETERS);members,data,_=inputs(c)
        with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')), \
             patch.object(fixtures,'solve',side_effect=AssertionError('NO SOLVE')):
            bundle=reports.baseline_bundle(entry.ROOT,entry.R1_RUNS,data,members,c)
        rows={r['name']:r for r in bundle['baselines']}
        self.assertEqual(set(rows),{'H0','BEST_FIXED_H','H0_H1_EQUAL','EOH_FROZEN'})
        self.assertAlmostEqual(rows['H0']['fitness'],-2.1118049606260487)
        self.assertAlmostEqual(rows['H0_H1_EQUAL']['fitness'],-1.9831442949150015)
        self.assertAlmostEqual(rows['EOH_FROZEN']['fitness'],-2.012187450378091)
        self.assertTrue(all(len(r['rows'])==21 for r in rows.values()))
        with self.assertRaises(ValueError):reports.baseline_bundle(entry.ROOT,entry.R1_RUNS,data,members,{**c,'window':11})

    def test_comparison_is_ratio_of_means_and_paired_wins_losses_ties(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);rows=[];base=[];refs=[]
            for i,(lb,new,old) in enumerate(((10,9,10),(20,24,20),(10,10,10))):
                name=str(i);refs.append({'file':name,'LB':lb})
                rows.append({'file':name,'score':-new/lb,'solution':{'makespan':new},'feasible':True,
                    'captured_solves':2,'semantic_sha256':'unit','recheck_semantic_sha256':'unit'})
                base.append({'file':name,'Cmax':old,'LB':lb})
            write(d/'Protocol.json',{});write(d/'Protocol.receipt.json',{'sha256':sha(d/'Protocol.json')})
            write(d/'checkpoint.json',{'identity':sha(d/'Protocol.json'),'evaluations':{'k':{'path':'result.json'}},
                'tasks':{'good':{'valid':True},'bad':{'valid':False}}})
            write(d/'result.json',{'instances':rows})
            write(d/'launch/baselines.json',{'instances':refs,'baselines':[{'name':'unit','fitness':-1.,'rows':base,
                'valid_rate':1.}],'historical_only':[{'name':'unit-history'}]})
            write(d/'launch/postprocess.receipt.json',{'baselines_sha256':sha(d/'launch/baselines.json')})
            (d/'exports').mkdir();champion={'id':'unit','candidate':{'key':'k'},'fitness':-3.1/3}
            reports.paired_comparison(d,champion)
            r=read(d/'exports/train21_comparison.json');table=r['comparisons'][0]
            self.assertAlmostEqual(table['mean_ratio_relative_change_percent'],100/30)
            self.assertEqual((table['wins'],table['losses'],table['ties']),(1,1,1))
            self.assertEqual(r['search_task_valid_rate'],.5);self.assertEqual(r['additional_solves'],0)
            rows.pop();write(d/'result.json',{'instances':rows})
            with self.assertRaises(ValueError):reports.paired_comparison(d,champion)

    def test_disabled_gate_never_prepares_or_requests(self):
        c=e.config({**entry.PARAMETERS,'real_requests_authorized':False})
        with patch.object(launch,'preflight',return_value=(c,{'blocking':[]},{})), \
             patch.object(launch.engine,'prepare') as prepare,redirect_stdout(io.StringIO()),self.assertRaises(PermissionError):
            launch.launch(entry.PARAMETERS,root=entry.ROOT,stage='b1',run_root=entry.RUN_ROOT,prefix=entry.RUN_PREFIX,
                min_free_gib=entry.MIN_FREE_GIB,r1_runs=entry.R1_RUNS,pilot_run=entry.R3_RUN_DIR,entry=Path(entry.__file__))
        prepare.assert_not_called()

    def test_resume_ignores_edited_top_parameters_and_uses_frozen_reporter(self):
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);helper=d/'launch/_search_reports.py'
            helper.parent.mkdir();helper.write_text('def finish(directory,summary): return {}\n')
            write(d/'launch/baselines.json',{})
            write(d/'launch/postprocess.receipt.json',{'helper_sha256':sha(helper),'baselines_sha256':sha(d/'launch/baselines.json')})
            with patch.dict(entry.PARAMETERS,{'generations':999,'api_attempt_cap':99999}), \
                 patch.object(e,'check',return_value=({'config':{'generations':50,'api_attempt_cap':1050}},{'phase':'paused'})), \
                 patch.object(e,'run') as run,patch.object(launch,'export',return_value={'phase':'completed','generation':50}), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(launch.existing(d,root=entry.ROOT,resume=True),0)
            run.assert_called_once_with(d.resolve(),allow_api=True)
            with patch.object(e,'check',return_value=({}, {'phase':'completed'})),patch.object(e,'run') as run, \
                 self.assertRaises(ValueError):launch.existing(d,root=entry.ROOT,resume=True)
            run.assert_not_called()


if __name__=='__main__':unittest.main()
