"""Handcrafted recording-only fixtures; no real model/benchmark requests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from resume_single_settlement import WireRecorder
from fjsp_usage.research_real.budget import BudgetStop


class Fake:
    config=None;identity='fake';secret='not-real';redact=staticmethod(str)
    calls=0
    def preflight(self,prompt):pass
    def dispatch(self,key,prompt,*,kind,on_sent):
        self.calls+=1;on_sent()
        return {'text':'handwritten local fixture, not a candidate','usage':{'input_tokens':2,'output_tokens':3}}


class RecorderTests(unittest.TestCase):
    def test_wire_reply_survives_downstream_metadata_failure_without_changing_response(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Fake();sent=[];checks=[]
            recorder=WireRecorder(base,tmp,lambda:checks.append(True))
            result=recorder.dispatch('r201/init/fixture','prompt',on_sent=lambda:sent.append(True))
            saved=json.loads(next(Path(tmp).glob('*.json')).read_text())
            self.assertEqual(result,saved['reply']);self.assertTrue(saved['send_confirmed'])
            self.assertEqual(base.calls,1);self.assertEqual(sent,[True]);self.assertTrue(checks)
            with self.assertRaises(BudgetStop):recorder.dispatch('r201/init/fixture','prompt')
            self.assertEqual(base.calls,1)

    def test_no_dispatch_when_recording_amendment_is_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Fake()
            def reject():raise BudgetStop('amendment changed')
            recorder=WireRecorder(base,tmp,reject)
            with self.assertRaises(BudgetStop):recorder.dispatch('one','prompt')
            self.assertEqual(base.calls,0)
            self.assertEqual(list(Path(tmp).glob('*.json')),[])


if __name__=='__main__':unittest.main()
