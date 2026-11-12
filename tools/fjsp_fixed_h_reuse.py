#!/usr/bin/env python3
"""Read specified fixed-H receipts and derive J. No H execution or solver."""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,sha,write,digest
from heuristic_design.core.terminal_ops import inputs
from heuristic_design.problems.routing_fixtures import precheck_instances,compile_members


def audit(source,output):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.exists():raise FileExistsError('new derived directory required; historical evidence is preserved')
    prep=source/'preparations/b1-v6-20261029'
    base=source/'reports/tier2-baseline-a-train21-seed501-20261024-v1'
    origin=source/'reports/baseline-a-provenance-timeout-audit-20261024-v1'
    hp=prep/'H_frozen.json';dp=prep/'train21.manifest.json'
    h=read(hp);manifest=read(dp);protocol=read(base/'Protocol.json')
    hs,data,provenance=inputs({'problem':'fjsp','h_file':str(hp),'data_manifest':str(dp)})
    compile_members('fjsp',hs)
    references=precheck_instances('fjsp',data)
    if len(hs)!=10 or len(data)!=21:raise ValueError('this reuse audit binds exactly existing 10H/train21')
    if [v['key'] for v in hs]!=protocol['H_order']:raise ValueError('H order/key mismatch')
    mapping=list(csv.DictReader((origin/'H_mapping.csv').open()))
    if [r['code_key'] for r in mapping]!=[v['key'] for v in hs]:raise ValueError('provenance H order mismatch')
    if [r['file'] for r in manifest['instances']]!=[r['file'] for r in protocol['instances']]:raise ValueError('train order mismatch')
    instance_rows=[]
    for current,old,ref in zip(manifest['instances'],protocol['instances'],references):
        if current['sha256']!=old['sha256'] or ref['reference']!=old['LB']:raise ValueError('data hash/LB mismatch')
        instance_rows.append({'file':current['file'],'source_sha256':current['sha256'],'LB':ref['reference']})
    costs=[r for r in csv.DictReader((base/'All_instances_1155.csv').open()) if r['strategy'] in {f'H{i}' for i in range(10)}]
    if len(costs)!=210 or len({(r['strategy'],r['file']) for r in costs})!=210:raise ValueError('missing/duplicate fixed-H receipt')
    output.mkdir(parents=True)
    derived=[];members=[]
    for i,member in enumerate(h['members']):
        rows=[r for r in costs if r['strategy']==f'H{i}']
        source_result=member['training_result']
        if not source_result['valid'] or source_result['total_instances']!=21 or len(source_result['instances'])!=21:
            raise ValueError('missing complete source validity')
        if [r['file'] for r in rows]!=[r['file'] for r in manifest['instances']]:raise ValueError('fixed-H result order mismatch')
        for row,ref,original in zip(rows,references,source_result['instances']):
            if row['complete_strategy_valid']!='True' or row['status']!='complete' or not row['native_recheck_sha256']:
                raise ValueError('missing accepted complete/two-solve receipt')
            cost=float(row['Cmax']);lb=float(row['LB']);old_score=float(row['score'])
            if not math.isfinite(cost) or lb!=ref['reference'] or not math.isclose(old_score,-cost/lb,rel_tol=0,abs_tol=1e-12):
                raise ValueError('cost/reference/old-score mismatch')
            if (original['file']!=row['file'] or original['makespan']!=cost or original['lower_bound']!=lb
                    or not original['feasible'] or original['deterministic_schedule_sha256']!=row['native_recheck_sha256']):
                raise ValueError('original complete result/recheck does not match reused receipt')
            derived.append({'H':f'H{i}','H_key':hs[i]['key'],'file':row['file'],'Cmax':cost,'LB':lb,
                'old_score':old_score,'J':(cost-lb)/lb,'native_recheck_sha256':row['native_recheck_sha256'],
                'valid':True,'timing_reused_as_current':False})
        j=sum(r['J'] for r in derived if r['H']==f'H{i}')/21
        if not math.isclose(j,-member['fitness']-1,rel_tol=0,abs_tol=1e-12):raise ValueError('new/old aggregate mapping mismatch')
        members.append({'H':f'H{i}','key':hs[i]['key'],'J':j,'complete_instances':21})
    with (output/'fixed-H-train21-J.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(derived[0]));w.writeheader();w.writerows(derived)
    files=[hp,dp,base/'Protocol.json',base/'All_instances_1155.csv',base/'Summary.json',origin/'H_mapping.csv',origin/'H_origin_checks.json']
    result={'scope':'STATIC_RECEIPT_REUSE_NOT_REEVALUATION','model_requests':0,'solves':0,
        'H_order':[r['key'] for r in hs],'instances':instance_rows,'complete_rows':210,
        'ranking':sorted(members,key=lambda r:(r['J'],r['H'])),
        'source_files':{str(p):sha(p) for p in files},
        'actions':'append-only; highest selected-H raw score; exact ties first original action; unchanged H scalar arguments',
        'compatibility_status':'compatible historical quality reference; final new-state commit still required',
        'validity_boundary':protocol['cache_contract'],
        'timing':'historical timing is not a same-environment measurement; no 420 new solves',
        'state_boundary':'extra sensors must not change H inputs, action enumeration, append semantics or ties; verify final state delivery',
        'input_provenance':provenance}
    write(output/'compatibility.json',result)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();r=audit(args.source_root,args.output)
    print(json.dumps({k:r[k] for k in ('scope','model_requests','solves','complete_rows','ranking')},ensure_ascii=False,indent=2))
