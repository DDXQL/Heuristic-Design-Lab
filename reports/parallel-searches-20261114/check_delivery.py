from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import parallel,configuration,cluster
from heuristic_design.core.storage import read,write,sha
out=Path(__file__).resolve().parent
pending={}
for name in ('two-eoh-502-503','two-u-502-503'):
 p=ROOT/'plans'/name/'Shared.json';value=parallel.inspect(p);pending[name]=value
 try:parallel.submit(p,'run',send=False,prefix=1,solve_cap=84)
 except PermissionError as e:assert 'PROTOCOL_PENDING' in str(e)
 else:raise AssertionError('pending study admitted')
assert all(r['pending']==['account_exclusion'] for r in pending['two-eoh-502-503']['members'])
assert all('freeze_status' in r['pending'] for r in pending['two-u-502-503']['members'])
write(out/'CHECK_ONLY_PENDING.json',{'expected_protocol_rejections':pending,'environment_error':False,'API_requests':0,'actual_solves':0})
# Only build real-mode command vectors under a synthetic gaps stub. No saved
# config is changed or approved, and no real command is executed.
p=ROOT/'plans/two-eoh-502-503/Shared.json'
with patch.object(configuration,'gaps',return_value=[]):
 finite=parallel.submit(p,'run',prefix=1,solve_cap=84)['commands']
 full=parallel.submit(p,'resume')['commands']
with tempfile.TemporaryDirectory(prefix='node-command-fixture-') as tmp:
 t=Path(tmp);mp=t/'Shared.json';m=read(p);write(mp,m)
 write(t/'Acceptance.json',{'manifest_sha256':sha(mp),'adapter_sha256':sha(parallel.shared.__file__),'validated_nodes':['SYNTHETIC-NODE-0','SYNTHETIC-NODE-1'],'real_dispatch_path_verified':False})
 with patch.object(configuration,'gaps',return_value=[]),patch.object(parallel.shared,'load',return_value=m):
  pinned=parallel.submit(mp,'resume')['commands']
 for i,cmd in enumerate(pinned):assert '--nodelist=SYNTHETIC-NODE-'+str(i) in cmd
for cmd in finite+full:
 i=cmd.index(str(ROOT/'experiments/triad/parallel.sbatch'));assert len(cmd[i+1:])==8
assert all(cmd[-3:-1]==['1','42'] for cmd in finite)
assert all(cmd[-3:-1]==['',''] for cmd in full)
mock=parallel.submit(ROOT/'plans/two-search-mock-acceptance/Shared.json','run',prefix=1,solve_cap=0)['commands']
with tempfile.TemporaryDirectory(prefix='parallel-shell-') as tmp:
 t=Path(tmp);stub=t/'srun';capture=t/'argv.json'
 stub.write_text('#!/bin/bash\nexec "$HDL_CAPTURE_PY" -s -B -c \'import sys,json,os;json.dump(sys.argv[1:],open(os.environ["HDL_CAPTURE"],"w"))\' "$@"\n');stub.chmod(0o700)
 env={**os.environ,'PATH':str(t)+':'+os.environ['PATH'],'SLURM_CPUS_PER_TASK':'2','HDL_CAPTURE_PY':sys.executable,'HDL_CAPTURE':str(capture)}
 checks=[]
 for label,cmd in [('finite',finite[0]),('full',full[0]),('mock',mock[0])]:
  i=cmd.index(str(ROOT/'experiments/triad/parallel.sbatch'));args=cmd[i+1:];args[3]=sys.executable
  subprocess.run(['/bin/bash',cmd[i],*args],cwd=ROOT,env=env,check=True,capture_output=True)
  actual=read(capture);assert '--shared-manifest' in actual
  if label=='mock':assert '--engineering' in actual and '--allow-api' not in actual and '--allow-solves' not in actual and actual[-1]=='0'
  else:assert '--allow-api' in actual and '--allow-solves' in actual
  checks.append({'variant':label,'passed':True,'API_requests':0,'solves':0,'actual_srun':False})
write(out/'SHELL_AND_COMMANDS.json',{'checks':checks,'real_mode_vectors_only':True,'research_approval_created':False,'Slurm_submitted':False})
# Public source and original r5p1 archive stay untouched.
public=subprocess.check_output(['git','ls-tree','-r','--name-only','923781f','code'],cwd=ROOT,text=True).splitlines()
for n in public:assert (ROOT/n).read_bytes()==subprocess.check_output(['git','show','923781f:'+n],cwd=ROOT)
assert (ROOT/'experiments/common/run_frozen.py').read_bytes()==subprocess.check_output(['git','show','923781f:experiments/common/run_frozen.py'],cwd=ROOT)
r5=Path('/Users/DDXQL/Developer/transfer-outbox/triad-six-groups-prepared-20261114-r5p1.zip')
assert sha(r5)=='4851e37e52067e298eda18f596be31b097944ea9dc791e625515f5ed11fd6b1e'
# Snapshot the shared retrieval extension using an invented terminal run. No SSH.
with tempfile.TemporaryDirectory(prefix='parallel-export-') as tmp:
 t=Path(tmp);d=t/'runs/SYNTHETIC';d.mkdir(parents=True);(t/'logs').mkdir();s=t/'plans/SYNTHETIC/Shared.json';write(s,{'synthetic':True});write(s.parent/'gate/ledger.json',{'synthetic':True});write(d/'Shared_execution.json',{'manifest':str(s)});write(d/'checkpoint.json',{'phase':'paused'})
 import io,contextlib,zipfile
 with patch.object(sys,'argv',['export',str(t),str(d),'123']),contextlib.redirect_stdout(io.StringIO()) as stdout:exec(cluster.EXPORT,{})
 packet=json.loads(stdout.getvalue())
 with zipfile.ZipFile(packet['path']) as z:
  man=json.loads(z.read('retrieval-manifest.json'))
  assert 'plans/SYNTHETIC/gate/ledger.json' in man['files']
  assert all(hashlib.sha256(z.read(n)).hexdigest()==h for n,h in man['files'].items())
write(out/'SOURCE_AND_RETRIEVAL.json',{'public_code_files_equal_923781f':len(public),'frozen_U_entry_unchanged':True,'r5p1_archive_unchanged':True,'synthetic_shared_export_hashes_passed':True,'remote_queries':0,'API_requests':0,'actual_solves':0})
print(json.dumps({'passed':True,'pending_refusals':True,'shell_variants':3,'validated_node_pinning':True,'public_code_equal':len(public),'shared_retrieval':True}))
