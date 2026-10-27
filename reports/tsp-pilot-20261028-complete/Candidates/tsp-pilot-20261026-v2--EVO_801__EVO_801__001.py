def use_heuristics(progress, current_to_start, mean_distance_current, std_distance_current, previous_heuristic):
    if progress < 0.5:
        return (1, (0, 0.8, 0.2, 0, 0))
    else:
        return (1, (0, 0.8, 0, 0.2, 0))
