"""No-network tests for exact saved-wire completion after a user pause."""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from tools.finish_paused_usage_reply import pending_binding,closed_record,sha
from fjsp_usage.research.events import atomic_json
from fjsp_usage.research.protocol import digest
from fjsp_usage.research_real.budget import BudgetStop


class PausedReplyTests(unittest.TestCase):
    def fixture(self,p):
        identifier='B/g0000/000000';key='r301/B/'+identifier;name=hashlib.sha256(key.encode()).hexdigest()+'.json'
        pk=digest({'prompt':'original prompt','kind':'U'});now=time.time()
        old={'status':'pending','before_used':10,'reserved':100,'send_confirmed':True,'started_at':now-5}
        reply={'text':'saved exact candidate','usage':{'input_tokens':2,'output_tokens':1},
            'metadata':{'model':'gpt-6.1-sol','gateway_request_id':'supplier'}}
        values={'budget.json':{'records':{key:{'status':'reserved','send_confirmed':True,'prompt_key':pk}}},
            'platform_quota.json':{'records':{key:old}},
            'r301/B/checkpoint.json':{'inflight':{'id':identifier,'initial':False,'prompt':'original prompt'},'attempts':[],'evaluations':{}},
            'r301/B/budgeted_evolution_requests.json':{'requests':{identifier:{'status':'pending','global_key':key,'prompt_key':pk,'prompt':'original prompt'}}},
            'billing/'+name:{'global_key':key,'status':'before_dispatch','before':{'success':True,'records':[]}},
            'wire_responses/'+name:{'global_key':key,'prompt_key':pk,'status':'wire_completed_before_settlement','send_confirmed':True,'reply':reply}}
        for n,b in values.items():atomic_json(p/n,b)
        wp=p/'wire_responses'/name;os.utime(wp,(now-1,now-1))
        pause={'status':'PAUSED_BY_USER','last_key':key,'last_wire_status':'wire_completed_before_settlement',
            'observed_at_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'immutable_snapshot_files_sha256':{n:sha(p/n) for n in ('budget.json','platform_quota.json','r301/B/checkpoint.json','wire_responses/'+name)}}
        pp=p/'User_pause.json';atomic_json(pp,pause)
        return pp,key,old,reply,values['billing/'+name],now-1

    def test_exact_complete_pending_wire_can_be_used_without_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);pp,key,_,reply,_,_=self.fixture(p)
            got,identifier,paths,bodies,_=pending_binding(p,pp)
            self.assertEqual(got,key);self.assertEqual(bodies['wire']['reply'],reply)
            self.assertEqual(bodies['budget']['records'][key]['status'],'reserved')

    def test_changed_source_failed_slot_prompt_or_missing_complete_wire_rejected(self):
        for change in ('budget','wire','prompt','failed','evaluated'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);pp,key,_,_,_,_=self.fixture(p)
                name='budget.json' if change=='budget' else 'r301/B/budgeted_evolution_requests.json'
                if change=='wire':name='wire_responses/'+hashlib.sha256(key.encode()).hexdigest()+'.json'
                if change=='evaluated':name='r301/B/checkpoint.json'
                d=json.loads((p/name).read_text())
                if change=='budget':d['records'][key]['send_confirmed']=False
                elif change=='wire':d['status']='pending'
                elif change=='prompt':d['requests']['B/g0000/000000']['prompt']='other prompt'
                elif change=='failed':d['requests']['B/g0000/000000']['status']='failed'
                else:d['evaluations']['B/g0000/000000']={'status':'pending'}
                atomic_json(p/name,d)
                with self.assertRaises(BudgetStop):pending_binding(p,pp)

    def test_receipt_exact_identity_window_usage_group_debit_and_reserve_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            pp,key,old,reply,bill,finished=self.fixture(Path(tmp))
            invoice={'model_name':'gpt-6.1-sol','type':2,'request_id':'supplier','created_at':old['started_at']+1,
                'group':'codex-deafult','quota':3,'prompt_tokens':2,'completion_tokens':1}
            after={'success':True,'records':[invoice]};balance={'total_used':13}
            account,matched=closed_record(old,finished,balance,after,bill,reply,'gpt-6.1-sol')
            self.assertEqual(matched,invoice);self.assertEqual(account['status'],'settled');self.assertEqual(old['status'],'pending')
            for field,value in [('request_id','other'),('model_name','wrong'),('created_at',finished+100),('quota',4),('group','wrong'),('prompt_tokens',99)]:
                bad=deepcopy(after);bad['records'][0][field]=value
                with self.assertRaises(BudgetStop):closed_record(old,finished,balance,bad,bill,reply,'gpt-6.1-sol')


if __name__=='__main__':unittest.main()
