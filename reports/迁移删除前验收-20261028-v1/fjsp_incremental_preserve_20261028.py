from pathlib import Path
import os,json,hashlib,shutil,stat,time
BASE=Path('/Users/DDXQL/Developer');OLD=Path('/Users/DDXQL/Documents/大学/硕士/代码');OUT=BASE/'迁移记录-删除前验收-20261028-v1'
rows=json.loads((OUT/'旧清单当前状态.json').read_text());initial=json.loads((BASE/'迁移记录-FJSP-20261027-v1/尚未取得文件.json').read_text());log=OUT/'增量复制.jsonl'
if log.exists():raise SystemExit('Existing journal; inspect instead of restarting')
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as a:
  for block in iter(lambda:a.read(2**20),b''):h.update(block)
 return h.hexdigest()
def copy_checked(source,destination):
 s=source.stat()
 if s.st_flags&0x40000000:raise RuntimeError('cloud placeholder; do not force-read')
 destination.parent.mkdir(parents=True,exist_ok=True);temp=destination.with_name(destination.name+'.migration-part-20261028')
 h=hashlib.sha256();count=0
 with source.open('rb') as a,temp.open('xb') as b:
  for chunk in iter(lambda:a.read(2**20),b''):
   b.write(chunk);h.update(chunk);count+=len(chunk)
  b.flush();os.fsync(b.fileno())
 end=source.stat()
 if count!=s.st_size or (s.st_size,s.st_mtime_ns)!=(end.st_size,end.st_mtime_ns):raise RuntimeError('short/changing source; retain partial evidence')
 shutil.copystat(source,temp);temp.chmod(stat.S_IMODE(s.st_mode));os.link(temp,destination);temp.unlink()
 if digest(destination)!=h.hexdigest():raise RuntimeError('destination hash mismatch')
 return {'sha256':h.hexdigest(),'bytes':count,'source_mtime_ns':s.st_mtime_ns}
start=time.time();count=0;total=0;skipped=[]
with log.open('x') as journal:
 for row in rows:
  key=row['path'];a=OLD/key;b=BASE/key
  if b.exists():continue
  try:
   result=copy_checked(a,b);journal.write(json.dumps({'path':key,'route':'resident original to missing counterpart',**result},ensure_ascii=False)+'\n');journal.flush();count+=1;total+=result['bytes']
  except Exception as e:
   skipped.append({'path':key,'reason':type(e).__name__+': '+str(e)[:160]});break
 # Restore missing package files only; never overwrite rebuilt h-usage packages.
 env_count=0
 if not skipped:
  for row in initial:
   parts=Path(row['path']).parts
   if '.venv' not in parts:continue
   a=OLD/row['path'];b=BASE/row['path']
   if b.exists() or not a.is_file() or a.stat().st_flags&0x40000000:continue
   try:
    result=copy_checked(a,b);journal.write(json.dumps({'path':row['path'],'route':'missing environment file only',**result},ensure_ascii=False)+'\n');journal.flush();env_count+=1
   except Exception as e:skipped.append({'path':row['path'],'reason':type(e).__name__+': '+str(e)[:160]});break
result={'scientific_and_source_files_copied':count,'bytes':total,'environment_missing_files_restored':env_count,'failures':skipped,'overwrites':0,'originals_deleted':False,'seconds':time.time()-start}
(OUT/'增量复制回执.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
