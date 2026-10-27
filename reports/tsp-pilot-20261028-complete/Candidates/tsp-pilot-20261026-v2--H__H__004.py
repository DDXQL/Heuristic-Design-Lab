def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    continuation = 0.7 * nearest_remaining_distance + 0.3 * mean_remaining_distance
    cost = distance_current + (1.0 - progress) * continuation + progress * distance_start
    return -cost
