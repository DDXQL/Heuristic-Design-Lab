"""T09: input snapshots, live read-only status and real-path gates without network."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from heuristic_design.core import evolution_v1 as e
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.core.terminal_ops import settings,snapshot

ROOT=Path(__file__).resolve().parents[1]


class Tests(unittest.TestCase):
    def test_fixed_train_input_snapshot_and_real_solves_both_problems(self):
        for problem in ('fjsp','tsp'):
            with tempfile.TemporaryDirectory() as t:
                root=Path(t)
                c=settings(ROOT/f'experiments/common/configs/{problem}-fixed-development.json')
                manifest=read(c['data_manifest']);manifest['split']='train'
                original=Path(c['data_manifest']).parent/manifest['instances'][0]['path']
                target=root/original.name;target.write_bytes(original.read_bytes())
                write(root/'train.json',manifest);c['data_manifest']=str(root/'train.json')
                c['population_size']=2
                rows=read(Path(c['p0_file']))[:2];c['p0_file']=None
                run=root/'run';e.prepare(run,c,imports=rows)
                # Frozen content must be independent of subsequent source edits.
                target.write_text('{}')
                self.assertEqual(e.run(run)['phase'],'completed')
                p,s=e.check(run)
                self.assertEqual(s['generation_requests'],0)
                self.assertEqual(s['initialization_requests'],0)
                self.assertTrue(all(t['fitness']<0 for t in s['tasks'].values()))
                before={x.name:sha(x) for x in run.iterdir() if x.is_file()}
                self.assertEqual(snapshot(run)['data_split'],['train'])
                self.assertEqual(before,{x.name:sha(x) for x in run.iterdir() if x.is_file()})

    def test_real_dispatch_requires_both_authorities_and_credentials_no_network(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            c=settings(ROOT/'experiments/common/configs/fjsp-real.template.json')
            c.update(data_manifest=str(ROOT/'experiments/common/fixtures/fjsp-development-manifest.json'),
                     population_size=2,generations=1,generation_request_cap=4,api_attempt_cap=4,
                     initialization='import',p0_file=None)
            rows=read(ROOT/'experiments/common/fixtures/p0-n5-handwritten.json')[:2]
            a=root/'blocked';e.prepare(a,c,imports=rows)
            with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')):
                with self.assertRaises(PermissionError):e.run(a,allow_api=True)
                c['real_requests_authorized']=True
                b=root/'authorized';e.prepare(b,c,imports=rows)
                with self.assertRaises(PermissionError):e.run(b)
                with patch.dict('os.environ',{},clear=True):
                    with self.assertRaises(ValueError):e.run(b,allow_api=True)
                self.assertEqual(read(b/'checkpoint.json')['phase'],'prepared')
                calls=[]
                def stub(transport,key,prompt,*,kind,on_sent):
                    calls.append(key);on_sent()
                    tag=int(digest(key)[:6],16)
                    return {'text':f'TEST STUB, NO NETWORK.\n```python\ndef use_heuristics(state):\n    tag = {tag}\n    return 0\n```',
                            'usage':None,'metadata':{'test_stub':True}}
                with patch.dict('os.environ',{'HEURISTIC_API_KEY':'dummy-only-for-unit-test'}),patch('heuristic_design.llm.routing_transport.JsonCandidateTransport.dispatch',stub):
                    self.assertEqual(e.run(b,allow_api=True)['phase'],'completed')
                self.assertEqual(len(calls),4)
                self.assertEqual(len(set(calls)),4)
                self.assertEqual(e.check(b)[1]['generation_requests'],4)
                text=(b/'Protocol.json').read_text()
                self.assertNotIn('dummy-only-for-unit-test',text)

    def test_live_status_accepts_inflight_while_recovery_refuses_unknown_send(self):
        with tempfile.TemporaryDirectory() as t:
            run=Path(t)/'run';e.prepare(run,{'generations':1,'generation_request_cap':10})
            s=read(run/'checkpoint.json');s['phase']='running'
            s['tasks']['pending']={'id':'pending','status':'request_reserved','valid':False}
            e.save(run,s)
            self.assertEqual(snapshot(run)['inflight'],['pending'])
            with self.assertRaisesRegex(ValueError,'in-flight'):e.run(run)


if __name__=='__main__':unittest.main()
