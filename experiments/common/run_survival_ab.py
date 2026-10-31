#!/usr/bin/env python3
"""One shared-P0 A/B pair. Preview is offline; paid execution stays OFF.
A=original Fitness survival, B=behavior representatives then ranked fill.
No automatic seed loop. Historical authorization is never imported.
"""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SOURCE_WORKSPACE=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab')
P0_SOURCE=SOURCE_WORKSPACE/'runs/b1-v6-b1-20261030-155904-688532-7ced645e'
PAIR_DIRECTORY=ROOT/'runs/survival-ab-seed501-01'  # A/B must use this same NEW pair directory
PAIR_API_ATTEMPT_CAP=2000  # 1000 A + 1000 B; historical P0 initialization cost is separate
AUTHORIZATION_FILE=None  # no new paid authorization is created by this task
PARAMETERS={
 'problem':'fjsp','state_schema':'constructive-common-v1-fjsp',
 'api_mode':'real','real_requests_authorized':False,'evaluation_mode':'solve',
 'initialization':'import','population_size':10,'generations':50,
 'search_seed':501,'solve_seed':501,'initialization_candidate_cap':10,'initialization_request_cap':10,
 'generation_request_cap':1000,'api_attempt_cap':1000,
 'api_concurrency':2,'evaluation_concurrency':2,'instance_timeout_seconds':30,
 'window':10,'enabled_groups':['construction','action_cost','trajectory','usage'],
 'recording_mode':'compact','milestone_generations':[10,20,30,40,50],'survival_policy':'fitness',
 'h_file':str(SOURCE_WORKSPACE/'preparations/b1-v6-20261029/H_frozen.json'),
 'data_manifest':str(SOURCE_WORKSPACE/'preparations/b1-v6-20261029/train21.manifest.json'),'p0_file':None,
 'provider':{'endpoint':'https://leafapi.cc/v1/chat/completions','model':'gpt-6.1-sol','protocol':'openai-chat-v1',
  'api_key_env':'LEAFAPI_API_KEY','connect_timeout':10,'read_timeout':240,'total_timeout':300,
  'max_output_tokens':8192,'max_prompt_bytes':262144,'temperature':None,'reasoning_effort':None,
  'expected_response_model':'gpt-6.1-sol','stream_response':True}}
# Parameters end. Reuse existing engine and frozen recovery, never reimplement them.
import argparse,json,sys
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.common._survival_ab import preview,show,launch,existing_arm,read_pair

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check-only',action='store_true')
    action.add_argument('--arm',choices=('A','B'))
    action.add_argument('--resume',choices=('A','B'))
    action.add_argument('--export',choices=('A','B'))
    parser.add_argument('--pair-dir',type=Path,default=PAIR_DIRECTORY)
    args=parser.parse_args();directory=(ROOT/args.pair_dir).resolve()
    try:
        if args.resume or args.export:return existing_arm(directory,args.resume or args.export,root=ROOT,resume=bool(args.resume))
        if directory.exists():plan=read_pair(directory,ROOT)
        else:plan=preview(PARAMETERS,source=P0_SOURCE,pair_directory=directory,root=ROOT,entry=Path(__file__),pair_attempt_cap=PAIR_API_ATTEMPT_CAP)
        print(json.dumps(show(plan),ensure_ascii=False,indent=2))
        if args.check_only:return 0
        return launch(plan,args.arm,root=ROOT,entry=Path(__file__),authorization_file=AUTHORIZATION_FILE)
    except Exception as exc:
        print(f'Pair stopped: {type(exc).__name__}: {exc}',file=sys.stderr);return 2

if __name__=='__main__':raise SystemExit(main())
