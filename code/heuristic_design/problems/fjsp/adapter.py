"""FJSP hooks over unchanged closed U language and certified T30 solver."""
from dataclasses import asdict
import multiprocessing as mp
from statistics import fmean
import time
from heuristic_design.llm.legacy import ClientConfig, JsonCandidateTransport
from fjsp_usage.research.candidates import CandidateError, parse_response
from fjsp_usage.baseline_a.validation import validate_result as _validate_result
from tools import experiment_ops as o
from tools.experiment_ops_prompts import build

class MockTransport:
    def __init__(self,p):
        self.p=p;self.config=ClientConfig(p);self.identity=o.digest({'mock_fixture_version':1,'config':self.config.payload()});self.secret=''
    def redact(self,text):return text
    def preflight(self,prompt):
        if len(prompt.encode())>self.config.provider.max_prompt_bytes:raise ValueError('mock prompt too long')
    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        on_sent();time.sleep(self.p['config']['mock_delay_seconds'])
        n=int(o.digest(key)[:4],16)
        value=o.candidate({'id':'MOCK_NOT_LLM','alpha':(.1,.2,.3,.4)[n%4]} if self.p['config']['space']=='h01'
                          else {'id':'MOCK_NOT_LLM','member':n%10},self.p['config']['space'])
        return {'text':'{MOCK deterministic engineering fixture, not LLM-generated.}\n```python\n'+value['code']+'```',
                'usage':{'input_tokens':0,'output_tokens':0},'metadata':{'model':'MOCK_OFFLINE_NOT_LLM','mock':True}}


def evaluate(directory,s,p,candidate):
    from tools import experiment_ops as o
    key=candidate.key
    if key in s['evaluations']:return o.read(directory/s['evaluations'][key]['path']),True
    if (len(s['evaluations'])+1)*len(p['instances'])>p['budgets']['max_program_instances']:raise ValueError('evaluation cap')
    folder=directory/'evaluations'/key;folder.mkdir(parents=True,exist_ok=False)
    s['evaluations'][key]={'status':'reserved'};o.write(directory/'checkpoint.json',s)
    paths=[directory/r['relative_path'] for r in p['instances']]
    instances=[o.certified.s.v2.load_instance(path) for path in paths]
    members=[o.checked_candidate(r['candidate'],'h') for r in o.read(directory/'H_frozen.json')['members']]
    payload={'folder':str(folder),'binding':p,'candidate':asdict(candidate),'train_paths':[str(path) for path in paths]}
    o.write(folder/'Input_receipt.json',{'candidate':asdict(candidate),'instances':p['instances'],'protocol_sha256':s['identity']})
    expected={**p['source_files'],**p['protected_files']};before={k:o.sha(o.ROOT/k) for k in expected};beg=time.monotonic()
    rows,failure,life=o.certified.collect(mp.get_context('spawn'),o.certified.worker,payload,members,instances,
        [r['file'] for r in p['instances']],30,(1,) if p['config']['space']=='h01' else (0,1),lambda r:o.write(folder/'lifecycle.json',r))
    result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,
            'instances':rows,'total_instances':len(instances),'primary_evaluation_seconds':time.monotonic()-beg,**(failure or {})}
    o.write(folder/'raw_result.json',result)
    boundary=o.certified.certify(result,dict(before=o.read(folder/'before.json') if (folder/'before.json').exists() else None,
        after=o.read(folder/'after.json') if (folder/'after.json').exists() else None,lifecycle=life,
        expected_identity=o.read(directory/'Solver_identity.json')['identity'],expected_files=expected,start_files=before,
        end_files={k:o.sha(o.ROOT/k) for k in expected},worker_failure=(folder/'worker_failure.json').exists()))
    o.write(folder/'boundary.json',boundary)
    if boundary['decision']=='stop':raise ValueError('certification Stop: '+boundary['reason'])
    _validate_result(result,p['instances'],'modern');result['boundary']=boundary;o.write(folder/'result.json',result)
    s['evaluations'][key]={'status':'completed','path':str((folder/'result.json').relative_to(directory)),'sha256':o.sha(folder/'result.json')}
    o.write(directory/'checkpoint.json',s);return result,False



class FjspAdapter:
    entrypoint='experiments/tier2/manage.py'
    CandidateError=CandidateError
    def __getattr__(self,name):return getattr(o,name)
    def client_config(self,p):return ClientConfig(p)
    def transport(self,p):
        return MockTransport(p) if p['config']['api_mode']=='mock' else JsonCandidateTransport(ClientConfig(p))
    def members(self,directory):
        return [o.checked_candidate(r['candidate'],'h') for r in o.read(directory/'H_frozen.json')['members']]
    def checked_candidate(self,value):return o.checked_candidate(value,'U')
    def parse_candidate(self,text,config):
        c=parse_response(text,kind='U',interface_version=o.INTERFACE,member_count=10)
        return o.h01.validate(c.code,c.description) if config['space']=='h01' else c
    def build_prompt(self,*args):return build(*args)
    def validate_result(self,result,instances):return _validate_result(result,instances,'modern')
    def evaluate(self,*args):return evaluate(*args)
    def detach(self,*args,**kwargs):return o.certified.detach(*args,**kwargs)
    def summary(self,*args,**kwargs):
        from tools.experiment_ops_report import summary
        return summary(*args,**kwargs)
