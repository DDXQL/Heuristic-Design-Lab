from pathlib import Path
import os,json,subprocess,hashlib,time
OLD=Path('/Users/DDXQL/Documents/大学/硕士/代码');DEV=Path('/Users/DDXQL/Developer');ROOT=DEV/'FJSP-Heuristic-Research-tsp-integration';BACK=Path('/Users/DDXQL/Backups/Heuristic-Design-Lab/legacy-20261028-v1');RETIRED=BACK/'retired-worktrees';MAIN='FJSP-Heuristic-Research';NAMES=[MAIN,MAIN+'-h-usage-space',MAIN+'-tsp-pilot',MAIN+'-u-single-experiments'];JOURNAL=BACK/'Retirement_journal.json'
if JOURNAL.exists():raise SystemExit('STOP: retirement journal exists; inspect and do not replay')
pre=json.loads((BACK/'Retirement_preflight.json').read_text());backup=json.loads((BACK/'Backup_receipt.json').read_text());remote=json.loads((BACK/'Remote_before_retirement.json').read_text())
assert pre['passed'] and backup['git_bundle_verified'] and backup['roundtrip_verified_members']==backup['all_archive_members'] and remote['verified']
assert pre['source_device']==pre['backup_device']
assert Path(backup['archive']).is_file() and Path(backup['git_bundle']).is_file()
if RETIRED.exists():raise SystemExit('STOP: retired destination exists')
RETIRED.mkdir(mode=0o700)
source_common=(OLD/MAIN/'.git').resolve();dev_common=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=ROOT,text=True).strip()).resolve();assert source_common!=dev_common
journal={'state':'started','mode':'recoverable move out of iCloud; no permanent purge','started_epoch':time.time(),'source_root':str(OLD),'retired_root':str(RETIRED),'moves':[],'developer_states':{},'scientific_files_verified':0,'credentials_values_logged':False}
def persist():
 tmp=JOURNAL.with_suffix('.json.tmp');tmp.write_text(json.dumps(journal,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,JOURNAL)
def call(args,cwd):
 q=subprocess.run(args,cwd=cwd,capture_output=True,text=True)
 if q.returncode:raise RuntimeError('command failed: '+str(args[:3])+' '+q.stderr[:400])
 return q.stdout
for text in call(['git','worktree','list','--porcelain'],ROOT).splitlines():
 if text.startswith('worktree '):
  p=Path(text[9:]);journal['developer_states'][str(p)]={'head':call(['git','rev-parse','HEAD'],p),'status':call(['git','-c','core.quotePath=false','status','--porcelain=v1','-uall'],p)}
# Recheck no unseen changes/unknown writer immediately before directory moves.
for name in NAMES:
 source=OLD/name;assert source.is_dir() and not source.is_symlink()
 if (source/'.git/index.lock').exists():raise RuntimeError('old Git index lock present')
 for key,args in [('head',['git','rev-parse','HEAD']),('branch',['git','branch','--show-current']),('status',['git','-c','core.quotePath=false','status','--porcelain=v1','-uall'])]:
  if call(args,source)!=pre['old_states'][name][key]:raise RuntimeError('source changed after preflight: '+name+' '+key)
persist()
try:
 # Git-supported moves retain dirty files and update registration; no force/reset/clean.
 for name in NAMES[1:]:
  source=OLD/name;target=RETIRED/name
  call(['git','worktree','move',str(source),str(target)],OLD/MAIN)
  journal['moves'].append({'name':name,'source':str(source),'destination':str(target),'method':'git worktree move'});persist();print('Retired linked worktree:',name,flush=True)
 # Git cannot move the primary worktree itself; same-device rename then repair links.
 source=OLD/MAIN;target=RETIRED/MAIN;os.rename(source,target)
 journal['moves'].append({'name':MAIN,'source':str(source),'destination':str(target),'method':'same-device primary directory rename'});journal['state']='all_directories_moved_pending_git_repair';persist()
 journal['git_repair_output']=call(['git','worktree','repair',*[str(RETIRED/name) for name in NAMES[1:]]],target)
 for name in NAMES:
  p=RETIRED/name
  for key,args in [('head',['git','rev-parse','HEAD']),('branch',['git','branch','--show-current']),('status',['git','-c','core.quotePath=false','status','--porcelain=v1','-uall'])]:
   if call(args,p)!=pre['old_states'][name][key]:raise RuntimeError('retired state differs: '+name+' '+key)
  if (OLD/name).exists():raise RuntimeError('source directory unexpectedly still present')
 index=json.loads((DEV/'迁移记录-删除前验收-20261028-v1/逐文件保存索引.json').read_text())
 for rel,row in index.items():
  p=RETIRED/rel;h=hashlib.sha256();size=0
  with p.open('rb') as f:
   for block in iter(lambda:f.read(2**20),b''):h.update(block);size+=len(block)
  if size!=row['bytes'] or h.hexdigest()!=row['sha256']:raise RuntimeError('retired file mismatch: '+rel)
  journal['scientific_files_verified']+=1
 for name in ['.env.leafapi.local','.env.deepseek.local']:
  p=RETIRED/MAIN/name;q=Path('/Users/DDXQL/.config/heuristic-design-lab')/name
  assert p.read_bytes()==q.read_bytes();p.chmod(0o600)
 for text,state in journal['developer_states'].items():
  p=Path(text)
  if call(['git','rev-parse','HEAD'],p)!=state['head'] or call(['git','-c','core.quotePath=false','status','--porcelain=v1','-uall'],p)!=state['status']:raise RuntimeError('active Developer state changed')
 journal.update(state='completed',finished_epoch=time.time(),original_icloud_project_paths_remaining=0,permanent_deletions=0,git_worktree_relations_repaired=True,private_credentials_verified=True)
 persist();print(json.dumps({k:v for k,v in journal.items() if k not in ('developer_states','git_repair_output')},ensure_ascii=False))
except BaseException as exc:
 journal.update(state='STOP_partial_retirement_preserve_all_paths',error_type=type(exc).__name__,error=str(exc)[:500]);persist();raise
