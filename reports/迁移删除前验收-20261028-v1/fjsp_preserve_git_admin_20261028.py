from pathlib import Path
import os,json,hashlib,zlib,subprocess,shutil,time
B=Path('/Users/DDXQL/Developer');O=Path('/Users/DDXQL/Documents/大学/硕士/代码/FJSP-Heuristic-Research/.git');N=B/'FJSP-Heuristic-Research/.git';R=B/'迁移记录-删除前验收-20261028-v1';repo=B/'FJSP-Heuristic-Research-tsp-integration';vault=R/'原公共Git管理文件';vault.mkdir(exist_ok=True);os.chmod(vault,0o700)
# All original ref values are preserved under new names, not over active branches.
refs=subprocess.check_output(['git','--no-optional-locks','show-ref'],cwd=O.parent,text=True);refrows=[line.split() for line in refs.splitlines()]
loose=[]
for directory in (O/'objects').iterdir():
 if directory.is_dir() and len(directory.name)==2 and all(c in '0123456789abcdef' for c in directory.name):
  for f in directory.iterdir():
   if len(f.name)==38:loose.append((directory.name+f.name,f))
ids=[oid for oid,_ in loose];q=subprocess.run(['git','cat-file','--batch-check=%(objectname) %(objecttype)'],input='\n'.join(ids)+'\n',cwd=repo,capture_output=True,text=True,check=True);absent={line.split()[0] for line in q.stdout.splitlines() if line.endswith(' missing')};recovered=[];missing=[]
for oid,f in loose:
 if oid not in absent:continue
 if f.stat().st_flags&0x40000000:missing.append({'oid':oid,'reason':'original cloud placeholder'});continue
 raw=f.read_bytes();payload=zlib.decompress(raw)
 if hashlib.sha1(payload).hexdigest()!=oid:raise RuntimeError('invalid original object '+oid)
 target=N/'objects'/oid[:2]/oid[2:];target.parent.mkdir(exist_ok=True)
 with target.open('xb') as out:out.write(raw)
 recovered.append(oid)
# A reachable old ref must not be installed unless its object is readable.
refsaved=[]
for oid,name in refrows:
 exists=subprocess.run(['git','cat-file','-e',oid],cwd=repo,capture_output=True).returncode==0
 if not exists:missing.append({'ref':name,'oid':oid,'reason':'missing ref target'});continue
 newname='refs/legacy-preserved/20261028/'+name.removeprefix('refs/')
 old=subprocess.run(['git','rev-parse','--verify',newname],cwd=repo,capture_output=True,text=True)
 if old.returncode==0 and old.stdout.strip()!=oid:raise RuntimeError('preservation ref conflict')
 if old.returncode:subprocess.run(['git','update-ref',newname,oid,'0'*40],cwd=repo,check=True)
 refsaved.append({'original_ref':name,'oid':oid,'preserved_ref':newname})
# Keep old index/HEAD/refs/reflogs/worktree registration as inert evidence, not active metadata.
metadata={};bad=[]
for current,dirs,files in os.walk(O,followlinks=False):
 dirs[:]=[d for d in dirs if d not in ('objects',)]
 for name in files:
  f=Path(current)/name;rel=f.relative_to(O)
  if f.is_symlink() or name.endswith('.lock'):bad.append({'path':str(rel),'reason':'link/lock; no automatic handling'});continue
  if f.stat().st_flags&0x40000000:bad.append({'path':str(rel),'reason':'cloud placeholder'});continue
  data=f.read_bytes();target=vault/rel;target.parent.mkdir(parents=True,exist_ok=True)
  if target.exists() and target.read_bytes()!=data:raise RuntimeError('existing metadata backup differs')
  if not target.exists():target.write_bytes(data);target.chmod(0o600)
  metadata[str(rel)]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
verify=subprocess.run(['git','fsck','--full'],cwd=repo,capture_output=True,text=True);(R/'Git_fsck.txt').write_text(verify.stdout+verify.stderr)
result={'old_common_git':str(O),'new_common_git':str(N),'original_loose_objects_checked':len(ids),'missing_before':len(absent),'objects_recovered':recovered,'unrecovered':missing,'preserved_refs':refsaved,'metadata_files':metadata,'metadata_unavailable':bad,'fsck_exit':verify.returncode,'original_refs_changed':False,'active_old_worktree_pointers_changed':False}
(R/'Git保存回执.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print('original objects',len(ids),'recovered',len(recovered),'unrecovered',len(missing),'refs saved',len(refsaved),'metadata',len(metadata),'unavailable',len(bad),'fsck',verify.returncode)
