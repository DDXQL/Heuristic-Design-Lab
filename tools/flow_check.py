#!/usr/bin/env python3
"""One bounded FJSP scheme-A engineering flow; default check-only, no solving."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core import flow_check as f
from heuristic_design.core.storage import read,sha

OUTBOX=Path('/Users/DDXQL/Developer/transfer-outbox')


def bundle():
    p,_,_,_=f.preflight()
    names=list(p['files'])+['deploy/flow-check/plan.json','deploy/flow-check/plan.sha256']
    OUTBOX.mkdir(parents=True,exist_ok=True)
    out=OUTBOX/'fjsp-state-a-flow-20261112.zip'
    if out.exists():
        with zipfile.ZipFile(out) as z:
            if set(z.namelist())!=set(names):raise ValueError('existing bundle differs; preserve it')
            import hashlib
            for name in names:
                if hashlib.sha256(z.read(name)).hexdigest()!=sha(ROOT/name):
                    raise ValueError('existing bundle content differs; do not overwrite')
    else:
        with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
            for name in names:z.write(ROOT/name,name)
        out.with_suffix('.zip.sha256').write_text(sha(out)+'  '+out.name+'\n')
    return out


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',nargs='?',default='check-only',choices=['check-only','run','resume','status','stop','export','bundle','check-mac-export'])
    parser.add_argument('--site',choices=['mac','cluster'],default='mac')
    parser.add_argument('--allow-api',action='store_true');parser.add_argument('--approve-api',type=int)
    parser.add_argument('--allow-evaluation',action='store_true');parser.add_argument('--approve-solves',type=int)
    parser.add_argument('--mac-export',type=Path)
    args=parser.parse_args(argv)
    try:
        p,_,_,_=f.preflight();d=f.directory(args.site)
        if args.action=='check-only':
            value={'offline':True,'model_requests':0,'solves':0,'version':f.VERSION,'plan_sha256':sha(f.PLAN),
                'new_api_cap':2,'new_total_solve_cap':12,'per_site_solve_cap':6,'old_budget_inherited':False,
                'state_abi':f.u.ABI,'state_spec':f.state_a.SPEC_SHA256,'wire':f.WIRE_VERSION,
                'data':'one 9-operation synthetic FJSP development instance; no holdout',
                'tasks':list(f.ROLES),'preplanned_pause':'after settled fixed_H0; same clock/budget resume once',
                'prompts':[{'role':role,'bytes':len(f.prompt(role,read(ROOT/p['members'])).encode()),
                            'sha256':hashlib.sha256(f.prompt(role,read(ROOT/p['members'])).encode()).hexdigest()} for role in f.ROLES[1:]],
                'tsp':'not run: frozen LKH reference provenance still needed; no NN substitute'}
        elif args.action in ('run','resume'):
            result=f.run(args.site,resume=args.action=='resume',allow_api=args.allow_api,approve_api=args.approve_api,
                allow_evaluation=args.allow_evaluation,approve_solves=args.approve_solves,mac_export=args.mac_export)
            value={**result,'summary':f.Adapter().summary(d),'export':str(d/'export.json')}
            print(json.dumps(value,ensure_ascii=False,indent=2))
            e=read(d/'export.json')
            return 0 if result['phase']=='completed' and e.get('cross_platform_passed',True) else 2
        elif args.action=='status':
            value=f.Adapter().summary(d) if (d/'checkpoint.json').exists() else {'phase':'incomplete_preparation' if d.exists() else 'not_started'}
        elif args.action=='stop':value=f.execution.stop(d,adapter=f.Adapter())
        elif args.action=='export':value={'export':str(f.export(args.site)),'model_requests':0,'solves':0}
        elif args.action=='check-mac-export':
            value={'admitted':True,'summary':f.accept_mac_export(args.mac_export)['summary'],'model_requests':0,'solves':0}
        else:value={'bundle':str(bundle()),'model_requests':0,'solves':0}
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0
    except Exception as error:
        # No credential values appear in these local gate errors. Wire errors are
        # redacted before the shared executor writes its preserved Stop receipt.
        print(type(error).__name__+': '+str(error),file=sys.stderr);return 2


if __name__=='__main__':raise SystemExit(main())
