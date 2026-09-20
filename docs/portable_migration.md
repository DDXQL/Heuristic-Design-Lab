# Tier1 baseline portable migration

## Scope

This migration packages `Tier1-Fixed-H-v1` as an independent project. It did
not call an LLM, run evolution, select a different rule, or evaluate test
instances. The canonical rule remains the seed `2026092002` rule selected
before the stability runs.

## Exported code

The runtime dependency closure was obtained from the Tier1 entrypoint imports
and recursively from imported `llm4ad` modules. The portable project contains:

- `llm4ad.base`;
- `llm4ad.method.eoh`;
- the HTTPS LLM adapter used by the entrypoint;
- the profiler modules imported by EoH;
- `llm4ad.task.optimization.fjsp_set`;
- Tier1 preflight, training, evaluation and selection entrypoints;
- frozen rules, run records, configs, tests and research documentation.

OBP, TSP, CVRP, EoH-S set evolution and unrelated LLM4AD methods were omitted.
No portable file imports code from the original repository.

## Minimal portable changes

The scheduler, feature contract, feasibility checks, lower bound, score,
baseline implementations, prompt, FJSP evaluation, EoH implementation and
frozen rules were not changed.

The working entrypoints under `experiments/tier1/` differ from their preserved
copies under `provenance/original_entrypoints/` only where project paths and
portable config locations had to change. Relative `data/fjsp` replaces the
machine-specific absolute `data_root`. `code/llm4ad/method/__init__.py` imports
only EoH because unrelated methods are intentionally absent. The complete
mapping and hashes are in `provenance/file_mapping.json`.

Original configs remain byte-identical under `provenance/original_configs/`.
Portable configs are new files; they retain the same split, task contract,
fitness, budgets, seeds and model metadata.

## Data handling

The 60 fixed split files and `sample.fjsp` were copied byte-for-byte from the
recorded local dataset directory. Source and destination SHA-256 values were
checked for all 61 files during the copy. The 28 test files were copied and
checksummed as opaque bytes; they were not parsed or scheduled. Because the
redistribution license is not confirmed, instance files are ignored by Git.

## Verification protocol

`verify_portable_baseline.py` removes the original repository from `sys.path`
and `PYTHONPATH`, imports the portable package, verifies manifest hashes,
checks the seven-argument interface and the makespan-4 micro instance, and
replays all recorded train and validation outcomes. It also replays EFT, SPT
and MWKR, checks all three rules for 100% feasibility, and runs unit tests.

The verifier does not invoke an LLM or evolution. It does not hash, parse or
evaluate test contents; it checks only that the 28 local paths and recorded
byte sizes exist. The reported test load and evaluation counts must both be
zero.

## Redistribution note

The EoH-S README states MIT, but the frozen tree does not contain its linked
license file. The root `LICENSE` preserves the MIT text from the related EoH
repository. Current LLM4AD upstream declares BSD-2-Clause, while files in the
frozen snapshot also contain an older research-use notice. See
`THIRD_PARTY_NOTICES.md` and confirm the applicable terms before publication.

