from pathlib import Path
import os,json,tarfile,gzip,hashlib,time,subprocess,stat
B=Path('/Users/DDXQL/Developer');ROOT=B/'FJSP-Heuristic-Research-tsp-integration';AUD=B/'迁移记录-删除前验收-20261028-v1';BACK=Path('/Users/DDXQL/Backups/Heuristic-Design-Lab/legacy-20261028-v1');INDEX=json.loads((AUD/'逐文件保存索引.json').read_text());archive=BACK/'legacy-scientific-workspace.tar.gz';temp=archive.with_suffix('.gz.INCOMPLETE')
if archive.exists() or temp.exists():raise SystemExit('STOP: archive exists; do not recreate or overwrite')
start=time.time();manifest={};seen=set();count=0;sourcebytes=0
with temp.open('xb') as output,gzip.GzipFile(fileobj=output,mode='wb',mtime=0,compresslevel=3) as compressed,tarfile.open(fileobj=compressed,mode='w|') as tar:
 for original,row in INDEX.items():
  p=Path(row['destination']);s=p.stat()
  if s.st_flags&0x40000000 or s.st_size!=row['bytes']:raise RuntimeError('STOP: saved asset unavailable or size changed: '+original)
  # hash during archive read, never trust a successful tar open alone.
  class Reader:
   def __init__(self,stream):self.stream=stream;self.h=hashlib.sha256();self.n=0
   def read(self,n=-1):
    block=self.stream.read(n);self.h.update(block);self.n+=len(block);return block
  info=tarfile.TarInfo('workspace/'+original);info.size=s.st_size;info.mode=0o600;info.mtime=s.st_mtime
  with p.open('rb') as stream:
   reader=Reader(stream);tar.addfile(info,reader)
  end=p.stat()
  if reader.n!=row['bytes'] or reader.h.hexdigest()!=row['sha256'] or (s.st_size,s.st_mtime_ns)!=(end.st_size,end.st_mtime_ns):raise RuntimeError('STOP: source digest/change during backup: '+original)
  manifest[info.name]={'sha256':row['sha256'],'bytes':row['bytes']};count+=1;sourcebytes+=row['bytes']
 for folder in [AUD,B/'迁移记录-FJSP-20261027-v1',B/'迁移记录-TSP-20261028-v1']:
  # Preserve migration receipts and inert old Git admin/objects, not project credential files.
  for p in sorted(folder.rglob('*')):
   if not p.is_file() or p.is_symlink():continue
   rel='migration-records/'+str(p.relative_to(B));s=p.stat()
   if s.st_flags&0x40000000:raise RuntimeError('STOP: migration receipt not local')
   if p.name.startswith('.env') or p.suffix in ('.key','.pem','.p12','.pfx'):raise RuntimeError('STOP: unexpected credential file in receipt folder')
   info=tarfile.TarInfo(rel);info.size=s.st_size;info.mode=0o600;info.mtime=s.st_mtime
   with p.open('rb') as stream:
    reader=Reader(stream);tar.addfile(info,reader)
   if reader.n!=s.st_size:raise RuntimeError('short receipt backup')
   manifest[rel]={'sha256':reader.h.hexdigest(),'bytes':reader.n};sourcebytes+=reader.n
# Verify archive roundtrip in a separate read, including every member and size.
verified=set()
with tarfile.open(temp,'r|gz') as tar:
 for item in tar:
  if not item.isfile() or item.name not in manifest:raise RuntimeError('unexpected archive entry')
  h=hashlib.sha256();n=0;stream=tar.extractfile(item)
  for block in iter(lambda:stream.read(2**20),b''):h.update(block);n+=len(block)
  expected=manifest[item.name]
  if n!=expected['bytes'] or h.hexdigest()!=expected['sha256']:raise RuntimeError('roundtrip mismatch: '+item.name)
  verified.add(item.name)
if verified!=set(manifest):raise RuntimeError('missing backup members')
os.link(temp,archive);temp.unlink();archive.chmod(0o600)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for block in iter(lambda:stream.read(2**20),b''):h.update(block)
 return h.hexdigest()
# Independent portable Git bundle; --all includes preserved original branch refs.
bundle=BACK/'all-preserved-git-history.bundle'
subprocess.run(['git','bundle','create',str(bundle),'--all'],cwd=ROOT,check=True,capture_output=True)
check=subprocess.run(['git','bundle','verify',str(bundle)],cwd=ROOT,capture_output=True,text=True)
(BACK/'Git_bundle_verify.txt').write_text(check.stdout+check.stderr)
if check.returncode:raise RuntimeError('STOP: Git bundle verification failed')
bundle.chmod(0o600)
(BACK/'Archive_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');(BACK/'Archive_manifest.json').chmod(0o600)
receipt={'scientific_files':count,'all_archive_members':len(manifest),'all_source_bytes':sourcebytes,'archive':str(archive),'archive_bytes':archive.stat().st_size,'archive_sha256':sha(archive),'roundtrip_verified_members':len(verified),'git_bundle':str(bundle),'git_bundle_bytes':bundle.stat().st_size,'git_bundle_sha256':sha(bundle),'git_bundle_verified':True,'credentials_included':False,'raw_asset_cloud_upload':False,'backup_type':'independent local folder on same Mac; not off-device protection','seconds':time.time()-start}
(BACK/'Backup_receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False))
