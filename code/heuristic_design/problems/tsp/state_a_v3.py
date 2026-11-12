"""Reuse the unchanged v2 TSP arithmetic; forced closure stays outside history."""
from .state_a import Sensors as BaseSensors
from heuristic_design.core.state_a_v3 import extend_packet


class Sensors(BaseSensors):
    def extract(self, tour, remaining, history):
        return extend_packet(super().extract(tour, remaining, history), history)
