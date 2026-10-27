"""Read-only snapshot relocation; no scheduling or generation."""
from pathlib import Path
import tempfile
import unittest
from heuristic_design.problems.fjsp.provenance import relocated_snapshot_source

class Tests(unittest.TestCase):
    def test_relocation_is_relative_not_fallback_to_old_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'code').mkdir()
            expected = root/'code/example.py'
            expected.write_text('immutable source')
            path, relative = relocated_snapshot_source('/old/snapshot/code/example.py',
                                                       '/old/snapshot', root)
            self.assertEqual(path, expected.resolve())
            self.assertEqual(relative, 'code/example.py')
            for old in ['/different/code/example.py', '/old/snapshot/../outside.py']:
                with self.assertRaises(ValueError):
                    relocated_snapshot_source(old, '/old/snapshot', root)
            (root/'escape').symlink_to(root.parent)
            with self.assertRaises(ValueError):
                relocated_snapshot_source('/old/snapshot/escape/file', '/old/snapshot', root)

    def test_fjsp_surface_is_same_implementation(self):
        from heuristic_design.problems.fjsp.solver import construct_usage_schedule
        from fjsp_usage.usage_v2.execution import construct_usage_schedule as legacy
        self.assertIs(construct_usage_schedule, legacy)

if __name__ == '__main__':
    unittest.main()
