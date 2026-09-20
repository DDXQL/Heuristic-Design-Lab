# Tier1 experiment entrypoints

- `preflight.py`: deterministic micro-instance and handwritten baseline checks.
- `run_eoh_single.py`: EoH single-rule generation. It requires explicit API environment variables and creates a new, non-overwriting run directory.
- `evaluate_single_rule.py`: validation selection and train/validation comparison for a completed run.
- `prepare_single_rule.py`: creates a new portable single-rule config without overwriting an existing config.
- `configs/`: project-relative portable configs and the frozen split.

The original byte-identical entrypoints and configs are retained in `provenance/`. Portable changes are limited to repository-root discovery, project-relative data/config paths and relocated frozen artifacts. The candidate interface, scheduler, fitness and selection rules are unchanged.
