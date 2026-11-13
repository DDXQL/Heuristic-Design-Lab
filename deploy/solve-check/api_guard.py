"""No model clients, network or credentials; frozen local solver is permitted."""
import importlib.abc
import os
from pathlib import Path
import socket
import sys


def deny(*args,**kwargs):raise RuntimeError('bounded solve acceptance forbids model clients, network and credentials')


class NoClients(importlib.abc.MetaPathFinder):
    def find_spec(self,name,path=None,target=None):
        if name.startswith('heuristic_design.llm') or name.startswith('fjsp_usage.research_real.real_transport'):
            raise ImportError('model client import forbidden by real-solve acceptance')


def install():
    for name in list(os.environ):
        if any(x in name.upper() for x in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):os.environ.pop(name,None)
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
        os.environ[name]='1'
    os.environ['PYTHONNOUSERSITE']='1';os.environ['PYTHONDONTWRITEBYTECODE']='1'
    sys.meta_path.insert(0,NoClients())
    socket.socket.connect=deny;socket.create_connection=deny;socket.getaddrinfo=deny
    def audit(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):deny()
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            p=Path(os.fsdecode(args[0]))
            if p.suffix=='.key' or p.name.startswith('.env') or any(x in ('.ssh','account-gate') for x in p.parts):deny()
    sys.addaudithook(audit)


def check():
    modules=[n for n in sys.modules if n.startswith('heuristic_design.llm') or n.startswith('fjsp_usage.research_real.real_transport')]
    if modules:raise RuntimeError('model client loaded unexpectedly')
    return {'model_requests':0,'credential_reads':0,'real_client_modules_loaded':modules}
