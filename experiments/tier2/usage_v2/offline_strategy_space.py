#!/usr/bin/env python3
"""Export full prompts and handwritten toy evidence, with no model or dataset.

This is not an experiment/search stage. Output must be a new directory inside
this checkout, outside runs/. H context is source-only and used for prompts;
it is never scored or imported as a frozen research asset.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'code'))
from fjsp_usage.research.candidates import validate_code
from fjsp_usage.research.events import atomic_json
from fjsp_usage.usage_v2.exports import export_prompts
from fjsp_usage.usage_v2.prompts import prompt_manifest
from fjsp_usage.usage_v2.strategy_examples import write_strategy_examples, toy_members

CHECKPOINT = '243ad401bfd5ff64da338277112933323621de1f'


def local_output(path):
    resolved = Path(path).resolve()
    try:
        relative = resolved.relative_to(ROOT)
    except ValueError as exc:
        raise ValueError('output must stay inside this worktree') from exc
    if not relative.parts or relative.parts[0] in ('.git', 'runs', 'data', 'code', 'tests', 'experiments'):
        raise ValueError('output must be a separate artifact directory, outside runs/data/source')
    if resolved.exists():
        raise ValueError('output already exists; never overwrite evidence')
    return resolved


def write_offline_bundle(output, context_path=None):
    output = local_output(output)
    if context_path is None:
        members = toy_members()
        context = {'kind': 'handwritten-toy', 'K': len(members)}
    else:
        if sys.version_info[:2] != (3, 12):
            raise ValueError('checkpoint H context requires project Python 3.12; do not rewrite source keys')
        path = Path(context_path).resolve()
        path.relative_to(ROOT)  # This runner never reads another checkout.
        raw = json.loads(path.read_text())
        if raw.get('purpose') != 'offline-prompt-context-only':
            raise ValueError('explicit source-only prompt context required')
        members = tuple(validate_code(row['code'], kind='h', description=row['description'])
            for row in raw['members'])
        if any(c.key != row['key'] for c, row in zip(members, raw['members'])):
            raise ValueError('H source context key mismatch')
        context = {'kind': 'source-only-context', 'file': str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'K': len(members),
            'notice': 'H source used only to render prompts; no research-H scheduling or approval.'}
    output.mkdir(parents=True, exist_ok=False)
    examples = write_strategy_examples(output / 'examples')
    prompts = export_prompts(output / 'prompts', members, 262144)
    paths = [ROOT / 'code/fjsp_usage/usage_v2' / name for name in (
        '__init__.py', 'candidates.py', 'execution.py', 'prompts.py', 'exports.py', 'strategy_examples.py')]
    paths += [ROOT / name for name in (
        'code/fjsp_usage/research/candidates.py', 'code/fjsp_usage/research/scheduler.py',
        'code/fjsp_usage/research_real/prompts.py', 'code/fjsp_usage/research_real/initialization.py',
        'code/fjsp_usage/research_real/state_diagnostics.py', 'code/fjsp_usage/offline_v2.py',
        'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
        'code/llm4ad/task/optimization/fjsp_set/instances.py', 'tests/test_h_usage_strategy_space.py')]
    paths.append(Path(__file__).resolve())
    manifest = {'common_checkpoint': CHECKPOINT, 'python_version': sys.version,
        'prompt_pack': prompt_manifest(),
        'H_prompt_context': context, 'prompt_comparison': prompts['comparison'],
        'examples': examples, 'source_sha256': {str(p.relative_to(ROOT)):
            hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'model_requests': 0, 'search_started': False, 'benchmark_files_opened': [],
        'current_40_call_AB_batch': 'not executed here; original single-experiments task is the sole executor',
        'evidence_scope': 'prompt contract coverage and handwritten offline behavior; not LLM generation or performance'}
    atomic_json(output / 'Manifest.json', manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--h-context', type=Path)
    args = parser.parse_args()
    result = write_offline_bundle(args.output, args.h_context)
    print(json.dumps({'output': str(args.output.resolve()),
        'complete_feasible_schedules': result['examples']['complete_feasible_schedules'],
        'model_requests': 0, 'benchmark_files_opened': []}, ensure_ascii=False))


if __name__ == '__main__':
    main()
