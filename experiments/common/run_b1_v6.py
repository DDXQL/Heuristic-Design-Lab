#!/usr/bin/env python3
"""B1-V6：历史冻结10H/train21，真实初始化→50代演化→导出并冻结训练冠军
本轮1050次已获明确授权，由用户终端启动；--check-only不请求API、不求解。
恢复用本脚本 --resume RUN_DIR，读取原Protocol，不读新顶部参数。
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
# ===== 实际参数：获得具体预算授权后，才将real_requests_authorized改为True =====
PARAMETERS = {'problem': 'fjsp',
 'state_schema': 'constructive-common-v1-fjsp',
 'evaluation_mode': 'solve',
 'search_seed': 501,
 'solve_seed': 501,
 'api_concurrency': 2,
 'evaluation_concurrency': 2,
 'window': 10,
 'enabled_groups': ['construction', 'action_cost', 'trajectory', 'usage'],
 'instance_timeout_seconds': 30,
 'h_file': 'preparations/b1-v6-20261029/H_frozen.json',
 'data_manifest': 'preparations/b1-v6-20261029/train21.manifest.json',
 'real_requests_authorized': True,
 'api_mode': 'real',
 'initialization': 'llm',
 'population_size': 10,            # 收集10个完整train21有效且AST去重的初始U
 'generations': 50,                # 每代每父代CROSS一次、独立MUTATE一次
 'generation_request_cap': 1000,   # 2*N*G；失败/重复也占逻辑预算，无自动补发
 'initialization_candidate_cap': 50,
 'initialization_request_cap': 50,
 'api_attempt_cap': 1050,          # 初始化50 + 演化1000；不是美元硬封顶
 'recording_mode': 'compact',      # 保留排程/H序列/两遍证据；不保存大动作表/状态轨迹
 'milestone_generations': [10, 20, 30, 40, 50],
 'p0_file': None,
 'provider': {'endpoint': 'https://leafapi.cc/v1/chat/completions',
              'model': 'gpt-6.1-sol',
              'protocol': 'openai-chat-v1',
              'api_key_env': 'LEAFAPI_API_KEY',
              'connect_timeout': 10,
              'read_timeout': 240,
              'total_timeout': 300,
              'max_output_tokens': 8192,
              'max_prompt_bytes': 262144,
              'temperature': None,
              'reasoning_effort': None,
              'expected_response_model': 'gpt-6.1-sol',
              'stream_response': True}}
R1_RUNS = {'common': 'runs/b1-v6-r1-train21-20261029-221535-858514-d3145ddd',
 'legacy': 'runs/b1-v6-r1-legacy-train21-20261030-100428-400291-dd2640cb',
 'eoh': 'runs/b1-v6-r1-eoh-train21-20261030-111505-503272-95a4a92f'}
RUN_ROOT = ROOT / "runs"  # 可改为 Path('/Volumes/外置卷/HDL-runs')；整个运行保存在该目录
RUN_PREFIX = "b1-v6-b1"
MIN_FREE_GIB = None  # 仅显示剩余空间，不设磁盘容量启动门槛；不改变API授权或预算
R3_RUN_DIR = 'runs/b1-v6-r3-20261030-134523-982946-70326e84'  # 已通过，不重复运行
R3_COMPATIBILITY_FILE = 'reports/b1-v6-n10g50-prepared-20261030/recording-compatibility.json'
AUTHORIZATION_FILE = 'reports/b1-v6-n10g50-prepared-20261030/AUTHORIZATION.json'  # 用户已批准本轮1050次；单次认领
# ===== 参数区结束；以下不实现新的API、演化、并发或恢复逻辑 =====
import argparse
import sys
sys.path[:0]=[str(ROOT/"code"),str(ROOT)]
from experiments.common._real_run import launch,existing

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_mutually_exclusive_group()
    actions.add_argument("--check-only",action="store_true")
    actions.add_argument("--resume",type=Path,help="仅安全paused；忽略新顶部参数，继承冻结预算")
    actions.add_argument("--export",type=Path,help="离线重导出并生成配对表，不求解/请求API")
    args=parser.parse_args()
    try:
        if args.resume or args.export:return existing(args.resume or args.export,root=ROOT,resume=bool(args.resume))
        return launch(PARAMETERS,root=ROOT,stage="b1",run_root=RUN_ROOT,prefix=RUN_PREFIX,
                      min_free_gib=MIN_FREE_GIB,r1_runs=R1_RUNS,pilot_run=R3_RUN_DIR,
                      entry=Path(__file__),check_only=args.check_only,authorization_file=AUTHORIZATION_FILE,
                      r3_compatibility_file=R3_COMPATIBILITY_FILE)
    except Exception as exc:
        print(f"启动停止：{type(exc).__name__}: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
