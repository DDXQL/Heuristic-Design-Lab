"""Process-local no-API boundary. Installed before importing the frozen engine."""
import importlib.abc
import os
from pathlib import Path
import socket
import sys
import types

ACTIVE=False
DENIED=[]


def deny(*args,**kwargs):
    DENIED.append('forbidden_operation')
    raise RuntimeError('no-API acceptance forbids credentials, network and real evaluation')


def preflight(config,allow_api):
    if (allow_api or config['api_mode']!='mock' or config['evaluation_mode']!='mock'
            or config['real_requests_authorized'] or config.get('provider') is not None
            or any(config.get(k) is not None for k in ('h_file','data_manifest','p0_file'))
            or config['execution_contract'].get('account_gate') is not None):
        deny()


class BlockClients(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if (fullname.startswith('heuristic_design.llm.')
                or fullname in ('heuristic_design.core.routing_evaluation','heuristic_design.core.flow_check')
                or fullname.startswith('fjsp_usage.research_real.real_transport')):
            DENIED.append('blocked_import:'+fullname)
            raise ImportError('real client/evaluator import forbidden in no-API acceptance')


def install():
    global ACTIVE
    if ACTIVE:return
    # Names only: never inspect or serialize credential values.
    for name in list(os.environ):
        if any(token in name.upper() for token in ('API_KEY','ACCESS_TOKEN','AUTH_TOKEN','SECRET')):
            os.environ.pop(name,None)
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS','BLIS_NUM_THREADS'):
        os.environ[name]='1'
    os.environ['PYTHONNOUSERSITE']='1'
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    parent=types.ModuleType('heuristic_design.llm');parent.__path__=[]
    stub=types.ModuleType('heuristic_design.llm.routing_transport')
    stub.preflight=preflight;stub.generate=deny;stub.NO_API_STUB=True
    sys.modules['heuristic_design.llm']=parent
    sys.modules['heuristic_design.llm.routing_transport']=stub
    sys.meta_path.insert(0,BlockClients())
    socket.socket.connect=deny;socket.create_connection=deny;socket.getaddrinfo=deny
    def audit(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):deny()
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            name=os.fsdecode(args[0]);parts=Path(name).parts
            if (any(p in ('.ssh','account-gate') for p in parts)
                    or Path(name).name.startswith('.env') or name.endswith('.key')):
                deny()
    sys.addaudithook(audit)
    ACTIVE=True


def assert_isolated():
    actual=[name for name in sys.modules if
            name.startswith('heuristic_design.llm.') and name!='heuristic_design.llm.routing_transport'
            or name.startswith('fjsp_usage.research_real.real_transport')]
    if actual or not getattr(sys.modules.get('heuristic_design.llm.routing_transport'),'NO_API_STUB',False):
        raise RuntimeError('actual model client reached no-API process')
    return {'no_API_stub':True,'real_client_modules_loaded':actual,'credential_reads':0,
            'model_requests':0,'formal_solves':0,'guard_denials':list(DENIED)}
