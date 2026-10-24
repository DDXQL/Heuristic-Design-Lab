"""Borda mechanism, V1/V2 regression and spawned bounded evaluation Mock."""
from dataclasses import asdict
import importlib
import math
import multiprocessing as mp
from pathlib import Path
import json
import random
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.fusion_v3.ranking import borda_twice,borda_scores,ws_certificate
from fjsp_usage.fusion_v3.execution import decode_rank,fuse_rank,fixed_borda,construct_rank_schedule
from fjsp_usage.fusion_v2.execution import construct_fusion_schedule,v1_adapter
from fjsp_usage.usage_v2.execution import construct_usage_schedule,UsageOutputError,NormalizationError,normalize_scores
from fjsp_usage.research.candidates import validate_code,H_ARGS
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance,Operation
from tools import fusion_v2_experiment as old
from tools import fusion_v3_experiment as batch


def toy():
    return FJSPInstance('rank-toy',2,((Operation(((0,2),(1,3))),Operation(((0,5),(1,6)))),(Operation(((0,4),)),)))


class RankTests(unittest.TestCase):
    def test_midranks_constants_singletons_and_tie_fairness(self):
        self.assertEqual(borda_twice((10,6,0)),(4,2,0))
        self.assertEqual(borda_twice((5,5,0,10)),(3,3,0,6))
        self.assertEqual(borda_twice((7,7,7)),(2,2,2))
        self.assertEqual(borda_twice((7,)),(0,))
        for n in (1,2,5,50):
            values=tuple(i//3 for i in range(n))
            self.assertEqual(sum(borda_twice(values)),n*(n-1))

    def test_borda_unique_action_outside_all_linear_WS(self):
        columns={0:(.6,1,.4,.5,.2,0),1:(.6,.4,1,.2,.5,0)}
        points,_=borda_scores(columns,(0,1))
        self.assertEqual(points,(16,14,14,8,8,0))
        self.assertEqual(max(range(6),key=points.__getitem__),0)
        self.assertEqual(sum(x==max(points) for x in points),1)
        certificate=ws_certificate(columns,columns,(0,1),0)
        self.assertEqual(certificate['status'],'outside_real_linear_WS')
        # For any alpha, at least one endpoint score >= their mean .7 > .6.
        self.assertGreater((1+.4)/2,.6)

    def test_rank_sum_borda_equivalence_and_monotone_invariance(self):
        values=(0,1,1,5,12)
        ranks=borda_twice(values)
        for transformed in (tuple(100*x+7 for x in values),tuple(x**3 for x in values)):
            self.assertEqual(ranks,borda_twice(transformed))
        columns={0:(10,6,0),1:(0,80,100)}
        points,_=borda_scores(columns,(0,1))
        self.assertEqual(points,(4,4,4))
        self.assertEqual(max(range(3),key=points.__getitem__),0)
        ws,_=old.fuse_scores(columns,(.5,.5),(0,1),'WEIGHTED_SUM')
        self.assertEqual(max(range(3),key=ws.__getitem__),1)

    def test_numeric_boundaries_do_not_minmax_before_ranking(self):
        values=(14.799999999999994,14.799999999999999,-100.)
        self.assertEqual(borda_twice(values),(2,4,0))
        self.assertEqual(borda_twice((-1e308,0.,1e308)),(0,2,4))
        for values in ((),(True,1),(math.nan,0),(math.inf,0),('1',2)):
            with self.assertRaises(ValueError):borda_twice(values)
        with self.assertRaises(ValueError):borda_scores({0:(1,),1:(1,2)},(0,1))

    def test_interface_support_weights_and_invalid_indices(self):
        for output in (('BORDA',(0,0,0)),('BORDA',(1,0,0)),('BORDA',(1,2,0)),
                       ('BORDA',(1,1,1)),('BORDA',(-1,1,0)),('BORDA',(True,1,0)),
                       ('BORDA',(1,math.nan,0)),('BORDA',(1,math.inf,0)),('BORDA',(1,1)),
                       ('BORDA',(1e100,1e-300,0))):
            with self.subTest(output=output),self.assertRaises((UsageOutputError,NormalizationError)):
                decode_rank(output,3)
        self.assertEqual(decode_rank(('BORDA',(.5,.5,0)),3)['dominant'],0)
        for pair in ((1,1),(-1,0),(0,3),(True,2),(1,0)):
            with self.assertRaises(ValueError):fixed_borda(pair,3)
        with self.assertRaises(UsageOutputError):fuse_rank({0:(0,1),1:(1,0)},(.3,.7),(0,1),'BORDA')

    def test_all_v2_operators_bitwise_schedule_compatibility(self):
        rules=(lambda p,w,n,j,m,s,f:-f,lambda p,w,n,j,m,s,f:w-p,lambda *s:2.)
        policies=[lambda *s:('SELECT',(0,0,0)),lambda *s:('SELECT',(-2,-1,-3)),
                  lambda *s:('WEIGHTED_SUM',(0,1,0)),lambda *s:('WEIGHTED_SUM',(.3,.7,0)),
                  lambda p,*s:('WEIGHTED_SUM',(p+.1,1-p,0)),
                  lambda *s:('MAX',(0,1,1)),lambda *s:('MIN',(1,1,0))]
        for policy in policies:
            trace1=[];trace2=[]
            first=construct_fusion_schedule(toy(),rules,policy,trace=trace1.append)
            second=construct_rank_schedule(toy(),rules,policy,trace=trace2.append)
            self.assertEqual(first,second)
            self.assertEqual([r['state'] for r in trace1],[r['state'] for r in trace2])
            self.assertEqual([r['chosen'] for r in trace1],[r['chosen'] for r in trace2])
        v1=lambda p,*s:(1,(p+.1,1-p,0))
        first=construct_usage_schedule(toy(),rules,v1)
        self.assertEqual(first.schedule,construct_rank_schedule(toy(),rules,v1_adapter(v1)).schedule)

    def test_stable_ties_previous_member_and_repeat_determinism(self):
        rules=(lambda *s:5.,lambda *s:5.,lambda *s:0.)
        trace=[];policy=fixed_borda((0,1),3)
        random.seed(501);first=construct_rank_schedule(toy(),rules,policy,trace=trace.append)
        random.seed(501);second=construct_rank_schedule(toy(),rules,policy)
        self.assertEqual(first,second)
        self.assertEqual(trace[0]['chosen'][:3],(0,0,0))
        self.assertEqual([r['state']['previous_heuristic'] for r in trace],[-1,0,0])
        self.assertTrue(all(type(x) is int for row in trace for x in row['scores']))

    def test_WS_exact_certificate_endpoints_interior_and_ties(self):
        columns={0:(1,.6,0),1:(0,.8,1)}
        self.assertEqual(ws_certificate(columns,columns,(0,1),0)['status'],'raw_endpoint_witness')
        self.assertEqual(ws_certificate(columns,columns,(0,1),1)['status'],'interior_IEEE_witness')
        columns={0:(1,1,0),1:(1,1,0)}
        self.assertEqual(ws_certificate(columns,columns,(0,1),1)['status'],'outside_real_linear_WS')

    def test_real_spawned_mock_and_identity_attestation(self):
        paths={str(Path(importlib.import_module(n).__file__).resolve().relative_to(batch.ROOT))
               for n in old.MODULES+batch.NEW_MODULES}
        p={'source_files':{n:old.sha(batch.ROOT/n) for n in paths},
           'instances':[{'relative_path':'inputs/train/toy.fjsp'}]}
        expected=batch.witness(p)
        with patch('fjsp_usage.fusion_v3.ranking.borda_twice',lambda x:()):
            with self.assertRaisesRegex(ValueError,'loaded function mismatch'):batch.witness(p)
        members=tuple(validate_code('def priority('+', '.join(H_ARGS)+'):\n    return -'+H_ARGS[-1]+'\n',kind='h') for _ in range(10))
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);spec=batch.specs()[0];folder=directory/'evidence'/spec['id'];folder.mkdir(parents=True)
            receipts=[]
            rows,failure,life=old.collect_with_lifecycle(mp.get_context('spawn'),batch.worker,
                {'directory':str(directory),'protocol':p,'spec':spec},members,(toy(),),('toy.fjsp',),15,None,receipts.append)
            self.assertIsNone(failure);self.assertEqual(life['exitcode'],0);self.assertFalse(life['alive'])
            self.assertEqual(rows[0]['physical_schedule_sha256'],rows[0]['recheck_physical_schedule_sha256'])
            self.assertEqual(old.read(folder/'before.json')['identity'],expected['identity'])
            self.assertEqual(old.read(folder/'after.json')['identity'],expected['identity'])
            self.assertEqual(rows[0]['network_guard'],{'network_attempts_blocked':0,'nontrain_opens_blocked':0})

    def test_unknown_reservation_stops_before_any_instance_or_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            state={'protocol_sha256':'bound','phase':'running',
                   'strategies':{batch.specs()[0]['id']:{'status':'reserved'}}}
            (directory/'checkpoint.json').write_text(json.dumps(state))
            with patch.object(batch,'check',return_value={}),patch.object(old,'sha',return_value='bound'),\
                 patch.object(old,'load_instance',side_effect=AssertionError('unexpected instance load')) as loader,\
                 patch.object(old,'collect_with_lifecycle',side_effect=AssertionError('unexpected solve')) as collector:
                with self.assertRaisesRegex(ValueError,'uncertain reservation'):batch.run(directory)
                loader.assert_not_called();collector.assert_not_called()


if __name__=='__main__':unittest.main()
