def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.65:
        return (0, (0, 1, 0, 0, 0))
    if std_distance_current > 0.12:
        return (0, (0, 0, 1, 0, 0))
    return (0, (0, 1, 0, 0, 0))
