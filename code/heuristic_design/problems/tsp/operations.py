"""TSP problem hooks using shared execution and one campaign-wide API journal."""
from dataclasses import asdict
from pathlib import Path
import time
from heuristic_design.core.storage import read,write,sha,digest
from heuristic_design.llm.legacy import ClientConfig,JsonCandidateTransport,AttemptJournal,WireRecorder,DeadlineTransport
from . import candidates,prompts,evaluation

ROOT=Path(__file__).resolve().parents[4]


def global_config(campaign):
    p=read(campaign/'Protocol.json')
    return ClientConfig({'config':p['config'],'budgets':{'logical_generation':50}})


class MockTransport:
    def __init__(self,config):
        self.config=config;self.identity=digest({'mock_tsp':1,'config':config.payload()});self.secret=''
    def redact(self,text):return text
    def preflight(self,prompt):
        if len(prompt.encode())>self.config.provider.max_prompt_bytes:raise ValueError('prompt too long')
    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        on_sent();n=int(digest(key)[:8],16)
        if kind=='h':code='def priority('+', '.join(candidates.H_ARGS)+'):\n    return -distance_current + '+str((n%11-5)/20)+' * distance_start\n'
        else:
            import re
            k=len(re.findall(r'H MEMBER \d+\n',prompt));a=n%k;b=(a+1)%k
            vector=['0']*k
            if n%2:vector[a]='progress + 0.1';vector[b]='1.1 - progress';mode=1
            else:vector[a]='1';mode=0
            code='def use_heuristics('+', '.join(candidates.U_ARGS)+'):\n    return ('+str(mode)+', ('+', '.join(vector)+'))\n'
        return {'text':'{MOCK engineering fixture, not LLM-generated.}\n```python\n'+code+'\n```','usage':{'input_tokens':0,'output_tokens':0},'metadata':{'model':'MOCK_OFFLINE_NOT_LLM','mock':True}}


class Adapter:
    ROOT=ROOT
    entrypoint='experiments/tsp/manage.py'
    CandidateError=candidates.CandidateError
    read=staticmethod(read);write=staticmethod(write);sha=staticmethod(sha);digest=staticmethod(digest)

    def check_run(self,directory):
        p=read(directory/'Protocol.json');campaign=Path(p['campaign'])
        from .campaign import check
        check(campaign)
        if sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():raise ValueError('stage protocol identity changed')
        for name,value in p['protected_files'].items():
            if sha(ROOT/name)!=value:raise ValueError('stage frozen input changed: '+name)
        if read(directory/'Members.json')!=p['members']:raise ValueError('stage H changed')
        return p

    def members(self,directory):return read(directory/'Members.json')
    def checked_candidate(self,value):
        # The scalar H signature is independent of K; U shape is inferred here.
        import ast
        k=next((len(n.value.elts[1].elts) for n in ast.walk(ast.parse(value['code'])) if isinstance(n,ast.Return) and isinstance(n.value,ast.Tuple)),1)
        return candidates.checked(value,k)
    def parse_candidate(self,text,config):return candidates.parse(text,config['candidate_kind'],config['member_count'])
    def build_prompt(self,*args):return prompts.build(*args)
    def validate_result(self,*args):return evaluation.validate_result(*args)
    def evaluate(self,*args):return evaluation.evaluate(*args)
    def client_config(self,p):return global_config(Path(p['campaign']))
    def transport(self,p):
        config=self.client_config(p)
        return MockTransport(config) if p['config']['api_mode']=='mock' else JsonCandidateTransport(config)
    def journal(self,directory,state,p,deadline):
        campaign=Path(p['campaign']);protocol=read(campaign/'Protocol.json');origin=Path(protocol.get('request_origin',{}).get('directory',str(campaign)))
        clock=read(origin/'Run_clock.json');deadline=min(deadline,clock['deadline'])
        wire=WireRecorder(self.transport(p),origin/'wire_responses',verify=lambda:self.check_run(directory))
        return AttemptJournal(origin/'API_attempts.json',config=self.client_config(p),context=sha(origin/'Protocol.json'),phase='tsp-pilot/'+sha(origin/'Protocol.json'),transport=DeadlineTransport(wire,deadline))
    def summary(self,directory,write_files=False):
        p=read(directory/'Protocol.json');s=read(directory/'checkpoint.json');records=[];best=None
        for task in read(directory/'Tasks.json'):
            t=s['tasks'].get(task['id']);record={'id':task['id'],'stage':task['stage'],'status':t['status'] if t else 'not_started','valid':False,'fitness':None}
            if t:
                record.update({k:t.get(k) for k in ('parents','AST_duplicate','cache_hit','failure','error','generation_status','candidate')})
                if t.get('status')=='completed' and t.get('valid'):
                    record.update(valid=True,fitness=t['fitness'])
                    if best is None or (-record['fitness'],record['id'])<(-best['fitness'],best['id']):best=record
            records.append(record)
        facts={'phase':s['phase'],'cursor':s['cursor'],'planned':p['budgets'],'records':records,'best_so_far':best,
            'physical_evaluations':len(s['evaluations']),'new_slots_used':sum(t['stage']=='new' for t in s['tasks'].values())}
        if write_files:write(directory/'results/Summary.json',facts)
        return facts
    def detach(self,args,log,env):
        import subprocess
        with open(log,'ab') as f:
            return subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=f,stderr=f,start_new_session=True).pid
