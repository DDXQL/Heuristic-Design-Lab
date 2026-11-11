"""No future items accepted: public count, current arrival and opened bins only."""
import math
from dataclasses import dataclass

from heuristic_design.core.state_a import History, observe, plain
from heuristic_design.core.routing import route_token


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def legal_actions(current_item, opened_used, capacity):
    if not _positive(capacity) or not _positive(current_item) or current_item > capacity:
        raise ValueError('finite capacity and item in (0,capacity] required')
    used = tuple(opened_used)
    if any(type(x) not in (int, float) or not math.isfinite(x) or not 0 < x <= capacity for x in used):
        raise ValueError('opened bins must have finite used capacity in (0,capacity]')
    # Compare using the same addition as commit; no epsilon changes legality.
    fitting = tuple(i for i, x in enumerate(used) if x + current_item <= capacity)
    return fitting or (len(used),)


def extract(current_item, opened_used, capacity, history):
    used = tuple(opened_used)
    actions = legal_actions(current_item, used, capacity)
    if ((history.count == 0) != (len(used) == 0) or len(used) > history.count
            or history.count >= history.decisions):
        raise ValueError('OBP opened-bin/history mismatch')
    packet = observe('obp', history=history, demands=(current_item / capacity,),
                     commitments=(x / capacity for x in used),
                     action_deltas=(int(i == len(used)) for i in actions))
    return packet, actions


@dataclass(frozen=True)
class StepResult:
    bin_index: int
    member: int
    committed_delta: int
    state: dict
    h_calls: tuple


class OnlineSession:
    """Single-arrival host adapter; no item stream, dataset, reference or evaluator.

    H(item_size, remaining_capacity) returns a scalar per legal bin, higher wins.
    The U packet contains summaries only. H ABI is preparatory and problem-local.
    """
    def __init__(self, *, public_total, capacity, member_count):
        if not _positive(capacity):
            raise ValueError('positive finite capacity required')
        self.capacity = capacity
        self.history = History(public_total, member_count)
        self.opened_used = []

    def step(self, current_item, heuristics, usage):
        members = tuple(heuristics)
        if len(members) != self.history.members or not all(callable(h) for h in members) or not callable(usage):
            raise ValueError('H count and callable U/H required')
        packet, actions = extract(current_item, self.opened_used, self.capacity, self.history)
        member = route_token(usage(packet), len(members))
        scores, calls = [], [0] * len(members)
        for i in actions:
            remaining = self.capacity - self.opened_used[i] if i < len(self.opened_used) else self.capacity
            value = members[member](current_item, remaining)
            calls[member] += 1
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError('finite scalar H score required')
            scores.append(value)
        winner = actions[max(range(len(actions)), key=lambda k: scores[k])]
        delta = int(winner == len(self.opened_used))
        if delta:
            self.opened_used.append(current_item)
        else:
            self.opened_used[winner] += current_item
        self.history.commit(member, delta)
        return StepResult(winner, member, delta, plain(packet), tuple(calls))
