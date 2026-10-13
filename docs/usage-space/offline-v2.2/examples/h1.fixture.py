def priority(processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, earliest_start, earliest_finish):
    if processing_time == 2:
        return 0
    if processing_time == 3:
        return 80
    if processing_time == 4:
        return 100
    return 1
