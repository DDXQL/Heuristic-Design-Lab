"""Saved-record report fixture. No real provider/solver or research candidates."""
from copy import deepcopy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import test_single_update as fixture_tests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('update_report',ROOT/'tools/report_single_update.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)

class ReportTest(unittest.TestCase):
    def test_full_saved_record_join_and_actual_parent_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);c,ledger,calls,p0,engine=fixture_tests.UpdateTest().fixture(tmp)
            a,b=engine('A'),engine('B')
            for boundary in (10,20,30):a.run_until(boundary);b.run_until(boundary)
            repeat=root/'r201';repeat.mkdir()
            for arm in ('A','B'):(root/arm).rename(repeat/arm)
            names=['HANDWRITTEN_TOY_'+str(i) for i in range(21)]
            def evaluation(fitness):
                return {'valid':True,'fitness':fitness,'total_instances':21,
                    'instances':[{'file':n,'lower_bound':100,'makespan':-100*fitness,
                        'score':fitness,'feasible':True,'single_solve_seconds':0.01,
                        'deterministic_recheck_seconds':0.02,'diagnostic_replay_seconds':0.03} for n in names]}
            for row in p0:row['training_result']=evaluation(row['fitness'])
            def write(name,data):
                (root/name).write_text(json.dumps(data))
            write('protocol.json',{'dataset':{'split':{'train':names}}})
            write('H_frozen.json',{'members':[{'fitness':p0[0]['fitness'],'training_result':evaluation(p0[0]['fitness'])}]})
            write('r201/Shared_initial.json',{'population':p0,'source_shared_hash':'HANDWRITTEN_FIXTURE','source_run':'HANDWRITTEN_P0'})
            old=deepcopy(p0[0]);old['id']='OLD_FIXTURE';old['fitness']=-9;old['training_result']=evaluation(-9)
            write('Frozen_historical_reference.json',{'row':old,'source':{'run':'HANDWRITTEN_OLD'}})
            write('Final_budget_handoff.json',{'fixture':True})
            out=root/'reports';summary=report.build(root,out,charts=False)
            self.assertTrue(summary['complete']);self.assertEqual(summary['actual_requests'],60)
            self.assertEqual(summary['champions']['OLD_FROZEN']['source_run'],'HANDWRITTEN_OLD')
            self.assertEqual(summary['champions']['INITIAL']['source_run'],'HANDWRITTEN_P0')
            self.assertEqual(summary['champions']['OLD_FROZEN']['code_key'],old['candidate']['key'])
            self.assertEqual(summary['known_points'],0);self.assertEqual(len(summary['unknown_fee_ids']),60)
            self.assertEqual(len(summary['milestones']),6);self.assertEqual(len(summary['comparison']),5)
            self.assertTrue(summary['lineage_chain']['parent_is_new'])
            proof=json.loads((out/'lineage_case/evidence.json').read_text())
            self.assertTrue(proof['parent_evaluation']['valid']);self.assertIn(proof['selected_at_slots'],(10,20))
            with (out/'requests.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),60);self.assertTrue(all(x['actual_platform_points']=='NA' for x in rows))
            self.assertTrue((out/'paired_instances.csv').exists())
            self.assertEqual(len(calls),60)  # report never dispatches or replays

if __name__=='__main__':unittest.main()
