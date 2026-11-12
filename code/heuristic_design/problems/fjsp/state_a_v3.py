"""Reuse the unchanged v2 FJSP arithmetic, then attach actual per-H history."""
from .state_a import Sensors as BaseSensors
from heuristic_design.core.state_a_v3 import extend_packet


class Sensors(BaseSensors):
    def extract(self, state, history, actions):
        return extend_packet(super().extract(state, history, actions), history)
