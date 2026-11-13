#!/usr/bin/env python3
"""Read-only validation of the returned 614474 receipts. Never constructs a schedule."""
import argparse
import copy
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'deploy/eoh-baseline'),str(ROOT/'code'),str(ROOT)]
import eoh_gap as e
from heuristic_design.problems import routing_fixtures
DEFAULT=Path('/Users/DDXQL/Developer/Heuristic-Design-Lab-fjsp-cluster-mock-20261113/reports/cluster-solve-check-20261113/fetch-20261113-073927-a5f646/result/run')


def deny(*a,**k):raise AssertionError('reused evidence checker forbids network/API/solves')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--acceptance-dir',type=Path,default=DEFAULT);args=p.parse_args();d=args.acceptance_dir
    with patch.object(socket.socket,'connect',deny),patch.object(socket,'create_connection',deny),patch.object(routing_fixtures,'solve',deny),patch.object(e,'evaluate_task',deny),patch.object(e.StrictNonstreamTransport,'__init__',deny):
        receipt=e.read(d/'acceptance.json');manifest=e.read(d/'results-manifest.json')
        assert receipt['job_id']=='614474' and receipt['passed'] and receipt['physical_solves']['confirmed_completed']==16
        protocol=e.read(d/'Protocol.json');data=e.preflight(e.HERE/'research.pending.json')[1]
        assert protocol['instances']==data[:2]
        used={};checked=[]
        for name in ('worker-receipts/serial/constant_H0/result.json','worker-receipts/serial/state_switch_H0_H1/result.json'):
            assert e.sha(d/name)==manifest['files'][name]
            result=e.read(d/name);adapter=e.Adapter();adapter._engineering_mode=False
            adapter.validate_result(result,protocol['instances']);checked.append(name);used[name]=e.sha(d/name)
            for field in ('raw_cost','reference','score'):
                bad=copy.deepcopy(result);bad['instances'][0][field]+=1
                try:adapter.validate_result(bad,protocol['instances'])
                except ValueError:pass
                else:raise AssertionError('tampered physical field admitted: '+field)
        result={'passed':True,'scope':'pure validation of already-returned serial engineering receipts; no fresh construction, no new EoH quality evidence',
          'source_job':'614474','source_directory':str(d),'source_files':used,'new_adapter_J_raw_cost_LB_and_feasibility_validated':True,
          'API_requests':0,'additional_actual_solves':0,'credential_reads':0,'checked_results':checked}
        e.write(ROOT/'reports/fjsp-eoh-gap-prep-20261113/reused-physical-validation.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
