"""One audited cleanup: verified archive first, then same-run byte-identical links.
No experiment imports, network, API, solver, source changes or directory deletion.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUNS=[ROOT/'runs'/name for name in (
 'b1-v6-r1-train21-20261029-01',
 'b1-v6-r1-train21-20261029-221535-858514-d3145ddd',
 'b1-v6-r3-20261030-134523-982946-70326e84')]
ARCHIVE=ROOT/'archives/r1-r3-dedup-20261030'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def save(name,value):
    path=OUT/name;temp=path.with_suffix(path.suffix+'.tmp')
    with temp.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def rel(path):return str(path.relative_to(ROOT))
def meta(path):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or path.is_symlink():raise ValueError('not regular file: '+rel(path))
    return dict(size=s.st_size,blocks=s.st_blocks,device=s.st_dev,inode=s.st_ino,nlink=s.st_nlink,
                mode=stat.S_IMODE(s.st_mode),uid=s.st_uid,gid=s.st_gid,mtime_ns=s.st_mtime_ns)


def idle(directory):
    if any('lock' in p.name.lower() for p in directory.iterdir()):raise ValueError('lock present: '+rel(directory))
    s=json.loads((directory/'checkpoint.json').read_text())
    if s['phase']!='completed' or any(t['status'] in ('request_reserved','evaluation_reserved') for t in s['tasks'].values()):
        raise ValueError('run is not safely completed: '+rel(directory))
    return s


def allocated(paths):
    seen=set();total=0
    for path in paths:
        s=path.stat();key=(s.st_dev,s.st_ino)
        if key not in seen:seen.add(key);total+=s.st_blocks*512
    return total


def unchanged(path,original):
    now=meta(path)
    for key in ('size','device','inode','mode','uid','gid','mtime_ns'):
        if now[key]!=original[key]:raise ValueError('file changed: '+rel(path))


def replace_duplicate(a,b,record):
    unchanged(a,record['source_metadata']);unchanged(b,record['alias_metadata'])
    if sha(a)!=record['sha256'] or sha(b)!=record['sha256']:raise ValueError('content changed before replacement')
    if a.stat().st_dev!=b.stat().st_dev:raise ValueError('cross-device link refused')
    temporary=b.with_name('.result.cleanup-link.tmp')
    if temporary.exists() or temporary.is_symlink():raise FileExistsError(str(temporary))
    try:
        os.link(a,temporary)  # Original alias remains intact until this succeeds.
        unchanged(b,record['alias_metadata'])
        os.replace(temporary,b)
        fd=os.open(b.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if temporary.exists():temporary.unlink()
    if not os.path.samefile(a,b) or sha(b)!=record['sha256']:raise ValueError('post-link certification failed')


def main():
    if (OUT/'result.json').exists() or (OUT/'plan.json').exists():raise FileExistsError('single-use cleanup; inspect previous receipts, do not rerun')
    started=datetime.now(ZoneInfo('Asia/Manila')).isoformat();free_before=shutil.disk_usage(ROOT).free
    pairs=[];files=[];by_name={};states={}
    for d in RUNS:
        states[rel(d)]=idle(d)
        for path in sorted(d.rglob('*')):
            if path.is_symlink():raise ValueError('unexpected symlink: '+rel(path))
            if path.is_file():files.append(path);by_name[rel(path)]={'metadata':meta(path),'sha256':None}
        for t in states[rel(d)]['tasks'].values():
            ev=states[rel(d)]['evaluations'].get(t.get('candidate',{}).get('key'))
            if not ev or t.get('duplicate_of'):continue
            a=d/ev['path'];b=d/'worker-receipts'/t['id']/'result.json'
            if not b.exists():continue
            ma,mb=meta(a),meta(b)
            if ma['size']!=mb['size']:raise ValueError('unequal size: '+rel(b))
            ha,hb=sha(a),sha(b)
            if ha!=hb or ha!=ev['sha256']:raise ValueError('unequal hash/checkpoint mismatch: '+rel(b))
            if (ma['mode'],ma['uid'],ma['gid'])!=(mb['mode'],mb['uid'],mb['gid']):raise ValueError('permission mismatch')
            if (ma['device'],ma['inode'])==(mb['device'],mb['inode']):raise ValueError('already linked; changed inventory')
            by_name[rel(a)]['sha256']=ha;by_name[rel(b)]['sha256']=hb
            pairs.append({'source':rel(a),'alias':rel(b),'sha256':ha,'source_metadata':ma,'alias_metadata':mb})
        print('hash_verified',d.name,flush=True)
    if len(pairs)!=30:raise ValueError('unexpected cleanup scope')
    for path in files:
        if by_name[rel(path)]['sha256'] is None:by_name[rel(path)]['sha256']=sha(path)
    aliases={r['alias']:r['source'] for r in pairs}
    allocated_before=allocated(files)
    plan={'started_at':started,'git_head':'242683d','free_before_bytes':free_before,
          'allocated_before_bytes':allocated_before,'runs':[rel(d) for d in RUNS],
          'action':'Replace only verified duplicate worker result copies with hardlinks to same-run canonical files',
          'pairs':pairs,'all_files':by_name,'backups':'independent gzip archive; unique content stored once with tar hardlink aliases',
          'predicted_duplicate_bytes':sum(r['alias_metadata']['blocks']*512 for r in pairs),
          'protected':'All filenames, result bytes, reports, champions, protocols, configurations, checkpoints, prompts, responses and failure evidence retained. No old run deleted.',
          'metadata_note':'Hardlinked aliases share canonical inode and modification time; original per-path metadata retained here.'}
    save('plan.json',plan)
    ARCHIVE.mkdir(parents=True,exist_ok=False)
    backup=ARCHIVE/'r1-r3-complete.tar.gz';pending=backup.with_suffix(backup.suffix+'.partial')
    ordinary=[p for p in files if rel(p) not in aliases];linked=[p for p in files if rel(p) in aliases]
    with tarfile.open(pending,'w:gz',compresslevel=1,format=tarfile.PAX_FORMAT) as archive:
        for path in ordinary:
            unchanged(path,by_name[rel(path)]['metadata']);archive.add(path,arcname=rel(path),recursive=False)
        for path in linked:
            item=archive.gettarinfo(str(path),arcname=rel(path));item.type=tarfile.LNKTYPE;item.size=0
            item.linkname=aliases[rel(path)];archive.addfile(item)
        archive.add(OUT/'plan.json',arcname='cleanup/plan.json',recursive=False)
    with pending.open('rb') as f:os.fsync(f.fileno())
    os.replace(pending,backup)
    print('backup_written_bytes',backup.stat().st_size,flush=True)
    verified={}
    with tarfile.open(backup,'r|gz') as archive:
        for member in archive:
            if member.name=='cleanup/plan.json':
                f=archive.extractfile(member);value=json.loads(f.read())
                if value!=plan:raise ValueError('backup manifest mismatch')
                continue
            if member.name not in by_name or member.name in verified:raise ValueError('unexpected/duplicate archive member')
            if member.islnk():
                if member.linkname!=aliases.get(member.name) or member.linkname not in verified:raise ValueError('invalid backup hardlink')
                got=verified[member.linkname]
            elif member.isfile():
                h=hashlib.sha256();f=archive.extractfile(member)
                for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
                got=h.hexdigest()
                if member.size!=by_name[member.name]['metadata']['size']:raise ValueError('backup size mismatch')
            else:raise ValueError('unsafe archive type')
            if got!=by_name[member.name]['sha256']:raise ValueError('backup hash mismatch: '+member.name)
            verified[member.name]=got
    if set(verified)!=set(by_name):raise ValueError('incomplete backup')
    backup_receipt={'path':rel(backup),'sha256':sha(backup),'size_bytes':backup.stat().st_size,
                    'verified_files':len(verified),'regular_content_files':len(ordinary),'hardlink_aliases':len(linked),
                    'all_streamed_SHA256_match':True,'backup_manifest_sha256':sha(OUT/'plan.json')}
    save('backup-verification.json',backup_receipt)
    shutil.copyfile(OUT/'backup-verification.json',ARCHIVE/'backup-verification.json')
    print('backup_verified',len(verified),'files; beginning atomic dedup',flush=True)
    free_before_link=shutil.disk_usage(ROOT).free;done=[]
    for d in RUNS:idle(d)
    for pair in pairs:
        a,b=ROOT/pair['source'],ROOT/pair['alias'];replace_duplicate(a,b,pair)
        done.append({'source':pair['source'],'alias':pair['alias'],'sha256':pair['sha256'],
                     'shared_inode':b.stat().st_ino,'link_count':b.stat().st_nlink})
        save('applied.json',{'completed_pairs':len(done),'pairs':done})
        print('linked',pair['alias'],flush=True)
    # Complete pre/post byte audit, including all checkpoint and request receipts.
    for path in files:
        if sha(path)!=by_name[rel(path)]['sha256']:raise ValueError('post-cleanup content mismatch: '+rel(path))
    for d in RUNS:
        if idle(d)!=states[rel(d)]:raise ValueError('checkpoint changed')
    if hasattr(os,'sync'):os.sync()
    free_after=shutil.disk_usage(ROOT).free;allocated_after=allocated(files)
    result={'completed_at':datetime.now(ZoneInfo('Asia/Manila')).isoformat(),'verified_pairs':len(done),
            'verified_file_paths':len(files),'bytes_unchanged':True,'all_paths_preserved':True,
            'allocated_before_bytes':allocated_before,'allocated_after_bytes':allocated_after,
            'run_allocated_bytes_released':allocated_before-allocated_after,
            'backup_bytes':backup.stat().st_size,'free_before_bytes':free_before,
            'free_before_link_bytes':free_before_link,'free_after_bytes':free_after,
            'observed_free_space_gain_bytes':free_after-free_before,
            'net_accounted_bytes_released':allocated_before-allocated_after-backup.stat().st_blocks*512,
            'free_space_GiB':free_after/2**30,'twenty_GiB_gate_satisfied':free_after>=20*2**30,
            'backup':backup_receipt,'experiments_started':0,'API_requests':0,'old_runs_deleted':0,
            'limitation':'Same-volume archive provides logical restoration, not protection against physical disk failure. Hardlink aliases share modification time and bytes; never edit completed result files.'}
    save('result.json',result);print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
