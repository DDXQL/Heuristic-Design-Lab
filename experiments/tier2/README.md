# Tier2 placeholder

No selector or usage strategy is implemented in this version.

A future Tier2 layer must expose:

```python
priority(processing_time, remaining_work, remaining_operations,
         job_ready_time, machine_ready_time,
         earliest_start, earliest_finish) -> finite float
```

It may internally call, select or combine multiple heuristics. It must reuse the Tier1 instance loader, seven feature definitions, fixed scheduler, feasibility checks, lower bound, normalized score and EFT implementation.
