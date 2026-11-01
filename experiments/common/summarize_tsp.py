#!/usr/bin/env python3
"""Offline committed-result report only: no API, solving, selection or freeze."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.tsp.reporting import report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--baseline',type=Path,help='explicit complete compatible constant-H run; otherwise placeholders')
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    result=report(args.run_dir.resolve(),baseline=args.baseline,output=args.output)
    print(result)


if __name__=='__main__':main()
