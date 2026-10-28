def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    return -(distance_current + (1.0 - progress) * (0.7 * nearest_remaining_distance + 0.3 * mean_remaining_distance) + (0.2 + 0.8 * progress * progress) * distance_start)
