def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    return (1, (0, 1 - 0.5 * progress, 0.5 * progress, 0, 0))
