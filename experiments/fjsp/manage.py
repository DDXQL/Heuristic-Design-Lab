#!/usr/bin/env python3
"""FJSP problem entry; delegates to the unchanged legacy operations CLI."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'code')]
from tools.experiment_ops import main

if __name__ == '__main__':
    main()
