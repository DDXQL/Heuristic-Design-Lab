"""LLM contract for a scalar priority on ready FJSP operation-machine pairs."""

template_program = '''
import math

def priority(processing_time: float, remaining_work: float,
             remaining_operations: int, job_ready_time: float,
             machine_ready_time: float, earliest_start: float,
             earliest_finish: float) -> float:
    """Return a finite priority for one currently eligible operation-machine pair.

    Higher means this pair is chosen earlier. The fixed scheduler handles
    precedence, machine assignment and schedule construction.
    """
    return -earliest_finish
'''

task_description = '''Design a constructive priority rule for flexible job-shop scheduling.
At each decision, the host enumerates the next unscheduled operation of each job
and every machine eligible for that operation. Your function scores ONE such pair.
All times are nonnegative. processing_time is the duration on this machine;
remaining_work is the sum of each remaining operation's shortest eligible duration;
remaining_operations includes the current operation; job_ready_time and
machine_ready_time are completion times of previously assigned operations;
earliest_start is their maximum and earliest_finish adds processing_time.
Return one finite scalar float; higher score wins. Do not modify the schedule,
use randomness, inspect files or environment variables, or return a vector.
The host resolves exact ties by lower job index and then lower machine index.
'''
