"""Static coverage, native semantic regression, cache and lifecycle integration."""
from copy import deepcopy
import gzip
import importlib
import json
import multiprocessing as mp
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch,Mock

from fjsp_usage.baseline_a.policies import specs,policy
from fjsp_usage.baseline_a.validation import validate_result,validate_ledger
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule,fuse_scores
from fjsp_usage.usage_v2.execution import construct_usage_schedule,combine_scores
from fjsp_usage.research.candidates import validate_code,H_ARGS
from fjsp_usage.research.protocol import digest
from fjsp_usage.research.events import atomic_json
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance,Operation
from llm4ad.task.optimization.fjsp_set.scheduler import construct_schedule
from tools import tier2_baseline_a as b
from tools.tier2_baseline_a_report import single_oracle


def toy():
    return FJSPInstance('baseline-toy',2,((Operation(((0,2),(1,3))),Operation(((0,5),(1,6)))),(Operation(((0,4),)),)))


def synthetic_row(name):
    physical={'makespan':1,'operations':[[0,0,0,0,1]]}
    return {'file':name,'makespan':1,'lower_bound':1.,'score':-1.,'feasible':True,
        'single_solve_seconds':.01,'deterministic_recheck_seconds':.01,'captured_solves':2,
        'physical_schedule':physical,'physical_schedule_sha256':digest(physical),'recheck_physical_schedule_sha256':digest(physical),
        'single_h_calls':[1,1],'recheck_h_calls':[1,1],'network_guard':{'network_attempts_blocked':0,'nontrain_opens_blocked':0}}


class StaticTests(unittest.TestCase):
    def test_exact_10_and_45_no_duplicate_or_missing_pairs(self):
        definitions=specs();self.assertEqual(len(definitions),55);self.assertEqual(len({s['id'] for s in definitions}),55)
        self.assertEqual([s['members'] for s in definitions[:10]],[[i] for i in range(10)])
        self.assertEqual({tuple(s['members']) for s in definitions[10:]},{(i,j) for i in range(10) for j in range(i+1,10)})
        for s in definitions:
            op,vector=policy(s)(0,0,0,0,0,0,-1)
            self.assertEqual(op,'SELECT' if s['category']=='A1' else 'WEIGHTED_SUM')
            self.assertEqual(sum(vector),1.)
            self.assertEqual([i for i,v in enumerate(vector) if v>0],s['members'])
        with self.assertRaises(ValueError):policy(dict(definitions[10],members=[1,0]))

    def test_single_raw_scores_and_double_independent_normalization(self):
        scores,info=fuse_scores({0:(-100.,-2.,-1.)},(1.,)+(0.,)*9,(0,),'SELECT')
        self.assertEqual(scores,(-100.,-2.,-1.))
        cols={0:(-3.,0.,3.),1:(50.,0.,25.)};weights=(.5,.5)+(0.,)*8
        self.assertEqual(fuse_scores(cols,weights,(0,1),'WEIGHTED_SUM')[0],(.5,.25,.75))
        self.assertEqual(fuse_scores(cols,weights,(0,1),'WEIGHTED_SUM'),combine_scores(cols,weights,(0,1)))
        self.assertEqual(fuse_scores({0:(9.,9.),1:(9.,9.)},weights,(0,1),'WEIGHTED_SUM')[0],(0.,0.))

    def test_native_single_and_v1_two_member_deterministic_compatibility(self):
        instance=toy();rules=[lambda p,w,n,j,m,s,f:-f,lambda p,w,n,j,m,s,f:w-p]+[lambda *a:0.]*8
        for s in specs():
            usage=policy(s);op,vector=usage()
            native=lambda *a:(0 if op=='SELECT' else 1,vector)
            random.seed(501);first=construct_fusion_schedule(instance,rules,usage)
            random.seed(501);second=construct_fusion_schedule(instance,rules,usage)
            self.assertEqual(first,second)
            legacy=construct_usage_schedule(instance,rules,native)
            self.assertEqual(first.schedule,legacy.schedule);self.assertEqual(first.score,legacy.score)
            if s['category']=='A1':self.assertEqual(first.schedule,construct_schedule(instance,rules[s['members'][0]]))
        constant=construct_fusion_schedule(instance,[lambda *a:0.]*10,policy(specs()[10]))
        self.assertEqual((constant.schedule.operations[0].job,constant.schedule.operations[0].machine),(0,0))

    def test_H01_all21_cache_and_recorded_matrix_v1_replay(self):
        result=b.v2.read(b.v2.DEFAULT/'evidence/H0_H1_WEIGHTED_SUM/result.json')
        legacy=b.v2.read(b.ROOT/'reports/usage-fixed-pair-weight-grid-20261018-v1/results/H0_H1_w50_50.json')
        self.assertEqual([(r['makespan'],r['score'],r['physical_schedule_sha256']) for r in result['instances']],
            [(r['makespan'],r['score'],r['physical_schedule_sha256']) for r in legacy['instances']])
        states=0
        for row in result['instances']:
            path=b.v2.DEFAULT/row['trace_path'];self.assertEqual(b.v2.sha(path),row['trace_sha256'])
            with gzip.open(path,'rt') as f:
                for t in map(json.loads,f):
                    columns={int(i):tuple(c) for i,c in t['columns'].items()}
                    scores,_=combine_scores(columns,t['weights'],tuple(t['support']))
                    self.assertEqual(tuple(t['scores']),scores)
                    self.assertEqual(max(range(len(scores)),key=scores.__getitem__),t['winner']);states+=1
        self.assertEqual(states,3800)

    def test_real_spawn_worker_two_solve_identity(self):
        modules=b.v2.MODULES+b.old.v3.NEW_MODULES+b.old.MODULES+b.MODULES
        paths={str(Path(importlib.import_module(n).__file__).resolve().relative_to(b.ROOT)) for n in modules}
        p={'source_files':{n:b.v2.sha(b.ROOT/n) for n in paths},'instances':[{'relative_path':'inputs/train/toy.fjsp'}]}
        expected=b.witness(p)
        with patch('fjsp_usage.baseline_a.policies.policy',lambda x:None):
            with self.assertRaisesRegex(ValueError,'loaded function differs'):b.witness(p)
        members=tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -'+H_ARGS[-1]+'\n',kind='h') for _ in range(10))
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);spec=specs()[10];folder=directory/'evidence'/spec['id'];folder.mkdir(parents=True)
            rows,failure,life=b.collect(mp.get_context('spawn'),b.worker,{'directory':str(directory),'protocol':p,'spec':spec},
                members,(toy(),),('toy.fjsp',),15,None,lambda x:None)
            self.assertIsNone(failure);self.assertEqual(life['exitcode'],0);self.assertFalse(life['alive'])
            self.assertEqual(b.v2.read(folder/'before.json')['identity'],expected['identity'])
            self.assertEqual(b.v2.read(folder/'after.json')['identity'],expected['identity'])
            validate_result({'valid':True,'fitness':rows[0]['score'],'total_instances':1,'instances':rows},
                [{'file':'toy.fjsp','LB':rows[0]['lower_bound']}],'modern')


class EvidenceTests(unittest.TestCase):
    def test_readonly_actual_cache_audit_full_H_order_and_missing_list(self):
        from tools.baseline_a_audit import audit_inputs
        audit=audit_inputs()
        self.assertEqual(audit['summary']['single_cached'],10);self.assertEqual(audit['summary']['pair_cached'],4)
        self.assertEqual(set(audit['cache'])-{f'H{i}' for i in range(10)},
            {'H0_H1_WS','H0_H2_WS','H0_H3_WS','H3_H6_WS'})
        self.assertEqual(len(audit['missing_strategies']),41)
        self.assertEqual(audit['summary']['new_evaluation_cap']+audit['summary']['deducted_cached_evaluations'],1155)
        frozen=b.v2.read(b.old.DEFAULT/'H_frozen.json')
        self.assertEqual(audit['H_order'],[r['candidate']['key'] for r in frozen['members']])

    def fixture(self):
        rows=[synthetic_row('toy')]
        return {'valid':True,'fitness':-1.,'total_instances':1,'instances':rows},[{'file':'toy','LB':1.}]

    def test_invalid_prefix_never_has_fitness_or_oracle(self):
        result,instances=self.fixture();validate_result(result,instances,'modern')
        invalid=dict(result,valid=False,fitness=None);validate_result(invalid,instances,'modern')
        with self.assertRaises(ValueError):validate_result(dict(invalid,fitness=-1.),instances,'modern')
        with self.assertRaises(ValueError):single_oracle({'H0':result},instances)

    def test_corrupt_cache_LB_hash_cost_and_member_calls_rejected(self):
        result,instances=self.fixture()
        for key,value in [('lower_bound',2.),('score',0.),('feasible',False),('captured_solves',1),
                          ('recheck_physical_schedule_sha256','wrong'),('single_solve_seconds',None),('recheck_h_calls',[2,1])]:
            broken=deepcopy(result);broken['instances'][0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):validate_result(broken,instances,'legacy_pair')

    def test_oracle_is_mean_of_instance_optima_ties_and_ratio(self):
        results={f'H{i}':{'valid':True,'instances':[{'file':'a','lower_bound':2.,'makespan':4+i,'score':-(4+i)/2},
            {'file':'b','lower_bound':3.,'makespan':10-i,'score':-(10-i)/3}]} for i in range(10)}
        instances=[{'file':'a','LB':2.},{'file':'b','LB':3.}]
        oracle=single_oracle(results,instances)
        self.assertEqual(oracle['fitness'],(-2.-1/3)/2)
        self.assertEqual([r['display_member'] for r in oracle['instances']],[0,9]);self.assertFalse(oracle['online_policy'])
        self.assertFalse(oracle['global_dynamic_upper_bound'])

    def test_ledger_cache_and_resume_budget_guards(self):
        result,instances=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);atomic_json(directory/'Protocol.json',{});atomic_json(directory/'H0.json',result)
            h=b.v2.sha(directory/'H0.json');p={'cache':{'H0':{'result_path':'H0.json','sha256':h,'level':'modern'}},
                'instances':instances,'new_evaluation_cap':861,'new_solve_pass_cap':1722}
            record={'status':'completed','origin':'cache','valid':True,'reserved_evaluations':0,'reserved_solve_passes':0,'result_path':'H0.json','result_sha256':h}
            state={'protocol_sha256':b.v2.sha(directory/'Protocol.json'),'strategies':{'H0':record}}
            self.assertEqual(validate_ledger(state,p,b.v2.read,b.v2.sha,directory),0)
            for change in ({'status':'reserved'},{'reserved_evaluations':21},{'result_sha256':'wrong'},{'origin':'new'}):
                bad=deepcopy(state);bad['strategies']['H0'].update(change)
                with self.assertRaises(ValueError):validate_ledger(bad,p,b.v2.read,b.v2.sha,directory)
            bad=deepcopy(state);bad['strategies']['H0_H1_WS']={**record,'origin':'new','reserved_evaluations':21,'reserved_solve_passes':42}
            with self.assertRaisesRegex(ValueError,'budget exceeded'):
                validate_ledger(bad,dict(p,new_evaluation_cap=0),b.v2.read,b.v2.sha,directory)

    def test_confirmed_timeout_continues_next_and_resume_does_not_repeat(self):
        definitions=[s for s in specs() if s['id'] in ('H0_H5_WS','H0_H6_WS')]
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);(directory/'evidence').mkdir();(directory/'proof.txt').write_text('synthetic')
            p={'instances':[{'file':f'MOCK{i}','LB':1.,'relative_path':f'MOCK{i}'} for i in range(21)],'cache':{},
                'new_evaluation_cap':861,'new_solve_pass_cap':1722,'source_files':{'proof.txt':b.v2.sha(directory/'proof.txt')},'protected_files':{}}
            atomic_json(directory/'Protocol.json',p)
            atomic_json(directory/'checkpoint.json',{'protocol_sha256':b.v2.sha(directory/'Protocol.json'),'phase':'prepared','strategies':{}})
            atomic_json(directory/'H_frozen.json',{'members':[{'candidate':{}} for _ in range(10)]})
            witness={'pid':123,'modules':{'synthetic':'fixed'},'identity':digest({'synthetic':'fixed'})}
            atomic_json(directory/'Expected_loaded_identity.json',witness)
            def collector(context,target,payload,members,instances,names,timeout,modes,persist):
                self.assertEqual(timeout,15);folder=directory/'evidence'/payload['spec']['id']
                atomic_json(folder/'before.json',witness)
                normal=payload['spec']['id']=='H0_H6_WS'
                life={'pid':123,'status':'terminal','alive':False,'exitcode':0 if normal else -15,
                    'deadline_seconds':15,'trigger':None if normal else 'parent_poll_timeout','expected_rows':21,
                    'rows_received':21 if normal else 0,'all_results_received':normal,'exit_grace_seconds':2.,
                    'exit_grace_used':normal,'results_complete_monotonic':1 if normal else None,
                    'cleanup':['join_exit_grace_2.0'] if normal else ['join_0.05','terminate']}
                persist(life)
                if normal:
                    atomic_json(folder/'after.json',witness);atomic_json(folder/'network_guard.json',{})
                    return [synthetic_row(n) for n in names],None,life
                return [],{'error_type':'Timeout','error':'whole-instance deadline exceeded','failed_instance':names[0]},life
            with patch.object(b,'ROOT',directory),patch.object(b,'check',return_value=p),patch.object(b,'train_guard',return_value={}),\
                 patch.object(b,'specs',return_value=definitions),patch.object(b.v2,'checked_candidate',return_value={}),\
                 patch.object(b.v2,'load_instance',return_value=object()),patch.object(b,'collect',side_effect=collector) as collect:
                b.run(directory);state=b.v2.read(directory/'checkpoint.json')
                self.assertFalse(state['strategies']['H0_H5_WS']['valid']);self.assertTrue(state['strategies']['H0_H6_WS']['valid'])
                self.assertIsNone(b.v2.read(directory/state['strategies']['H0_H5_WS']['result_path'])['fitness'])
                b.run(directory);self.assertEqual(collect.call_count,2)


if __name__=='__main__':unittest.main()
