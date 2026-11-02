#!/usr/bin/env python3
"""Offline EoH comparison export only; no API, solving or champion reselection policy."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.problems.tsp.eoh_reporting import report,preview


def main():
    p=argparse.ArgumentParser(description=__doc__)
    choice=p.add_mutually_exclusive_group(required=True);choice.add_argument('--run-dir',type=Path);choice.add_argument('--preview-config',type=Path)
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.preview_config:
        if not a.output:p.error('--preview-config requires --output under reports/')
        print(preview(a.preview_config,a.output))
    else:print(report(a.run_dir,a.output))


if __name__=='__main__':main()
