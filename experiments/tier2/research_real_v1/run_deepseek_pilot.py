#!/usr/bin/env python3
"""Check configuration without spending; run a bounded official DeepSeek pilot."""

import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'code'))

from fjsp_usage.research_real.deepseek_pilot import DeepSeekPilot, PilotConfig, load_local_key, input_metadata
from fjsp_usage.research_real.locking import RunLock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('check', 'run', 'report'))
    parser.add_argument('--key-file', type=Path, default=ROOT/'.env.deepseek.local')
    parser.add_argument('--run-dir', type=Path, default=ROOT/'runs/deepseek-pilot-20261008-v1')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    config = PilotConfig()
    if args.stage == 'check':
        print('官方 DeepSeek Flash；关闭思考；输出上限 2048 token；并发 1。')
        print('全局最多 50 次；阶段最多 1+6+12+10=29 次；预计费用停止线 3 元。')
        print('EFT/SPT 演示 H；一个微型实例及 train 前三个实例；不访问 validation/test。')
        rows = input_metadata(ROOT)
        print('输入路径检查：' + ('通过' if all(Path(r['path']).exists() for r in rows) else '有缺失文件'))
        try:
            load_local_key(args.key_file)
            print('本机密钥格式：已填写（未发送或验证有效性）。')
        except ValueError as exc:
            print('本机密钥：' + str(exc))
        print('此检查没有发起网络请求，也没有解析 benchmark 实例。')
        return
    directory = args.run_dir.resolve()
    if not directory.is_relative_to(ROOT/'runs') or directory == ROOT/'runs':
        parser.error('运行目录必须在项目 runs/ 内')
    if directory.exists() and any(directory.iterdir()) and not args.resume and args.stage == 'run':
        parser.error('已有运行须加 --resume；配置或源码改变须新建目录')
    if args.stage == 'report' and not (directory/'pilot_protocol.json').exists():
        parser.error('该目录还没有试跑记录')
    if args.stage == 'run':
        try:
            key = load_local_key(args.key_file)
        except ValueError as exc:
            parser.error(str(exc))
        os.environ['DEEPSEEK_API_KEY'] = key
    with RunLock(directory):
        pilot = DeepSeekPilot(directory, root=ROOT, config=config)
        result = pilot.run() if args.stage == 'run' else pilot.report()
    if result['stop_reason']:
        print('本次已停止：' + result['stop_reason'])
        sys.exit(2)


if __name__ == '__main__':
    main()
