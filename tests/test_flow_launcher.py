"""Shell launch gates with local stubs only: no SSH, API, solve or sbatch."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class FlowLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.state=self.root/'state'
        deploy=self.root/'deploy/flow-check';deploy.mkdir(parents=True)
        (self.root/'reports/flow-check-20261112').mkdir(parents=True)
        (self.root/'bin').mkdir();self.zip=self.root/'fixture.zip'
        self.zip.write_bytes(b'local stub, never an actual upload')
        stub='''import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
with open(os.environ['TRACE'],'a') as f:f.write(name+' '+(' '.join(sys.argv[1:]) if name=='fixture-python' else '')+'\\n')
if name=='caffeinate':
 assert os.environ.get('LEAFAPI_API_KEY')=='synthetic-key'
 if os.environ.get('EXPECT_RESUME'):assert 'resume' in sys.argv
 if os.environ.get('FAIL_MAC'):sys.exit(2)
 p=pathlib.Path(os.environ['STAGE']);p.mkdir(exist_ok='resume' in sys.argv);(p/'export.json').write_text('{}');sys.exit(0)
assert 'LEAFAPI_API_KEY' not in os.environ
if name=='ssh' and '-O' not in sys.argv and os.environ.get('FAIL_REMOTE'):sys.exit(3)
if name=='ssh' and 'sbatch' in sys.argv[-1]:
 assert '--no-requeue' in sys.argv[-1]
 with open(os.environ['TRACE'],'a') as f:f.write('SUBMIT-COMPUTE-STUB\\n')
 print('701234');sys.exit(0)
if name=='ssh' and 'scontrol show job' in sys.argv[-1] and os.environ.get('ARCHIVED_JOB'):sys.exit(1)
if name=='ssh' and 'sacct -X' in sys.argv[-1]:print('701234 COMPLETED 0:0')
if name=='fixture-python' and 'check-mac-export' in sys.argv:
 assert pathlib.Path(os.environ['STAGE'],'export.json').exists()
'''
        for name in ['ssh','scp','caffeinate','fixture-python']:
            p=self.root/'bin'/name;p.write_text('#!'+sys.executable+'\n'+stub);p.chmod(0o700)
        source=(ROOT/'deploy/flow-check/start.sh').read_text()
        source=source.replace('HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)','HDL_ROOT='+shlex.quote(str(self.root)))
        source=source.replace('HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python','HDL_PY='+shlex.quote(str(self.root/'bin/fixture-python')))
        source=source.replace('HDL_STATE="$HOME/hdl-flow-validation/fjsp-state-a-flow-20261112/mac"','HDL_STATE='+shlex.quote(str(self.state)))
        source=source.replace('HDL_ZIP=/Users/DDXQL/Developer/transfer-outbox/fjsp-state-a-flow-20261112.zip','HDL_ZIP='+shlex.quote(str(self.zip)))
        self.launch=deploy/'start.sh';self.launch.write_text(source)
        (deploy/'submit_cluster.sh').write_text('printf "SUBMIT-WRAPPER\\n" >> "$TRACE"\n')
        self.env={'PATH':str(self.root/'bin')+os.pathsep+os.defpath,'TRACE':str(self.root/'trace'),'STAGE':str(self.state),'LEAFAPI_API_KEY':'synthetic-key'}
        self.args=['/bin/bash',str(self.launch),'--allow-api','--approve-api','2','--allow-evaluation','--approve-solves','12']

    def run_fixture(self,args=None):
        return subprocess.run(args or self.args,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=8)

    def trace(self):
        p=self.root/'trace';return p.read_text() if p.exists() else ''

    def test_remote_preflight_failure_stops_before_mac_work(self):
        self.env['FAIL_REMOTE']='1';r=self.run_fixture()
        self.assertEqual(r.returncode,3);self.assertNotIn('caffeinate',self.trace());self.assertNotIn('SUBMIT',self.trace())
        self.assertFalse(self.state.exists());self.assertNotIn('synthetic-key',r.stdout)

    def test_mac_failure_never_submits_cluster(self):
        self.env['FAIL_MAC']='1';r=self.run_fixture()
        self.assertEqual(r.returncode,2);self.assertIn('caffeinate',self.trace());self.assertNotIn('SUBMIT',self.trace())

    def test_success_delegates_once_after_mac_with_no_key_to_ssh(self):
        r=self.run_fixture();self.assertEqual(r.returncode,0,r.stdout)
        t=self.trace();self.assertEqual(t.count('SUBMIT-WRAPPER'),1)
        self.assertLess(t.index('ssh'),t.index('caffeinate'));self.assertNotIn('synthetic-key',r.stdout)

    def test_existing_stage_cannot_be_rerun(self):
        self.state.mkdir();r=self.run_fixture()
        self.assertEqual(r.returncode,2);self.assertEqual(self.trace(),'')

    def test_resume_wrapper_uses_existing_stage_without_new_run(self):
        self.state.mkdir();(self.state/'checkpoint.json').write_text('{"phase":"paused"}')
        self.env['EXPECT_RESUME']='1';args=self.args[:2]+['--resume']+self.args[2:]
        result=self.run_fixture(args);self.assertEqual(result.returncode,0,result.stdout)
        self.assertEqual(self.trace().count('caffeinate'),1)
        self.assertEqual(self.trace().count('SUBMIT-WRAPPER'),1)

    def test_wrong_budget_and_missing_key_stop_before_ssh(self):
        args=self.args.copy();args[4]='4';r=self.run_fixture(args)
        self.assertEqual(r.returncode,2);self.assertEqual(self.trace(),'')
        self.env.pop('LEAFAPI_API_KEY');r=self.run_fixture()
        self.assertEqual(r.returncode,2);self.assertEqual(self.trace(),'')

    def test_immediately_completed_submission_retains_job_id_without_resubmit(self):
        self.state.mkdir();(self.state/'export.json').write_text('{}');self.env['ARCHIVED_JOB']='1'
        source=(ROOT/'deploy/flow-check/submit_cluster.sh').read_text()
        source=source.replace('HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)','HDL_ROOT='+shlex.quote(str(self.root)))
        source=source.replace('HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python','HDL_PY='+shlex.quote(str(self.root/'bin/fixture-python')))
        source=source.replace('HDL_EXPORT="$HOME/hdl-flow-validation/fjsp-state-a-flow-20261112/mac/export.json"','HDL_EXPORT='+shlex.quote(str(self.state/'export.json')))
        script=self.root/'deploy/flow-check/submit-real-source.sh';script.write_text(source)
        result=self.run_fixture(['/bin/bash',str(script),'run','--allow-evaluation','--approve-solves','12'])
        self.assertEqual(result.returncode,0,result.stdout)
        self.assertEqual(self.trace().count('SUBMIT-COMPUTE-STUB'),1)
        report=self.root/'reports/flow-check-20261112'
        self.assertEqual((report/'submitted-jobs.txt').read_text().strip(),'701234')
        self.assertEqual(len(list(report.glob('transfer-*/accounting-after-submit.txt'))),1)


if __name__=='__main__':unittest.main()
