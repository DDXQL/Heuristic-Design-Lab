def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    spread_weight = 0.3 * (1 - progress) * (1 - progress)
    return (1, (0, 1 - spread_weight, spread_weight, 0, 0))
