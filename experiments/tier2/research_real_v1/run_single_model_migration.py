#!/usr/bin/env python3
"""Registered gpt61 diagnostic then fresh scalar-ID four-arm train-only batch.

prepare is offline. execute sends at most one diagnostic then <=60 candidates.
No retry, fallback, old U import, validation/test entry or historical mutation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'code'))
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research_real.config import ExperimentConfig, fingerprint
from fjsp_usage.research_real.conditional_research import (MIGRATION_VERSION,prepare,freeze_h,
    dispatch_check,history_summary)
from fjsp_usage.research_real.budget import BudgetJournal,BudgetStop
from fjsp_usage.research_real.leafapi import load_local_key,KEY_ENV
from fjsp_usage.research_real.locking import RunLock
from fjsp_usage.research_real.model_migration import (VERSION as MODEL_VERSION,MODEL,EXPRESSION,
    DIAGNOSTIC_PROMPT,MigrationWire,MigrationQuota,risk_reservation)
from fjsp_usage.research_real.single_billing import InvoiceTransport
from fjsp_usage.research_real.single_experiments import (VERSION,Guard,GuardedTransport,
    file_hashes,verify_sources,budget_inventory,worktree_roots,declaration_pins)
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from fjsp_usage.research_real.single_report import write_results
from fjsp_usage.research_real.workflow import Workflow,ARMS
from run_single_experiments import export_prompts

OLD='single-ID-paired-training-20261013-authorized-v1'
PREFLIGHT='single-ID-gpt61-preflight-20261014-v1'


class MigrationWorkflow(Workflow):
    def client(self):
        if self._client is None:
            guard=Guard(self,self.read('Worktree_binding.json','Worktree_binding'));guard.check()
            historical=dispatch_check(self)
            wire=MigrationWire(self.config)
            quota=MigrationQuota(wire,self.directory/'platform_quota.json',self.context,
                retained_extra=historical['retained_account_hold'],
                settlement_min_used=historical['latest_saved_account_used'])
            self._client=GuardedTransport(InvoiceTransport(quota,self.directory/'billing'),guard)
        return self._client


def prepare_batch(directory,origin):
    original=file_hashes(origin);verify_sources(ROOT,origin,original)
    pins=declaration_pins(original)
    for name in (OLD,PREFLIGHT):
        for path in sorted((ROOT/'runs'/name).rglob('*')):
            if path.is_file():pins[str(path.relative_to(ROOT/'runs'))]=hashlib.sha256(path.read_bytes()).hexdigest()
    config=json.loads((ROOT/'runs'/OLD/'config.single.authorized.json').read_text())
    config['provider'].update(model=MODEL,expected_response_model=MODEL)
    config.update(total_request_cap=61,platform_quota_reservation=1000000)
    config['phase_request_caps']['r201/diagnostic']=1
    declaration=config['conditional_research'];declaration.update(version=MIGRATION_VERSION,
        source_files_sha256=pins,history_batches=[*declaration['history_batches'],OLD])
    declaration['model_migration']={'version':MODEL_VERSION,'retired_run':OLD,'retired_model':'gpt-5.6-sol',
        'new_model':MODEL,'authorization_reviewer':'DDXQL',
        'retirement':'MODEL_ACCESS_FAILURE_ABORTED_UNUSED_59_AUTHORIZATION_RETIRED',
        'diagnostic':{'cap':1,'max_output_tokens':256,'prompt':DIAGNOSTIC_PROMPT,'candidate':False,'retry':False},
        'risk_policy':{'basis':'conditional-engineering-envelope-not-certified-provider-bound',
            'expression':EXPRESSION,'max_input_rate':5,'max_output_rate':15,'group':'codex-deafult',
            'group_ratio':0.5,'quota_per_unit':500000,'safety_factor':2,'round_to_points':1000,
            'input_envelope_rule':'max(65536,utf8_prompt_bytes+4096)',
            'output_envelope':32768,'max_per_request_points':1000000},'preflight_run':PREFLIGHT}
    c=ExperimentConfig.from_dict(config)
    inventory=budget_inventory(worktree_roots(ROOT))
    old_identity=json.loads((ROOT/'runs'/OLD/'budget.json').read_text())['identity']
    expected={**budget_inventory([origin]),old_identity:hashlib.sha256((ROOT/'runs'/OLD/'budget.json').read_bytes()).hexdigest()}
    if inventory!=expected:raise BudgetStop('unregistered peer consumption; reconcile before new migration')
    dataset=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    with RunLock(directory):
        atomic_json(directory/'config.migration.authorized.json',c.payload())
        flow=MigrationWorkflow(directory,config=c,dataset=dataset,project_root=ROOT)
        binding=flow.write('Worktree_binding.json','Worktree_binding',version=VERSION,
            migration_version=MODEL_VERSION,origin_root=str(origin),source_files_sha256=original,
            real_budget_inventory=inventory,
            checkpoint_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip())
        atomic_json(directory/'Human_authorization.json',{
            'reviewer':'DDXQL','source':'explicit user model-migration authorization in this conversation',
            'model':MODEL,'exclusive_caller_branch':'codex/u-single-experiments',
            'diagnostic_max':1,'formal_max':60,'seed':201,'N':5,'init_max':20,
            'arms':list(ARMS),'generations':1,'slots_each':10,'instance_deadline':15,
            'train_only':True,'old_unused_authorization_retired':59,
            'old_unknown_holds_unchanged':True,'engineering_risk_adaptation_authorized':True,
            'scope_approval_inherited':declaration['scope_approval'],
            'no_new_member_technical_review_claim':True})
        atomic_json(directory/'Old_stage_retirement.json',{'old_run':OLD,
            'status':declaration['model_migration']['retirement'],'unused_calls_retired':59,
            'request_slots':1,'sends':1,'valid_U':0,'fee':None,'wire_usage':None,
            'hold_points':12000000,'original_files_sha256':{k:v for k,v in pins.items() if k.startswith(OLD+'/')}})
        print('离线：原H代码/编号/人工审查保持；新模型协议重评10×21训练。',flush=True)
        asset=prepare(flow);frozen=freeze_h(flow)
        _,members=flow.h_asset();export_prompts(directory,members)
        (directory/'prompts/Diagnostic.txt').write_text(DIAGNOSTIC_PROMPT+'\n')
        historical=history_summary(ROOT,c)
        if historical['historical_request_slots']!=80 or historical['retained_account_hold']!=24000000:
            raise BudgetStop('expected eighty historical slots and two unchanged twelve-million holds')
        Guard(flow,binding).check()
        files=set(fingerprint(ROOT)['files'])|{'data/fjsp_manifest.json','README.md'}
        with tarfile.open(directory/'code-prompts-config-data-snapshot.tar.gz','w:gz') as archive:
            for name in sorted(files):archive.add(ROOT/name,arcname=name)
            for name,path in zip(dataset.names['train'],dataset.paths['train']):archive.add(path,arcname='train/'+name)
            for path in [directory/'protocol.json',directory/'config.migration.authorized.json',
                directory/'Worktree_binding.json',directory/'Human_authorization.json',
                *sorted((directory/'prompts').glob('*'))]:
                archive.add(path,arcname='registration/'+str(path.relative_to(directory)))
        flow.write('Migration_readiness.json','Migration_readiness',status='OFFLINE_VERIFIED_PAID_NOT_STARTED',
            h_valid=sum(r['result']['valid'] for r in asset['rows']),
            h_reproduced=sum(r['same_training_makespans_as_source'] for r in asset['rows']),
            source_H=declaration['scope_approval']['source_H_sha256'],history=historical,
            maximum_lifetime_slots=141,new_model_slots=61,holdout_parses=0,
            risk_example=risk_reservation(DIAGNOSTIC_PROMPT,declaration['model_migration']['risk_policy']),
            snapshot_sha256=hashlib.sha256((directory/'code-prompts-config-data-snapshot.tar.gz').read_bytes()).hexdigest())
        print('新版本准备完成，累计最大141/300；旧未知占用2400万点不变。',flush=True)


def finish(flow,stop):
    results=write_results(flow)
    diag_path=flow.directory/'Diagnostic_requests.json'
    diag=json.loads(diag_path.read_text())['requests'] if diag_path.exists() else {}
    ledger=flow.ledger.summary();quota_path=flow.directory/'platform_quota.json'
    quota=json.loads(quota_path.read_text()) if quota_path.exists() else None
    invoices=[json.loads(p.read_text()) for p in (flow.directory/'billing').glob('*.json')] if (flow.directory/'billing').exists() else []
    settled=[v for v in invoices if v.get('actual_platform_units') is not None and v.get('status')=='invoice_account_matched']
    summary=flow.write('Migration_final.json','Migration_final',status='STOPPED' if stop else 'COMPLETED_TRAIN_ONLY',
        stop_reason=stop,diagnostic=diag,budget=ledger,
        actual_known_new_points=sum(v['actual_platform_units'] for v in settled),
        new_fee_unknown_count=sum(v.get('actual_platform_units') is None for v in invoices),
        latest_quota_used=quota.get('observed_used') if quota else None,
        old_unknown_hold=24000000,account_ceiling=30000000,groups=results['costs'],
        old_stage='gpt5.6 model access failure aborted; no valid U or comparison',
        new_stage='gpt61 fresh conditional fixed-H training only; no independent generalization conclusion',
        validation_executed=False,test_executed=False)
    atomic_json(flow.directory/'Exclusive_call_handoff.json',{'caller_released':True,
        'status':summary['status'],'budget_file_sha256':hashlib.sha256((flow.directory/'budget.json').read_bytes()).hexdigest(),
        'budget':ledger,'quota':quota,'settlement_audits':[str(p.relative_to(flow.directory)) for p in (flow.directory/'billing').glob('*.json')],
        'historical_unknowns_preserved':True,'old_unused_59_retired':True})
    print(json.dumps({k:summary[k] for k in ('status','stop_reason','actual_known_new_points','new_fee_unknown_count')},ensure_ascii=False),flush=True)


def execute(directory,env_file):
    c=ExperimentConfig.from_dict(json.loads((directory/'config.migration.authorized.json').read_text()))
    os.environ[KEY_ENV]=load_local_key(env_file)
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    with RunLock(directory):
        flow=MigrationWorkflow(directory,config=c,dataset=ds,project_root=ROOT)
        stop=None
        try:
            Guard(flow,flow.read('Worktree_binding.json','Worktree_binding')).check()
            journal=BudgetJournal(directory/'Diagnostic_requests.json',phase='r201/diagnostic',cap=1,
                transport=flow.client(),ledger=flow.ledger)
            record=journal.request('access/000000',DIAGNOSTIC_PROMPT)
            if (record['status']!='completed' or record.get('text','').strip()!='OK'
                    or record.get('usage') is None or record.get('response_metadata',{}).get('model')!=MODEL
                    or not record.get('response_metadata',{}).get('billing_certified')):
                raise BudgetStop('single diagnostic not fully verified; no retries or formal candidate sends')
            flow.write('Diagnostic_verified.json','Diagnostic_verified',record=record,candidate=False)
            initial=flow.initialize_u(201)
            if initial['status']!='initialized':raise BudgetStop('fresh initialization incomplete: '+initial['status'])
            searched=flow.search_all()
            if any(r['status']!='completed' for r in searched['entries']):raise BudgetStop('four groups not all complete; retain actual partial results')
        except Exception as exc:
            stop=str(exc)[:500];print('停止新增请求：'+stop,flush=True)
        finally:finish(flow,stop)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=('prepare','execute','report'))
    parser.add_argument('--run-dir',required=True,type=Path)
    parser.add_argument('--origin-root',type=Path);parser.add_argument('--env-file',type=Path)
    args=parser.parse_args();directory=args.run_dir.resolve()
    if directory.parent!=ROOT/'runs':parser.error('own worktree runs child required')
    if args.stage=='prepare':
        if directory.exists() or not args.origin_root:parser.error('new run dir and read-only origin root required')
        prepare_batch(directory,args.origin_root.resolve())
    elif args.stage=='execute':
        if not args.env_file:parser.error('explicit credential source required')
        execute(directory,args.env_file)
    else:
        c=ExperimentConfig.from_dict(json.loads((directory/'config.migration.authorized.json').read_text()))
        ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
        with RunLock(directory):finish(MigrationWorkflow(directory,config=c,dataset=ds,project_root=ROOT),'report-only; no dispatch')


if __name__=='__main__':main()
