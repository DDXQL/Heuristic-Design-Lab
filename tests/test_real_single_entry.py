"""Real entry offline checks; no model transport, formal prepare or solving."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from experiments.common import run_r3,run_b1_v6
from experiments.common import _real_run as launcher,_search_reports as reports
from heuristic_design.core.storage import write,sha


def kwargs(module,stage):
    return dict(root=module.ROOT,stage=stage,run_root=module.RUN_ROOT,prefix=module.RUN_PREFIX,
        min_free_gib=module.MIN_FREE_GIB,r1_runs=module.R1_RUNS,pilot_run=None,entry=Path(module.__file__),
        authorization_file=module.AUTHORIZATION_FILE)


def offline_receipts(folder):
    """Synthetic metadata only, never a generated/evaluated candidate."""
    tasks={};plan=[]
    for subject in ('A','B'):
        for operator in ('CROSS','MUTATE'):
            tid=subject+'-'+operator
            task={'id':tid,'stage':'evolution','generation':1,'operator':operator,'subject':subject,
                'parents':[subject,'B' if subject=='A' else 'A'] if operator=='CROSS' else [subject],
                'parent_keys':[subject+'-key'], 'valid':True,'request_key':'unit/'+tid,
                'response_path':'responses/'+tid+'.json','sent_confirmed':True,
                'wire_send_confirmed_at_unix':1.,'generation_timing':{'started_at_unix':0.,'finished_at_unix':3.}}
            tasks[tid]=task;plan.append(task.copy())
            write(folder/task['response_path'],{'ok':True,'value':{'usage':{'input_tokens':10,'output_tokens':2},
                'metadata':{'http_status':200,'model':'UNIT_TEST_ONLY_MODEL'}}})
            write(folder/'worker-receipts'/tid/'lifecycle.json',{'all_results_received':True,'exitcode':0,'alive':False,
                'started_monotonic':1.,'finished_monotonic':3.})
    write(folder/'plans/G001.json',{'population':[{'id':'A'},{'id':'B'}],'tasks':plan})
    for i,subject in enumerate(('A','B')):
        ids=[subject+'-CROSS',subject+'-MUTATE']
        write(folder/'batch-receipts'/f'{i}.json',{'tasks':ids,'semantics_commit_order':ids})
    p={'config':{'provider':{'expected_response_model':'UNIT_TEST_ONLY_MODEL'}}}
    write(folder/'Protocol.json',p);write(folder/'Protocol.receipt.json',{'sha256':sha(folder/'Protocol.json')})
    s={'identity':sha(folder/'Protocol.json'),'phase':'completed','generation':1,'initialization_complete':True,
       'initialization_requests':2,'generation_requests':4,'tasks':tasks,
       'plans':{'1':{'path':'plans/G001.json','sha256':sha(folder/'plans/G001.json')}}}
    write(folder/'checkpoint.json',s)
    return p,s


class Tests(unittest.TestCase):
    def test_actual_R1_preflight_and_dry_run_never_prepare_solve_or_connect(self):
        with patch('socket.socket.connect',side_effect=AssertionError('NO NETWORK')), \
             patch.object(launcher.engine,'prepare',side_effect=AssertionError('NO PREPARE')), \
             patch.object(launcher.engine,'run',side_effect=AssertionError('NO SOLVE')),redirect_stdout(io.StringIO()):
            self.assertEqual(launcher.launch(run_r3.PARAMETERS,**kwargs(run_r3,'r3'),check_only=True),0)

    def test_disabled_API_refuses_before_new_run_or_credential_access(self):
        c=deepcopy(run_r3.PARAMETERS)
        c['real_requests_authorized']=False
        with patch.object(launcher,'preflight',return_value=(c,{'blocking':[]},{})), \
             patch.object(launcher.engine,'prepare') as prepare,redirect_stdout(io.StringIO()),self.assertRaises(PermissionError):
            launcher.launch(c,**kwargs(run_r3,'r3'))
        prepare.assert_not_called()

    def test_full_run_has_storage_and_pilot_gates_before_paid_start(self):
        c,plan,_=launcher.preflight(run_b1_v6.PARAMETERS,**{k:v for k,v in kwargs(run_b1_v6,'b1').items() if k not in ('prefix','entry')})
        self.assertTrue(c['real_requests_authorized']);self.assertTrue(plan['blocking'])
        self.assertTrue(any('R3_RUN_DIR' in r for r in plan['blocking']))
        self.assertEqual(plan['total_attempt_cap'],1050)

    def test_unknown_provider_parameter_fails_instead_of_being_ignored(self):
        parameters=deepcopy(run_r3.PARAMETERS);parameters['provider']['unused_option']=1
        with self.assertRaises(TypeError):
            launcher.preflight(parameters,**{k:v for k,v in kwargs(run_r3,'r3').items() if k not in ('prefix','entry')})

    def test_claimed_R3_authorization_blocks_another_new_paid_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'authorization.json'
            path.write_bytes((run_r3.ROOT/run_r3.AUTHORIZATION_FILE).read_bytes())
            write(path.with_suffix('.claim.json'),{'run_directory':'UNIT_ONLY_ALREADY_BOUND'})
            args={k:v for k,v in kwargs(run_r3,'r3').items() if k not in ('prefix','entry')}
            args['authorization_file']=path
            _,plan,_=launcher.preflight(run_r3.PARAMETERS,**args)
            self.assertTrue(any('UNIT_ONLY_ALREADY_BOUND' in s for s in plan['blocking']))

    def test_more_than_approved_attempts_requires_a_new_explicit_scope(self):
        parameters=deepcopy(run_r3.PARAMETERS)
        parameters.update(initialization_candidate_cap=5,initialization_request_cap=5,api_attempt_cap=9)
        with self.assertRaises(PermissionError):
            launcher.preflight(parameters,**{k:v for k,v in kwargs(run_r3,'r3').items() if k not in ('prefix','entry')})

    def test_overlaps_and_parent_receipts_are_required_for_online_acceptance(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);offline_receipts(path)
            good=reports.evidence(path)
            self.assertTrue(good['passed']);self.assertEqual(len(good['api_client_overlap']),2)
            self.assertEqual(len(good['cpu_worker_overlap']),2)
            reply=reports.read(path/'responses/A-CROSS.json');reply['value']['metadata']['http_status']=429
            write(path/'responses/A-CROSS.json',reply)
            bad=reports.evidence(path)
            self.assertFalse(bad['passed']);self.assertIn('A-CROSS',bad['transport_or_model_failures'])

    def test_stream_instance_export_skips_trace_and_preserves_quality(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'result.json';write(path,{'instances':[{'file':'unit','score':-2.,
                'solution':{'operations':[{'job':0}], 'makespan':12},'trace':[{'file':'not-an-instance'}],
                'captured_solves':2,'feasible':True}]})
            rows=list(reports.instance_rows(path))
            self.assertEqual(rows,[{'file':'unit','score':-2.,'Cmax':12,'captured_solves':2,'feasible':True}])

    def test_skipped_duplicate_does_not_get_a_second_instance_evaluation(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder);p={'config':{'provider':{'expected_response_model':'UNIT_ONLY'}},
                                'references':[{'file':'unit','reference':6}]}
            write(path/'Protocol.json',p);write(path/'Protocol.receipt.json',{'sha256':sha(path/'Protocol.json')})
            original={'id':'original','candidate':{'key':'k'},'valid':True}
            duplicate={'id':'duplicate','candidate':{'key':'k'},'valid':False,'duplicate_of':'original'}
            s={'identity':sha(path/'Protocol.json'),'phase':'completed','generation':0,'initialization_complete':True,
               'initialization_requests':0,'generation_requests':0,'tasks':{'original':original,'duplicate':duplicate},
               'plans':{},'evaluations':{'k':{'path':'evaluations/k/result.json'}}}
            write(path/'checkpoint.json',s);write(path/'evaluations/k/result.json',{'instances':[{
                'file':'unit','score':-2.,'solution':{'makespan':12},'captured_solves':2,'feasible':True}]})
            (path/'exports').mkdir();reports.finish(path,{'champion':None})
            import csv
            with (path/'exports/per_instance.csv').open() as stream:rows=list(csv.DictReader(stream))
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['candidate'],'original')


if __name__=='__main__':unittest.main()
