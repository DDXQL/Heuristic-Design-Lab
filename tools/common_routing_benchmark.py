"""Fixed handwritten policies, real synthetic solve/recheck at CPU widths 1/2/4."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import evolution_v1 as e, routing
from heuristic_design.core.routing_evaluation import evaluate_task
from heuristic_design.core.storage import write, digest
from heuristic_design.problems import routing_fixtures as fixtures


def command(args):
    r=subprocess.run(args,text=True,capture_output=True)
    return {'returncode':r.returncode,'stdout':r.stdout.strip(),'stderr':r.stderr.strip()}


def memory_snapshot():
    return {'vm_stat':command(['/usr/bin/vm_stat']),
            'swap':command(['/usr/sbin/sysctl','vm.swapusage'])}


def hardware():
    import platform
    r=command(['/usr/sbin/system_profiler','SPHardwareDataType','-json'])
    allowed=('machine_name','machine_model','chip_type','physical_memory','number_processors')
    rows=[]
    if r['returncode']==0:
        rows=[{k:v for k,v in row.items() if k in allowed} for row in json.loads(r['stdout']).get('SPHardwareDataType',[])]
    return {'hardware':rows,'os':platform.platform(),'python':platform.python_version(),
            'logical_cpus':os.cpu_count(),'process_inventory':'ps unavailable under sandbox; not certified idle',
            'BLAS_threads':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','VECLIB_MAXIMUM_THREADS')},
            'note':'system_profiler output filtered; identifiers excluded'}


def benchmark(directory,*,size_fjsp=90,size_tsp=70,candidates=4,count=2):
    directory=Path(directory).resolve()
    if directory.exists():raise ValueError('new benchmark output required')
    directory.mkdir(parents=True)
    meta=hardware()
    inputs={p:{'members':fixtures.members(p),'instances':fixtures.instances(p,size=size_fjsp if p=='fjsp' else size_tsp,count=count,seed=61029)} for p in ('fjsp','tsp')}
    tasks=[]
    for problem in ('fjsp','tsp'):
        for i in range(candidates):
            code=(f'def use_heuristics(state):\n'
                  f'    return {i%3} if state["construction_progress"] < {(i+1)/(candidates+1)!r} else {(i+1)%3}\n')
            tasks.append({'id':f'{problem}-handwritten-{i}','problem':problem,
                          'candidate':asdict(routing.validate(code,'Fixed handwritten benchmark; not generated',3))})
    write(directory/'fixed-inputs.json',{'data':inputs,'tasks':tasks,'hardware':meta,
                                         'H_order_source':'handwritten declaration, no quality-rank sort'})
    expected=None;rows=[]
    for width in (1,2,4):
        dest=directory/f'workers-{width}'
        dest.mkdir()
        protocols={p:{**inputs[p],'config':e.config({'problem':p,'evaluation_mode':'solve','evaluation_concurrency':width}),
                      'source_files':e.source_identity(),'run_directory':str(dest)} for p in inputs}
        before=memory_snapshot()
        start=time.perf_counter()
        # Threads supervise independent spawned CPU workers. There is no nested
        # instance pool and no network generation in this benchmark.
        with ThreadPoolExecutor(max_workers=width) as pool:
            futures=[pool.submit(evaluate_task,task,protocols[task['problem']]) for task in tasks]
            results=[f.result() for f in futures]
        elapsed=time.perf_counter()-start
        after=memory_snapshot()
        semantics=[{'id':t['id'],'valid':r['valid'],'fitness':r['fitness'],
                    'rows':[{k:x[k] for k in ('file','score','semantic_sha256','recheck_semantic_sha256','h_calls')} for x in r['instances']]} for t,r in zip(tasks,results)]
        if expected is None:expected=semantics
        same=semantics==expected
        if not same:raise AssertionError('serial/parallel result difference; preserve evidence')
        physical_solves=sum(sum(x['captured_solves'] for x in r['instances']) for r in results if r['valid'])
        solve_seconds=sum(sum(x['solve_seconds']+x['recheck_solve_seconds'] for x in r['instances']) for r in results)
        sensor_seconds=sum(sum(x['observation_seconds']+x['recheck_observation_seconds'] for x in r['instances']) for r in results)
        peak=max((x['worker_peak_rss_bytes'] for r in results for x in r['instances']),default=0)
        row={'evaluation_concurrency':width,'candidate_evaluations':len(tasks),'physical_solves':physical_solves,
             'wall_seconds':elapsed,'candidate_throughput_per_second':len(tasks)/elapsed,
             'physical_solve_throughput_per_second':physical_solves/elapsed,'api_wait_seconds':0,
             'summed_worker_solve_seconds':solve_seconds,'summed_observation_seconds':sensor_seconds,
             'observation_share_of_worker_solve':sensor_seconds/solve_seconds if solve_seconds else None,
             'max_worker_peak_rss_bytes':peak,'worker_memory_envelope_bytes':width*peak,
             'memory_note':'per-worker measured peak; width*peak is an envelope, not measured aggregate peak',
             'memory_before':before,'memory_after':after,'timeouts':sum(not r['valid'] and r.get('failure',{}).get('error_type')=='Timeout' for r in results),
             'invalid_candidates':sum(not r['valid'] for r in results),'same_semantics_as_serial':same,
             'result_semantics_sha256':digest(semantics),'per_problem':{}}
        for problem in inputs:
            group=[r for t,r in zip(tasks,results) if t['problem']==problem]
            row['per_problem'][problem]={'evaluation_seconds_sum':sum(r['evaluation_seconds'] for r in group),
                'fitness':[r['fitness'] for r in group],'valid':all(r['valid'] for r in group)}
        rows.append(row)
        write(directory/f'width-{width}.json',{'summary':row,'semantic_results':semantics})
        print(json.dumps({k:row[k] for k in ('evaluation_concurrency','wall_seconds','physical_solves','timeouts','same_semantics_as_serial')}),flush=True)
    fastest=min(rows,key=lambda r:r['wall_seconds'])
    for row in rows:row['speedup_vs_serial']=rows[0]['wall_seconds']/row['wall_seconds']
    result={'type':'REAL_SYNTHETIC_FIXED_WORKLOAD_NOT_SEARCH','real_API_calls':0,'hardware':meta,
            'rows':rows,'fastest_measured_width':fastest['evaluation_concurrency'],
            'workload':{'candidate_evaluations_per_width':len(tasks),'instance_count_per_problem':count,
                        'size_fjsp':size_fjsp,'size_tsp':size_tsp,'input_identity':digest({'inputs':inputs,'tasks':tasks})},
            'limitation':'one fixed workload and one width order; startup/system contention included, not confidence intervals or quality evidence'}
    write(directory/'benchmark.json',result)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--fjsp-size',type=int,default=90);p.add_argument('--tsp-size',type=int,default=70)
    args=p.parse_args();benchmark(args.output,size_fjsp=args.fjsp_size,size_tsp=args.tsp_size)
