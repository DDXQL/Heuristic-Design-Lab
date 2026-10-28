def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    remaining = 1.0 - progress
    return -distance_current - progress * progress * distance_start - remaining * nearest_remaining_distance - 0.2 * remaining * mean_remaining_distance
