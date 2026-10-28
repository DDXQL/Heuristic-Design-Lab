def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    p = progress
    p2 = p * p
    p3 = p2 * p
    continuation_weight = 0.65 - 0.2 * p
    density_weight = 0.1 * (1.0 - p)
    return -(distance_current + continuation_weight * nearest_remaining_distance + density_weight * mean_remaining_distance + (0.04 + 0.96 * p3) * distance_start)
