"""Export real synthetic solve traces, numeric source examples and sensor costs."""
import argparse
from dataclasses import asdict
from pathlib import Path
import sys
import time
from statistics import fmean

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'code'), str(ROOT)]
from heuristic_design.core.storage import write, digest
from heuristic_design.core.constructive_state import NUMERIC_FIELDS, SPEC, SPEC_SHA256
from heuristic_design.problems import routing_fixtures as fixtures


def export(directory):
    import numpy as np
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report = {'data_scope': 'synthetic-development only', 'real_API_calls': 0, 'spec': SPEC,
              'spec_sha256': SPEC_SHA256, 'problems': {}}
    for problem in ('fjsp','tsp'):
        hs = fixtures.members(problem)
        data = fixtures.instances(problem,size=12,count=2)
        policy = fixtures.sample_policy(len(hs))
        rows = [fixtures.solve(problem,x,hs,policy) for x in data]
        checks = [fixtures.solve(problem,x,hs,policy) for x in data]
        for a,b in zip(rows,checks):
            assert (a['solution'],a['trace'],a['h_calls'],a['score']) == (b['solution'],b['trace'],b['h_calls'],b['score'])
        write(directory/(problem+'-traces.json'), {'H':hs,'H_order_source':'handwritten declaration order, not performance sorted',
              'U':policy,'instances':data,'results':rows,'recheck_semantics_sha256':digest([r['trace'] for r in checks])})
        states = [r['state'] for row in rows for r in row['trace']]
        constants, stats, correlations = [], {}, []
        for field in NUMERIC_FIELDS:
            values = [s[field] for s in states if s['availability'][field]]
            constant = len(set(values)) <= 1
            if constant: constants.append(field)
            stats[field] = {'available':len(values),'missing':len(states)-len(values),
                            'min':min(values) if values else None,'max':max(values) if values else None,
                            'mean':fmean(values) if values else None,'constant_on_these_traces':constant}
        for i,a in enumerate(NUMERIC_FIELDS):
            for b in NUMERIC_FIELDS[i+1:]:
                pairs = [(s[a],s[b]) for s in states if s['availability'][a] and s['availability'][b]]
                if len(pairs) >= 3 and len({x for x,y in pairs}) > 1 and len({y for x,y in pairs}) > 1:
                    correlations.append({'a':a,'b':b,'n':len(pairs),'pearson':float(np.corrcoef(np.array(pairs).T)[0,1])})
        # Real measured repeated complete solves. Overhead is extraction time within
        # the new constructor, not an unsupported causal claim about old/new speed.
        elapsed, sensor, steps = 0., 0., 0
        for _ in range(10):
            for inst in data:
                r = fixtures.solve(problem,inst,hs,policy)
                elapsed += r['solve_seconds'];sensor += r['observation_seconds'];steps += len(r['trace'])
        report['problems'][problem] = {'states':len(states),'fields':stats,'constant_fields':constants,
            'pairwise_correlations':correlations,'measured_solves':20,'measured_steps':steps,
            'total_solve_seconds':elapsed,'observation_seconds':sensor,
            'observation_fraction':sensor/elapsed,'observation_us_per_step':1e6*sensor/steps,
            'first_state':states[0], 'limitation':'small synthetic fixtures, not feature usefulness or quality evidence'}
    write(directory/'state-diagnostics.json',report)
    return {'path':str(directory),'problems':{p:{k:v[k] for k in ('states','observation_us_per_step','observation_fraction','constant_fields')} for p,v in report['problems'].items()}}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    print(export(p.parse_args().output))
