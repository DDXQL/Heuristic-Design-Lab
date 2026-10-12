#!/usr/bin/env python3
"""Check Leaf configuration, query token metadata, or launch a staged run."""

import argparse
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'code'))

from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.leafapi import load_local_key, query_status, KEY_ENV


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('check','status','preflight','generate-h','review-h','freeze-h',
                                         'initialize-u','search-arm','search','select','freeze','test','report'))
    credentials = parser.add_mutually_exclusive_group()
    credentials.add_argument('--prompt-key', action='store_true', help='在终端隐藏输入，仅设置本进程环境变量，不读写密钥文件')
    credentials.add_argument('--env-file',type=Path,help='显式从既有本机密钥文件加载到进程环境；API 客户端仍只读环境变量')
    parser.add_argument('--config',type=Path,default=ROOT/'experiments/tier2/research_real_v1/config.api-pilot.draft.json')
    parser.add_argument('--run-dir',type=Path)
    parser.add_argument('--reviews',type=Path)
    parser.add_argument('--resume',action='store_true')
    parser.add_argument('--seed',type=int)
    parser.add_argument('--arm',choices=('B0','B1','B2','P'))
    args = parser.parse_args()
    config = ExperimentConfig.from_dict(json.loads(args.config.read_text()))
    if config.provider.api_key_env != KEY_ENV or config.provider.endpoint != 'https://leafapi.cc/v1/chat/completions':
        parser.error('此入口只接受独立 LEAFAPI_API_KEY 和 leafapi.cc 配置')
    if args.prompt_key:
        if not sys.stdin.isatty():
            parser.error('--prompt-key 需要交互式本机终端；不接受管道输入')
        os.environ[KEY_ENV] = getpass.getpass('API key（隐藏输入，仅本进程环境变量）：').strip()
    elif args.env_file:
        try:
            os.environ[KEY_ENV] = load_local_key(args.env_file)
        except ValueError as exc:
            parser.error(str(exc))
    if args.stage == 'check':
        print('荷叶 API：'+config.provider.endpoint+'；模型：'+config.provider.model)
        print('账号申请额度：200元（用户提供，尚未查询核实，不等于已批准全部支出）。')
        print('真实生成授权：'+str(config.real_requests_authorized)+'；草案请求上限：'+str(config.total_request_cap))
        print('进程密钥环境变量：'+('已设置；尚未验证有效性。' if os.environ.get(KEY_ENV) else '未设置。'))
        print('仅离线检查，网络请求与模型请求均为0。')
        return
    if args.stage == 'status':
        try:
            key = os.environ.get(KEY_ENV)
            if not key:
                raise ValueError('请设置 LEAFAPI_API_KEY 或在终端使用 --prompt-key')
            # This deployment's observed canonical path ends in '/'. No redirect following.
            result = query_status(key,quota_path='/api/usage/token/')
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result,ensure_ascii=False,indent=2))
        print('这是令牌额度/模型列表查询，不调用模型；原始额度单位不能直接当人民币。')
        return
    if not args.run_dir:
        parser.error('分阶段执行须指定新的 --run-dir；旧配置目录不能混用')
    env = dict(os.environ)
    # Only candidate generation needs the key. Validation/test/report/preflight do not.
    if args.stage in ('generate-h','initialize-u','search-arm','search'):
        try:
            config.check_dispatch()
            if not env.get(KEY_ENV):
                raise ValueError('请设置 LEAFAPI_API_KEY 或在终端使用 --prompt-key')
        except ValueError as exc:
            parser.error(str(exc))
    command = [sys.executable,str(ROOT/'experiments/tier2/research_real_v1/run.py'),args.stage,
        '--config',str(args.config),'--manifest',str(ROOT/'data/fjsp_manifest.json'),'--run-dir',str(args.run_dir)]
    if args.resume: command.append('--resume')
    if args.reviews: command += ['--reviews',str(args.reviews)]
    if args.seed is not None: command += ['--seed',str(args.seed)]
    if args.arm is not None: command += ['--arm',args.arm]
    raise SystemExit(subprocess.run(command,cwd=ROOT,env=env).returncode)


if __name__ == '__main__':
    main()
