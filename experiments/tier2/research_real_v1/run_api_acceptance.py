#!/usr/bin/env python3
"""Train-only, tiny API acceptance; no formal comparisons or holdout stages."""

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'code'))

from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.integration_smoke import SmokeConfig, IntegrationSmoke
from fjsp_usage.research_real.leafapi import KEY_ENV, query_status, load_local_key
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.staged_evaluation import StagedDataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','preflight','status','generate-h','generate-h-sample','import-h-samples','review-h','generate-u'))
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--config',type=Path)
    parser.add_argument('--reviews',type=Path)
    parser.add_argument('--source-h',nargs=2,action='append',metavar=('RUN_DIR','REQUEST_ID'),
        help='Explicit previous h acceptance run and request ID; reuse response only, re-evaluate all train')
    parser.add_argument('--resume',action='store_true')
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument('--prompt-key',action='store_true',help='隐藏输入，只设置本进程环境变量')
    credentials.add_argument('--env-file',type=Path,help='按用户确认，从既有本机文件导入本进程环境；客户端只读环境')
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT/'runs') or directory == ROOT/'runs':
        parser.error('acceptance directory must be a child of project runs/')
    if directory.exists() and any(directory.iterdir()) and not args.resume:
        parser.error('nonempty directory requires --resume; changed source/config needs a new directory')
    if args.stage == 'review-h' and not args.reviews:
        parser.error('review-h requires a real --reviews file; it never fills approval automatically')
    if args.stage == 'import-h-samples':
        if not args.source_h or len(args.source_h) != 2:
            parser.error('import-h-samples requires exactly two --source-h RUN_DIR REQUEST_ID')
        for source,_ in args.source_h:
            if not Path(source).resolve().is_relative_to(ROOT/'runs'):
                parser.error('source acceptance runs must be children of project runs/')
    if args.prompt_key:
        if not sys.stdin.isatty():
            parser.error('--prompt-key requires an interactive local terminal, no piped credentials')
        os.environ[KEY_ENV] = getpass.getpass('API key（隐藏输入，仅本进程环境变量）：').strip()
    elif args.env_file:
        try:
            os.environ[KEY_ENV] = load_local_key(args.env_file)
        except ValueError as exc:
            parser.error(str(exc))
    with RunLock(directory):
        if args.stage == 'prepare':
            path = directory/'config.smoke.draft.json'
            if path.exists():
                parser.error('draft already exists; not overwritten')
            atomic_json(path,SmokeConfig().payload())
            atomic_json(directory/'scope.json',{'scope':'API integration acceptance only',
                'maximum_requests':20,'planned_requests':3,'estimated_cost_stop_CNY':5,
                'prices_unverified':True,'formal_experiments_authorized':False,
                'stages':'2 generated h/full train -> STOP for actual human review -> 1 U/full train',
                'holdout_access':False,'credential_source':'process environment only'})
            print('禁用请求的冒烟草案已准备；先核验 CNY 价格与 key 环境变量。')
            return
        if args.stage == 'status':
            key = os.environ.get(KEY_ENV)
            if not key:
                parser.error('LEAFAPI_API_KEY absent; use a local terminal --prompt-key')
            result = query_status(key,quota_path='/api/usage/token/')
            atomic_json(directory/'provider_status.json',result)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            return
        if not args.config:
            parser.error('this stage requires --config with its independent smoke budget')
        config = SmokeConfig.from_dict(json.loads(args.config.read_text()))
        if config.mode != 'real':
            parser.error('this CLI accepts real smoke only; local fixtures belong to tests')
        dataset = StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        smoke = IntegrationSmoke(directory,config=config,dataset=dataset,project_root=ROOT)
        try:
            if args.stage == 'preflight':
                try:
                    config.check_dispatch()
                    blocked = None
                except BudgetStop as exc:
                    blocked = str(exc)
                report = smoke.report('PREFLIGHT_BLOCKED' if blocked else 'PREFLIGHT_COMPLETE',blocked)
            elif args.stage == 'generate-h':
                report = smoke.generate_h()
            elif args.stage == 'generate-h-sample':
                report = smoke.generate_h_sample()
            elif args.stage == 'import-h-samples':
                report = smoke.import_h_samples(args.source_h)
            elif args.stage == 'review-h':
                smoke.review_h(json.loads(args.reviews.read_text()))
                report = smoke.read('Smoke_status.json','Integration_smoke_status')
            else:
                report = smoke.generate_u()
        except (BudgetStop,ValueError,FileNotFoundError) as exc:
            smoke.report('STOPPED',str(exc))
            print('停止：'+str(exc),file=sys.stderr)
            raise SystemExit(2)
        print(json.dumps({'stage':report['stage'],'reason':report['reason'],
            'confirmed_model_requests':report['budget']['confirmed_sends'],
            'reserved_request_slots':report['budget']['request_slots'],
            'budget':report['budget']},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
