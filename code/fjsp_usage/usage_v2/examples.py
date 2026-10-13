"""Inspectable program files and complete traces on independent three-action toy."""
from dataclasses import asdict
from pathlib import Path
from fjsp_usage.research.candidates import U_ARGS,H_ARGS,validate_code,compile_candidate
from fjsp_usage.research.events import atomic_json
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance,Operation
from .execution import construct_usage_schedule
from . import VERSION


def write_examples(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    instance=FJSPInstance('HANDWRITTEN-three-action-toy',2,((Operation(((0,2),(1,3))),Operation(((0,5),(1,6)))),(Operation(((0,4),)),)))
    members=[]
    triples=((10,6,0),(0,80,100),(2,0,20))
    for i,(a,b,c) in enumerate(triples):
        source='def priority('+', '.join(H_ARGS)+'):\n    if processing_time == 2:\n        return '+str(a)+'\n    if processing_time == 3:\n        return '+str(b)+'\n    if processing_time == 4:\n        return '+str(c)+'\n    return 1\n'
        h=validate_code(source,kind='h');members.append(h);(directory/f'h{i}.fixture.py').write_text(h.code)
    results=[]
    for name,output in [('fixed-h2','(0,(0,0,1))'),('score-select','(0,(3,2,1))'),('dual-mix','(1,(3,2,0))')]:
        c=validate_code('def use_heuristics('+', '.join(U_ARGS)+'):\n    return '+output+'\n',interface_version=VERSION,member_count=3)
        (directory/f'{name}.fixture.py').write_text(c.code)
        trace=[];cost=[]
        result=construct_usage_schedule(instance,[compile_candidate(h) for h in members],compile_candidate(c),trace=trace.append,cost=cost.append)
        record={'name':name,'candidate':asdict(c),'result':asdict(result),'trace':trace,'cost':cost,
            'notice':'Handwritten independent toy; not model-generated or imported into real population.'}
        atomic_json(directory/f'{name}.json',record);results.append(record)
    choices=[(r['trace'][0]['chosen']['job'],r['trace'][0]['chosen']['machine']) for r in results]
    assert choices==[(1,0),(0,0),(0,1)]
    summary={'notice':'Complete toy schedules only; no benchmark performance evidence.','new_real_requests':0,
        'first_actions':dict(zip(['fixed-h2','score-select','dual-mix'],choices)),
        'dual_first_scores':[a['score'] for a in results[2]['trace'][0]['actions']],
        'complete_feasible_schedules':len(results)}
    atomic_json(directory/'Examples_summary.json',summary);return summary
