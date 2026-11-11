"""Strictly offline state/ABI checks; no solve, evaluation, model or subprocess."""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'code'), str(ROOT / 'tests'), str(ROOT)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', required=True,
                        help='required: arithmetic snapshots and static source/ABI only')
    parser.add_argument('--report', type=Path, help='optional new report file; never overwritten')
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error('report must be a new file')

    def guard(event, values):
        if event.startswith(('socket.', 'subprocess.', 'urllib.', 'http.client.')) or event in ('os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty'):
            raise PermissionError('check-only denies network and subprocess: ' + event)
    sys.addaudithook(guard)

    # Numpy can attempt a CPU probe on import; deny network/processes even then.
    import test_state_a_offline
    from heuristic_design.core import state_a, routing_state_a
    forbidden = []
    def profile(frame, event, arg):
        if event != 'call':
            return
        module = frame.f_globals.get('__name__', '')
        name = frame.f_code.co_name
        if ((module.startswith('heuristic_design.problems.') and name in ('construct', 'construct_state_a', 'solve', 'step', 'nearest_neighbor', 'tour_length'))
                or module.startswith(('heuristic_design.llm.', 'heuristic_design.core.routing_evaluation', 'heuristic_design.core.evolution_v1'))):
            forbidden.append(module + '.' + name)
            raise PermissionError('check-only forbids solver/model/evaluation entry: ' + forbidden[-1])
    sys.setprofile(profile)
    output = io.StringIO()
    try:
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_state_a_offline)
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    finally:
        sys.setprofile(None)

    paths = [p for folder in ('code/heuristic_design',) for p in (ROOT / folder).rglob('*.py')]
    paths += [ROOT / 'tools/check_state_a.py', ROOT / 'tests/test_state_a_offline.py']
    for path in paths:
        ast.parse(path.read_text(), filename=str(path))
    rule_paths = ('AGENTS.md', 'docs/中文科研写作规范.md', '.agents/skills/humanizer-zh/SKILL.md',
                  '/Users/DDXQL/.codex/skills/ahd-experiment-copilot/SKILL.md')
    rules = {name: (Path(name) if name.startswith('/') else ROOT / name).is_file() for name in rule_paths}
    files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = dict(mode='CHECK_ONLY_NO_SOLVE_NO_REQUEST', success=result.wasSuccessful() and not forbidden,
                  tests_run=result.testsRun, state_version=state_a.VERSION, u_abi=routing_state_a.ABI,
                  spec_sha256=state_a.SPEC_SHA256, rules_discoverable=rules,
                  forbidden_entries=forbidden, model_requests=0, constructive_solves=0,
                  final_evaluations=0, numeric_fields=list(state_a.NUMERIC_FIELDS),
                  source_sha256=files, test_output=output.getvalue(),
                  scope='manual partial-state snapshots, history bookkeeping, U-only execution, static host-call inspection')
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    print(output.getvalue(), end='')
    print(json.dumps({k: v for k, v in report.items() if k not in ('source_sha256', 'test_output')}, ensure_ascii=False, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
