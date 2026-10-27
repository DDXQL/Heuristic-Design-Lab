"""P1 migration and generation-two acceptance. Synthetic fitness, no solves/API."""
from copy import deepcopy
from dataclasses import replace
import random
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.evolution import select_parents, _tuple_tree
from fjsp_usage.research.protocol import digest
from tools import b1_p1_resume as resume
from test_b1_nonstream_local import Inner


class P1ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        old = Path(os.environ.get('B1_RESUME_TEST_ORIGIN',resume.ROOT/'runs'/resume.ORIGIN_NAME))
        self.c = resume.read(old/'r501/B/checkpoint.json')
        self.j = resume.read(old/'r501/B/batch_requests.json')
        self.p = resume.read(old/'Protocol.json')
        base = resume.legacy.ns.Config.from_dict(self.p['config'])
        self.config = replace(base,mode='synthetic',provider=replace(base.provider,
            endpoint='http://localhost/mock',api_key_env=None))
        self.inner = Inner(self.config)
        self.profile = resume.legacy.ns.CompleteNonstreamTransport(self.inner,self.path/'received')
        self.transport = resume.legacy.ns.TimedRecorder(self.profile,self.path/'wire')
        self.target = self.path/'r501/B'

    def bundle(self):
        return resume.migrate(self.c,self.j,self.config,self.transport.identity,'MOCK-CONTEXT',
            self.target,self.p['H_order'],self.p['request_phase'])

    def test_migration_keeps_all_science_rng_and_old_budget(self):
        b = self.bundle(); c = deepcopy(b['checkpoint.json']); c['signature']=self.c['signature']
        self.assertEqual(c,self.c)
        j = deepcopy(b['batch_requests.json']); j['identity']=self.j['identity'];j.pop('recovery_source_P1')
        self.assertEqual(j,self.j)
        self.assertEqual(len(b['batch_requests.json']['requests']),19)

    def test_unknown_boundary_does_not_migrate(self):
        for field,value in [('inflight',{'id':'UNKNOWN'}),('generation',0),('cursor',1),('children',[{}])]:
            c=deepcopy(self.c);c[field]=value
            with self.assertRaises(ValueError):
                resume.migrate(c,self.j,self.config,'T','C',self.target,self.p['H_order'],self.p['request_phase'])

    def test_ten_synthetic_slots_preserve_first_parent_rng_and_survival(self):
        # Full byte-preservation is tested above. Keep this synthetic execution
        # test small instead of serializing historical action traces every slot.
        for cache in self.c['evaluations'].values():
            r=cache['result']
            if r.get('valid'):
                cache['result']={'valid':True,'total_instances':21,'fitness':r['fitness'],
                    'instances':[{'file':n,'score':r['fitness']} for n in self.p['train_names']]}
            else:
                cache['result']={'valid':False,'total_instances':21,'fitness':None,'instances':[]}
        bundle=self.bundle()
        original_cursor=self.c['cursor'];original_slots=len(self.c['attempts'])
        for k,v in bundle.items():atomic_json(self.target/k,v)
        atomic_json(self.path/'Protocol.json',{'MOCK':True})
        evaluated=[]
        def evaluate(c):
            evaluated.append(c.key)
            return {'valid':True,'total_instances':21,'fitness':-2.0,
                'instances':[{'file':n,'score':-2.0,'lower_bound':10,'makespan':20}
                    for n in self.p['train_names']]}
        # Hard traps: this test must never contact a provider or scheduler.
        with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')), \
             patch('fjsp_usage.research_real.runtime.evaluate',side_effect=AssertionError('NO SOLVE')), \
             patch.object(resume,'check_live',return_value=None):
            e=resume.ResumeSearch(self.target,experiment=self.config,training_names=self.p['train_names'],
                arm='B',config=self.config.u_search(501),members=[resume.checked_candidate(x['candidate'],'h')
                    for x in resume.read(Path(self.config.fixed_h_source['directory'])/'H_frozen.json')['members']],
                evaluator=evaluate,transport=self.transport,context='MOCK-CONTEXT')
            e.resume_protocol={}
            rng=random.Random();rng.setstate(_tuple_tree(self.c['rng']))
            parents=select_parents(self.c['population'],2,rng)
            e.run()
            self.assertEqual(e.state['phase'],'completed')
            self.assertEqual(e.state['generation'],2)
            self.assertEqual(len(e.state['attempts']),29)
            self.assertEqual(len(self.inner.sent),10-original_cursor)
            self.assertEqual(len(e.ledger.data['api_attempts']),29)
            new=e.state['attempts'][original_slots:]
            self.assertEqual(new[0]['parents'],[r['id'] for r in parents])
            self.assertEqual([a['operator'] for a in new],(['CROSS']*5+['MUTATE']*5)[original_cursor:])
            self.assertTrue(all(a['id']==f'B/g0001/{i+original_cursor:06d}' for i,a in enumerate(new)))
            self.assertEqual(e.state['population_snapshots']['P1'],[
                {k:r[k] for k in ('id','fitness','candidate')} for r in self.c['population']])

    def test_remaining_six_slots_keep_partial_children_and_budget(self):
        origin=os.environ.get('B1_RESUME_TEST_PARTIAL')
        if not origin:self.skipTest('no partial-stage fixture')
        r=Path(origin)
        self.c=resume.read(r/'r501/B/checkpoint.json');self.j=resume.read(r/'r501/B/batch_requests.json')
        self.assertEqual(self.c['cursor'],4)
        old_children=deepcopy(self.c['children'])
        b=self.bundle()
        self.assertEqual(b['checkpoint.json']['children'],old_children)
        self.assertEqual(len(b['batch_requests.json']['requests']),23)
        self.test_ten_synthetic_slots_preserve_first_parent_rng_and_survival()

    def test_exit_grace_changes_cleanup_only_not_result_wait(self):
        from unittest.mock import Mock
        from tools.b1_exit_grace import collect_with_exit_grace
        process=Mock(pid=42,exitcode=0);process.is_alive.return_value=False
        receive,send=Mock(),Mock();receive.poll.return_value=True;receive.recv.return_value={'file':'MOCK'}
        context=Mock();context.Pipe.return_value=(receive,send);context.Process.return_value=process
        rows,failure,life=collect_with_exit_grace(context,None,None,(),(),('MOCK',),15,(0,1),lambda r:None)
        receive.poll.assert_called_once_with(15)
        process.join.assert_called_once_with(timeout=1.0)
        process.terminate.assert_not_called();self.assertIsNone(failure)
        self.assertEqual(life['exitcode'],0)


if __name__=='__main__':unittest.main()
