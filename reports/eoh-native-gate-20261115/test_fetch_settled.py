"""Fake SSH/accounting/ZIP fixtures only; no live authentication or API."""
import hashlib
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
from unittest.mock import patch
from fetch_settled import SettledConnection,original


def deny(*args,**kwargs):raise AssertionError('offline: no network/auth/model/solver')


def main():
    with tempfile.TemporaryDirectory(prefix='settled-fetch-offline-') as folder,patch.object(socket.socket,'connect',deny):
        tmp=Path(folder);fixtures={}
        import zipfile
        for job in ('618885','618886'):
            path=tmp/(job+'.zip');name='runs/SYNTHETIC-'+job+'/checkpoint.json';raw=json.dumps({'phase':'initialization_incomplete','SYNTHETIC':True}).encode()
            with zipfile.ZipFile(path,'x') as z:
                z.writestr(name,raw);z.writestr('retrieval-manifest.json',json.dumps({'files':{name:hashlib.sha256(raw).hexdigest()}}))
            fixtures[job]=path
        class Fake:
            queue='999999|RUNNING\n';state='FAILED';queue_error=False;copies=0
            def run(self,args,source=None,check=True):
                if args[0]=='squeue':
                    assert '-j' not in args and args==['squeue','-h','-u','qiuqian','-o','%i|%T']
                    if self.queue_error:raise RuntimeError('SYNTHETIC SSH failure; not an absent job')
                    text=self.queue
                elif args[0]=='sacct':text=args[args.index('-j')+1]+'|'+self.state+'|2:0|00:01|2|123K|SYNTHETIC-NODE\n' if self.state else ''
                elif args[0]=='cat':
                    if args[1].endswith('Shared.json'):
                        text=json.dumps({'members':[{'run_dir':original.REMOTE+'/runs/SYNTHETIC-'+job,'group':'fjsp-eoh','seed':seed} for job,seed in [('618885',501),('618886',502)]]})
                    else:text=json.dumps({'state':'submitted','job_id':'618885' if '618885' in args[1] else '618886'})
                else:
                    assert '-c' in args and args[-1] in fixtures
                    job=args[-1];text=json.dumps({'path':'/SYNTHETIC/'+job+'.zip','sha256':hashlib.sha256(fixtures[job].read_bytes()).hexdigest(),'phase':'initialization_incomplete'})
                return subprocess.CompletedProcess(args,0,stdout=text,stderr='')
            def copy(self,source,dest):
                self.copies+=1;shutil.copyfile(fixtures[Path(source).stem],dest)
        fake=Fake();out=tmp/'retrieved';out.mkdir();result=original.fetch(SettledConnection(fake),original.REAL,out)
        assert result['retrieved'] and len(result['members'])==2 and all(r['hashes_verified'] and r['Slurm_state']=='FAILED' for r in result['members']) and fake.copies==2
        assert (out/'618885-squeue.txt').read_text()==''
        for tag,queue,state,error in [('active','618885|RUNNING\n','RUNNING',False),('missing-accounting','','',False),('network','','FAILED',True)]:
            fake=Fake();fake.queue=queue;fake.state=state;fake.queue_error=error;dest=tmp/tag;dest.mkdir()
            try:original.fetch(SettledConnection(fake),original.REAL,dest)
            except (PermissionError,RuntimeError):pass
            else:raise AssertionError('uncertain/active state wrongly retrieved')
            assert fake.copies==0
        print(json.dumps({'passed':True,'checks':['terminal job absent from squeue but exact FAILED sacct record -> two ZIPs retrieved and hashes verified','unrelated queued job does not block exact settled jobs','active job refused','missing terminal accounting refused','SSH/queue failure refused'],'network_calls':0,'API_requests':0,'actual_solves':0,'Slurm_submitted':False},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
