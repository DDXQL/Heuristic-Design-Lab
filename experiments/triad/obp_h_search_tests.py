"""Offline regression for the H401 40-slot and duplicate-pilot paths."""

from pathlib import Path
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "code"), str(ROOT)]

from experiments.triad import assets, obp_h_search, runtime, six_ops
from heuristic_design.core import execution
from heuristic_design.core.storage import read, write


def deny(*args, **kwargs):
    raise AssertionError("offline test forbids network and real evaluations")


def run_case(folder, *, duplicate):
    config = six_ops.config("obp-u")
    config.update(mode="mock", freeze_status="engineering_only", credential_file=None,
                  mock_faults={str(i): "duplicate" for i in range(10)} if duplicate else {})
    config["h_build"]["generation_policy"] = obp_h_search.POLICY
    cfg = folder / f"config-{duplicate}.json"
    write(cfg, config)
    run = folder / f"run-{duplicate}"
    protocol = runtime.prepare(run, cfg, engineering=True, run_kind="h-build")
    assert protocol["budgets"]["API_attempts"] == 40
    assert protocol["budgets"]["max_solve_passes"] == 7680
    execution.start(run, adapter=runtime.Adapter())
    saved = read(run / "checkpoint.json")
    ledger = read(run / "API_attempts.json")
    records = list(saved["tasks"].values())
    assert len({t["prompt"] for t in records[:10]}) == 10
    assert len(ledger["api_attempts"]) == saved["cursor"] == saved["eoh"]["initialization_requests"]
    assert saved["eoh"]["operator_cursor"] == 0
    if duplicate:
        assert (saved["phase"], saved["cursor"]) == ("initialization_incomplete", 10)
        assert len(saved["evaluations"]) == 1
        print("Repeated pilot stops at 10 slots and preserves its requests.")
    else:
        assert (saved["phase"], saved["cursor"]) == ("completed", 40)
        assert [r["h_strategy"] for r in records[10:14]] == ["complementary_search", "local_search"] * 2
        assert len(records[10]["parents"]) == 2 and len(records[11]["parents"]) == 1
        frozen = folder / "synthetic-H401.json"
        report = assets.freeze_h(run, frozen)
        assert report["H_count"] == 10 and report["API_requests"] == report["new_solves"] == 0
        assert read(frozen)["engineering_only"] is True
        print("Diverse pilot proceeds to slot 40 and freezes 10 synthetic rules.")


if __name__ == "__main__":
    (ROOT / "runs").mkdir(exist_ok=True)
    with (TemporaryDirectory(prefix="OFFLINE-h401-feedback-", dir=ROOT / "runs") as tmp,
          patch.object(socket.socket, "connect", deny),
          patch.object(runtime.evaluation, "evaluate", deny),
          patch.object(execution.sys, "platform", "linux")):
        run_case(Path(tmp), duplicate=False)
        run_case(Path(tmp), duplicate=True)
