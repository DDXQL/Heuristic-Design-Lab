#!/usr/bin/env python3
"""R3：真实API接入与同代任务并发验收，最多8次尝试
修改顶部参数后一次运行。默认真实请求关闭；--check-only不请求API、不求解。
恢复用原common/manage.py resume --allow-api，读取原Protocol，不读新顶部参数。
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
 'population_size': 2,
 'generations': 1,
 'generation_request_cap': 4,
 'initialization_candidate_cap': 4,
 'initialization_request_cap': 4,
 'api_attempt_cap': 8,
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
RUN_ROOT = ROOT / "runs"
RUN_PREFIX = "b1-v6-r3"
MIN_FREE_GIB = 10  # 另按R1实测归档量计算预检门槛，不删除旧证据
AUTHORIZATION_FILE = "preparations/b1-v6-r3-20261030/authorization.json"  # 仅此8次批次
# ===== 参数区结束；以下不实现新的API、演化、并发或恢复逻辑 =====
import argparse
import sys
sys.path[:0]=[str(ROOT/"code"),str(ROOT)]
from experiments.common._real_run import launch

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only",action="store_true")
    args=parser.parse_args()
    try:
        return launch(PARAMETERS,root=ROOT,stage="r3",run_root=RUN_ROOT,prefix=RUN_PREFIX,
                      min_free_gib=MIN_FREE_GIB,r1_runs=R1_RUNS,pilot_run=None,
                      entry=Path(__file__),check_only=args.check_only,authorization_file=AUTHORIZATION_FILE)
    except Exception as exc:
        print(f"启动停止：{type(exc).__name__}: {exc}",file=sys.stderr)
        return 2

if __name__=="__main__":raise SystemExit(main())
