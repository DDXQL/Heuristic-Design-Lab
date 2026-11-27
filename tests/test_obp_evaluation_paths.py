from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from experiments.triad import evaluation, obp_h, obp_state_preset, problems, six_ops
from heuristic_design.core import state_a_v3 as state


def recording_rules(calls):
    def best_fit(item, capacities):
        assert isinstance(capacities, tuple)
        calls.append((0, item, capacities))
        return [-(capacity - item) for capacity in capacities]

    def last_feasible(item, capacities):
        calls.append((1, item, capacities))
        return list(range(len(capacities)))

    return [best_fit, last_feasible]


def assert_fixed_matches_routed(capacity, items):
    config = six_ops.config("obp-eoh")
    instance = {"N": len(items), "capacity": capacity, "items": items}
    routed_calls, fixed_calls = [], []
    routed = problems.solve_obp(instance, recording_rules(routed_calls)[:1], lambda _: 0, config)
    with patch.object(obp_state_preset, "extract", side_effect=AssertionError("unneeded state")):
        fixed = problems.solve_obp(instance, recording_rules(fixed_calls)[:1], None, config)
    assert fixed == routed
    assert fixed_calls == routed_calls
    assert all(type(value) is type(capacity) for _, _, row in fixed_calls for value in row)


class ObpEvaluationPathTests(unittest.TestCase):
    def test_fixed_h_matches_singleton_u_without_constructing_state(self):
        for capacity, items in (
            (10, [10, 4, 7, 6, 3, 2, 8, 5]),
            (2**63 - 1, [2**63 - 1, 2**63 - 2, 1]),
            (1.0, [0.7, 0.3, 0.25, 0.75, 0.1]),
        ):
            with self.subTest(capacity=capacity):
                assert_fixed_matches_routed(capacity, items)

    def test_u_reuses_state_provider_actions_and_retains_exact_feedback(self):
        config = six_ops.config("obp-u")
        items = [2, 3, 9, 6, 4, 8, 1, 7, 5]
        capacity = 10
        history = state.History(len(items), 2)
        used, placements, members, counts = [0] * len(items), [], [], [0, 0]
        expected_packets, expected_calls, actual_packets, actual_calls = [], [], [], []
        hs = recording_rules(expected_calls)
        for item in items:
            packet, actions = obp_state_preset.extract(item, tuple(used), capacity, history)
            expected_packets.append(packet)
            member = int(packet["h_usage_count"][0] > packet["h_usage_count"][1])
            choice = problems.obp_choose_action(
                item, used, capacity, actions, hs[member], obp_h.ABI, config["obp_actions"],
            )
            bin_index = choice["bin_index"]
            history.commit(member, int(used[bin_index] == 0))
            used[bin_index] += item
            placements.append(bin_index)
            members.append(member)
            counts[member] += 1

        def route(packet):
            actual_packets.append(packet)
            return int(packet["h_usage_count"][0] > packet["h_usage_count"][1])

        instance = {"N": len(items), "capacity": capacity, "items": items}
        with patch.object(obp_state_preset, "legal_obp_actions", wraps=problems.legal_obp_actions) as scan:
            with patch.object(problems, "legal_obp_actions", side_effect=AssertionError("duplicate scan")):
                solution, sequence, calls = problems.solve_obp(instance, recording_rules(actual_calls), route, config)
        assert scan.call_count == len(items)
        assert (solution["placements"], solution["used"], sequence, calls) == (placements, used, members, counts)
        assert actual_packets == expected_packets
        assert actual_calls == expected_calls


    def test_fixed_h_preserves_worker_recheck_and_training_j(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        tmp_path = Path(directory.name)
        config = six_ops.config("obp-eoh")
        h = asdict(obp_h.validate(
            "def priority(item_size, remaining_capacities):\n    return [-x for x in remaining_capacities]\n"
        ))
        selector = asdict(problems.u_language.validate("def use_heuristics(state):\n    return 0\n", "test", 1))
        items = [10, 4, 7, 6, 3, 2, 8, 5]
        instance = {"N": len(items), "capacity": 10, "items": items}
        spec = {"file": "synthetic", "value": instance}
        reference = problems.obp_reference_details(instance, config["obp_bound"])
        source = Path(problems.__file__)
        result = evaluation.evaluate({"id": "fixed-h", "candidate": None}, {
            "config": config,
            "members": [h],
            "instances": [spec],
            "references": [reference],
            "source_files": {str(source.relative_to(evaluation.ROOT)): evaluation.sha(source)},
            "run_directory": tmp_path,
        })
        evaluation.validate(result, [spec], "obp", config["obp_actions"])
        assert result["valid"]
        old_row = problems.solve_row(spec, [h], selector, config, reference["reference"])
        row, = result["instances"]
        assert all(row[key] == value for key, value in old_row.items())
        assert row["captured_solves"] == 2
        assert result["fitness"] == -old_row["score"]

    def test_parallel_workers_match_order_and_j_and_retain_all_physical_passes(self):
        results = self.compare_parallel(
            "[-x for x in remaining_capacities]",
            ([10, 2], [5, 3, 4, 2, 8], [6, 2, 4], [7, 4, 5], [8, 2, 3, 1]),
        )
        self.assertTrue(all(result["valid"] for result in results))
        for width, result in zip((1, 2, 4), results):
            self.assertEqual(result["fitness"], results[0]["fitness"])
            self.assertEqual(
                [row["semantic_sha256"] for row in result["instances"]],
                [row["semantic_sha256"] for row in results[0]["instances"]],
            )
            files = list((self.output / "worker-receipts" / f"width-{width}").rglob("physical-solves.jsonl"))
            self.assertEqual(len(files), width)
            self.assertEqual(sum(len(file.read_text().splitlines()) for file in files), 20)

    def test_parallel_invalid_candidate_keeps_first_failure_and_only_ordered_prefix(self):
        results = self.compare_parallel(
            "[x / (item_size - 7) for x in remaining_capacities]",
            ([6, 2, 4], [10, 7], [8, 2, 3, 1], [7, 4, 5]),
        )
        for result in results:
            self.assertFalse(result["valid"])
            self.assertIsNone(result["fitness"])
            self.assertEqual(result["failure"]["failed_instance"], "test-1")
            self.assertEqual([row["file"] for row in result["instances"]], ["test-0"])

    def compare_parallel(self, expression, item_lists):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        config = six_ops.config("obp-eoh")
        h = asdict(obp_h.validate(
            f"def priority(item_size, remaining_capacities):\n    return {expression}\n"
        ))
        rows = [{"file": f"test-{i}", "value": {"capacity": 10, "items": items}}
                for i, items in enumerate(item_lists)]
        refs = [problems.obp_reference_details(row["value"], config["obp_bound"]) for row in rows]
        source = Path(problems.__file__)
        inputs = {"members": [h], "instances": rows, "references": refs,
                  "source_files": {str(source.relative_to(evaluation.ROOT)): evaluation.sha(source)},
                  "run_directory": self.output}
        results = []
        for width in (1, 2, 4):
            result = evaluation.evaluate({"id": f"width-{width}", "candidate": None}, {
                **inputs, "config": {**config, "evaluation_concurrency": width},
            })
            evaluation.validate(result, rows, "obp", config["obp_actions"])
            results.append(result)
        return results
