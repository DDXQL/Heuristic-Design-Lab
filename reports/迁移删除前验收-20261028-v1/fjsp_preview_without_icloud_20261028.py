from pathlib import Path
import sys,os,runpy,json,subprocess,time
B=Path('/Users/DDXQL/Developer');ROOT=B/'FJSP-Heuristic-Research-tsp-integration';R=B/'迁移记录-删除前验收-20261028-v1'
if len(sys.argv)>1 and sys.argv[1]=='--child':
 sys.dont_write_bytecode=True
 old='/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research'
 def guard(event,args):
  if event in ('socket.connect','socket.connect_ex','http.client.connect','urllib.Request'):
   raise RuntimeError('NETWORK_FORBIDDEN_IN_AUDIT')
  if event in ('open','os.listdir','os.scandir') and args:
   p=args[0]
   if isinstance(p,(str,bytes,os.PathLike)):
    p=os.path.abspath(os.fsdecode(p))
    if p.startswith(old):raise RuntimeError('OLD_PROJECT_ACCESS_FORBIDDEN '+p)
 sys.addaudithook(guard)
 entry=ROOT/sys.argv[2];sys.argv=[str(entry),*sys.argv[3:]];os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'code')];runpy.run_path(str(entry),run_name='__main__');raise SystemExit
commands=[['experiments/manage.py','--problem','fjsp','doctor'],['experiments/manage.py','--problem','tsp','doctor'],['experiments/fjsp/manage.py','plan','--config','experiments/fjsp/configs/fixed-toy.json'],['experiments/tsp/manage.py','plan','--config','experiments/tsp/configs/pilot-mock.json'],['experiments/tsp/inspect_archive.py','--receipt','reports/TSP最新成果迁移-20261028-v1/Asset_copy_result.json','--verify-all']]
rows=[]
for args in commands:
 start=time.monotonic();q=subprocess.run([str(ROOT/'.venv/bin/python'),'-B',__file__,'--child',*args],cwd=ROOT,capture_output=True,text=True,timeout=60)
 rows.append({'args':args,'exit':q.returncode,'seconds':time.monotonic()-start,'stdout':q.stdout,'stderr':q.stderr,'guard':'deny network and old project file opens'})
(R/'禁止旧路径与网络的入口验证.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n');print([(r['args'][:3],r['exit']) for r in rows]);assert all(r['exit']==0 for r in rows)
