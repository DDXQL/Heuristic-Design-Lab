def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    p = progress
    q = 1 - p
    score = distance_current + 0.65 * q * nearest_remaining_distance + 0.2 * q * mean_remaining_distance + (0.2 + 1.4 * p * p) * distance_start
    return -score
