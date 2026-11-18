"""Pure fake-SSH/render acceptance for the R13 Mac bridge; no remote call."""
import json
from pathlib import Path
import socket
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from experiments.triad import r13_tsp_mac as bridge


class Fake:
    def __init__(self):self.calls=[];self.exists=False;self.active=False;self.valid=True
    def run(self,args,*a,**kw):
        self.calls.append(args)
        if bridge.VERIFY in args:
            return SimpleNamespace(stdout=json.dumps({'handoff_proof_valid':self.valid,'scientific_status':'incomplete','account_unoccupied_at_check':True,'fixture_only':False,'new_task_authorized':False}))
        if bridge.INSPECT in args:return SimpleNamespace(stdout=json.dumps({'plan_exists':self.exists,'activated':self.active,'STOP':False,'closed':False}))
        if 'prepare' in args:self.exists=True
        if 'activate' in args:self.active=True
        return SimpleNamespace(stdout=json.dumps({'synthetic':True,'submitted':'submit' in args or 'resume' in args}))


def main():
    def deny(*a,**k):raise AssertionError('OFFLINE: real SSH/network forbidden')
    with patch.object(bridge.cluster.shared,'Connection',deny),patch.object(socket.socket,'connect',deny),tempfile.TemporaryDirectory(prefix='OFFLINE-R13-bridge-') as tmp:
        p=Path(tmp);a=SimpleNamespace(action='prefix-preview',create_plan=False,activate_plan=False,exclusive_hours=72)
        f=Fake();v=bridge.operate(f,a,p)
        assert v['prefix_requests_max']==2 and v['inclusive_prefix_solves_max']==80
        assert not any('prepare' in x or 'activate' in x or 'submit' in x for x in f.calls)
        a.action='prefix-submit'
        try:bridge.operate(f,a,p)
        except PermissionError:pass
        else:raise AssertionError('missing explicit plan permission accepted')
        a.create_plan=True;a.activate_plan=True;bridge.operate(f,a,p)
        assert f.active and f.calls[-1]==bridge.command('prefix-submit')
        c=f.calls[-1];assert c[c.index('--settled-prefix')+1]=='1' and c[c.index('--approve-segment-solves')+1]=='80'
        before=len(f.calls)
        try:bridge.operate(f,a,p)
        except PermissionError:pass
        else:raise AssertionError('activated plan was recreated/repeated')
        assert not any('prepare' in x for x in f.calls[before:])
        a.action='certify';bridge.operate(f,a,p);assert f.calls[-1]==bridge.command('certify')
        a.action='continue';bridge.operate(f,a,p);c=f.calls[-1]
        assert 'resume' in c and '--settled-prefix' not in c and c[c.index('--approve-requests')+1]=='2040'
        a.action='prefix-submit';f.valid=False;before=len(f.calls)
        try:bridge.operate(f,a,p)
        except PermissionError:pass
        else:raise AssertionError('failed handoff accepted')
        assert not any('prepare' in x or 'activate' in x or 'submit' in x for x in f.calls[before:])
        for action in ('prefix-submit','continue'):
            try:bridge.main([action])
            except PermissionError:pass
            else:raise AssertionError('submission without manual budget accepted')
    out=ROOT/'reports/explore-runtime-20261118';out.mkdir(parents=True,exist_ok=True)
    v={'passed':True,'existing_R13_unchanged':True,'scope':'fake SSH + exact command render only','menus':6,
       'no_automatic_prepare_or_activation':True,'existing_plan_never_recreated':True,'handoff_verifier_contract_checked':True,
       'prefix_requests_max':2,'inclusive_prefix_solves_max':80,'original_cap':2040,
       'certify_side_effect':'no API; writes original batch Acceptance.json','same_R13_identity_resume':True,
       'SSH_attempts':0,'API_requests':0,'actual_solves':0,'Slurm_submitted':False,'current_remote_account_or_plan_state':'not inspected'}
    (out/'R13_BRIDGE_OFFLINE.json').write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(v,ensure_ascii=False))


if __name__=='__main__':main()
