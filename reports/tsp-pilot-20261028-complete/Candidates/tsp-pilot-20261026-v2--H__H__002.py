def priority(distance_current, distance_start, mean_remaining_distance, nearest_remaining_distance, progress):
    early = 1 - progress
    return -(distance_current + progress * progress * distance_start + early * (0.7 * nearest_remaining_distance + 0.3 * mean_remaining_distance))
