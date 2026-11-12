"""Check both scheme-A interfaces offline. Never execute a solver, H or model."""
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
    parser.add_argument('--check-only', action='store_true', required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.report is not None and args.report.exists():
        parser.error('report must be a new file')
    def deny(event, values):
        if event.startswith(('socket.', 'subprocess.', 'urllib.', 'http.client.')) or event in ('os.system', 'os.posix_spawn', 'os.fork', 'os.forkpty'):
            raise PermissionError('check-only denies network/processes: ' + event)
    sys.addaudithook(deny)
    import test_state_a_offline, test_state_a_v3_offline
    from heuristic_design.core import state_a_v3, routing_state_a_v3
    forbidden = []
    def profile(frame, event, arg):
        if event != 'call':
            return
        module, name = frame.f_globals.get('__name__', ''), frame.f_code.co_name
        if ((module.startswith('heuristic_design.problems.') and (name.startswith('construct') or name in ('solve', 'step', 'nearest_neighbor', 'tour_length')))
                or module.startswith(('heuristic_design.llm.', 'heuristic_design.core.routing_evaluation', 'heuristic_design.core.evolution_v1'))):
            forbidden.append(module + '.' + name)
            raise PermissionError('forbidden solver/model/evaluation: ' + forbidden[-1])
    stream = io.StringIO()
    sys.setprofile(profile)
    try:
        loader = unittest.defaultTestLoader
        suite = unittest.TestSuite([loader.loadTestsFromModule(test_state_a_offline), loader.loadTestsFromModule(test_state_a_v3_offline)])
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    finally:
        sys.setprofile(None)
    paths = list((ROOT / 'code/heuristic_design').rglob('*.py')) + [ROOT / name for name in
        ('tests/test_state_a_offline.py', 'tests/test_state_a_v3_offline.py', 'tools/check_state_a.py', 'tools/check_state_a_v3.py')]
    for path in paths:
        ast.parse(path.read_text(), filename=str(path))
    report = dict(mode='CHECK_ONLY_NO_SOLVE_NO_REQUEST', success=result.wasSuccessful() and not forbidden,
                  tests_run=result.testsRun, state_version=state_a_v3.VERSION, u_abi=routing_state_a_v3.ABI,
                  spec_sha256=state_a_v3.SPEC_SHA256, h_fields=list(state_a_v3.H_FIELDS),
                  old_v2_checks_included=True, model_requests=0, constructive_solves=0, final_evaluations=0,
                  forbidden_entries=forbidden, test_output=stream.getvalue(),
                  source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open('x') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    print(stream.getvalue(), end='')
    print(json.dumps({k: v for k, v in report.items() if k not in ('test_output', 'source_sha256')}, ensure_ascii=False, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
