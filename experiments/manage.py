#!/usr/bin/env python3
"""Problem router only. Subcommand help/preview is supplied by each real CLI."""
from pathlib import Path
import argparse
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--problem', choices=['fjsp', 'tsp'], required=True)
    parser.add_argument('--state-schema', help='explicit legacy schema; common draft is disabled')
    if '--problem' not in sys.argv[1:]:
        parser.print_help()
        return
    args, rest = parser.parse_known_args()
    sys.path[:0] = [str(ROOT), str(ROOT / 'code')]
    from heuristic_design.core.state_contracts import require_executable_schema
    try:
        require_executable_schema(args.problem, args.state_schema)
    except ValueError as exc:
        parser.error(str(exc))
    entry = ROOT / 'experiments' / args.problem / 'manage.py'
    sys.argv = [str(entry), *rest]
    runpy.run_path(str(entry), run_name='__main__')

if __name__ == '__main__':
    main()
