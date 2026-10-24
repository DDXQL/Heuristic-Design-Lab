"""Independent search sampling and durable query accounting; evaluator injected.

The sampler sees ONLY space size/budget/search seed. It cannot read H labels,
cache, Fitness or incumbents. A completed plan never repeats consumed queries;
unresolved reservations fail closed. Synthetic tests use disjoint toy spaces.
"""
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import fmean


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def read(path):return json.loads(Path(path).read_text())


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    path=Path(path);tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n');tmp.replace(path)


def sample_indices(size,budget,seed):
    if any(type(x) is not int for x in (size,budget,seed)) or not 1<=budget<=size:raise ValueError('valid finite sample dimensions')
    return random.Random(seed).sample(range(size),budget)


def validate_result(result,instances):
    if type(result.get('valid')) is not bool or result.get('total_instances')!=len(instances):raise ValueError('result shape')
    rows=result.get('instances',[])
    if len(rows)>len(instances):raise ValueError('too many rows')
    for r,e in zip(rows,instances):
        if (r['file']!=e['file'] or r['lower_bound']!=e['LB'] or r.get('feasible') is not True
            or type(r['makespan']) is not int or r['makespan']<=0 or r['score']!=-r['makespan']/e['LB']):
            raise ValueError('instance/LB/score mismatch')
    if result['valid']:
        if len(rows)!=len(instances) or result.get('fitness')!=fmean(r['score'] for r in rows):raise ValueError('full mean required')
    elif result.get('fitness') is not None:raise ValueError('invalid prefix cannot have Fitness')


class Campaign:
    def __init__(self,directory):self.directory=Path(directory)

    @classmethod
    def create(cls,directory,protocol,plans):
        directory=Path(directory)
        if directory.exists():raise ValueError('new directory required')
        if len(plans)!=len(protocol['search_seeds']):raise ValueError('repeat coverage')
        for plan,seed in zip(plans,protocol['search_seeds']):
            if plan!=sample_indices(protocol['space_size'],protocol['queries_per_repeat'],seed):raise ValueError('plan not seeded uniform sample')
        directory.mkdir();(directory/'queries').mkdir()
        write(directory/'Plans.json',plans);protocol=dict(protocol,plans_sha256=sha(directory/'Plans.json'))
        write(directory/'Protocol.json',protocol)
        write(directory/'checkpoint.json',{'protocol_sha256':sha(directory/'Protocol.json'),'phase':'prepared','queries':[]})
        return cls(directory)

    def validate(self):
        d=self.directory;p=read(d/'Protocol.json');plans=read(d/'Plans.json');state=read(d/'checkpoint.json')
        if sha(d/'Protocol.json')!=state['protocol_sha256'] or sha(d/'Plans.json')!=p['plans_sha256']:raise ValueError('protocol/plan identity mismatch')
        if 'run_clock_sha256' in state:
            if not (d/'Run_clock.json').exists() or sha(d/'Run_clock.json')!=state['run_clock_sha256']:
                raise ValueError('run clock identity mismatch; no time-budget reset')
        if len(plans)!=len(p['search_seeds']):raise ValueError('plan count mismatch')
        for plan in plans:
            if len(plan)!=p['queries_per_repeat'] or len(set(plan))!=len(plan) or any(type(i) is not int or not 0<=i<p['space_size'] for i in plan):
                raise ValueError('plan membership or duplicate')
        flat=[(r,k,t) for r,plan in enumerate(plans) for k,t in enumerate(plan)]
        if len(state['queries'])>len(flat):raise ValueError('logical budget exceeded')
        physical=0
        for row,(repeat,slot,index) in zip(state['queries'],flat):
            if (row['repeat'],row['slot'],row['ticket'])!=(repeat,slot,index):raise ValueError('query order/identity')
            if row['status']!='completed':raise ValueError('unresolved reservation; no automatic repeat')
            if (row['logical_evaluations'],row['logical_passes'])!=(len(p['instances']),2*len(p['instances'])):raise ValueError('logical ledger mismatch')
            if row['origin'] not in ('historical_cache','campaign_cache','new'):raise ValueError('unknown origin')
            expected=len(p['instances']) if row['origin']=='new' else 0
            if row['physical_reserved_evaluations']!=expected or row['physical_reserved_passes']!=expected*2:raise ValueError('physical ledger mismatch')
            physical+=expected;path=d/row['result_path']
            if not path.resolve().is_relative_to(d.resolve()) or sha(path)!=row['result_sha256']:raise ValueError('query result identity')
            validate_result(read(path),p['instances'])
            provenance=path.parent/'provenance.json'
            if sha(provenance)!=row['provenance_sha256']:raise ValueError('provenance identity mismatch')
            for relative,expected_hash in read(provenance).get('evidence_sha256',{}).items():
                evidence=path.parent/relative
                if not evidence.resolve().is_relative_to(path.parent.resolve()) or sha(evidence)!=expected_hash:
                    raise ValueError('process evidence identity mismatch')
        if physical>p['new_evaluation_cap'] or 2*physical>p['new_solve_pass_cap']:raise ValueError('physical budget exceeded')
        if state['phase']=='completed' and len(state['queries'])!=len(flat):raise ValueError('false completed marker')
        return p,plans,state,flat

    def execute(self,evaluator,limit=None,clock=None,wall_deadline=None):
        if (self.directory/'Stop.json').exists():raise ValueError('persistent Stop, no automatic resume')
        try:
            p,plans,state,flat=self.validate()
            if state['phase'] in ('completed','wall_budget_stopped'):return
            completed_this_call=0
            for repeat,slot,index in flat[len(state['queries']):]:
                if limit is not None and completed_this_call>=limit:return
                if wall_deadline is not None and clock()+650>wall_deadline:
                    state['phase']='wall_budget_stopped';write(self.directory/'checkpoint.json',state);return
                number=len(state['queries']);folder=self.directory/'queries'/f'q{number:04d}'
                if folder.exists():raise ValueError('orphan query evidence; no automatic repeat')
                folder.mkdir()
                row={'repeat':repeat,'slot':slot,'ticket':index,'status':'reserved',
                     'logical_evaluations':len(p['instances']),'logical_passes':2*len(p['instances']),
                     'physical_reserved_evaluations':0,'physical_reserved_passes':0}
                state['queries'].append(row);state['phase']='running';write(self.directory/'checkpoint.json',state)
                def reserve_physical():
                    # Called once, before spawning any physical evaluator.
                    if row['physical_reserved_evaluations']:raise ValueError('duplicate physical reservation')
                    row['physical_reserved_evaluations']=len(p['instances']);row['physical_reserved_passes']=2*len(p['instances'])
                    if sum(r['physical_reserved_evaluations'] for r in state['queries'])>p['new_evaluation_cap']:raise ValueError('physical cap')
                    write(self.directory/'checkpoint.json',state)
                result,origin,provenance=evaluator(index,folder,reserve_physical)
                validate_result(result,p['instances'])
                if (row['physical_reserved_evaluations']>0)!=(origin=='new'):raise ValueError('reservation/origin disagreement')
                write(folder/'result.json',result);write(folder/'provenance.json',provenance)
                row.update(status='completed',origin=origin,result_path=str((folder/'result.json').relative_to(self.directory)),
                           result_sha256=sha(folder/'result.json'),provenance_sha256=sha(folder/'provenance.json'))
                write(self.directory/'checkpoint.json',state);completed_this_call+=1
            state['phase']='completed';write(self.directory/'checkpoint.json',state);self.validate()
        except BaseException as exc:
            if not (self.directory/'Stop.json').exists():write(self.directory/'Stop.json',{'type':type(exc).__name__,'error':str(exc),'automatic_retry':False})
            raise
