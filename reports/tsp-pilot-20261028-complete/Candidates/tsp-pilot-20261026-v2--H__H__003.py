def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    future_access_cost = 0.6 * nearest_remaining_distance + 0.4 * mean_remaining_distance
    return -(distance_current + progress * distance_start + (1 - progress) * future_access_cost)
