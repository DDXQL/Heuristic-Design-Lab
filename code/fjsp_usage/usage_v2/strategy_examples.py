"""Handwritten strategies and independent toys, with no search or model client.

These examples demonstrate expressibility and executor behavior, not generation
probability or research performance. Candidate sources use only the existing
terminal-tuple language, for any fixed K >= 3.
"""
from dataclasses import asdict
from pathlib import Path

from fjsp_usage.research.candidates import U_ARGS, H_ARGS, validate_code, compile_candidate
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation
from . import VERSION
from .execution import construct_usage_schedule, usage_summary


NOTICE = 'Handwritten engineering examples; no LLM generation, real population or benchmark performance evidence.'


def strategy_candidates(size=3):
    if type(size) is not int or size < 3:
        raise ValueError('examples require fixed K >= 3')

    def vector(first, fill='0'):
        return '(' + ', '.join((*first, *((fill,) * (size - 3)))) + ')'

    bodies = {
        'constant-select': 'return (0, ' + vector(('0', '0', '1')) + ')',
        'score-select': '''dispersion = remaining_work_std / (1.0 + remaining_work_mean)
q0 = 1.0 - progress
q1 = progress + 2.0 * dispersion * dispersion
if previous_heuristic == 1:
    q1 = q1 + 0.05
return (0, ''' + vector(('q0', 'q1', '-2'), '-2') + ')',
        'fixed-dual': 'return (1, ' + vector(('3', '2', '0')) + ')',
        'state-weights': '''r0 = 3.0 - 2.0 * progress
r1 = 2.0 + 2.0 * progress
return (1, ''' + vector(('r0', 'r1', '0')) + ')',
        'state-support-mode': '''if previous_heuristic == -1:
    return (0, ''' + vector(('0', '0', '1')) + ''')
spread = machine_ready_std / (1.0 + machine_ready_mean)
if progress < 0.5:
    return (1, ''' + vector(('1.0 + spread', '1.0 - spread', '0')) + ''')
return (1, ''' + vector(('0', '1.0 + spread', '1.0 - spread')) + ')',
    }
    signature = 'def use_heuristics(' + ', '.join(U_ARGS) + '):\n'
    return {name: validate_code(signature + '    ' + body.replace('\n', '\n    ') + '\n',
            description=NOTICE, interface_version=VERSION, member_count=size)
            for name, body in bodies.items()}


def toy_instance():
    return FJSPInstance('HANDWRITTEN-strategy-space-three-actions', 2, (
        (Operation(((0, 2), (1, 3))), Operation(((0, 5), (1, 6)))),
        (Operation(((0, 4),)),),
    ))


def toy_members():
    # First-step score matrix: A=(10,0,2), B=(6,80,0), C=(0,100,20).
    columns = ((10, 6, 0), (0, 80, 100), (2, 0, 20))
    signature = 'def priority(' + ', '.join(H_ARGS) + '):\n'
    return tuple(validate_code(signature + ''.join(
            '    if processing_time == ' + str(p) + ':\n        return ' + str(score) + '\n'
            for p, score in zip((2, 3, 4), column)) + '    return 1\n',
            kind='h', description=NOTICE) for column in columns)


def write_strategy_examples(directory):
    """Create new local evidence only; never overwrite or use an experiment run."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    instance = toy_instance()
    members = toy_members()
    for i, member in enumerate(members):
        (directory / f'h{i}.fixture.py').write_text(member.code)
    # K10 exports prove tuple shape only; schedules below use K3 toy H.
    (directory / 'K10').mkdir()
    for name, candidate in strategy_candidates(10).items():
        (directory / 'K10' / f'{name}.py').write_text(candidate.code)
    summaries = []
    for name, candidate in strategy_candidates().items():
        (directory / f'{name}.py').write_text(candidate.code)
        trace = []
        result = construct_usage_schedule(instance, [compile_candidate(h) for h in members],
            compile_candidate(candidate), trace=trace.append)
        repeated = construct_usage_schedule(instance, [compile_candidate(h) for h in members],
            compile_candidate(candidate))
        if repeated != result:
            raise AssertionError('offline example changed on deterministic recheck')
        record = {'notice': NOTICE, 'candidate': asdict(candidate), 'result': asdict(result),
            'trace': trace, 'usage': usage_summary(result, len(members)), 'deterministic_recheck': True}
        atomic_json(directory / f'{name}.json', record)
        summaries.append({'name': name, 'makespan': result.schedule.makespan,
            'first_action': trace[0]['chosen'], 'supports': [list(d[2]) for d in result.decisions],
            'weights': [list(d[3]) for d in result.decisions], 'modes': [d[0] for d in result.decisions],
            'h_calls': list(result.member_calls), 'semantic_sha256': digest(asdict(result))})
    summary = {'notice': NOTICE, 'interface': VERSION, 'schedule_member_count': 3,
        'extra_K10_sources': 'syntax/interface examples only; not evaluated on research H',
        'complete_feasible_schedules': len(summaries), 'deterministic_rechecks': len(summaries),
        'model_requests': 0, 'benchmark_files_opened': [], 'examples': summaries}
    atomic_json(directory / 'Summary.json', summary)
    return summary
