#!/usr/bin/env python3
"""Process-local admission adapter around the unchanged frozen U entry."""
import argparse
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import shared_admission as shared
from experiments.common import run_frozen

def execute(args,b,d):
    with shared.frozen_hooks(b,d):return run_frozen.main(args)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--shared-manifest',type=Path,required=True);ap.add_argument('--member-config',type=Path,required=True);ap.add_argument('args',nargs=argparse.REMAINDER);a=ap.parse_args()
    args=a.args[1:] if a.args and a.args[0]=='--' else a.args
    launch=Path(args[args.index('--config')+1]);_,c,d,pending=run_frozen.configuration(launch)
    if pending:raise PermissionError('original U protocol pending')
    b=shared.binding(a.shared_manifest,d,a.member_config)
    if args[0] not in ('run','resume'):raise PermissionError('shared frozen adapter is only an execution hook')
    return execute(args,b,d)

if __name__=='__main__':raise SystemExit(main())
