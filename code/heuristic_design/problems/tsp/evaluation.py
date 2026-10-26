"""T30 child execution, complete score vector and exact solve/recheck traces."""
from dataclasses import asdict
import multiprocessing as mp
import os
from pathlib import Path
import socket
from statistics import fmean
import time
from heuristic_design.core.storage import write,read,sha,digest
from heuristic_design.core.results import validate_complete
from heuristic_design.core.lifecycle import collect
from .candidates import checked,compile_candidate
from .solver import distances,construct,tour_length


def worker(pipe,payload,members,instances,names,allowed_modes):
    os.environ.pop('LEAFAPI_API_KEY',None)
    def denied(*args,**kwargs):raise PermissionError('candidate worker networking forbidden')
    socket.socket.connect=denied;socket.create_connection=denied
    folder=Path(payload['folder']);source_files=payload['source_files']
    try:
        actual={name:sha(payload['root']/Path(name)) for name in source_files}
        write(folder/'before.json',{'files':actual,'pid':os.getpid()})
        if actual!=source_files:raise RuntimeError('worker source changed')
        c=checked(payload['candidate'],max(1,len(members)))
        if c.kind=='h':hs=[compile_candidate(c,1)];u=lambda *args:(0,(1,))
        else:hs=[compile_candidate(checked(m,len(members)),len(members)) for m in members];u=compile_candidate(c,len(members))
        for spec,name in zip(instances,names):
            d=distances(read(spec['source'])['coordinates']);started=time.perf_counter()
            first=construct(d,hs,u);first_s=time.perf_counter()-started;started=time.perf_counter()
            second=construct(d,hs,u);second_s=time.perf_counter()-started
            if first!=second:raise ValueError('full solve/recheck mismatch')
            trace_sha=digest(first.trace);nn=spec['NN_length'];length=tour_length(d,first.tour)
            row={'file':name,'length':length,'NN_length':nn,'ratio':length/nn,'score':-length/nn,'tour':list(first.tour),
                'tour_sha256':digest(first.tour),'trace_sha256':trace_sha,'recheck_tour_sha256':digest(second.tour),
                'recheck_trace_sha256':digest(second.trace),'single_h_calls':first.h_calls,'recheck_h_calls':second.h_calls,
                'single_solve_seconds':first_s,'deterministic_recheck_seconds':second_s,'captured_solves':2,'feasible':True,
                'SELECT_steps':sum(r['mode']==0 for r in first.trace),'MIX_steps':sum(r['mode']==1 for r in first.trace),
                'dual_steps':sum(len(r['support'])==2 for r in first.trace),
                'weight_changes':sum(a['weights']!=b['weights'] for a,b in zip(first.trace,first.trace[1:])),
                'supports':sorted({str(r['support']) for r in first.trace})}
            write(folder/(Path(name).stem+'.json'),row);pipe.send(row)
        actual={name:sha(payload['root']/Path(name)) for name in source_files}
        write(folder/'after.json',{'files':actual,'pid':os.getpid()})
    except BaseException as exc:
        write(folder/'Failure.json',{'error_type':type(exc).__name__,'error':str(exc)[:500]})
        pipe.send({'error_type':type(exc).__name__,'error':str(exc)[:500]})
    finally:pipe.close()


def validate_result(result,instances):
    validate_complete(result,instances)
    for r,e in zip(result['instances'],instances):
        if (r['NN_length']!=e['NN_length'] or r['score']!=-r['length']/e['NN_length'] or r['ratio']!=r['length']/e['NN_length'] or r['length']<=0 or not r['feasible'] or r['captured_solves']!=2 or r['tour_sha256']!=digest(r['tour']) or r['tour_sha256']!=r['recheck_tour_sha256'] or r['trace_sha256']!=r['recheck_trace_sha256'] or list(r['single_h_calls'])!=list(r['recheck_h_calls'])):raise ValueError('TSP row/recheck identity invalid')


def evaluate(directory,state,protocol,candidate):
    key=candidate.key
    if key in state['evaluations']:return read(directory/state['evaluations'][key]['path']),True
    folder=directory/'evaluations'/key;folder.mkdir(parents=True,exist_ok=False)
    state['evaluations'][key]={'status':'reserved'};write(directory/'checkpoint.json',state)
    members=read(directory/'Members.json');rowspec=protocol['instances']
    files=protocol['source_files'];beg=time.monotonic()
    write(folder/'Input_receipt.json',{'candidate':asdict(candidate),'source_files':files,'instances':rowspec,'protocol':state['identity']})
    rows,failure,life=collect(mp.get_context('spawn'),worker,{'candidate':asdict(candidate),'folder':str(folder),'source_files':files,'root':directory.parents[1]},
        members,rowspec,[r['file'] for r in rowspec],30,(0,1),lambda r:write(folder/'lifecycle.json',r))
    result={'valid':failure is None,'fitness':fmean(r['score'] for r in rows) if failure is None else None,'instances':rows,
        'total_instances':len(rowspec),'primary_evaluation_seconds':time.monotonic()-beg,**(failure or {})}
    if life['alive'] or not life['receiver_thread_stopped']:raise RuntimeError('unknown worker termination')
    if result['valid']:
        for name in ('before','after'):
            identity=read(folder/(name+'.json'))
            if identity!={'files':files,'pid':life['pid']}:raise RuntimeError('worker source identity mismatch')
        if life['exitcode']!=0 or life['cleanup']!=['join_exit_grace_2.0']:raise RuntimeError('normal exit not certified')
    for name,value in files.items():
        if sha(directory.parents[1]/name)!=value:raise RuntimeError('source changed during evaluation')
    validate_result(result,rowspec);write(folder/'result.json',result)
    state['evaluations'][key]={'status':'completed','path':str((folder/'result.json').relative_to(directory)),'sha256':sha(folder/'result.json')}
    write(directory/'checkpoint.json',state);return result,False
