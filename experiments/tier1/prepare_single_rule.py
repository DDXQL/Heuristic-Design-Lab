"""Freeze the Tier1 single-rule EoH experiment before any model calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE_CONFIG = Path(__file__).with_name('configs') / 'portable_formal_config.json'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path,
                        default=Path(__file__).with_name('configs') / 'portable_single_rule_config.json')
    args = parser.parse_args()
    digest_path = args.output.with_suffix('.sha256')
    if args.output.exists() or digest_path.exists():
        raise FileExistsError('single-rule config already exists; refusing to overwrite')
    expected_base = BASE_CONFIG.with_suffix('.sha256').read_text().strip()
    if sha256(BASE_CONFIG) != expected_base:
        raise ValueError('base FJSP formal config hash mismatch')
    base = json.loads(BASE_CONFIG.read_text())
    eohs_rule = ROOT / 'baselines/tier1_single_rule_v1/rules/eohs_heuristic_0_reference.py'
    if sha256(eohs_rule) != '3c7b2813a54b30385784c5d99f2eccf79ac85effb76ec41d62a0737aae5adb9e':
        raise ValueError('EoH-S comparison rule changed')
    sources = [
        'experiments/tier1/prepare_single_rule.py',
        'experiments/tier1/run_eoh_single.py',
        'experiments/tier1/evaluate_single_rule.py',
        'experiments/tier1/preflight.py',
        'code/llm4ad/task/optimization/fjsp_set/instances.py',
        'code/llm4ad/task/optimization/fjsp_set/scheduler.py',
        'code/llm4ad/task/optimization/fjsp_set/template.py',
        'code/llm4ad/task/optimization/fjsp_set/evaluation.py',
        'code/llm4ad/method/eoh/eoh.py',
        'code/llm4ad/method/eoh/population.py',
        'code/llm4ad/method/eoh/prompt.py',
        'code/llm4ad/method/eoh/sampler.py',
        'code/llm4ad/method/eoh/profiler.py',
        'code/llm4ad/base/evaluate.py',
        'code/llm4ad/base/sample.py',
        'code/llm4ad/base/code.py',
        'code/llm4ad/tools/llm/llm_api_https.py',
        'code/llm4ad/tools/profiler/profile.py',
    ]
    config = {
        'protocol_version': 1,
        'experiment': 'Tier1 FJSP single general constructive priority rule using EoH',
        'git_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                            text=True).strip(),
        'base_fjsp_config': str(BASE_CONFIG.relative_to(ROOT)),
        'base_fjsp_config_sha256': expected_base,
        'split': base['split'],
        'data_root': 'data/fjsp',
        'data_file_sha256': {name: info['sha256']
                             for name, info in base['data']['files'].items()},
        'candidate_contract': {
            'function': 'priority(processing_time, remaining_work, remaining_operations, job_ready_time, machine_ready_time, earliest_start, earliest_finish) -> float',
            'scheduler': 'unchanged append-only scheduler selects the highest finite priority',
            'training_fitness': 'arithmetic mean of all 21 per-instance normalized scores',
            'instance_score': '-makespan/lower_bound; higher is better',
        },
        'stages': {
            'smoke': {'seed': 2026092001, 'max_sample_nums': 6,
                      'max_generations': 5, 'pop_size': 2,
                      'num_samplers': 1, 'num_evaluators': 1,
                      'timeout_seconds': 180, 'debug_mode': False},
            'formal': {'seed': 2026092002, 'max_sample_nums': 40,
                       'max_generations': 10, 'pop_size': 5,
                       'num_samplers': 1, 'num_evaluators': 1,
                       'timeout_seconds': 180, 'debug_mode': False},
        },
        'model': 'deepseek-flash',
        'model_seed_note': 'host and NumPy seeds are fixed; the API exposes no confirmed server-side seed',
        'selection': {
            'candidate_pool': 'final EoH population only',
            'criterion': 'highest arithmetic mean normalized score on all 11 validation instances',
            'tie_break': 'lower final-population index',
            'test_used': False,
        },
        'comparison': {
            'partitions': ['train', 'validation'],
            'methods': ['selected_EoH', 'EFT', 'SPT', 'MWKR', 'EoHS_heuristic_0'],
            'eohs_rule': str(eohs_rule.relative_to(ROOT)),
            'eohs_rule_sha256': sha256(eohs_rule),
            'groupings': ['exact jobs x machines', 'jobs', 'machines'],
            'worst_group': 'minimum selected-rule mean normalized score; also report minimum mean gap versus EFT',
        },
        'test_policy': 'The 28-instance test split is excluded from generation, selection, comparison and tuning.',
        'source_sha256': {name: sha256(ROOT / name) for name in sources},
    }
    args.output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    digest_path.write_text(sha256(args.output) + '\n')
    print(json.dumps({'config': str(args.output), 'sha256': sha256(args.output),
                      'train': len(base['split']['train']),
                      'validation': len(base['split']['validation']),
                      'test_excluded': len(base['split']['test'])}, indent=2))


if __name__ == '__main__':
    main()
