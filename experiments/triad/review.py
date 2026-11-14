#!/usr/bin/env python3
"""Assemble independent configs from one human review. Never runs anything."""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import configuration


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--review',type=Path,default=ROOT/'experiments/triad/study-review.draft.json');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--groups',nargs='+',choices=configuration.GROUPS,default=list(configuration.GROUPS))
    a=ap.parse_args();review=read(a.review);out=a.output.resolve()
    if out.exists():raise FileExistsError('new reviewed-config directory required; no overwrite of any batch')
    out.mkdir(parents=True);rows=[]
    if len(set(a.groups))!=len(a.groups):raise ValueError('distinct selected groups required')
    for group in a.groups:
        source=ROOT/'experiments/triad/recommended.draft'/(group+'.json');c=configuration.load(source)
        common=review['common']
        for key,value in common.items():
            if key=='resources':c['resources'].update(value)
            else:c[key]=value
        patch=copy.deepcopy(review['groups'].get(group,{}))
        if 'resources' in patch:c['resources'].update(patch.pop('resources'))
        c.update(patch);c.update(repeat_count=review['repeat_count'],search_seeds=review['search_seeds']);c['real_requests_authorized']=False
        if c['problem']=='obp' and review.get('adopt_obp_candidate_state') is True and review.get('adopt_study_parameters') is True:c['state_delivery']={**c['state_delivery'],'adoption':'adopted'}
        if review.get('adopt_study_parameters') is True or group in review.get('adopt_groups',[]):
            c['freeze_status']='frozen';c['protocol_receipt']={'manual_review_file_sha256':sha(a.review),'adoption_source':'explicit human-edited review document; not API authorization'}
        else:c['freeze_status']='draft_unapproved'
        target=out/'configs'/(group+'.json')
        # Keep known asset paths portable. User-supplied new bindings must be absolute.
        for key in ('data_manifest','h_file','reference_file','frozen_u_template','compatible_fixed_results'):
            if c.get(key):
                p=Path(c[key])
                if not p.is_absolute():p=(a.review.parent/p).resolve()
                c[key]=os.path.relpath(p,target.parent)
        if isinstance(c['state_delivery'],dict):
            state_file=Path(c['state_delivery']['file'])
            if not state_file.is_absolute():state_file=(a.review.parent/state_file).resolve()
            c['state_delivery']['file']=os.path.relpath(state_file,target.parent)
        write(target,c);validated=configuration.load(target);rows.append({'group':group,'config':str(target),'pending':configuration.gaps(validated)})
    seeds=review['search_seeds'];count=review['repeat_count']
    write(out/'campaign.json',{'version':'triad-serial-batch-v1','campaign_id':review['campaign_id'],'repeat_count':count,'search_seeds':seeds,'global_generation_tasks':1,
      'run_root':str(ROOT/'runs'/review['campaign_id']),'groups':[{'group':g,'config':'configs/'+g+'.json'} for g in a.groups]})
    write(out/'review-status.json',{'adopted':review['adopt_study_parameters'],'adopted_groups':a.groups if review['adopt_study_parameters'] else review.get('adopt_groups',[]),'groups':rows,'API_requests':0,'actual_solves':0,'credential_reads':0})
    print(json.dumps({'campaign':str(out/'campaign.json'),'groups':rows,'API_requests':0,'actual_solves':0},ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as x:print(json.dumps({'error_type':type(x).__name__,'error':str(x)},ensure_ascii=False),file=sys.stderr);raise SystemExit(2)
