"""Bounded engineering regression; never generates candidates or reads holdouts.

FJSP: existing frozen H0/equal, toy and already-certified Behnke1 only.
TSP: four synthetic coordinates, two fixed policies. Refuses output overwrite.
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'code')]
from dataclasses import asdict
import argparse
import json
import subprocess
from tools import experiment_ops as o

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True)
    args = parser.parse_args()
    report = Path(args.report_dir).resolve()
    target = report / 'Regression.json'
    if target.exists():
        raise ValueError('never overwrite regression evidence')
    reference = o.read(ROOT / 'reports/generic-extraction-20261026-v1/after.json')
    config = o.read(ROOT / 'experiments/fjsp/configs/fixed-toy.json')
    config['question'] = 'Directory-only engineering parity: toy and certified Behnke1'
    config['dataset']['files'].append('data/fjsp/Behnke1.fjsp')
    config_path = report / 'fjsp.config.json'
    o.write(config_path, config)
    detail = o.describe(config_path)
    from heuristic_design.problems.fjsp.solver import construct_usage_schedule
    from fjsp_usage.usage_v2.execution import construct_usage_schedule as legacy
    assert construct_usage_schedule is legacy
    members = tuple(o.certified.compile_candidate(o.checked_candidate(m['candidate'], 'h'))
                    for m in detail['H']['members'])
    semantic = {}
    for task in detail['tasks']:
        usage = o.certified.compile_candidate(o.checked_candidate(task['candidate'], 'U'))
        for row in detail['instances']:
            instance = o.certified.s.v2.load_instance(row['source'])
            passes = []
            for _ in range(2):
                trace = []
                result = construct_usage_schedule(instance, members, usage,
                                                 trace=trace.append, max_actions=10000)
                passes.append({'result': asdict(result), 'trace': trace})
            assert passes[0] == passes[1]
            semantic[task['id'] + '/' + row['file']] = passes
    semantic = json.loads(json.dumps(semantic))
    assert semantic == reference['semantic'], 'state/action/score/schedule trace changed'
    run = ROOT / 'runs/multi-problem-layout-regression-20261027-v1'
    if run.exists():
        raise ValueError('engineering run already exists; no automatic replay')
    o.prepare(config_path, run)
    subprocess.run([sys.executable, '-B', str(ROOT/'experiments/fjsp/manage.py'),
                    'run', '--run-dir', str(run)], check=True, stdout=subprocess.DEVNULL)
    state = o.read(run/'checkpoint.json')
    assert state['phase'] == 'completed'
    certified = {}
    for tid, task in state['tasks'].items():
        result = o.read(run/state['evaluations'][task['evaluation_key']]['path'])
        assert result['valid']
        certified[tid] = {'fitness': result['fitness'], 'rows': [
            {k: row[k] for k in ('file', 'makespan', 'lower_bound', 'score',
                                'physical_schedule_sha256', 'recheck_physical_schedule_sha256',
                                'commit_sequence_sha256', 'single_h_calls', 'recheck_h_calls')}
            for row in result['instances']]}
    assert certified == reference['certified'], 'certified results changed'
    from heuristic_design.problems.tsp.solver import construct, distances
    matrix = distances([[0, 0], [1, 0], [.7, .8], [0, 1]])
    h = [lambda dc, ds, mean, nearest, p: -dc,
         lambda dc, ds, mean, nearest, p: ds-dc]
    tsp = {}
    for name, u in [('select', lambda *s: (0, (1, 0))),
                    ('ws', lambda *s: (1, (.4, .6)))]:
        a, b = asdict(construct(matrix, h, u)), asdict(construct(matrix, h, u))
        assert a == b
        tsp[name] = [a, b]
    assert json.loads(json.dumps(tsp)) == o.read(report/'TSP迁入前toy轨迹.json')
    o.write(report/'fjsp.semantic.json', semantic)
    o.write(report/'tsp.semantic.json', tsp)
    o.write(target, {'passed': True, 'FJSP_pairs': 4, 'FJSP_trace_passes': 8,
                    'FJSP_certified_passes': 8, 'TSP_toy_passes': 4,
                    'API_calls': 0, 'formal_searches': 0,
                    'compared': ['all U inputs', 'all legal actions and scores',
                                 'chosen actions', 'complete schedules/tours',
                                 'Fitness', 'primary/recheck fingerprints and H calls'],
                    'certified': certified, 'run': str(run)})
    print('PASS: FJSP legacy traces and certified results; TSP source toy parity; API=0')

if __name__ == '__main__':
    main()
