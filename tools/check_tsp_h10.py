"""Relevant offline checks. File entry is required by spawn-based solver workers."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]


def main():
    patterns=['test_tsp_h10_build.py','test_tsp_routing_preparation.py','test_tsp_integration.py',
        'test_common_execution_v1.py','test_coverage_evolution_v1.py','test_common_routing_v1.py','test_tsp_adapter.py']
    suite=unittest.TestSuite()
    for pattern in patterns:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':raise SystemExit(main())
