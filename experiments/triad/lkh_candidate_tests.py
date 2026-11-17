#!/usr/bin/env python3
"""Changed-path checks only. Real clients, solvers, make and Slurm are denied."""
import copy
from contextlib import ExitStack
import gzip
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'code'), str(ROOT)]
from heuristic_design.core.storage import read, write, sha, digest
from heuristic_design.core import execution
from heuristic_design.llm.strict_nonstream import StrictNonstreamTransport
from experiments.triad import lkh_sources as sources, assets, six_ops, runtime, problems, evaluation


def deny(*args, **kwargs):
    raise AssertionError('OFFLINE: real network/model/solver/make/Slurm prohibited')


def rejected(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except (ValueError, PermissionError, FileExistsError, FileNotFoundError, gzip.BadGzipFile, EOFError, tarfile.TarError):
        return
    raise AssertionError('unsafe input unexpectedly accepted')


def synthetic_tar(extra=None, version='3.0.13'):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for name in ('README.txt', 'Makefile', 'SRC/Makefile', 'SRC/LKHmain.c'):
            body = (f'Version {version}\nThe code is distributed for research use. The author reserves all rights.\n' if name=='README.txt' else 'SYNTHETIC; NEVER COMPILE\n').encode()
            m = tarfile.TarInfo('LKH-3.0.13/'+name);m.size=len(body);t.addfile(m, io.BytesIO(body))
        if extra is not None:
            t.addfile(extra, io.BytesIO(b''))
    return buf.getvalue()


def main():
    out=ROOT/'reports/tsp-lkh-candidate-20261117';out.mkdir(parents=True,exist_ok=True)
    candidate=ROOT/'preparations/operations/lkh-candidate-3.0.13/LKH-3.0.13.tgz'
    preserved={str(p):sha(p) for p in (candidate,candidate.parent/'source-receipt.json')}
    results={}
    with ExitStack() as stack:
        for obj, name in ((socket.socket,'connect'),(socket,'create_connection'),
                          (StrictNonstreamTransport,'__init__'),(subprocess,'Popen'),
                          (problems,'solve_row'),(problems,'solve_obp'),(evaluation,'evaluate'),
                          (sources.urllib.request,'urlopen')):
            stack.enter_context(patch.object(obj,name,deny))
        with tempfile.TemporaryDirectory(prefix='lkh-source-offline-') as tmp:
            tmp=Path(tmp)
            dest=tmp/'candidate';receipt=sources.import_candidate(candidate,dest)
            assert receipt['official_equivalence_verified'] is False and 'official_URL' not in receipt
            assert receipt['declared_repository_commit']==read(sources.PIN)['declared_repository_commit']
            rejected(sources.bind,dest,tmp/'not-built.json')
            rejected(sources.import_candidate,candidate,dest)
            reserved=tmp/'official-failure';reserved.mkdir();write(reserved/'source-receipt.json',{'state':'download_reserved'})
            old=sha(reserved/'source-receipt.json');rejected(sources.import_candidate,candidate,reserved)
            assert sha(reserved/'source-receipt.json')==old
            bad=tmp/'bad.tgz';bad.write_bytes(b'wrong SHA');rejected(sources.import_candidate,bad,tmp/'wrong-sha')
            assert not (tmp/'wrong-sha').exists()
            raw=candidate.read_bytes();broken=bytearray(raw);broken[-1]^=1
            rejected(sources.inspect_archive,bytes(broken))
            for name,typ in (('LKH-3.0.13/../escape',tarfile.REGTYPE),('LKH-3.0.13/link',tarfile.SYMTYPE),('/absolute',tarfile.DIRTYPE),('LKH-3.0.13/README.txt',tarfile.REGTYPE)):
                m=tarfile.TarInfo(name);m.type=typ;m.linkname='/tmp/escape'
                rejected(sources.inspect_archive,synthetic_tar(m))
            rejected(sources.inspect_archive,synthetic_tar(version='3.0.12'))
            with patch.object(sources,'EXPANDED_LIMIT',1024):rejected(sources.inspect_archive,synthetic_tar())
            results['candidate_import']={'pin_and_commit_retained':True,'no_official_relabel':True,'wrong_SHA_gzip_paths_links_duplicates_version_expansion_rejected':True,'old_download_reserved_preserved':True,'binding_before_build_rejected':True}
            # A fake make callable writes an inert fixture. No subprocess or binary is executed.
            def fake_make(command,**kw):
                assert command==['make']
                (Path(kw['cwd'])/'LKH').write_bytes(b'INERT OFFLINE BUILD FIXTURE; NOT AN EXECUTABLE\n')
                kw['stdout'].write('SYNTHETIC BUILD RECEIPT ONLY\n')
                return subprocess.CompletedProcess(command,0)
            rejected(sources.prepare_source,dest,build=True,academic=False)
            with patch.object(sources.subprocess,'run',fake_make):
                sources.prepare_source(dest,build=True,academic=True)
            spec=tmp/'bound.json';sources.bind(dest,spec);s=read(spec)
            assert s['source_identity']['source_kind']=='third_party_candidate' and 'official_URL' not in s['source_identity']
            assert s['runs']==10 and s['max_trials']==1000 and s['cpu_seconds']==120 and s['timeout_seconds']==150 and s['additional_parameters']=={'TIME_LIMIT':10}
            # Synthetic tour import only: no solver. A subset must never become a zero reference.
            refdir=tmp/'tour-fixture';refdir.mkdir()
            inp=refdir/'input.json';value={'coordinates':[[0,0],[1,0],[0,1]]};write(inp,value)
            tour=refdir/'result.tour'
            plan={'spec':s,'commands':[{'file':'synthetic-three-points','input':str(inp),'instance_sha256':digest(value),'tour':str(tour)}]}
            write(refdir/'reference-plan.json',plan)
            def tour_receipt(text):
                tour.write_text(text)
                write(refdir/'LKH-run-receipt.json',{'phase':'completed','plan_sha256':sha(refdir/'reference-plan.json'),'completed_processes':1,'attempts':[{'file':'synthetic-three-points','state':'completed','tour_sha256':sha(tour)}]})
            tour_receipt('TOUR_SECTION\n1\n-1\n')
            rejected(assets.lkh_import,refdir,tmp/'subset.json')
            tour_receipt('TOUR_SECTION\n1\n2\n3\n-1\n')
            assets.lkh_import(refdir,tmp/'reference.json')
            assert read(tmp/'reference.json')['lkh_identity']['source_identity']['source_kind']=='third_party_candidate'
            assert read(tmp/'reference.json')['instances'][0]['reference']>0
            results['reference_import']={'synthetic_only':True,'incomplete_tour_rejected':True,'candidate_origin_retained':True}
            rejected(sources.prepare_source,dest,build=True,academic=True)
            (dest/'build.log').write_text('tampered');rejected(sources.bind,dest,tmp/'tampered-build.json')
            results['build_and_bind']={'mock_receipt_only':True,'no_make_or_binary_execution':True,'D06_unchanged':True,'log_tampering_and_rebuild_rejected':True}
        check=six_ops.check_only();assert len(check['runs'])==18
        for row in check['runs']:
            if row['group'].startswith('tsp'):
                assert row['pending']==['asset:D06_LKH_reference','reference_file'],row['pending']
        for method,n,policy in (('u',5,'bounded_initialization_until_population'),('eoh',10,'native_EoH')):
            c=six_ops.config('tsp-'+method)
            assert (c['population_size'],c['initialization_request_cap'],c['evolution_request_cap'],c['api_attempt_cap'],c['initialization_policy'])==(n,20,1000,1020,policy)
            assert c['search_seeds']==[501,502,503] and not c['real_requests_authorized']
        assert six_ops.config('obp-eoh')['initialization_policy']=='native_N_finite_or_fail'
        # Retain N5/N10 and init20, shorten evolution only in engineering profiles.
        runs=ROOT/'runs';runs.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='OFFLINE-tsp-candidate-',dir=runs) as tmp:
            tmp=Path(tmp);m=read(ROOT/'preparations/triad/tsp/train20.manifest.json')
            ref=tmp/'ref.json';write(ref,{'kind':'mock-reference-v1','engineering_only':True,'instances':[{'file':r['file'],'reference':1.0} for r in m['instances']]})
            def run(method,seed,policy=None):
                c=copy.deepcopy(six_ops.config('tsp-'+method))
                c.update(mode='mock',freeze_status='engineering_only',search_seed=seed,
                         reference_file=str(ref),evolution_request_cap=2,api_attempt_cap=22,
                         window_seconds=3600,credential_file=None,account_gate=None,account_exclusion=None,
                         mock_faults={'8':'duplicate','9':'duplicate'} if method=='eoh' else {})
                if policy:c['initialization_policy']=policy
                cp=tmp/(method+'-'+str(seed)+'-'+c['initialization_policy']+'.json');write(cp,c)
                d=cp.with_suffix('');runtime.prepare(d,cp,engineering=True)
                before=read(d/'checkpoint.json');assert before['tasks']=={} and before['population']==[]
                # Skip only the Mac caffeinate helper; all subprocesses remain denied.
                with patch.object(execution.sys,'platform','linux'):
                    result=execution.start(d,adapter=runtime.Adapter())
                _,state=runtime.protocol_state(d)
                return result,state
            for method in ('u','eoh'):
                states=[]
                for seed in (501,502,503):
                    result,s=run(method,seed);assert result['phase']=='completed',result
                    assert s['eoh']['operator_cursor']==2 and s['eoh']['initialization_requests']<20
                    states.append(s)
                assert len({s['identity'] for s in states})==3
                results['TSP_'+method]={'three_independent_initializations':True,'target_population':5 if method=='u' else 10,'initialization_max':20,'engineering_evolution_attempts':2,'unused_initialization_not_transferred':True,'synthetic_scores_only':True}
            result,s=run('eoh',501,'native_N_finite_or_fail')
            assert result['phase']=='initialization_incomplete' and s['eoh']['operator_cursor']==0
            results['policy_separation']={'TSP_native_continues_with_fewer_finite_parents':True,'strict_stops_without_refill':True,'OBP_strict_preserved':True}
    assert all(sha(p)==h for p,h in preserved.items())
    public=subprocess.check_output(['git','diff','923781f','--','code/','experiments/common/run_frozen.py'],cwd=ROOT)
    assert not public
    report={'passed':True,'results':results,'public_923781f_unchanged':True,'API_requests':0,'actual_solves':0,'make_executed':False,'LKH_runs':0,'Slurm_submitted':False,'source_candidate_preserved':True,'scope':'changed paths only; historical full Mock evidence reused; no live account or R11 inspected/modified'}
    write(out/'OFFLINE.json',report)
    print(json.dumps({'passed':True,'evidence':str(out/'OFFLINE.json'),'API_requests':0,'actual_solves':0,'make_executed':False,'Slurm_submitted':False}))


if __name__=='__main__':main()
