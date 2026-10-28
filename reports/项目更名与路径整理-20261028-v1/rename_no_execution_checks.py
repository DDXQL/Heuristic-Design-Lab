from pathlib import Path
import sys,os,subprocess,runpy,json,time
ROOT=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab');REC=ROOT.parent/'迁移记录-项目更名-20261028-v1'
if '--child' in sys.argv:
 i=sys.argv.index('--child');entry=sys.argv[i+1];args=sys.argv[i+2:];sys.dont_write_bytecode=True
 def audit(event,args):
  if event in ('socket.connect','socket.connect_ex','http.client.connect','urllib.Request'):raise AssertionError('NETWORK FORBIDDEN')
  if event in ('open','os.listdir','os.scandir') and args and isinstance(args[0],(str,bytes,os.PathLike)):
   p=os.path.abspath(os.fsdecode(args[0]))
   if p.startswith('/Users/DDXQL/Developer/FJSP-Heuristic-Research-tsp-integration') or p.startswith('/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research'):raise AssertionError('OLD PROJECT PATH FORBIDDEN')
 sys.addaudithook(audit);os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'code')]
 from fjsp_usage.usage_v2 import execution as f
 from heuristic_design.problems.tsp import solver as t
 def deny(*args,**kwargs):raise AssertionError('SOLVER FORBIDDEN')
 f.construct_usage_schedule=deny;t.construct=deny
 from tools import cross_feedback_ab_execute as certified
 certified.construct_usage_schedule=deny
 sys.argv=[str(ROOT/entry),*args];runpy.run_path(str(ROOT/entry),run_name='__main__');raise SystemExit
cases=[('router help',['experiments/manage.py','--help'],0),('FJSP help',['experiments/manage.py','--problem','fjsp','--help'],0),('TSP help',['experiments/manage.py','--problem','tsp','--help'],0),('FJSP doctor',['experiments/manage.py','--problem','fjsp','doctor'],0),('TSP doctor',['experiments/manage.py','--problem','tsp','doctor'],0),('FJSP config',['experiments/fjsp/manage.py','check','--config','experiments/fjsp/configs/fixed-toy.json'],0),('FJSP plan',['experiments/fjsp/manage.py','plan','--config','experiments/fjsp/configs/fixed-toy.json'],0),('TSP config',['experiments/tsp/manage.py','check','--config','experiments/tsp/configs/pilot-real.json'],0),('TSP plan',['experiments/tsp/manage.py','plan','--config','experiments/tsp/configs/pilot-mock.json'],0),('FJSP legacy state',['experiments/manage.py','--problem','fjsp','--state-schema','fjsp-seven-v1-legacy','doctor'],0),('TSP legacy state',['experiments/manage.py','--problem','tsp','--state-schema','tsp-five-v1-legacy','doctor'],0),('draft disabled',['experiments/manage.py','--problem','fjsp','--state-schema','constructive-common-v0-draft','doctor'],2),('wrong problem state',['experiments/manage.py','--problem','tsp','--state-schema','fjsp-seven-v1-legacy','doctor'],2),('unknown state',['experiments/manage.py','--problem','fjsp','--state-schema','unknown-v999','doctor'],2),('historical TSP explicit vault',['experiments/tsp/inspect_archive.py','--receipt','reports/TSP最新成果迁移-20261028-v1/Asset_copy_result.json','--vault','archives/tsp-c3b74b7-20261028-v1','--verify-all'],0)]
results=[]
for label,args,expected in cases:
 start=time.monotonic();q=subprocess.run([str(ROOT/'.venv/bin/python'),'-B',__file__,'--child',*args],cwd=ROOT,capture_output=True,text=True,timeout=60);ok=q.returncode==expected
 if expected==2:ok=ok and 'state schema' in q.stderr
 results.append({'check':label,'args':args,'expected_exit':expected,'actual_exit':q.returncode,'passed':ok,'seconds':time.monotonic()-start,'stdout':q.stdout,'stderr':q.stderr})
(REC/'CLI_checks.json').write_text(json.dumps({'passed':all(r['passed'] for r in results),'checks':results,'network_forbidden':True,'solvers_forbidden':True,'old_project_file_access_forbidden':True,'real_LLM_calls':0,'formal_searches':0},ensure_ascii=False,indent=2)+'\n');print([(r['check'],r['passed']) for r in results]);assert all(r['passed'] for r in results)
