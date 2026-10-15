def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    gap = remaining_work_mean - machine_ready_mean
    pressure = gap + remaining_work_std - machine_ready_std
    flexibility = candidate_pair_ratio * (1.0 - progress)
    threshold = 0.08 - 0.2 * flexibility
    target = 0
    if progress < 0.35:
        if pressure < threshold:
            target = 8
    if progress >= 0.35:
        if progress < 0.75:
            target = 5
            if pressure < threshold:
                target = 9
        if progress >= 0.75:
            target = 1
            if pressure < threshold:
                target = 3
    boundary = abs(pressure - threshold)
    if boundary < 0.05:
        if progress < 0.35:
            if previous_heuristic == 0:
                target = 0
            if previous_heuristic == 8:
                target = 8
        if progress >= 0.35:
            if progress < 0.75:
                if previous_heuristic == 5:
                    target = 5
                if previous_heuristic == 9:
                    target = 9
            if progress >= 0.75:
                if previous_heuristic == 1:
                    target = 1
                if previous_heuristic == 3:
                    target = 3
    s0 = 0.0
    s1 = 0.0
    s2 = 0.0
    s3 = 0.0
    s4 = 0.0
    s5 = 0.0
    s6 = 0.0
    s7 = 0.0
    s8 = 0.0
    s9 = 0.0
    if target == 0:
        s0 = 1.0
        if previous_heuristic == 0:
            s0 = 1.25
    if target == 1:
        s1 = 1.0
        if previous_heuristic == 1:
            s1 = 1.25
    if target == 3:
        s3 = 1.0
        if previous_heuristic == 3:
            s3 = 1.25
    if target == 5:
        s5 = 1.0
        if previous_heuristic == 5:
            s5 = 1.25
    if target == 8:
        s8 = 1.0
        if previous_heuristic == 8:
            s8 = 1.25
    if target == 9:
        s9 = 1.0
        if previous_heuristic == 9:
            s9 = 1.25
    return (0, (s0, s1, s2, s3, s4, s5, s6, s7, s8, s9))
