def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    return -distance_current + 0.15 * (mean_remaining_distance - nearest_remaining_distance)
