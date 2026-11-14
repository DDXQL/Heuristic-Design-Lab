#!/usr/bin/env python3
"""Current login inventory; only lstat credential metadata, never read its bytes."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time


def probe(argv):
    try:
        p=subprocess.run(argv,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        return {'returncode':p.returncode,'stdout':p.stdout[:30000],'stderr':p.stderr[:2000]}
    except Exception as e:return {'returncode':None,'error_type':type(e).__name__,'error':str(e)}


def inspect(root):
    root=Path(root);key=Path('/public2/home/qiuqian/.config/hdl/leafapi.key');metadata={'path':str(key),'exists':key.exists(),'value_read':False}
    if key.exists():
        s=key.lstat();metadata.update(owner_uid=s.st_uid,mode=oct(stat.S_IMODE(s.st_mode)),regular=stat.S_ISREG(s.st_mode),symlink=stat.S_ISLNK(s.st_mode),runtime_acceptable=s.st_uid==os.getuid() and stat.S_IMODE(s.st_mode)==0o600 and stat.S_ISREG(s.st_mode))
    py='/public2/home/qiuqian/hdl-envs/portable-v2/bin/python';parent=root
    while not parent.exists():parent=parent.parent
    cmds={'environment':[py,'-s','-B','-c','import json,platform,numpy,pytz,tqdm; print(json.dumps(dict(python=platform.python_version(),numpy=numpy.__version__,pytz=pytz.__version__,tqdm=tqdm.__version__)))'],
      'space':['df','-Pk',str(parent)],'quota':['quota','-s'],'partitions':['sinfo','-h','-o','%P|%a|%l|%C|%m'],
      'nodes':['sinfo','-N','-h','-p','128C_02','-o','%N|%t|%C|%m'],
      'associations':['sacctmgr','-n','-P','show','assoc','where','user=qiuqian','format=Cluster,Account,User,Partition,QOS,DefaultQOS,GrpTRES,MaxTRES,MaxJobs,MaxSubmitJobs'],
      'qos':['sacctmgr','-n','-P','show','qos','format=Name,MaxWall,MaxJobsPU,MaxSubmitPU,MaxTRESPU,GrpTRES'],
      'queue':['squeue','-h','-u','qiuqian','-o','%i|%T|%C|%m|%P|%j'],
      'filesystem':['stat','-f','-c','%T',str(parent)]}
    releases={}
    for name in ('fjsp-noapi-923781f-20261113-r1','fjsp-real-solve-16-923781f-20261113-r1','triad-six-groups-20261114-r4p1',root.name):
        p=root.parent/name/'release.json';releases[name]={'exists':p.exists()}
        if p.exists():
            d=json.loads(p.read_text());releases[name].update(version=d.get('version'),engineering_commit=d.get('engineering_commit'),files=len(d.get('files',{})))
    commands={k:probe(v) for k,v in cmds.items()};active=None
    if commands['queue']['returncode']==0:
        try:active=sum(int(r.split('|')[2]) for r in commands['queue']['stdout'].splitlines() if len(r.split('|'))>=3 and r.split('|')[1] in ('RUNNING','CONFIGURING','COMPLETING'))
        except ValueError:active=None
    return {'at_unix':time.time(),'kind':'CURRENT_READ_ONLY_LOGIN_INVENTORY','remote_root':str(root),'ancestor_writable':os.access(parent,os.W_OK),'credential':metadata,'releases':releases,'commands':commands,'active_user_CPUs':active,'aggregate_user_memory':'see raw queue/TRES; not inferred from missing or per-node fields','API_requests':0,'solver_calls':0,'credential_values_read':0,'compute_node_checks':'TLS/API/gate semantics not proven by login-node inventory','unknown_or_denied_limits_are_unlimited':False}

if __name__=='__main__':print(json.dumps(inspect(sys.argv[1]),ensure_ascii=False,indent=2))
