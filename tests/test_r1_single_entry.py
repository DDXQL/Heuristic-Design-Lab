"""Launcher-only checks: no model requests or solver execution."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.common import _single_run as launch
from experiments.common import run_r1 as entry


class Tests(unittest.TestCase):
    def args(self, root):
        return dict(root=entry.ROOT, run_root=Path(root)/"runs", prefix="r1-test",
                    name=None, entry=Path(entry.__file__), expected_h=10, expected_train=21)

    def test_actual_train_check_only_has_no_network_solver_or_output_directory(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch("socket.socket.connect", side_effect=AssertionError("NO NETWORK")), \
                patch.object(launch.engine, "prepare", side_effect=AssertionError("NO PREPARE")), \
                patch.object(launch.engine, "run", side_effect=AssertionError("NO SOLVES")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(launch.launch_r1(entry.PARAMETERS, check_only=True, **self.args(folder)), 0)
            self.assertFalse((Path(folder)/"runs").exists())

    def test_api_switch_and_unknown_parameter_rejected(self):
        for changes in ({"api_mode":"real"}, {"real_requests_authorized":True},
                        {"api_attempt_cap":1}, {"generations":1}, {"provider":{}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                launch.preflight({**entry.PARAMETERS, **changes}, entry.ROOT, 10, 21)

    def test_top_parameters_reach_effective_config_and_wrong_candidate_count_rejected(self):
        c, plan = launch.preflight({**entry.PARAMETERS, "evaluation_concurrency":1, "window":5},
                                   entry.ROOT, 10, 21)
        self.assertEqual((c["evaluation_concurrency"], c["window"]), (1,5))
        self.assertEqual(plan["max_solve_passes"], 504)
        self.assertEqual(plan["API_requests"], 0)
        with self.assertRaisesRegex(ValueError, "P0"):
            launch.preflight({**entry.PARAMETERS, "population_size":11}, entry.ROOT, 10, 21)

    def test_existing_completed_directory_is_never_resumed_or_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/"runs"/"existing"
            target.mkdir(parents=True)
            marker=target/"checkpoint.json"
            marker.write_text('{"phase":"completed"}')
            kwargs={**self.args(folder), "name":"existing"}
            with patch.object(launch, "preflight", return_value=({},{})), \
                    patch.object(launch.engine, "prepare") as prepare, \
                    patch.object(launch.engine, "run") as run, \
                    redirect_stdout(io.StringIO()), self.assertRaises(FileExistsError):
                launch.launch_r1(entry.PARAMETERS, **kwargs)
            prepare.assert_not_called();run.assert_not_called()
            self.assertEqual(marker.read_text(), '{"phase":"completed"}')

    def test_orchestration_freezes_parameters_logs_then_exports_with_api_disabled(self):
        events=[]
        c={**entry.PARAMETERS, "population_size":2}
        def prepare(directory, config):
            events.append("prepare");directory.mkdir(parents=True)
            self.assertEqual(config, c)
            return {"protocol":"test-only-not-real-evidence"}
        def run(directory, *, allow_api):
            events.append("run");self.assertIs(allow_api, False)
            self.assertTrue((directory/"launch"/"parameters.json").exists())
            print("TEST_ONLY_PROGRESS_NO_SOLVES")
            return {"phase":"completed"}
        def export(directory):
            events.append("export");(directory/"exports").mkdir()
            return {"phase":"completed", "valid_unique_evaluations":2,
                    "failed_or_duplicate_tasks":0, "real_API_calls":0}
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(launch, "preflight", return_value=(c,{"test_only":True})), \
                patch.object(launch.engine, "prepare", side_effect=prepare), \
                patch.object(launch.engine, "run", side_effect=run), \
                patch.object(launch, "export", side_effect=export), redirect_stdout(io.StringIO()):
            kwargs={**self.args(folder), "name":"new"}
            self.assertEqual(launch.launch_r1(entry.PARAMETERS, **kwargs), 0)
            directory=Path(folder)/"runs"/"new"
            self.assertEqual(json.loads((directory/"launch"/"parameters.json").read_text()), c)
            self.assertIn("TEST_ONLY_PROGRESS_NO_SOLVES", (directory/"terminal.log").read_text())
            self.assertTrue((directory/"exports").is_dir())
        self.assertEqual(events, ["prepare", "run", "export"])

    def test_failure_keeps_lock_and_log_without_export_or_retry(self):
        def prepare(directory, config):
            directory.mkdir(parents=True)
            return {"protocol":"test-only-not-real-evidence"}
        def fail(directory, *, allow_api):
            (directory/".coordinator.lock").write_text("test-only")
            raise RuntimeError("TEST_ONLY_UNKNOWN_WORKER")
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(launch, "preflight", return_value=(entry.PARAMETERS,{})), \
                patch.object(launch.engine, "prepare", side_effect=prepare), \
                patch.object(launch.engine, "run", side_effect=fail) as run, \
                patch.object(launch, "export") as export, \
                redirect_stdout(io.StringIO()), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "UNKNOWN_WORKER"):
                launch.launch_r1(entry.PARAMETERS, **{**self.args(folder), "name":"failed"})
            directory=Path(folder)/"runs"/"failed"
            self.assertTrue((directory/".coordinator.lock").exists())
            self.assertIn("TEST_ONLY_UNKNOWN_WORKER", (directory/"terminal.log").read_text())
            run.assert_called_once();export.assert_not_called()


if __name__ == "__main__":
    unittest.main()
