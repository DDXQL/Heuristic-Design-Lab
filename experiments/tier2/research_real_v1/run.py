#!/usr/bin/env python3
"""Staged runner; new request_budget protocols use local counters, no Leaf metadata.

all-synthetic never calls an LLM or benchmark holdouts. Historical specialized
fair/update runners keep their original quota/settlement gates.
"""

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
from fjsp_usage.research_real.budget import BudgetStop


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('all-synthetic', 'preflight', 'bind-fixed-h', 'prepare-research', 'freeze-conditional-h', 'training-report', 'prepare-continuation', 'generate-h', 'review-h', 'freeze-h',
                                         'initialize-u', 'search-arm', 'search', 'select', 'freeze', 'test', 'report',
                                         'development-select','development-freeze','development-test','development-report'))
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--reviews', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--seed', type=int)
    parser.add_argument('--arm', choices=('B0','B1','B2','P'))
    parser.add_argument('--max-new-requests', type=int)
    args = parser.parse_args()
    if args.stage in ('initialize-u','search-arm') and args.seed is None:
        parser.error('this stage requires an explicitly declared --seed')
    if args.stage == 'search-arm' and args.arm is None:
        parser.error('search-arm requires --arm; it never dispatches other arms')
    if args.max_new_requests is not None and (args.stage != 'initialize-u' or args.max_new_requests < 1):
        parser.error('--max-new-requests requires initialize-u and a positive count')
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
            from fjsp_usage.research_real import development_acceptance
            from fjsp_usage.research_real import conditional_research
            from fjsp_usage.research_real.training_report import write_training_report
            from fjsp_usage.research_real.fixed_h import bind_h, source_bundle
            if config.fixed_h_source is not None:
                source_bundle(ROOT, config, dataset)
            actions = {'generate-h': workflow.generate_h, 'search': workflow.search_all,
                'bind-fixed-h': lambda: bind_h(workflow),
                'prepare-research': lambda: conditional_research.prepare(workflow),
                'freeze-conditional-h': lambda: conditional_research.freeze_h(workflow),
                'training-report': lambda: write_training_report(workflow),
                'prepare-continuation': workflow.prepare_continuation,
                'review-h': workflow.review_h,
                'initialize-u': lambda: workflow.initialize_u(args.seed, max_new_requests=args.max_new_requests),
                'search-arm': lambda: workflow.search_arm(args.seed, args.arm),
                'select': workflow.select, 'freeze': workflow.freeze, 'test': workflow.test,
                'report': lambda: write_report(workflow),
                'development-select': lambda: development_acceptance.selection(workflow),
                'development-freeze': lambda: development_acceptance.freeze(workflow),
                'development-test': lambda: development_acceptance.test(workflow),
                'development-report': lambda: development_acceptance.report(workflow),
                'freeze-h': lambda: workflow.freeze_h(json.loads(args.reviews.read_text()) if args.reviews else None)}
            try:
                if args.stage == 'all-synthetic':
                    for stage in ('generate-h', 'freeze-h', 'search', 'select', 'freeze', 'test', 'report'):
                        print('合成验收阶段：' + stage, flush=True)
                        actions[stage]()
                elif args.stage == 'preflight':
                    workflow.progress('PREFLIGHT_COMPLETE', split_files_opened=0)
                    print('配置、数据清单及适用的本地预算已校验；未打开实例、未创建模型客户端。', flush=True)
                else:
                    result = actions[args.stage]()
                    if args.stage in ('initialize-u','search-arm') and result['status'] not in ('initialized','completed','initialization_paused'):
                        raise BudgetStop('stage returned terminal failure: '+result['status'])
            except (BudgetStop, ValueError, FileNotFoundError) as exc:
                workflow.progress('STAGE_STOPPED', requested_stage=args.stage,
                    error_type=type(exc).__name__, reason=str(exc)[:500])
                print('阶段停止：'+str(exc),file=sys.stderr,flush=True)
                raise SystemExit(2)
            except KeyboardInterrupt:
                workflow.progress('STAGE_INTERRUPTED', requested_stage=args.stage)
                raise SystemExit(130)
            finally:
                if traffic is not None:
                    atomic_json(directory/'fixture_traffic_latest.json', {'synthetic': True,
                        'http_posts_this_execution': len(traffic['requests']),
                        'request_ids': [p['request_id'] for p in traffic['requests']]})
            print('完成，报告/进度目录：' + str(directory), flush=True)


if __name__ == '__main__':
    main()
