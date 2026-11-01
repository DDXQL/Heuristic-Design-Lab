def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    return -distance_current + -0.125 * (1 - progress) * distance_start + 0.0 * nearest_remaining_distance
