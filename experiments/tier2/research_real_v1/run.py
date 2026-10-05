#!/usr/bin/env python3
"""S1-S6 staged runner. all-synthetic never calls an LLM or benchmark holdouts."""

import argparse
from contextlib import nullcontext
from dataclasses import replace
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'code'))

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.config import ExperimentConfig, ProviderConfig
from fjsp_usage.research_real.fixtures import fixture_server, fixture_response
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.staged_evaluation import StagedDataset, create_synthetic_dataset
from fjsp_usage.research_real.workflow import Workflow
from fjsp_usage.research_real.report import write_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('all-synthetic', 'preflight', 'generate-h', 'freeze-h',
                                         'search', 'select', 'freeze', 'test', 'report'))
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT/'runs') or directory == ROOT/'runs':
        parser.error('run directory must be a child of project runs/')
    if directory.exists() and any(directory.iterdir()) and not args.resume:
        parser.error('nonempty directory requires --resume; protocol changes require a new directory')
    with RunLock(directory):
        if args.stage == 'all-synthetic':
            saved = directory/'config.json'
            previous = ExperimentConfig.from_dict(json.loads(saved.read_text())) if saved.exists() else None
            if previous and previous.mode != 'synthetic':
                parser.error('all-synthetic cannot resume a real run')
            port = urlsplit(previous.provider.endpoint).port if previous else 0
            offset = len(json.loads((directory/'budget.json').read_text())['records']) if (directory/'budget.json').exists() else 0
            server = fixture_server(port=port, responder=lambda p, i: fixture_response(p, i+offset))
        else:
            server = nullcontext((None, None))
        with server as (endpoint, traffic):
            if args.stage == 'all-synthetic':
                config = previous or ExperimentConfig(provider=ProviderConfig(endpoint, 'HANDWRITTEN-HTTP-FIXTURE'),
                    H_size=3, H_initialization_cap=15, H_attempts=10, H_generations=1,
                    population_size=10, cross_parents=5, initialization_cap=20,
                    attempts_per_generation=10, generations=1, seeds=(101,102), total_request_cap=200)
                atomic_json(directory/'config.json', config.payload())
                manifest = directory/'fixtures/manifest.json'
                if not manifest.exists():
                    create_synthetic_dataset(manifest.parent)
                dataset_root = manifest.parent
            else:
                if not args.config or not args.manifest:
                    parser.error('staged commands require --config and --manifest')
                config = ExperimentConfig.from_dict(json.loads(args.config.read_text()))
                manifest = args.manifest.resolve()
                dataset_root = ROOT if config.mode == 'real' else manifest.parent
            dataset = StagedDataset(manifest, project_root=dataset_root, mode=config.mode)
            workflow = Workflow(directory, config=config, dataset=dataset, project_root=ROOT)
            actions = {'generate-h': workflow.generate_h, 'search': workflow.search_all,
                'select': workflow.select, 'freeze': workflow.freeze, 'test': workflow.test,
                'report': lambda: write_report(workflow),
                'freeze-h': lambda: workflow.freeze_h(json.loads(args.reviews.read_text()) if args.reviews else None)}
            try:
                if args.stage == 'all-synthetic':
                    for stage in ('generate-h', 'freeze-h', 'search', 'select', 'freeze', 'test', 'report'):
                        print('合成验收阶段：' + stage, flush=True)
                        actions[stage]()
                elif args.stage == 'preflight':
                    workflow.progress('PREFLIGHT_COMPLETE', split_files_opened=0)
                    print('配置与数据清单已校验；未打开任何实例，未创建模型客户端。', flush=True)
                else:
                    actions[args.stage]()
            finally:
                if traffic is not None:
                    atomic_json(directory/'fixture_traffic_latest.json', {'synthetic': True,
                        'http_posts_this_execution': len(traffic['requests']),
                        'request_ids': [p['request_id'] for p in traffic['requests']]})
            print('完成，报告/进度目录：' + str(directory), flush=True)


if __name__ == '__main__':
    main()
