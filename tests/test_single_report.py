"""Report fixtures retain nonsurvivors, duplicates and unknown costs."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from fjsp_usage.research_real.single_report import write_results


class ReportTests(unittest.TestCase):
    def test_all_attempts_exports_and_unknown_costs_are_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);folder=directory/'r201/INIT';folder.mkdir(parents=True)
            (directory/'billing').mkdir()
            attempts=[];records={};ledger={};evaluations={}
            result={'valid':True,'fitness':-1.,'primary_evaluation_seconds':.9,'instances':[
                {'file':'toy','makespan':4,'feasible':True,'score':-1.,'single_solve_seconds':.1,
                 'deterministic_recheck_seconds':.2,'diagnostic_replay_seconds':.3}]}
            for i,category in enumerate(('valid','code_duplicate','api_failure')):
                identifier=f'INIT/init/{i:06d}';key='r201/init/'+identifier
                usage={'input_tokens':2,'output_tokens':3} if i==0 else None
                records[identifier]={'global_key':key,'status':'completed' if i<2 else 'failed','usage':usage}
                if i<2:records[identifier]['text']='{fixture}\n```python\ndef select_heuristic():\n    return 0\n```'
                attempts.append({'id':identifier,'category':category,'status':category})
                ledger[key]={'send_confirmed':True,'reservation':{'input_tokens':65536,'output_tokens':32768}}
                if i==0:evaluations[identifier]={'result':result}
                bill={'status':'invoice_account_matched','actual_platform_units':7 if i==0 else 0}
                if i==2:bill={'status':'settlement_not_certified','actual_platform_units':None}
                (directory/'billing'/(hashlib.sha256(key.encode()).hexdigest()+'.json')).write_text(json.dumps(bill))
            (folder/'checkpoint.json').write_text(json.dumps({'attempts':attempts,'evaluations':evaluations}))
            (folder/'budgeted_initial_requests.json').write_text(json.dumps({'requests':records}))
            entries=[{'arm':a,'phase':'not_started'} for a in ('B0','B1','B2','P')]
            training={'artifact_sha256':'fixture','entries':entries,'fixed_h_train_results':[]}
            flow=SimpleNamespace(directory=directory,ledger=SimpleNamespace(data={'records':ledger},summary=lambda:{'request_slots':3}),
                dataset=SimpleNamespace(names={'train':['toy']}),write=lambda name,kind,**fields:fields)
            with patch('fjsp_usage.research_real.single_report.write_training_report',return_value=training):
                report=write_results(flow)
            self.assertEqual(len(report['requests']),3);self.assertEqual(len(report['candidates']),2)
            self.assertEqual(report['costs'][0]['known_invoice_platform_units'],7)
            self.assertEqual(report['costs'][0]['unknown_invoice_requests'],1)
            self.assertEqual(report['costs'][0]['unknown_wire_usage_requests'],2)
            self.assertEqual(report['requests'][1]['actual_platform_units'],0)
            self.assertIsNone(report['requests'][2]['actual_platform_units'])
            self.assertEqual(report['candidates'][0]['evaluation']['instances'][0]['makespan'],4)
            self.assertEqual(report['costs'][0]['categories']['code_duplicate'],1)
            self.assertEqual(len(list((directory/'candidate_exports').glob('*.response.txt'))),2)
            self.assertEqual(report['status'],'partial_or_stopped')


if __name__=='__main__':unittest.main()
