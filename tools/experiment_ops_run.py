"""Compatibility entry for the generic runner with the FJSP adapter."""
from heuristic_design.core import execution as engine
from heuristic_design.llm.legacy import ClientConfig, DeadlineTransport, JsonCandidateTransport
from heuristic_design.problems.fjsp.adapter import FjspAdapter, MockTransport, evaluate


def ledger(directory,s,p):return engine.ledger(directory,s,p,adapter=FjspAdapter())
def pause_sequence(directory):return engine.pause_sequence(directory,adapter=FjspAdapter())
def stop(directory):return engine.stop(directory,adapter=FjspAdapter())
def start(directory,*,resume=False,allow_api=False,background=False):
    return engine.start(directory,adapter=FjspAdapter(),resume=resume,allow_api=allow_api,background=background)
def work(directory):return engine.work(directory,adapter=FjspAdapter())
