def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.5:
        return (1, (0, 0, 0.6, 0, 0.4))
    if progress < 0.85:
        return (1, (0, 0.65, 0.35, 0, 0))
    return (1, (0, 0.6, 0, 0.4, 0))
