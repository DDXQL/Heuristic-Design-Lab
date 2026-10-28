from pathlib import Path
import os,json,hashlib,shutil,stat,time,collections
B=Path('/Users/DDXQL/Developer');O=Path('/Users/DDXQL/Documents/大学/硕士/代码');R=B/'迁移记录-删除前验收-20261028-v1';I=B/'FJSP-Heuristic-Research-tsp-integration';V=I/'archives/legacy-cleanup-audit-20261028-v1';rows=json.loads((R/'源文件元数据.json').read_text());tsp=json.loads((I/'reports/TSP最新成果迁移-20261028-v1/Assets_manifest.json').read_text());cache={};records={};new=[];fail=[];start=time.time()
def sha(p):
 s=p.stat();key=(str(p),s.st_size,s.st_mtime_ns)
 if key in cache:return cache[key]
 if s.st_flags&0x40000000:raise RuntimeError('cloud placeholder; no forced read')
 h=hashlib.sha256();n=0
 with p.open('rb') as f:
  for block in iter(lambda:f.read(2**20),b''):h.update(block);n+=len(block)
 end=p.stat()
 if n!=s.st_size or (s.st_size,s.st_mtime_ns)!=(end.st_size,end.st_mtime_ns):raise RuntimeError('changing source/destination')
 cache[key]=h.hexdigest();return cache[key]
for row in rows:
 key=row['path'];source=O/key;root,rel=key.split('/',1)
 try:
  current=source.stat()
  if (current.st_size,current.st_mtime_ns)!=(row['bytes'],row['mtime_ns']):raise RuntimeError('source changed since census')
  h=sha(source);target=None;route=None
  candidates=[(B/key,'exact-counterpart')]
  if root=='FJSP-Heuristic-Research-tsp-pilot':
   candidates.append((I/rel,'integrated-TSP-code-or-report'))
   if rel in tsp['files'] and tsp['files'][rel]['sha256']==h:
    candidates.append((I/'archives/tsp-c3b74b7-20261028-v1/workspace'/rel,'previously-certified-TSP-vault'))
  for p,kind in candidates:
   if p.is_file() and p.stat().st_size==current.st_size and sha(p)==h:target=p;route=kind;break
  if target is None:
   target=V/'workspace'/key;target.parent.mkdir(parents=True,exist_ok=True)
   if target.exists():
    if sha(target)!=h:raise RuntimeError('existing vault differs; never overwrite')
   else:
    temp=target.with_name(target.name+'.copying');temp.write_bytes(source.read_bytes());temp.chmod(0o600)
    after=source.stat()
    if (after.st_size,after.st_mtime_ns)!=(current.st_size,current.st_mtime_ns) or sha(temp)!=h:raise RuntimeError('copy race/hash mismatch')
    os.link(temp,target);temp.unlink();new.append(key)
   route='preserved-original-differing-or-unique-file'
  records[key]={'sha256':h,'bytes':current.st_size,'source_mtime_ns':current.st_mtime_ns,'destination':str(target),'route':route}
 except Exception as e:fail.append({'path':key,'reason':type(e).__name__+': '+str(e)[:240]});break
(R/'逐文件保存索引.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n');result={'source_files':len(rows),'verified_files':len(records),'source_bytes':sum(r['bytes'] for r in rows),'verified_bytes':sum(r['bytes'] for r in records.values()),'routes':dict(collections.Counter(r['route'] for r in records.values())),'unique_original_files_saved':new,'failures':fail,'credential_contents_read':False,'original_files_modified':False,'seconds':time.time()-start};(R/'资产覆盖回执.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False)[:3500])
