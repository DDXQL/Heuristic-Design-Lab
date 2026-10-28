def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.5 and current_to_start > mean_distance_current:
        return (1, (0, 0.65, 0, 0.35, 0))
    if progress < 0.5:
        return (1, (0, 0, 0.7, 0, 0.3))
    return (1, (0, 0.7, 0, 0.3, 0))
