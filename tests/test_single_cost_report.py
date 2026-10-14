"""Handcrafted cost-report fixtures, never generated U or benchmark results."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from summarize_single_migration import build


class CostReportTests(unittest.TestCase):
    def run_fixture(self,sent):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);p=Path(tmp.name);(p/'billing').mkdir()
        key='r201/init/FIXTURE';dkey='r201/diagnostic/FIXTURE'
        def write(name,value):
            path=p/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_text(json.dumps(value))
        request={'global_key':key,'id':'FIXTURE','group':'INIT','send_confirmed':sent,'status':'failed',
            'wire_usage':None,'error':'cannot inspect supplier billing before dispatch',
            'attempt':{'category':'api_failure'}}
        write('Single_results.json',{'requests':[request],'context':'HANDWRITTEN_COST_FIXTURE',
            'budget':{},'status':'partial_or_stopped','train_comparisons':[]})
        write('Training_report.json',{'initialization':[{'accepted_population':[]}],
            'entries':[{'arm':a,'phase':'not_started','attempts':0} for a in ('B0','B1','B2','P')],
            'fixed_h_train_results':[]})
        write('budget.json',{'identity':'fake','records':{key:{'send_confirmed':sent},dkey:{'send_confirmed':True}}})
        records={dkey:{'status':'settled','reserved':410000}}
        if sent:records[key]={'status':'settlement_unknown','reserved':410000}
        write('platform_quota.json',{'records':records,'observed_used':3,'halted':True})
        write('Diagnostic_requests.json',{'requests':{'local':{'global_key':dkey,'usage':{'input_tokens':1,'output_tokens':2},
            'status':'completed','response_metadata':{}}}})
        write('billing/'+hashlib.sha256(dkey.encode()).hexdigest()+'.json',{'status':'invoice_account_matched',
            'actual_platform_units':3,'invoice':{'quota':3,'prompt_tokens':1,'completion_tokens':2}})
        write('billing/'+hashlib.sha256(key.encode()).hexdigest()+'.json',{'status':'before_dispatch',
            'before':{'success':False,'http_status':429},'actual_platform_units':None})
        return build(p)

    def test_proved_unsent_is_not_a_paid_request_or_unknown_wire_use(self):
        artifact=self.run_fixture(False)
        self.assertEqual(artifact['formal_requests'],0);self.assertEqual(artifact['formal_slots'],1)
        self.assertEqual(artifact['proved_unsent_slots'],1);self.assertEqual(artifact['known_new_cost_points'],3)
        self.assertEqual(artifact['unknown_cost_requests'],[])
        self.assertEqual(artifact['unknown_wire_usage_requests'],[])
        row=next(r for r in artifact['requests'] if r['group']=='INIT')
        self.assertIsNone(row['wire_usage']);self.assertIsNone(row['actual_platform_units'])
        self.assertEqual(row['cost_status'],'not_applicable_no_inference_request')

    def test_sent_unknown_cost_and_wire_are_not_converted_to_zero(self):
        artifact=self.run_fixture(True)
        self.assertEqual(artifact['formal_requests'],1);self.assertEqual(artifact['proved_unsent_slots'],0)
        self.assertEqual(len(artifact['unknown_cost_requests']),1)
        self.assertEqual(artifact['new_unknown_fee_hold_points'],410000)
        self.assertEqual(len(artifact['unknown_wire_usage_requests']),1)


if __name__=='__main__':unittest.main()
