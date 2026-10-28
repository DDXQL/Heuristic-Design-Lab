def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.5 and std_distance_current > 0.12:
        return (1, (0.7, 0, 0.3, 0, 0))
    return (1, (1, 0, 0, 0, 0))
