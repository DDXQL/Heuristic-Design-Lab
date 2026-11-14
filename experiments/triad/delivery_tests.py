#!/usr/bin/env python3
"""Synthetic final-delivery checks: no real 501, model, solver or published pickle."""
import copy
import hashlib
import io
import json
from pathlib import Path
import pickle
import socket
import sys
import tempfile
import zipfile
from contextlib import redirect_stdout
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'code'),str(ROOT)]
from heuristic_design.core.storage import read,write,sha
from experiments.triad import configuration,review,registration,obp_data,problems,entry,batch,slurm,cluster


def deny(*a,**kw):raise AssertionError('OFFLINE: real source/request/solve forbidden')


def rejects(fn,error=Exception):
    try:fn()
    except error:return
    raise AssertionError('expected refusal')


def main():
    checks=[]
    with tempfile.TemporaryDirectory(prefix='triad-delivery-') as tmp,patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(problems,'solve_row',deny),patch.object(problems,'solve_obp',deny):
        root=Path(tmp).resolve()
        # Assemble all six recommended configs, preserving OFF and draft identity.
        output=root/'reviewed'
        with patch.object(sys,'argv',['review','--output',str(output)]),redirect_stdout(io.StringIO()):assert review.main()==0
        for group in configuration.GROUPS:
            c=configuration.load(output/'configs'/(group+'.json'))
            assert c['freeze_status']=='draft_unapproved' and c['real_requests_authorized'] is False
            assert c['repeat_count']==3 and c['search_seeds']==[501,502,503] and c['api_attempt_cap']==1020
            for key in ('data_manifest','h_file','frozen_u_template'):
                if c[key]:assert Path(c[key]).exists(),(group,key,c[key])
            if group.startswith('obp-'):assert sha(c['state_delivery']['file'])==c['state_delivery']['sha256']
        assert len(batch.plan(output/'campaign.json')['rows'])==18
        checks.append('six draft configs preserve paths, recommendations and no authorization')
        # Registration reads ONLY a synthetic completed source with real format.
        c=configuration.load(ROOT/'experiments/triad/recommended.draft/fjsp-u.json');c.update(freeze_status='frozen',protocol_receipt='SYNTHETIC ADOPTION',search_seed=501)
        row={'group':'fjsp-u','seed':501,'protected_existing_501':True}
        with patch.object(registration,'read',deny):rejects(lambda:registration.register(row,c,False),PermissionError)
        data=[{'file':'synthetic','sha256':'a'*64}];hs=[{'key':'b'*64}]
        p=read(ROOT/'preparations/triad/fjsp/U_frozen_template.json')
        profile={'config':p['settings'],'source_files':read(ROOT/'preparations/triad/fjsp/public-runtime-923781f.json')['files'],'instances':data,'members':hs}
        profile['config']['search_seed']=501
        registration.check_profile(profile,c,data,[hs[0]['key']])
        bad=copy.deepcopy(profile);bad['config']['provider']['model']='WRONG';rejects(lambda:registration.check_profile(bad,c,data,[hs[0]['key']]))
        source=root/'synthetic-501';write(source/'Protocol.json',profile);identity=sha(source/'Protocol.json')
        write(source/'Protocol.receipt.json',{'sha256':identity});write(source/'checkpoint.json',{'synthetic':True})
        write(source/'checkpoint.receipt.json',{'identity':identity,'sha256':sha(source/'checkpoint.json')})
        summary={'phase':'completed','protocol_sha256':identity,'initialization_attempts':8,'evolution_attempts':1000,'request_reservations':1008,'unknown_sends':0,'best_J':1.0,'champion_id':'SYNTHETIC','candidate_failures':2}
        write(source/'exports/summary.json',summary);(source/'exports/candidates.csv').write_text('evolution_attempt,best_J\n1000,1.0\n')
        original={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
        with patch.object(registration,'PROTECTED_501',source),patch.object(problems,'load_inputs',return_value=(data,[],hs)):
            receipt=registration.register(row,c,True);packet=root/'receipt.json';write(packet,receipt)
            assert registration.accept_receipt(row,c,packet,sha(packet),True)==receipt
            assert receipt['checkpoint_copied'] is False and receipt['snapshot']['failures']==2
            bad=copy.deepcopy(receipt);bad['snapshot']['evolution_attempts']=999;write(root/'bad.json',bad)
            rejects(lambda:registration.accept_receipt(row,c,root/'bad.json',sha(root/'bad.json'),True))
            (source/'.coordinator.lock').write_text('SYNTHETIC');rejects(lambda:registration.register(row,c,True));(source/'.coordinator.lock').unlink()
        assert original=={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
        assert batch.state(row)['execution_prohibited']
        rejects(lambda:slurm.command(row,'run',sys.executable),PermissionError)
        forbidden_run=ROOT/'runs'/('triad-OFFLINE-PROTECTED-'+root.name)
        with patch.object(configuration,'load',return_value=c),patch.object(sys,'argv',['entry','prepare','--config',str(output/'configs/fjsp-u.json'),'--run-dir',str(forbidden_run)]):
            rejects(entry.main,PermissionError)
        assert not forbidden_run.exists()
        checks.append('synthetic 501 registration/import, identity mismatch, incomplete/locked refusal and rerun guards')
        # Test importer with invented two-case pickle; never read official train/test.
        dataset={f'instance_{i}':{'num_items':2,'capacity':10,'items':np.array([3,7],dtype=np.int32)} for i in range(2)}
        raw=pickle.dumps(dataset,protocol=4);source=root/'synthetic-training.pkl';source.write_bytes(raw)
        digest=hashlib.sha256(raw).hexdigest();blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        spec=read(ROOT/'experiments/triad/obp-data.pending.json');spec.update(adopted=True,source_sha256=digest,source_git_blob=blob,expected_instances=2,train_indices=[0],validation_indices=[1]);write(root/'split.json',spec)
        with patch.object(obp_data,'TRAIN_SHA',digest),patch.object(obp_data,'TRAIN_BLOB',blob):
            value=obp_data.prepare(source,root/'split.json',root/'data');assert value['prechecked_instances']==2 and value['actual_solves']==0
            manifest=read(root/'data/train.manifest.json');assert manifest['instances'][0]['source_items_dtype']=='int32'
            assert read(root/'data/instances/instance_0.json')['N']==2
            spec['adopted']=False;write(root/'unadopted.json',spec)
            rejects(lambda:obp_data.prepare(root/'absent.pkl',root/'unadopted.json',root/'no-output'),PermissionError)
        checks.append('synthetic NumPy int32 training import, natural split/reference precheck, unadopted refusal before source read')
        # Exercise the exact upload installer locally, on invented read-only inputs.
        asset=root/'preparations/synthetic/instance.json';write(asset,{'synthetic':True})
        manifest=asset.parent/'train.json';write(manifest,{'split':'train','instances':[{'path':'instance.json','sha256':sha(asset)}]})
        with patch.object(cluster,'ROOT',root):
            files=cluster.input_assets([{'data_manifest':str(manifest)}]);assert len(files)==2
            rejects(lambda:cluster.input_assets([{'h_file':str(root/'receipt.json')}]))
        packet=root/'inputs.zip'
        with zipfile.ZipFile(packet,'w') as z:
            for n,p in files.items():z.write(p,n)
            z.writestr('asset-manifest.json',json.dumps({n:sha(p) for n,p in files.items()}))
        remote=root/'synthetic-remote';remote.mkdir()
        def install():
            with patch.object(sys,'argv',['installer',str(packet),str(remote),sha(packet)]),redirect_stdout(io.StringIO()):exec(cluster.ASSET_INSTALL,{})
        install();install();assert sha(remote/'preparations/synthetic/instance.json')==sha(asset)
        (remote/'preparations/synthetic/instance.json').write_text('DIFFERENT; PRESERVE')
        rejects(install,SystemExit)
        assert (remote/'preparations/synthetic/instance.json').read_text()=='DIFFERENT; PRESERVE'
        checks.append('runtime input upload allowlist, exact installer hash checks, idempotence and no overwrite on conflict')
    value={'passed':True,'checks':checks,'API_requests':0,'actual_solves':0,'LKH_runs':0,'real_501_read':False,'published_OBP_data_read':False}
    path=ROOT/'reports/triad-package-20261113/FINAL_DELIVERY_CHECKS.json';write(path,value);print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
