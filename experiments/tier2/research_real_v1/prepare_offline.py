#!/usr/bin/env python3
"""Export disabled V5 protocol drafts; optionally calibrate on train, no API."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'code'))

from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.preparation import calibrate_training, write_preparation
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.config import ExperimentConfig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT/'data/fjsp_manifest.json')
    parser.add_argument('--calibrate-train', action='store_true')
    parser.add_argument('--calibration-timeout', type=float, default=10.0)
    parser.add_argument('--provider-config',type=Path,
        help='Use the provider from a disabled staged configuration, e.g. the Leaf API draft')
    args = parser.parse_args()
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT/'runs') or directory == ROOT/'runs':
        parser.error('output must be a new child directory under project runs/')
    if directory.exists() and any(directory.iterdir()):
        parser.error('output directory is nonempty; use a new directory')
    dataset = StagedDataset(args.manifest, project_root=ROOT, mode='real')
    provider = None
    if args.provider_config:
        selected = ExperimentConfig.from_dict(json.loads(args.provider_config.read_text()))
        if selected.real_requests_authorized:
            parser.error('offline preparation accepts only a disabled provider draft')
        provider = selected.provider
    with RunLock(directory):
        calibration = None
        if args.calibrate_train:
            print(f'离线校准：仅 {len(dataset.names["train"])} 个 train；不加载真实 validation/test。', flush=True)
            calibration = calibrate_training(dataset, timeout=args.calibration_timeout)
        # RunLock creates a transient lock file: keep the export under a subdirectory.
        plan = write_preparation(directory/'artifacts', root=ROOT, dataset=dataset, calibration=calibration, provider=provider)
    print('准备完成：' + str(directory/'artifacts/offline_plan.json'), flush=True)
    print('模型请求：0；配置草案均禁止真实请求；正式规模和金额待确定。', flush=True)
    if calibration is not None and not calibration['all_batches_valid']:
        raise SystemExit('校准存在失败，请检查记录；没有据此确定正式期限。')


if __name__ == '__main__':
    main()
