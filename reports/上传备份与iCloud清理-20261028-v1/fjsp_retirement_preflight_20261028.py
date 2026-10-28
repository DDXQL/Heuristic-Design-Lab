from pathlib import Path
import os,json,subprocess,stat
O=Path('/Users/DDXQL/Documents/大学/硕士/代码');B=Path('/Users/DDXQL/Developer');ROOT=B/'FJSP-Heuristic-Research-tsp-integration';BACK=Path('/Users/DDXQL/Backups/Heuristic-Design-Lab/legacy-20261028-v1');AUD=B/'迁移记录-删除前验收-20261028-v1';expected=json.loads((AUD/'源文件元数据.json').read_text());pinned={r['path']:r for r in expected};names=['FJSP-Heuristic-Research','FJSP-Heuristic-Research-h-usage-space','FJSP-Heuristic-Research-tsp-pilot','FJSP-Heuristic-Research-u-single-experiments'];actual={};cloud=[];gitlocks=[];credentials=[]
for name in names:
 root=O/name
 if root.is_symlink() or not root.is_dir():raise RuntimeError('unexpected source root')
 for current,dirs,files in os.walk(root,followlinks=False):
  for file in files:
   p=Path(current)/file
   if p.is_symlink():continue
   s=p.stat()
   if s.st_flags&0x40000000:cloud.append(str(p.relative_to(O)))
   if '.git' in p.parts and p.name.endswith('.lock'):gitlocks.append(str(p.relative_to(O)))
  # Full tree residency above, scientific metadata below follows original census exclusions.
 for current,dirs,files in os.walk(root,followlinks=False):
  dirs[:]=[d for d in dirs if d not in ('.git','.venv','venv','__pycache__','.pytest_cache','.ruff_cache') and not (Path(current)/d).is_symlink()]
  for file in files:
   p=Path(current)/file
   if p.is_symlink():continue
   if file.startswith('.env') or file=='config.local.sh' or p.suffix.lower() in ('.key','.pem','.p12','.pfx'):credentials.append(str(p.relative_to(O)));continue
   if file=='.DS_Store' or p.suffix in ('.pyc','.pyo') or file=='.git':continue
   s=p.stat();actual[name+'/'+str(p.relative_to(root))]={'bytes':s.st_size,'mtime_ns':s.st_mtime_ns}
changed=[k for k in actual.keys()&pinned.keys() if any(actual[k][f]!=pinned[k][f] for f in ('bytes','mtime_ns'))];added=sorted(set(actual)-set(pinned));missing=sorted(set(pinned)-set(actual))
old_states={}
for name in names:
 p=O/name;old_states[name]={}
 for k,args in [('head',['rev-parse','HEAD']),('branch',['branch','--show-current']),('status',['-c','core.quotePath=false','status','--porcelain=v1','-uall'])]:
  q=subprocess.run(['git','--no-optional-locks',*args],cwd=p,capture_output=True,text=True,timeout=30);assert q.returncode==0;old_states[name][k]=q.stdout
 original=json.loads((AUD/'原始Git现场.json').read_text())[str(p)]
 for key in ('head','branch','status'):
  if old_states[name][key]!=original[key]:raise RuntimeError('source Git state changed since audit: '+name+' '+key)
q=subprocess.run(['lsof','-nP','-Fpcn'],capture_output=True,text=True,timeout=30);pid=None;comm=None;opened=[]
for line in q.stdout.splitlines():
 if line.startswith('p'):pid=line[1:]
 elif line.startswith('c'):comm=line[1:]
 elif line.startswith('n') and any(line[1:].startswith(str(O/name)) for name in names):opened.append({'pid':pid,'process':comm,'path':line[1:]})
for file in ['.env.leafapi.local','.env.deepseek.local']:
 assert (O/names[0]/file).read_bytes()==(Path('/Users/DDXQL/.config/heuristic-design-lab')/file).read_bytes()
result={'scientific_files':len(actual),'added':added,'missing':missing,'changed':changed,'cloud_files':cloud,'git_locks':gitlocks,'open_old_paths':opened,'credential_paths':credentials,'private_credentials_match':True,'source_device':(O/names[0]).stat().st_dev,'backup_device':BACK.stat().st_dev,'old_states':old_states,'passed':not(added or missing or changed or cloud or gitlocks or opened)}
(BACK/'Retirement_preflight.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print({k:len(v) if isinstance(v,list) else v for k,v in result.items() if k not in ('old_states','credential_paths')})
