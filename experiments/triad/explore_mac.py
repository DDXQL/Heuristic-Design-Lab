#!/usr/bin/env python3
"""New-root deployment/fetch shim over the existing transport; default is help."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import six_mac
six_mac.REMOTE='/public2/home/qiuqian/hdl-deploy/triad-explore-runtime-20261118-r14'
six_mac.BUNDLE=Path('/Users/DDXQL/Developer/transfer-outbox/triad-explore-runtime-20261118-r14.zip')
if __name__=='__main__':
    if len(sys.argv)==1:sys.argv.append('--help')
    six_mac.main()
