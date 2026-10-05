#!/usr/bin/env python3
"""Read-only compact snapshot of an offline run; no model/token consumption."""

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    args = parser.parse_args()
    for label in ('shared_initial', 'B0', 'B1', 'B2', 'P', 'H_adapter'):
        checkpoint = args.run_dir / label / 'checkpoint.json'
        if not checkpoint.exists():
            print(f'{label}: 尚未启动')
            continue
        data = json.loads(checkpoint.read_text())
        valid = sum(a['status'] == 'valid' for a in data['attempts'])
        pending = data.get('inflight')
        print(f'{label}: {data["phase"]} | 已完成代 {data["generation"]} | '
              f'尝试 {len(data["attempts"])} | 有效 {valid} | '
              f'正在处理 {pending["id"] if pending else "无"}')


if __name__ == '__main__':
    main()
