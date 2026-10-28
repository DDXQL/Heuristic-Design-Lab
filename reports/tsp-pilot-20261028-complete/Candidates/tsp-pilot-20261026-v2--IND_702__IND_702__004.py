def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.65:
        return (0, (0, 1, 0, 0, 0))
    return (1, (0, 0.7, 0.3, 0, 0))
