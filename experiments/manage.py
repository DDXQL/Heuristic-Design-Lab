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
    if '--problem' not in sys.argv[1:]:
        parser.print_help()
        return
    args, rest = parser.parse_known_args()
    entry = ROOT / 'experiments' / args.problem / 'manage.py'
    sys.argv = [str(entry), *rest]
    runpy.run_path(str(entry), run_name='__main__')

if __name__ == '__main__':
    main()
