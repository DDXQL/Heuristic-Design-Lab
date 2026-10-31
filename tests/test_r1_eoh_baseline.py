"""Targeted native-rule adapter checks; no formal train scheduling or model requests."""
from contextlib import redirect_stdout
from dataclasses import asdict
import io
import multiprocessing as mp
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from experiments.common import run_r1_eoh as entry
from tools import r1_eoh_baseline as eoh
from heuristic_design.core.lifecycle import collect
from heuristic_design.core.storage import read, sha
from heuristic_design.problems.routing_fixtures import compile_members
from heuristic_design.problems.fjsp.routing import construct
from llm4ad.task.optimization.fjsp_set.instances import FJSPInstance, Operation
from llm4ad.task.optimization.fjsp_set.scheduler import construct_schedule


def small_instance():
    return FJSPInstance("adapter-unit-only",2,(
        (Operation(((0,3),(1,5))),Operation(((0,4),(1,2)))),
        (Operation(((0,2),(1,3))),)))


class Tests(unittest.TestCase):
    def test_real_input_preflight_pins_original_rule_without_solving_or_network(self):
        with patch("socket.socket.connect",side_effect=AssertionError("NO NETWORK")), \
                patch.object(eoh,"construct_schedule",side_effect=AssertionError("NO TRAIN SOLVES")):
            c,candidate,instances,provenance=eoh.preflight(entry.PARAMETERS)
        self.assertEqual(len(instances),21)
        self.assertEqual(candidate.code,Path(c["rule_source"]).read_text())
        self.assertEqual(candidate.key,"0991e17f833e7ab773b0ff13ea2396a0cb3ccb9d94715984fb1ef421ea89496a")
        self.assertIn("** 0.5",candidate.code)
        self.assertEqual(provenance["historical_experiment"]["budget_per_seed"]["max_sample_nums"],40)

    def test_reject_api_unknown_fields_other_seed_and_timeout_change(self):
        for change in ({"api_mode":"real"},{"real_requests_authorized":True},{"other":1},
                       {"instance_timeout":60},{"rule_source":"baselines/tier1_single_rule_v1/rules/selected_rule_seed_2026092003.py"}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                eoh.preflight({**entry.PARAMETERS,**change})

    def test_native_scheduler_matches_common_fixed_H0_on_small_parity_case(self):
        frozen=read(entry.ROOT/"preparations/b1-v6-20261029/H_frozen.json")
        hs=compile_members("fjsp",[r["candidate"] for r in frozen["members"]])
        instance=small_instance()
        native=construct_schedule(instance,hs[0])
        common=construct(instance,hs,lambda state:0,trace=False)
        self.assertEqual(native,common.schedule)

    def test_native_worker_uses_existing_T30_and_modern_two_pass_validation(self):
        c,candidate,_,_=eoh.preflight(entry.PARAMETERS)
        receipts=[];instance=small_instance()
        rows,failure,life=collect(mp.get_context("spawn"),eoh.worker,
            {"candidate":asdict(candidate),"files":{c["rule_source"]:sha(c["rule_source"])}},
            [],[instance],[instance.name],30,(),receipts.append)
        self.assertIsNone(failure)
        self.assertEqual(life["cleanup"],["join_exit_grace_2.0"])
        result={"valid":True,"fitness":rows[0]["score"],"instances":rows,"total_instances":1}
        eoh.Adapter().validate_result(result,[{"file":instance.name,"LB":eoh.lower_bound_v5(instance)}])
        self.assertEqual(rows[0]["captured_solves"],2)
        self.assertGreater(rows[0]["single_h_calls"][0],0)

    def test_resume_reads_frozen_run_and_ignores_modified_top_parameters(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(entry,"PARAMETERS",{"api_mode":"real"}), \
                patch.object(entry,"preflight",side_effect=AssertionError("NO NEW PARAMETERS")), \
                patch.object(eoh.Adapter,"check_run",return_value={}), \
                patch.object(eoh.Adapter,"summary",return_value={"phase":"completed","valid":True,
                    "fitness":-2.0,"complete_instances":21,"API_requests":0}), \
                patch.object(entry.execution,"start",return_value={"phase":"completed"}) as start, \
                patch("sys.argv",["run_r1_eoh.py","--resume",folder]),redirect_stdout(io.StringIO()):
            self.assertEqual(entry.main(),0)
            self.assertTrue(start.call_args.kwargs["resume"])
            self.assertFalse(start.call_args.kwargs["allow_api"])


if __name__=="__main__":unittest.main()
