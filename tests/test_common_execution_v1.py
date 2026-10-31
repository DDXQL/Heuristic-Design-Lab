"""Real solver-backed new executor, separate CPU/request pools and pause control."""
from dataclasses import asdict
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from heuristic_design.core import evolution_v1 as e, routing
from heuristic_design.core.evolution_export import export
from heuristic_design.core.storage import read
from heuristic_design.core.storage import digest
from heuristic_design.problems import routing_fixtures


def p0():
    return [{'source':'handwritten-test-'+str(i),'candidate':asdict(routing.validate(
        'def use_heuristics(state):\n    return '+str(i)+'\n',member_count=3)),
        'old_fitness':99999} for i in range(2)]


class Tests(unittest.TestCase):
    def test_precheck_rejects_incompatible_data_before_any_request_or_run_creation(self):
        with tempfile.TemporaryDirectory() as t:
            bad=routing_fixtures.instances('fjsp',count=1)
            bad[0]['value']['jobs'][0][0][0][1]=1.5
            bad[0]['sha256']=digest(bad[0]['value'])
            folder=Path(t)/'bad'
            with self.assertRaises(ValueError):e.prepare(folder,{},instances=bad)
            self.assertFalse(folder.exists())
            bad=[{'file':'zero','split':'synthetic-development','value':{'coordinates':[[0,0]]*3}}]
            bad[0]['sha256']=digest(bad[0]['value'])
            with self.assertRaises(ValueError):e.prepare(folder,{'problem':'tsp'},instances=bad)
            self.assertFalse(folder.exists())

    def test_real_new_state_evaluation_import_refresh_cache_and_parallel_parity(self):
        with tempfile.TemporaryDirectory() as t:
            for problem in ('fjsp','tsp'):
                states=[]
                for width in (1,2):
                    folder=Path(t)/(problem+str(width))
                    e.prepare(folder,{'problem':problem,'population_size':2,'generations':1,
                              'generation_request_cap':4,'initialization':'import','evaluation_mode':'solve',
                              'api_concurrency':1,'evaluation_concurrency':width},imports=p0())
                    result=e.run(folder)
                    self.assertEqual(result['phase'],'completed')
                    p,s=e.check(folder);states.append(s)
                    self.assertEqual(s['initialization_requests'],0)
                    self.assertEqual(s['generation_requests'],4)
                    self.assertTrue(all(r['fitness']<0 for r in s['population']))
                    self.assertEqual(len(s['evaluations']),6)
                    for ev in s['evaluations'].values():
                        r=read(folder/ev['path'])
                        self.assertTrue(r['valid']);self.assertFalse(r['mock'])
                        self.assertFalse(r['lifecycle']['alive'])
                        self.assertEqual(r['lifecycle']['cleanup'],['join_exit_grace_2.0'])
                        self.assertEqual(len(r['instances']),2)
                        for row in r['instances']:
                            self.assertEqual(row['semantic_sha256'],row['recheck_semantic_sha256'])
                            self.assertEqual(row['captured_solves'],2)
                    report=export(folder)
                    self.assertEqual(report['generation_transport'],'MOCK_OFFLINE_NOT_LLM')
                    self.assertFalse(report['quality_claim'])
                self.assertEqual(states[0]['population'],states[1]['population'])
                self.assertEqual(states[0]['generations'],states[1]['generations'])

    def test_live_pause_drains_batch_and_never_resends(self):
        with tempfile.TemporaryDirectory() as t:
            folder=Path(t)/'pause'
            e.prepare(folder,{'population_size':2,'generations':3,'generation_request_cap':12,
                             'mock_delay_seconds':.1,'api_concurrency':2,'evaluation_concurrency':1})
            outcomes=[]
            th=threading.Thread(target=lambda:outcomes.append(e.run(folder)))
            with patch.object(socket.socket,'connect',side_effect=AssertionError('NO NETWORK')):
                th.start()
                deadline=time.monotonic()+3
                while not list((folder/'prompts').glob('*.txt')) and time.monotonic()<deadline:time.sleep(.005)
                e.request_pause(folder)
                th.join(timeout=5)
                self.assertFalse(th.is_alive())
                self.assertEqual(outcomes[0]['phase'],'paused')
                _,s=e.check(folder)
                previous=set(s['tasks'])
                self.assertEqual(s['initialization_requests'],2)
                self.assertFalse((folder/'.coordinator.lock').exists())
                self.assertEqual(e.run(folder)['phase'],'completed')
                _,final=e.check(folder)
                self.assertEqual(final['initialization_requests'],2)
                self.assertEqual(final['generation_requests'],12)
                self.assertTrue(previous <= set(final['tasks']))
                self.assertEqual(len(list((folder/'responses').glob('*.json'))),14)


if __name__=='__main__':unittest.main()
