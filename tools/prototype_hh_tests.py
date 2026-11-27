"""Pure offline tests: fake evaluation receipts; no H/constructor/API/Slurm runs."""
import copy
from dataclasses import asdict, dataclass
import io
from contextlib import redirect_stdout, redirect_stderr
import json
from pathlib import Path
import random
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import prototype_hh as cli
from experiments.prototype_hh import genetics, model, runner
from heuristic_design.core import state_a_v3 as state
from heuristic_design.core.storage import digest, read, sha, write
from experiments.triad import problems, evaluation


def deny(*args, **kwargs):
    raise AssertionError("real network, evaluator, H or constructor forbidden")


def packet(problem="tsp", used=False):
    history = state.History(4, 2)
    if used:
        history.commit(1, 0.0)
    return state.observe(problem, history=history, demands=(0.2,),
                         commitments=() if problem == "obp" and not used else (0.0,),
                         action_deltas=(0.0, 0.5))


def test_protocol(folder, seed=501):
    cfg = {**genetics.DEFAULTS, "population_size": 4, "iterations": 3, "initial_prototypes": 2}
    p = {"version": runner.VERSION, "seed": seed, "search": cfg, "source_files": {},
         "engineering_only": True, "members": [{}, {}], "config": {"problem": "tsp"},
         "binding": {"fake": True}, "instances": [{"file": "fake"}], "references": []}
    write(folder / "Protocol.json", p)
    identity = sha(folder / "Protocol.json")
    (folder / "Protocol.sha256").write_text(identity)
    s = {"identity": identity, "phase": "prepared", "cursor": 0, "iteration": 0,
         "records": [], "population": [], "children": [], "queue": [], "parents": [],
         "seen": {}, "inflight": None, "rng": random.Random(seed).getstate(), "search_wall_seconds": 0.0}
    return p, s


def fake_evaluator(task, p):
    # All candidates have the same objective: stable IDs must retain the
    # earliest initialization champion, not the latest child/final arrival.
    result = {"valid": True, "fitness": -0.2, "instances": [{"file": "fake", "score": 0.2,
              "raw_cost": 6, "reference": 5, "member_sequence": [], "h_calls": []}],
              "mock": True, "evaluation_seconds": 0.0, "failure": None}
    write(Path(p["run_directory"]) / "worker-receipts" / task["id"] / "result.json", result)
    return result


class PrototypeTests(unittest.TestCase):
    def test_encoding_masks_categories_and_group_weights(self):
        a, b = packet("obp"), packet("obp", True)
        za, zb = model.encode(a, 2), model.encode(b, 2)
        dimension, weights = model.layout(2)
        self.assertEqual(len(za), dimension)
        self.assertAlmostEqual(sum(weights), 1.0)
        self.assertEqual(za[8:12], [0, 0, 0, 0])  # missing OBP resources
        self.assertEqual(zb[8:12], [0, 1, 0, 1])  # real zeros stay available
        self.assertEqual(za[-6:-3], [0, 0, 1])  # previous H=None
        self.assertEqual(zb[-6:-3], [0, 1, 0])  # previous H=1, categorical
        self.assertNotEqual(za, zb)

    def test_nearest_state_switch_ties_and_frozen_copy(self):
        a, b = packet(), packet(used=True)
        row = model.candidate([{"center": model.encode(a, 2), "h": 0},
                               {"center": model.encode(b, 2), "h": 1}], 2)
        route = model.compile_selector(row, 2)
        self.assertEqual((route(a), route(b)), (0, 1))
        row["prototypes"][0]["h"] = 1
        self.assertEqual(route(a), 0)
        tied = model.candidate([{"center": model.encode(a, 2), "h": 1},
                                {"center": model.encode(a, 2), "h": 0}], 2)
        self.assertEqual(model.compile_selector(tied, 2)(a), 1)

    def test_wrong_contract_nonfinite_and_labels_fail(self):
        row = genetics.initialize(random.Random(1), 2, genetics.DEFAULTS)
        for change in (lambda x: x.update(member_count=3),
                       lambda x: x["prototypes"][0].update(h=True),
                       lambda x: x["prototypes"][0]["center"].__setitem__(0, float("nan")),
                       lambda x: x.update(state_spec_sha256="wrong")):
            bad = copy.deepcopy(row)
            change(bad)
            with self.assertRaises(ValueError):
                model.compile_selector(bad, 2)

    def test_operators_preserve_fields_bounds_and_original_parents(self):
        cfg = genetics.DEFAULTS
        rng = random.Random(8)
        a, b = genetics.initialize(rng, 2, cfg), genetics.initialize(rng, 2, cfg)
        b["prototypes"] = b["prototypes"][:1]
        pop = [{"id": "a", "candidate": a, "valid": True, "J": 1.0},
               {"id": "b", "candidate": b, "valid": False, "J": None}]
        original = copy.deepcopy(pop)
        for _ in range(300):
            children, parents = genetics.offspring(pop, rng, 2, cfg)
            self.assertEqual(len(children), 2)
            self.assertEqual(len(parents), 2)
            for child in children:
                model.validate(child, 2)
                self.assertLessEqual(len(child["prototypes"]), 32)
        self.assertEqual(pop, original)

    def test_pause_resume_matches_uninterrupted_search_and_pair_parents(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            a.mkdir(); b.mkdir()
            p, s = test_protocol(a)
            runner.run_loop(p, s, a, evaluator=fake_evaluator)
            q, t = test_protocol(b)
            runner.run_loop(q, t, b, max_candidates=5, evaluator=fake_evaluator)
            self.assertEqual(t["phase"], "paused")
            self.assertEqual(len(t["queue"]), 1)  # second child not regenerated
            q, t = runner.load_run(b)
            runner.run_loop(q, t, b, evaluator=fake_evaluator)
            for key in ("records", "population", "rng", "iteration", "cursor"):
                self.assertEqual(s[key], t[key])
            self.assertEqual(s["cursor"], 10)
            for index in range(4, 10, 2):
                self.assertEqual(s["records"][index]["parents"], s["records"][index + 1]["parents"])
            runner.export(a)
            artifact = read(a / "exports/frozen-model.json")
            self.assertEqual(artifact["training_champion"]["id"], "P-0000000")
            self.assertTrue(artifact["engineering_only"])

    def test_duplicate_slots_cache_once_and_all_invalid_still_consume_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p, s = test_protocol(folder)
            fixed = genetics.initialize(random.Random(7), 2, p["search"])
            calls = []
            def evaluate(task, context):
                calls.append(task["id"])
                result = {"valid": False, "fitness": None, "instances": [], "mock": True,
                          "evaluation_seconds": 0.0, "failure": {"error_type": "Timeout"}}
                write(folder / "worker-receipts" / task["id"] / "result.json", result)
                return result
            with (patch.object(genetics, "initialize", return_value=fixed),
                  patch.object(genetics, "offspring", side_effect=lambda *a: ([fixed, fixed], ["P-0000000"] * 2))):
                report = runner.run_loop(p, s, folder, evaluator=evaluate)
            self.assertEqual(len(calls), 1)
            self.assertEqual(report["logical_candidates"], 10)
            self.assertEqual(report["cache_hits"], 9)
            self.assertEqual(report["phase"], "completed_no_valid_candidate")
            runner.export(folder)
            self.assertFalse((folder / "exports/frozen-model.json").exists())

    def test_infrastructure_failure_never_replays_inflight(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p, s = test_protocol(folder)
            with self.assertRaises(RuntimeError):
                runner.run_loop(p, s, folder, evaluator=lambda *a: (_ for _ in ()).throw(RuntimeError("unknown worker")))
            p, s = runner.load_run(folder)
            self.assertTrue(s["inflight"])
            with self.assertRaisesRegex(RuntimeError, "no automatic replay"):
                runner.run_loop(p, s, folder, evaluator=deny)

    def test_real_search_rejects_mock_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            p, s = test_protocol(folder)
            p["engineering_only"] = False
            with self.assertRaisesRegex(ValueError, "mock result"):
                runner.run_loop(p, s, folder, evaluator=fake_evaluator)

    def test_bind_snapshot_without_solving_and_no_holdout_read(self):
        from experiments.triad.configuration import load
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            cfg = {"version": runner.VERSION, "problem": "fjsp", "seeds": [501, 502, 503],
                   "source_u_protocol": None, "source_u_protocol_sha256": None, "search": genetics.DEFAULTS}
            config = folder / "template.json"
            write(config, cfg)
            self.assertEqual(runner.check(config)[3]["logical_candidate_slots_per_seed"], 1040)
            c = load(runner.ROOT / "configurations/six-groups-20261116/fjsp-u.json")
            value = {"machines": 1, "jobs": [[[[0, 2]]]]}
            data = [{"file": "fake-fjsp", "value": value, "sha256": digest(value), "split": "train"}]
            hs = [asdict(problems.validate_h("fjsp", "def priority(" + ", ".join(problems.h_args("fjsp"))
                    + "):\n    return " + str(i) + "\n", "synthetic check only")) for i in range(10)]
            protocol = {"run_kind": "u", "config": {**c, "instance_count": 1, "evaluation_mode": "solve"},
                "instances": data, "references": problems.fixtures.precheck_instances("fjsp", data), "members": hs,
                "state_schema": state.schema_id("fjsp"), "source_files": runner.scientific_sources("fjsp")}
            path = folder / "source.json"
            write(path, protocol)
            out = folder / "bound.json"
            runner.bind(config, path, out)
            _, context, binding, report = runner.check(out)
            self.assertEqual(report["pending"], [])
            self.assertEqual(context["members"], hs)
            self.assertEqual(binding["training_instance_contents"], [digest(value)])
            self.assertFalse(context["config"]["real_requests_authorized"])
            self.assertEqual(report["actual_solves"], 0)
            protocol["instances"][0]["value"]["machines"] = 2
            write(path, protocol)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                runner.check(out)

    def test_all_three_problem_dispatches_select_only_one_H(self):
        @dataclass
        class Schedule:
            makespan: int = 3
            operations: tuple = ()
        row = model.candidate([{"center": model.encode(packet(), 2), "h": 1}], 2)
        captured = []
        def constructor(*args, **kwargs):
            hs, selector = args[1:3]
            self.assertEqual(len(hs), 2)
            self.assertEqual(selector(packet()), 1)
            captured.append(1)
            return SimpleNamespace(tour=(0, 1, 0), length=3, schedule=Schedule(), member_sequence=(1,), h_calls=(0, 1))
        # Only constructor boundaries are exercised. Neither a real H nor a
        # real schedule/tour/packing is ever executed in this test.
        with (patch.object(problems, "compile_h", return_value=deny),
              patch.object(problems.fixtures, "decode_instance", return_value=None),
              patch("heuristic_design.problems.fjsp.routing.construct_state_a_v3", constructor),
              patch("heuristic_design.problems.tsp.solver.distances", return_value=None),
              patch("heuristic_design.problems.tsp.routing.construct", constructor)):
            for problem in ("fjsp", "tsp"):
                result = problems.solve_row({"file": "fake", "value": {"coordinates": []}}, [{}, {}], row,
                                            {"problem": problem}, 2)
                self.assertEqual(result["score"], 0.5)
            def obp(instance, hs, selector, config):
                self.assertEqual(selector(packet()), 1)
                captured.append(1)
                return {"bin_count": 3}, [1], [0, 1]
            with patch.object(problems, "solve_obp", obp):
                self.assertEqual(problems.solve_row({"file": "fake", "value": {}}, [{}, {}], row,
                                                   {"problem": "obp"}, 2)["score"], 0.5)
        self.assertEqual(len(captured), 3)

    def test_solver_default_loader_still_rejects_nontraining_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "validation.json"
            write(path, {"problem": "tsp", "split": "validation", "instances": []})
            with self.assertRaises(ValueError):
                problems.load_inputs({"problem": "tsp", "data_manifest": str(path)})

    def test_frozen_evaluation_rejects_train_overlap_without_solving(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            candidate = genetics.initialize(random.Random(1), 2, genetics.DEFAULTS)
            artifact = {"kind": "frozen-prototype-router-v1", "engineering_only": False, "source_files": {},
                "candidate": candidate, "members": [{"key": "a"}, {"key": "b"}],
                "training_champion": {"candidate_key": digest(candidate)},
                "binding": {"problem": "fjsp", "H_keys": ["a", "b"], "state_spec_sha256": state.SPEC_SHA256,
                            "training_instance_contents": ["overlap"]}, "config": {"problem": "fjsp"}}
            artifact_path, manifest_path = folder / "model.json", folder / "manifest.json"
            write(artifact_path, artifact)
            write(manifest_path, {"split": "test", "instances": [{}]})
            target = folder / "evaluation"
            target.mkdir()
            with patch.object(problems, "load_inputs", return_value=([{"sha256": "overlap"}], [], [])):
                with self.assertRaisesRegex(ValueError, "relabelled"):
                    runner.evaluate_frozen(artifact_path, manifest_path, None, "test", target)
            self.assertFalse((target / "Evaluation-plan.json").exists())

    def test_summary_requires_three_completed_seeds_and_uses_sample_std(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = []
            for seed in (501, 502, 503):
                folder = Path(tmp) / str(seed)
                folder.mkdir()
                p, s = test_protocol(folder, seed)
                runner.run_loop(p, s, folder, evaluator=fake_evaluator)
                folders.append(folder)
            report = runner.summarize_runs(folders)
            self.assertAlmostEqual(report["mean_training_J"], 0.2)
            self.assertEqual(report["sample_std_training_J"], 0)
            with self.assertRaises(ValueError):
                runner.summarize_runs(folders[:2])

    def test_holdout_summary_preserves_failed_seed_instead_of_averaging_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = []
            for seed in (501, 502, 503):
                folder = Path(tmp) / str(seed)
                folder.mkdir()
                valid = seed != 503
                write(folder / "Frozen-evaluation.json", {"seed": seed, "valid": valid,
                    "J": 0.1 if valid else None, "frozen_model_sha256": str(seed), "split": "test",
                    "manifest_sha256": "same-data", "references_sha256": "same-refs",
                    "binding": {"same": "training-inputs"}, "search": genetics.DEFAULTS})
                folders.append(folder)
            report = runner.summarize_evaluations(folders)
            self.assertFalse(report["complete"])
            self.assertEqual(len(report["runs"]), 3)
            self.assertIsNone(report["mean_J"])

    def test_no_execute_flag_means_no_training_or_holdout(self):
        for args in (["train", "missing.json", "--seed", "501", "--run-dir", "unused"],
                     ["evaluate", "--model", "missing", "--manifest", "missing", "--split", "test", "--run-dir", "unused"]):
            with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                cli.main(args)

    def test_writer_excludes_duplicate_writers_and_r15_paths(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "ROOT", Path(tmp).resolve()):
            with runner.writer(Path(tmp) / "runs/prototype-hh/test") as folder:
                with self.assertRaises(RuntimeError):
                    with runner.writer(folder):
                        pass
            with self.assertRaises(ValueError):
                with runner.writer(Path(tmp) / "runs/r15-old"):
                    pass


if __name__ == "__main__":
    with (patch.object(socket.socket, "connect", deny), patch.object(socket, "create_connection", deny),
          patch.object(evaluation, "evaluate", deny), patch.object(evaluation, "_collect_candidate", deny)):
        unittest.main(verbosity=2)
