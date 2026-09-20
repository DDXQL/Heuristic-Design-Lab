# FJSP heuristic usage layer

This directory is reserved for a future Tier2 wrapper. No strategy is implemented yet.

The wrapper boundary is the frozen seven-feature `priority(...) -> finite float` interface. Code added here must not change `llm4ad.task.optimization.fjsp_set` or the Tier1 evaluation protocol without creating a new explicit experiment version.
