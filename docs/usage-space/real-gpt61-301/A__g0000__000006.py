def use_heuristics(progress, candidate_pair_ratio, remaining_work_mean, remaining_work_std, machine_ready_mean, machine_ready_std, previous_heuristic):
    work_dispersion = remaining_work_std / (1.0 + remaining_work_mean)
    ready_dispersion = machine_ready_std / (1.0 + machine_ready_mean)
    if progress < 0.3:
        if candidate_pair_ratio < 0.5:
            if work_dispersion < 0.1:
                target = 0
            else:
                target = 1
        elif machine_ready_mean < 0.25:
            if ready_dispersion < 0.08:
                target = 2
            else:
                target = 3
        elif remaining_work_mean < 0.25:
            target = 4
        else:
            target = 5
    elif progress < 0.75:
        if machine_ready_mean < remaining_work_mean:
            if work_dispersion < 0.1:
                target = 6
            else:
                target = 7
        elif ready_dispersion < 0.08:
            target = 8
        else:
            target = 9
    elif candidate_pair_ratio < 0.5:
        target = 9
    elif remaining_work_std > 0.5 * remaining_work_mean:
        target = 2
    else:
        target = 9
    return (0, (1.0 if target == 0 else 0.0, 1.0 if target == 1 else 0.0, 1.0 if target == 2 else 0.0, 1.0 if target == 3 else 0.0, 1.0 if target == 4 else 0.0, 1.0 if target == 5 else 0.0, 1.0 if target == 6 else 0.0, 1.0 if target == 7 else 0.0, 1.0 if target == 8 else 0.0, 1.0 if target == 9 else 0.0))
