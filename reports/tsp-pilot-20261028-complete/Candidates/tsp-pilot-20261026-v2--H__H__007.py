def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    late = progress * progress * progress
    score = distance_current
    score = score + late * distance_start
    score = score + (0.35 + 0.55 * (1.0 - progress)) * nearest_remaining_distance
    score = score + 0.22 * (1.0 - progress) * mean_remaining_distance
    return -score
