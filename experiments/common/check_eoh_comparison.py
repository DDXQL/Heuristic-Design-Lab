#!/usr/bin/env python3
"""Read-only EoH preparation audit. This entry has no training action."""
import argparse
import json
from pathlib import Path
from statistics import fmean
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read, sha

CONFIG=ROOT/'experiments/common/configs/eoh-comparison.pending.json'
HISTORICAL_ROOT=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab')
RUN='runs/b1-v6-r1-eoh-train21-20261030-111505-503272-95a4a92f'


def audit(config_path=CONFIG, historical_root=HISTORICAL_ROOT):
    c=read(config_path)
    if c['training_enabled'] is not False or c['real_requests_authorized'] is not False:
        raise ValueError('preparation entry cannot enable or authorize EoH training')
    manifest=read(ROOT/'baselines/tier1_single_rule_v1/portable_manifest.json')
    directory=historical_root/RUN
    if sha(directory/'Protocol.json')!=(directory/'Protocol.sha256').read_text().strip():
        raise ValueError('historical protocol hash mismatch')
    state=read(directory/'checkpoint.json');summary=read(directory/'results/Summary.json')
    if state['phase']!='completed' or not summary['valid'] or summary['API_requests']!=0:
        raise ValueError('historical fixed evaluation is incomplete')
    if sha(directory/'Frozen_native_rule.py')!=manifest['rules']['canonical']['sha256']:
        raise ValueError('canonical source mismatch')
    evaluations=[]
    for record in state['evaluations'].values():
        path=directory/record['path']
        if record['status']!='completed' or sha(path)!=record['sha256']:raise ValueError('evaluation receipt mismatch')
        value=read(path);rows=value['instances']
        if not value['valid'] or len(rows)!=21 or any(r['captured_solves']!=2 or not r['feasible'] for r in rows):
            raise ValueError('complete 21-instance solve/recheck required')
        fitness=fmean(r['score'] for r in rows)
        if fitness!=value['fitness'] or fitness!=summary['fitness']:raise ValueError('historical summary mismatch')
        evaluations.append({'fitness':fitness,'complete_instances':len(rows),'result_sha256':sha(path)})
    if len(evaluations)!=1:raise ValueError('expected exactly one canonical evaluation')
    return {'historical_run':str(directory),'historical_protocol_sha256':sha(directory/'Protocol.json'),
        'historical_evaluation':evaluations[0],
        'historical_model':manifest['experiment']['llm']['name'],
        'historical_budget':manifest['experiment']['budget_per_seed'],
        'historical_selection':manifest['experiment']['selection'],
        'pending_fields':[k for k,v in c.items() if v is None],
        'training_ready':False,'training_enabled':False,'API_requests':0,'solves':0,
        'notice':'Historical frozen-rule quality reference only; current-model budget-matched EoH training is not implemented or authorized.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only',action='store_true',required=True)
    parser.add_argument('--config',type=Path,default=CONFIG)
    parser.add_argument('--historical-root',type=Path,default=HISTORICAL_ROOT)
    args=parser.parse_args()
    try:print(json.dumps(audit(args.config,args.historical_root),ensure_ascii=False,indent=2));return 0
    except (ValueError,KeyError,FileNotFoundError) as exc:
        print(f'EoH核对停止：{exc}',file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
