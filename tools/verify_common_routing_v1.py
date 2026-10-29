"""Persist Mock 3/20-generation, pause/resume, out-of-order and lineage evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import evolution_v1 as e
from heuristic_design.core.evolution_export import export
from heuristic_design.core.storage import write, read, sha, digest


def semantic(state):
    return {k:state[k] for k in ('population','rng','generations','seen','generation_requests',
        'initialization_requests','initialization_complete','completed_tasks')}


def verify(directory,report):
    directory=Path(directory).resolve();report=Path(report).resolve()
    if directory.exists():raise ValueError('new acceptance run directory required')
    directory.mkdir(parents=True);report.mkdir(parents=True,exist_ok=True)
    facts={'label':'MOCK_OFFLINE_ENGINEERING_ONLY','real_API_calls':0,'cases':{},'assertions':{}}
    cases=[('n5-g3-serial',5,3,1,1,False),('n5-g3-resume',5,3,1,1,False),
           ('n5-g3-reordered',5,3,4,2,True),('n5-g20',5,20,4,4,False),('n10-g20',10,20,4,4,False)]
    states={}
    for name,n,g,api,cpu,reverse in cases:
        dest=directory/name
        c=dict(population_size=n,generations=g,generation_request_cap=2*n*g,
               api_concurrency=api,evaluation_concurrency=cpu,mock_reverse_delay=reverse)
        e.prepare(dest,c)
        started=time.perf_counter()
        if name.endswith('resume'):
            paused=e.run(dest,max_tasks=18)
            assert paused['phase']=='paused'
            write(report/'pause-receipt.json',paused)
        outcome=e.run(dest)
        elapsed=time.perf_counter()-started
        p,s=e.check(dest);states[name]=s
        summary=export(dest,report/name)
        # Plans contain exact original parent records and RNG before/after.
        for source in (dest/'plans').glob('*.json'):
            target=report/name/'plans'/source.name;target.parent.mkdir(exist_ok=True)
            shutil.copyfile(source,target)
        write(report/name/'P0.json',read(dest/'populations/P000.json'))
        write(report/name/'final-population.json',s['population'])
        facts['cases'][name]={**outcome,'wall_seconds':elapsed,'source_files_sha256':digest(p['source_files']),
                             'protocol_sha256':sha(dest/'Protocol.json'),'run_path':str(dest),
                             'planned_evolution_candidates':summary['planned_evolution_candidates']}
    a,b,c=(states[k] for k in ('n5-g3-serial','n5-g3-resume','n5-g3-reordered'))
    facts['assertions']['pause_resume_semantics_equal']=semantic(a)==semantic(b)
    facts['assertions']['out_of_order_semantics_equal']=semantic(a)==semantic(c)
    facts['assertions']['generation_2_children_enter_generation_3_parents']=any(
        r['id'].startswith('G002') for r in read(directory/'n5-g3-serial/plans/G003.json')['population'])
    receipts=[read(x) for x in (directory/'n5-g3-reordered/batch-receipts').glob('*.json')]
    facts['assertions']['response_order_actually_different']=any(x['response_completion_order']!=x['semantics_commit_order'] for x in receipts)
    write(report/'reordered-batch-receipts.json',receipts)
    facts['assertions']['20_generations_n5_n10_complete']=all(states[k]['generation']==20 for k in ('n5-g20','n10-g20'))
    assert all(facts['assertions'].values()),facts['assertions']
    write(report/'acceptance.json',facts)
    print(json.dumps(facts,ensure_ascii=False,indent=2))
    return facts


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-root',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();verify(args.run_root,args.report)
