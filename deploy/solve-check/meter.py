"""Observe each native solve invocation in its child; never adds a solve."""
import hashlib
import json
import os
from pathlib import Path
import resource
import sys
import time


def peak_rss():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform=='darwin' else value*1024)


def install(directory):
    from heuristic_design.problems import routing_fixtures
    original=routing_fixtures.solve
    root=Path(directory);protocol=json.loads((root/'Protocol.json').read_text())
    by_key={v['candidate']['key']:v['id'] for v in protocol['U']}
    expected=[v['file'] for v in protocol['instances'] for _ in range(2)]
    count=0;mode=os.environ['HDL_SOLVE_CHECK_MODE']
    def emit(row):
        path=root/'physical-solves'/('pid-'+str(os.getpid())+'.jsonl')
        with path.open('a') as f:f.write(json.dumps(row,allow_nan=False)+'\n');f.flush();os.fsync(f.fileno())
    def observed(problem,instance,members,candidate,**kwargs):
        nonlocal count
        uid=by_key[candidate['key']];reservation=mode+'/'+uid
        state=json.loads((root/'checkpoint.json').read_text())
        if (count>=len(expected) or instance['file']!=expected[count]
                or state['identity']!=hashlib.sha256((root/'Protocol.json').read_bytes()).hexdigest()
                or state['reserved_solves']>16 or state['reservations'][reservation]['status']!='reserved'):
            raise RuntimeError('undeclared native solve; stopped before invocation')
        count+=1;clock=time.monotonic();cpu=time.process_time()
        common={'pid':os.getpid(),'mode':mode,'U':uid,'instance':instance['file'],
                'pass':1 if count%2 else 2,'sequence':count}
        emit({**common,'event':'started','monotonic':clock,'wall':time.time()})
        try:
            result=original(problem,instance,members,candidate,**kwargs)
            emit({**common,'event':'completed','monotonic':time.monotonic(),'wall':time.time(),
                  'CPU_seconds':time.process_time()-cpu,'wall_seconds':time.monotonic()-clock,
                  'peak_rss_bytes':peak_rss(),'raw_cost':result['raw_cost'],'reference':result['reference']})
            return result
        except BaseException as error:
            emit({**common,'event':'failed','monotonic':time.monotonic(),'wall':time.time(),
                  'CPU_seconds':time.process_time()-cpu,'peak_rss_bytes':peak_rss(),'error_type':type(error).__name__})
            raise
    routing_fixtures.solve=observed
