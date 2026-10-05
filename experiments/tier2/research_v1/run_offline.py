#!/usr/bin/env python3
"""Offline-only end-to-end mock exercise; never opens validation/test data."""

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'code'))
sys.path.insert(0, str(ROOT))

from experiments.tier2.offline_v2.run_training_demo import DEMO_H, state_u
from fjsp_usage.training_v2 import TrainingEvaluation
from fjsp_usage.research.candidates import H_ARGS, validate_code
from fjsp_usage.research.events import atomic_json, Events
from fjsp_usage.research.evolution import Search
from fjsp_usage.research.protocol import SearchConfig, build_protocol, digest, source_hashes
from fjsp_usage.research.requests import MockTransport
from fjsp_usage.research.runtime import evaluate
from fjsp_usage.research.scheduler import construct_usage_schedule
from fjsp_usage.research.sets import export_mock_set
from fjsp_usage.research.viewer import write_replay
from llm4ad.task.optimization.fjsp_set import load_instance


def demo_members():
    return tuple(validate_code('def priority(' + ', '.join(H_ARGS) + '):\n    return ' + expression,
                               kind='h', description=description)
                 for expression, description in (
                     ('-earliest_finish', 'EFT: return negative raw earliest finish.'),
                     ('-processing_time', 'SPT: return negative raw processing duration.')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('tiny', 'train'), default='tiny')
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--generations', type=int, default=2)
    parser.add_argument('--population', type=int, default=5)
    parser.add_argument('--attempts', type=int, default=10)
    parser.add_argument('--seed', type=int, default=20261005)
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if directory.exists() and any(directory.iterdir()) and not args.resume:
        parser.error('nonempty run directory: use --resume or a new directory')
    if directory == ROOT or not directory.is_relative_to(ROOT / 'runs'):
        parser.error('run directory must be inside this project runs/ (ignored by Git)')
    config = SearchConfig(population_size=args.population, cross_parents=args.population,
                          attempts_per_generation=args.attempts, generations=args.generations,
                          initialization_cap=5 * args.population, seed=args.seed)
    started = time.monotonic()
    tiny_path = ROOT / 'experiments/tier2/offline_v1/tiny.fjsp'
    tiny = load_instance(tiny_path)
    if args.suite == 'train':
        training = TrainingEvaluation(ROOT / 'data/fjsp_manifest.json', project_root=ROOT)
        instances, names = training.instances, training.training_files
        training_hashes = training.training_hashes
        manifest_key = training.manifest_sha256
    else:
        instances, names = (tiny,), ('synthetic-tiny',)
        training_hashes = {names[0]: hashlib.sha256(tiny_path.read_bytes()).hexdigest()}
        manifest_key = None
    members = demo_members()
    protocol = build_protocol(config, training_files=names, training_hashes=training_hashes,
                              data_manifest_sha256=manifest_key, members=members)
    protocol['suite'] = args.suite
    protocol['source_sha256'] = source_hashes(ROOT)
    protocol_key = digest(protocol)
    protocol_path = directory / 'protocol.json'
    if protocol_path.exists() and digest(json.loads(protocol_path.read_text())) != protocol_key:
        parser.error('resume source/data/protocol mismatch')
    atomic_json(protocol_path, protocol)
    events = Events(directory / 'events.jsonl')
    events.emit('run', status='resume' if args.resume else 'start', suite=args.suite,
                instance_count=len(instances), mode='MOCK; no LLM calls')
    # Only three tiny steps are traced by default, never every training action.
    trace = []
    replay_result = construct_usage_schedule(tiny, DEMO_H, state_u, trace=trace.append)
    atomic_json(directory / 'tiny_trace.json', {'trace': trace, 'result': asdict(replay_result)})
    write_replay(directory / 'replay.html', trace=trace, makespan=replay_result.schedule.makespan,
                 score=replay_result.score, instance=tiny.name)
    for record in trace:
        events.emit('tiny_step', **record)
    print(f'MOCK: {len(instances)} 个训练/合成实例；已保存微型排程回放', flush=True)

    transport = MockTransport()
    def evaluate_u(candidate):
        return evaluate(candidate, members, instances, names, timeout=config.instance_timeout)

    shared = Search(directory / 'shared_initial', arm='INIT', config=config,
                    members=members, evaluator=evaluate_u, transport=transport, context=protocol_key)
    if not shared.initialize():
        raise SystemExit('shared initialization failed: see checkpoint and events')
    initial = shared.state['population']
    atomic_json(directory / 'shared_initial_population.json', initial)
    reports = {}
    for arm in ('B0', 'B1', 'B2', 'P'):
        search = Search(directory / arm, arm=arm, config=config, members=members,
                        evaluator=evaluate_u, transport=transport, context=protocol_key, initial=initial)
        reports[arm] = search.run()
        events.emit('arm_completed', arm=arm, generations=reports[arm]['generation'],
                    reserved_requests=reports[arm]['evolution_requests'])
        print(f'{arm}: {reports[arm]["generation"]} 代完成，'
              f'{reports[arm]["evolution_requests"]} 次模拟请求', flush=True)

    # Separate H adapter exercise, never substituted into the four-arm demo H.
    h_config = replace(config, population_size=2, cross_parents=2, initialization_cap=10)
    h_search = Search(directory / 'H_adapter', arm='H', config=h_config, members=(),
                      evaluator=lambda c: evaluate(c, (), instances, names, timeout=config.instance_timeout),
                      transport=transport, context=protocol_key, kind='h')
    h_report = h_search.run()
    audit = json.loads((ROOT / 'experiments/tier2/research_v1/source_audit.json').read_text())
    if h_report['phase'] == 'completed':
        export_mock_set(directory / 'mock_H.json', h_report['population'], size=2,
                        training_files=names, audit_sha256=digest(audit))
    report = {'status': 'OFFLINE MOCK infrastructure exercise; not research results',
              'protocol_sha256': protocol_key, 'llm_called': False,
              'validation_evaluated': False, 'test_evaluated': False,
              'H_status': protocol['H_status'], 'suite': args.suite,
              'train_instance_count': len(instances), 'shared_initial': shared.report(),
              'groups': reports, 'H_adapter': h_report,
              'mock_request_slots': shared.initial_requests.calls
                  + sum(r['evolution_requests'] for r in reports.values())
                  + h_report['initialization_requests'] + h_report['evolution_requests'],
              'real_input_tokens': None, 'real_output_tokens': None,
              'invocation_elapsed_seconds': time.monotonic() - started}
    atomic_json(directory / 'report.json', report)
    events.emit('run_completed', mock_request_slots=report['mock_request_slots'])
    print(f'完成：{directory / "report.json"}', flush=True)
    if any(r['phase'] != 'completed' for r in reports.values()) or h_report['phase'] != 'completed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
