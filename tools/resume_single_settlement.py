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
from fjsp_usage.research_real.single_billing import match_invoice,query_invoices
from fjsp_usage.research_real.single_experiments import Guard
from fjsp_usage.research_real.model_migration import check_live_tariff,public_json
from fjsp_usage.research_real.staged_evaluation import StagedDataset
from run_single_model_migration import MigrationWorkflow,finish

VERSION='single-ID-nonsemantic-recording-settlement-amendment-v1-20261014'
FAILED_KEY='r201/init/INIT/init/000005'
SUPPLIER_ID='202610141327527602746288268d9d6TjCvhB6b'


from fjsp_usage.research_real.single_io import (
    InvoiceQueryPacer, MetadataPacer, ProtectedInvoice, WireRecorder)


def reconcile(flow,quota):
    from fjsp_usage.research_real.single_settlement import reconcile as shared
    return shared(flow,quota,query_fallback=query_invoices)


def run(directory,env_file):
    c=ExperimentConfig.from_dict(json.loads((directory/'config.migration.authorized.json').read_text()))
    os.environ[KEY_ENV]=load_local_key(env_file)
    ds=StagedDataset(ROOT/'data/fjsp_manifest.json',project_root=ROOT,mode='real')
    own_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with RunLock(directory):
        flow=MigrationWorkflow(directory,config=c,dataset=ds,project_root=ROOT)
        guard=Guard(flow,flow.read('Worktree_binding.json','Worktree_binding'));guard.check()
        client=flow.client();quota=client.inner.inner
        metadata=MetadataPacer(directory/'Metadata_global_pacing.json')
        original_quota_query=quota.query
        quota.query=lambda:metadata.call('/api/usage/token/',original_quota_query)
        def public_query(secret,path,**kwargs):
            return metadata.call(path,lambda:public_json(secret,path,**kwargs))
        quota.tariff_query=lambda secret:check_live_tariff(secret,query=public_query)
        previous=[]
        for invoice_file in (directory/'billing').glob('*.json'):
            bill=json.loads(invoice_file.read_text())
            previous.extend(v.get('observed_at',0) for v in (bill.get('before',{}),bill.get('after',{})))
        original_invoice_query=client.inner.query
        invoice_query=lambda:metadata.call('/api/log/token',original_invoice_query)
        pacer=InvoiceQueryPacer(invoice_query,directory/'Invoice_query_pacing.json',
            c.platform_quota_query_interval,initial=max(previous,default=0)+15)
        client.inner.query=pacer;quota.invoice_query=pacer
        client.inner=ProtectedInvoice(client.inner,quota)
        amendment={'version':VERSION,'source_protocol_context':flow.context,'entry_file':str(Path(__file__)),
            'entry_sha256':own_sha,'change':'durable wire replies; paced metadata GETs; fail-closed pre-dispatch billing; existing-checkpoint resume',
            'unchanged':['model parameters','prompt pack','candidate validation','state','evaluator','H','parents','survival','budget caps'],
            'prior_initial_stop_retained':json.loads((directory/'r201/Initialization_status.json').read_text()),
            'checkpoint_sha256':{str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (directory/'r201').glob('*/checkpoint.json')},
            'already_sent_diagnostic':1,'formal_already_sent':len(flow.ledger.data['records'])-1,
            'remaining_formal_max':c.total_request_cap-len(flow.ledger.data['records']),'no_request_replay':True,'no_old_model_candidates_imported':True,
            'global_metadata_get_min_interval_seconds':15,'invoice_get_min_interval_seconds':75,
            'supplier_rate_limit_known':False,
            'authorization':'DDXQL current model batch plus autonomous nonsemantic recording repairs'}
        path=directory/('Execution_amendment.'+digest(amendment)+'.json')
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
            entries=[]
            for arm in ('B0','B1','B2','P'):
                row=flow.search_arm(201,arm);entries.append(row)
                if row['status']!='completed':raise BudgetStop('arm stopped: '+arm+' '+row['status'])
            # Preserve the prior stopped Search_complete.json as historical.
            flow.write('Search_complete_resumed.json','Search_complete',dataset_hash=ds.key,
                H_hash=H['artifact_sha256'],reference_H_hash=H['artifact_sha256'],seeds=[201],
                entries=entries,population_hashes=[r['population_hash'] for r in entries],
                note='Full actual resumed generation outcomes; prior stopped gate retained unchanged.')
            flow.progress('SEARCH_COMPLETE_AFTER_METADATA_SETTLEMENTS')
        except Exception as exc:stop=str(exc)[:500];print('停止新增请求：'+stop,flush=True)
        finally:finish(flow,stop)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',required=True,type=Path)
    p.add_argument('--env-file',required=True,type=Path);a=p.parse_args()
    directory=a.run_dir.resolve()
    if directory.parent!=ROOT/'runs':p.error('own run dir required')
    run(directory,a.env_file)


if __name__=='__main__':main()
