"""Only the current arrival and opened bins are accepted. No stream lookahead."""
import math

from .state_a import extract as base_extract, legal_actions, StepResult, _positive
from heuristic_design.core.state_a_v3 import History, extend_packet, plain
from heuristic_design.core.routing import route_token


def extract(current_item, opened_used, capacity, history):
    packet, actions = base_extract(current_item, opened_used, capacity, history)
    return extend_packet(packet, history), actions


class OnlineSession:
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
