def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    p = progress
    lookahead = (0.85 - 0.3 * p) * nearest_remaining_distance + 0.22 * mean_remaining_distance
    closure = (0.08 + 1.35 * p * p * p) * distance_start
    return -(distance_current + lookahead + closure)
