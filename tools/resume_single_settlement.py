#!/usr/bin/env python3
"""Nonsemantic wire-recording/settlement amendment to the frozen d71fd1f batch.

No change to config, prompts, AST, evaluator, selection or candidate results.
Preserve failed slot/body absence. Resume the existing checkpoint's next slot.
Capture complete future replies BEFORE account checks can discard them.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
sys.path.insert(0,str(ROOT/'experiments/tier2/research_real_v1'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop
from fjsp_usage.research_real.config import ExperimentConfig
from fjsp_usage.research_real.leafapi import KEY_ENV,load_local_key
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.single_billing import match_invoice
from fjsp_usage.research_real.single_experiments import Guard
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from run_single_model_migration import MigrationWorkflow,finish

VERSION='single-ID-nonsemantic-recording-settlement-amendment-v1-20261014'
FAILED_KEY='r201/init/INIT/init/000005'
SUPPLIER_ID='202610141327527602746288268d9d6TjCvhB6b'


class WireRecorder:
    def __init__(self,inner,directory,verify=lambda:None):
        self.inner,self.directory,self.verify=inner,Path(directory),verify
        self.config,self.identity,self.secret,self.redact=inner.config,inner.identity,inner.secret,inner.redact
        self.directory.mkdir(exist_ok=True)

    def preflight(self,prompt):self.verify();return self.inner.preflight(prompt)

    def dispatch(self,key,prompt,*,kind='U',on_sent=lambda:None):
        self.verify()
        path=self.directory/(hashlib.sha256(key.encode()).hexdigest()+'.json')
        if path.exists():raise BudgetStop('wire recorder forbids request identity replay')
        record={'version':VERSION,'global_key':key,'prompt_key':digest({'prompt':prompt,'kind':kind}),
            'transport_identity':self.identity,'status':'pending','send_confirmed':False}
        atomic_json(path,record)
        def sent():record.update(send_confirmed=True);atomic_json(path,record);on_sent()
        try:
            reply=self.inner.dispatch(key,prompt,kind=kind,on_sent=sent)
            record.update(status='wire_completed_before_settlement',reply=reply)
            atomic_json(path,record)
            return reply
        except Exception as exc:
            record.update(status='wire_failed',error=self.redact(str(exc))[:500],
                usage=getattr(exc,'usage',None),metadata=getattr(exc,'metadata',{}) or {})
            atomic_json(path,record);raise


def reconcile(flow,quota):
    directory=flow.directory
    invoice_path=directory/'billing'/(hashlib.sha256(FAILED_KEY.encode()).hexdigest()+'.json')
    original=json.loads(invoice_path.read_text());old=original['original_quota_record']
    before=original['before']
    qpath=directory/'Settlement_recheck_02_quota.json';ipath=directory/'Settlement_recheck_02_invoices.json'
    q=json.loads(qpath.read_text());invoices=json.loads(ipath.read_text())
    if q.get('success') is not True or invoices.get('success') is not True:
        raise BudgetStop('final supplier settlement evidence unavailable')
    account={**old,'status':'settled','after_used':q['quota']['total_used'],
        'observed_account_delta':q['quota']['total_used']-old['before_used'],
        'finished_at':max(q['observed_at'],old['finished_at'])}
    invoice=match_invoice(before,invoices,account,flow.config.provider.model,failed=True,response_id=SUPPLIER_ID)
    if (invoice.get('group')!='codex-deafult' or invoice['quota']!=5946
            or original['wire_usage']!={'input_tokens':2072,'output_tokens':1964}
            or invoice.get('prompt_tokens')!=2072 or invoice.get('completion_tokens')!=1964
            or account['after_used']+quota.check_retained()>flow.config.platform_quota_ceiling):
        raise BudgetStop('restored settlement does not match original usage/group/debit or ceiling')
    target=directory/'Settlement_resume_proof.json'
    proof={'version':VERSION,'global_key':FAILED_KEY,'supplier_request_id':SUPPLIER_ID,
        'original_quota_record':old,'original_billing_sha256':hashlib.sha256(invoice_path.read_bytes()).hexdigest(),
        'invoice':invoice,'reconciled_account':account,'actual_platform_units':5946,
        'evidence_files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (qpath,ipath)},
        'wire_usage':original['wire_usage'],'slot_remains_failed':True,'lost_body_not_reconstructed':True,
        'historical_24million_hold_unchanged':True,'new_unknown_cost_reservation_released_by_invoice_only':410000}
    if target.exists():
        if json.loads(target.read_text())!=proof:raise BudgetStop('settlement proof changed')
        if quota.data['halted']:raise BudgetStop('another new stop requires its own evidence; no blanket unhalt')
        return proof
    if (quota.data.get('stop_reason')!='supplier billing metadata unavailable; no settlement inferred'
            or quota.data['records'].get(FAILED_KEY)!=old
            or any(r['status']=='pending' for r in quota.data['records'].values())
            or flow.ledger.data['halted']):
        raise BudgetStop('only the precisely identified 429 metadata gate can be reconciled')
    atomic_json(target,proof)
    quota.data.setdefault('invoice_reconciliations',[]).append(proof)
    quota.data.update(halted=False,stop_reason=None)
    quota.save()
    quota.balance()  # a fresh protected observation; stale receipts alone never allow sends
    return proof


def run(directory,env_file):
    c=ExperimentConfig.from_dict(json.loads((directory/'config.migration.authorized.json').read_text()))
    os.environ[KEY_ENV]=load_local_key(env_file)
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    own_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with RunLock(directory):
        flow=MigrationWorkflow(directory,config=c,dataset=ds,project_root=ROOT)
        guard=Guard(flow,flow.read('Worktree_binding.json','Worktree_binding'));guard.check()
        client=flow.client();quota=client.inner.inner
        amendment={'version':VERSION,'source_protocol_context':flow.context,'entry_file':str(Path(__file__)),
            'entry_sha256':own_sha,'change':'durable wire replies before settlement; explicit existing-checkpoint resume',
            'unchanged':['model parameters','prompt pack','candidate validation','state','evaluator','H','parents','survival','budget caps'],
            'prior_stop_retained':json.loads((directory/'r201/Initialization_status.json').read_text()),
            'next_init_cursor':6,'accepted_U_retained':4,'already_sent_diagnostic':1,'formal_already_sent':6,
            'remaining_formal_max':54,'no_request_replay':True,'no_old_model_candidates_imported':True,
            'authorization':'DDXQL current model batch plus autonomous nonsemantic recording repairs'}
        path=directory/'Execution_amendment.json'
        if path.exists():
            if json.loads(path.read_text())!=amendment:raise BudgetStop('execution amendment changed')
        else:atomic_json(path,amendment)
        def verify():
            guard.check()
            if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=own_sha or json.loads(path.read_text())!=amendment:
                raise BudgetStop('nonsemantic driver amendment changed during dispatch')
        stop=None
        try:
            reconcile(flow,quota)
            quota.transport=WireRecorder(quota.transport,directory/'wire_responses',verify)
            H,members=flow.h_asset()
            name='r201/Shared_initial.json'
            if not (directory/name).exists():
                engine=flow.search_engine('r201/INIT','INIT',members,c.u_search(201),'r201/init','r201/B0')
                if engine.state['init_cursor']<6 or len(engine.state['population'])<4:
                    raise BudgetStop('cannot discard previous initialized state/counters')
                if not engine.initialize():raise BudgetStop('initialization cap exhausted with fewer than N5')
                flow.write(name,'Shared_initial',seed=201,H_hash=H['artifact_sha256'],
                    training_files=list(ds.names['train']),population=engine.export_rows())
                flow.progress('U_INITIALIZED_AFTER_CERTIFIED_METADATA_SETTLEMENT',seed=201)
            searched=flow.search_all()
            if any(row['status']!='completed' for row in searched['entries']):raise BudgetStop('four groups not all completed')
        except Exception as exc:stop=str(exc)[:500];print('停止新增请求：'+stop,flush=True)
        finally:finish(flow,stop)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',required=True,type=Path)
    p.add_argument('--env-file',required=True,type=Path);a=p.parse_args()
    directory=a.run_dir.resolve()
    if directory.parent!=ROOT/'runs':p.error('own run dir required')
    run(directory,a.env_file)


if __name__=='__main__':main()
