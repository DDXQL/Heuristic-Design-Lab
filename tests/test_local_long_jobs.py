"""No FJSP evaluations: bounded synthetic process-disconnect and safety tests."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

from fjsp_usage.a4_static.engine import Campaign,read,write
from fjsp_usage.long_jobs import local as jobs

OUT=jobs.ROOT/'reports/a4-closeout-20261025-v1'
BASE=jobs.ROOT/'runs'/('long-job-acceptance-'+uuid.uuid4().hex[:10])
RECEIPTS=[]

def until(fn,seconds=90):
    # Internal bounded test synchronization; no repeated model/tool interactions.
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.1)
    raise AssertionError('synthetic test synchronization deadline; do not retry the job')

def terminal(d):
    def check():
        v=jobs.observe(d)
        return v if 'state = not running' in v['fields'] else None
    return until(check)

def cleanup(d):
    v=read(d/'Launch_receipt.json')
    result=subprocess.run(['/bin/launchctl','bootout',v['domain']+'/'+v['label']],capture_output=True,text=True)
    if result.returncode:raise RuntimeError('own terminal synthetic service cleanup failed')

class LongJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):BASE.mkdir()

    def test_a_launch_session_hangup_does_not_kill_launchd_job(self):
        d=jobs.create_toy(BASE/'controller-hangup',.8)
        code="from fjsp_usage.long_jobs.local import launch;from pathlib import Path;import signal;d=Path(%r);launch(d);(d/'Controller_ready').write_text('submitted');signal.pause()"%str(d)
        controller=subprocess.Popen([sys.executable,'-B','-c',code],stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,env={**os.environ,'PYTHONPATH':str(jobs.ROOT/'code')+':'+str(jobs.ROOT)})
        try:
            until(lambda:(d/'Controller_ready').exists())
            os.killpg(controller.pid,signal.SIGHUP);controller.communicate(timeout=5)
            self.assertEqual(controller.returncode,-signal.SIGHUP)
            v=terminal(d);identity=read(d/'Run_identity.json')
            self.assertEqual(identity['ppid'],1);self.assertEqual(v['summary']['phase'],'completed')
            self.assertEqual(v['summary']['completed_queries'],3);self.assertIn('last exit code = 0',v['fields'])
            self.assertFalse(v['lock_present']);self.assertFalse(v['Stop_present'])
            RECEIPTS.append({'test':'controller session SIGHUP/closed pipes','controller_returncode':controller.returncode,
                'run_identity':identity,'observation':v,'run_directory':str(d.relative_to(jobs.ROOT))})
        finally:
            if controller.poll() is None:
                controller.terminate();controller.wait(timeout=5)
        cleanup(d)

    def test_b_pause_only_after_committed_candidate(self):
        d=jobs.create_toy(BASE/'boundary-pause',1.)
        jobs.launch(d);until(lambda:(d/'Active_candidate.json').exists())
        jobs.request_pause(d,'synthetic controller requests pause while a query is in flight')
        v=terminal(d);state=Campaign(d).validate()[2]
        self.assertEqual(v['summary']['phase'],'paused_at_candidate_boundary')
        self.assertEqual(len(state['queries']),1);self.assertEqual(state['queries'][0]['status'],'completed')
        self.assertFalse(v['lock_present']);self.assertFalse(v['Stop_present'])
        with self.assertRaises(ValueError):jobs.work(d)
        RECEIPTS.append({'test':'cooperative boundary pause','observation':v,'ledger':state,'run_directory':str(d.relative_to(jobs.ROOT))})
        cleanup(d)

    def test_c_crash_preserves_unknown_reservation_and_lock_no_restart(self):
        d=jobs.create_toy(BASE/'synthetic-crash',0.,True)
        jobs.launch(d);v=terminal(d)
        self.assertIn('last exit code = 13',v['fields']);self.assertTrue(v['lock_present'])
        self.assertEqual(read(d/'checkpoint.json')['queries'][0]['status'],'reserved')
        with self.assertRaisesRegex(ValueError,'unresolved reservation'):jobs.check(d)
        with self.assertRaises(ValueError):jobs.launch(d)
        self.assertEqual(read(d/'checkpoint.json')['queries'][0]['status'],'reserved')
        RECEIPTS.append({'test':'synthetic os._exit13, unknown reservation not cleared','observation':v,'run_directory':str(d.relative_to(jobs.ROOT))})
        cleanup(d)

    def test_d_wall_clock_gap_and_expired_launch_gate(self):
        d=jobs.create_toy(BASE/'clock-gap',0.)
        t={'wall':0.,'monotonic':0.}
        def evaluate(i,f,reserve):
            reserve();t['wall']=800.;t['monotonic']=1.
            rows=[{'file':'SYNTHETIC-A','makespan':4,'lower_bound':2.,'score':-2.,'feasible':True},
                  {'file':'SYNTHETIC-B','makespan':6,'lower_bound':3.,'score':-2.,'feasible':True}]
            return {'valid':True,'total_instances':2,'instances':rows,'fitness':-2.},'new',{'synthetic':True}
        phase=jobs.run_boundaries(Campaign(d),evaluate,1000,lambda:jobs.check(d),clock_fn=lambda:dict(t))
        self.assertEqual(phase,'clock_gap_paused_at_boundary');self.assertEqual(len(Campaign(d).validate()[2]['queries']),1)
        e=jobs.create_toy(BASE/'expired',0.)
        phase=jobs.run_boundaries(Campaign(e),lambda *x:self.fail('must not launch'),500,lambda:jobs.check(e),clock_fn=lambda:{'wall':0,'monotonic':0})
        self.assertEqual(phase,'launch_deadline_stopped');self.assertEqual(Campaign(e).validate()[2]['queries'],[])
        RECEIPTS.append({'test':'synthetic suspend gap and UTC launch deadline','gap':read(d/'Clock_gap.json')})

    def test_e_source_scope_duplicate_and_foreign_lock_guards(self):
        d=jobs.create_toy(BASE/'foreign-lock',0.);write(d/'.job.lock',{'token':'foreign','pid':-1})
        with self.assertRaises(FileExistsError):jobs.work(d)
        self.assertEqual(read(d/'.job.lock')['token'],'foreign')
        j=read(d/'Job.json');j['formal_FJSP_cap']=1;write(d/'Job.json',j)
        with self.assertRaises(PermissionError):jobs.check(d)
        f=jobs.create_toy(BASE/'source-mismatch',0.);j=read(f/'Job.json');j['source_files'][str(Path(jobs.__file__).resolve())]='0'*64;write(f/'Job.json',j)
        with self.assertRaisesRegex(ValueError,'source changed'):jobs.check(f)
        unknown_clock=jobs.create_toy(BASE/'unknown-clock',0.);write(unknown_clock/'Run_clock.json',{'deadline':1})
        with self.assertRaisesRegex(ValueError,'unknown clock'):jobs.work(unknown_clock)
        self.assertEqual(read(unknown_clock/'Run_clock.json'),{'deadline':1})
        old=jobs.ROOT/'runs/a4-static-rs60x5-train21-seed501-v1'
        with self.assertRaises(ValueError):jobs.create_toy(old)
        self.assertEqual(read(old/'checkpoint.json')['phase'],'wall_budget_stopped')

if __name__=='__main__':
    path=OUT/'Long_job_acceptance.json'
    if path.exists():raise ValueError('preserve acceptance receipt; no new test jobs started')
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LongJobTests))
    receipt={'passed':result.wasSuccessful(),'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'files':{str(p.relative_to(jobs.ROOT)):jobs.sha(p) for p in (Path(jobs.__file__).resolve(),jobs.ROOT/'tools/local_long_job.py',Path(__file__).resolve())},
        'receipts':RECEIPTS,'formal_solves':0,'API_calls':0,'note':'Only synthetic seven-ticket/two-row campaign; no formal865 sampling. No auto restart or unknown-lock cleanup.'}
    write(path,receipt)
    if not receipt['passed']:sys.exit(1)
