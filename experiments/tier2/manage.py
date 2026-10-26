#!/usr/bin/env python3
"""User operations entry. Help/check/plan never generate or solve."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'code')]
from tools.experiment_ops import main

if __name__=='__main__':main()
