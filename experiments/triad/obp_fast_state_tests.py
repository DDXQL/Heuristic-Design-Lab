"""Check exact D08 observations and actions along synthetic placement traces."""

import random

import numpy as np

from heuristic_design.core import state_a_v3
from . import obp_fast_state, obp_state_preset


def main():
    rng = random.Random(718)
    checked = 0
    for capacity in (1, 2, 7, 17, 100, 127, 511, 1024):
        n, k = 153, 10
        used = np.zeros(n, dtype=np.int64)
        history = state_a_v3.History(n, k)
        for _ in range(n):
            item = rng.randint(1, capacity)
            original, actions = obp_state_preset.extract(item, used.tolist(), capacity, history)
            packet, fast_actions, remaining = obp_fast_state.extract(item, used, capacity, history)
            assert state_a_v3.plain(packet) == state_a_v3.plain(original)
            assert fast_actions == actions
            assert remaining == tuple(capacity - int(used[slot]) for slot in actions)
            slot = rng.choice(actions)
            history.commit(rng.randrange(k), int(used[slot] == 0))
            used[slot] += item
            checked += 1
    print(f"{checked} exact state packets, masks, action lists and capacities")


if __name__ == "__main__":
    main()
