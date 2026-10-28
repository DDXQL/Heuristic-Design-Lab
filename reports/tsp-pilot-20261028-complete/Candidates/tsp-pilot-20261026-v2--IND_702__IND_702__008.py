def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.6:
        return (1, (0.0, 0.65, 0.35, 0.0, 0.0))
    return (1, (0.55, 0.0, 0.45, 0.0, 0.0))
