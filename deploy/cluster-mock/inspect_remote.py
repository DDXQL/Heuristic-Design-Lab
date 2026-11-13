#!/usr/bin/env python3
"""Read-only login-node inventory, compatible with the system Python 3.6."""
import json
import os
import subprocess
import time
os.environ['PYTHONNOUSERSITE']='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
for name in list(os.environ):
    if any(token in name.upper() for token in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):
        os.environ.pop(name,None)
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
    os.environ[name]='1'

PY='/public2/home/qiuqian/hdl-envs/portable-v2/bin/python'
REMOTE='/public2/home/qiuqian/hdl-deploy/fjsp-noapi-923781f-20261113-r1'


def probe(argv):
    try:
        result=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=12)
        return {'returncode':result.returncode,'stdout':result.stdout[:24000],'stderr':result.stderr[:5000],
                'stdout_truncated':len(result.stdout)>24000,'stderr_truncated':len(result.stderr)>5000}
    except Exception as error:return {'returncode':None,'error_type':type(error).__name__,'error':str(error)}


def inspect():
    parent=REMOTE
    while not os.path.exists(parent):parent=os.path.dirname(parent)
    code=('import json,platform,numpy,pytz,tqdm; print(json.dumps({"python":platform.python_version(),'
          '"numpy":numpy.__version__,"pytz":pytz.__version__,"tqdm":tqdm.__version__}))')
    commands={
        'identity':['id'],'platform':['uname','-a'],'glibc':['getconf','GNU_LIBC_VERSION'],
        'environment':[PY,'-B','-c',code],'space':['df','-Pk',parent],'quota':['quota','-s'],
        'partitions':['sinfo','-h','-o','%P|%a|%l|%C|%m'],
        'partition_details':['scontrol','show','partition','-o'],
        'associations':['sacctmgr','-n','-P','show','assoc','where','user=qiuqian',
                        'format=Cluster,Account,User,Partition,QOS,DefaultQOS,GrpTRES,MaxTRES,MaxJobs,MaxSubmitJobs'],
        'qos':['sacctmgr','-n','-P','show','qos','format=Name,MaxWall,MaxJobsPU,MaxSubmitPU,MaxTRESPU,GrpTRES'],
        'queue':['squeue','-h','-u','qiuqian','-o','%i|%T|%C|%m|%P|%j']}
    result={name:probe(command) for name,command in commands.items()}
    active_cpus=0;queue_known=result['queue'].get('returncode')==0
    if queue_known:
        for line in result['queue']['stdout'].splitlines():
            fields=line.split('|')
            if len(fields)>=3 and fields[1] in ('RUNNING','COMPLETING','CONFIGURING'):
                try:active_cpus+=int(fields[2])
                except ValueError:queue_known=False
    return {'kind':'READ_ONLY_LOGIN_INVENTORY','at_unix':time.time(),'remote_root':REMOTE,
            'existing_ancestor':parent,'ancestor_readable':os.access(parent,os.R_OK),
            'ancestor_writable':os.access(parent,os.W_OK),'environment_available':result['environment'].get('returncode')==0,
            'active_user_cpus':active_cpus if queue_known else None,
            'requested_Mock_resources':{'cpus':3,'memory_mib':1024,'wall_seconds':600},
            'account_QOS_limits':'raw evidence only; denied/unsupported/empty is unknown, not unlimited',
            'model_requests':0,'formal_solves':0,'commands':result}


if __name__=='__main__':print(json.dumps(inspect(),ensure_ascii=False,indent=2))
