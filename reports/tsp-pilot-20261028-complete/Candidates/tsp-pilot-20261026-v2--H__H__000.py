def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    late = progress * progress
    continuation = 0.6 * nearest_remaining_distance + 0.4 * mean_remaining_distance
    return -((1.0 - 0.35 * late) * distance_current + (0.25 + 0.75 * late) * distance_start + (0.35 - 0.2 * late) * continuation)
