"""Read-only collector checks; no SSH, model calls, solving or scheduler calls."""
import contextlib
import importlib.util
import io
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('collector', ROOT/'tools/api_reliability_collect.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class CollectorTests(unittest.TestCase):
    def remote_fixture(self, pending=True, resources=False, unreadable=False,
                       disable_requeue=False, plan_matches=True, owner_matches=True, update_fails=False,
                       long_policy=False, archived=False, accounting_parent=True, accounting_terminal=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        release = root/'release'
        release.mkdir()
        (release/'deploy/api-common').mkdir(parents=True)
        (release/'deploy/api-common/plan.json').write_bytes(
            (ROOT/'deploy/api-common/plan.json').read_bytes() if plan_matches else b'{}')
        state = root/'hdl-api-validation/mac-cluster-api-v5-20261111/cluster'
        code = c.REMOTE.replace('/public2/home/qiuqian/hdl-deploy/api-common-v5-20261111', str(release))
        code = code.replace('/public2/home/qiuqian/hdl-api-validation/mac-cluster-api-v5-20261111/cluster', str(state))
        if not pending:
            state.mkdir(parents=True)
            (state/'ledger.json').write_text(json.dumps({'status':'failed_closed','totals':{'reserved':1}}))
            (release/'logs').mkdir()
            (release/'logs/api-v5-609676.err').write_text('fixture sk-sensitivefixturevalue\n')
        calls = [];updated=[False]
        def query(args, **kw):
            calls.append(args)
            self.assertIn(args[0], ['squeue','sacct','scontrol','sinfo','sacctmgr'])
            self.assertNotIn('requeue',args)
            if 'update' in args:
                self.assertTrue(disable_requeue)
                self.assertEqual(args,['scontrol','update','JobId=609676','Requeue=0'])
                updated[0]=not update_fails
                return types.SimpleNamespace(returncode=1 if update_fails else 0,stdout='',stderr='fixture denied' if update_fails else '')
            if args[0] == 'squeue':
                stdout = '609676 hdl-api-v5 PENDING Resources\n' if pending else ''
            elif args[0] == 'sacct':
                stdout = '609676 PENDING 0:0\n' if pending else '609676 FAILED 2:0\n'
                if archived:stdout=('609676' if accounting_parent else '609676.0')+' hdl-api-v5 '+('COMPLETED' if accounting_terminal else 'RUNNING')+' 0:0 00:00:22 node15\n'
            else:
                stdout = ('JobId=609676 Partition=128C_02 Requeue='+('0' if updated[0] else '1')+
                          ' Restarts=0 UserId=qiuqian('+('1078' if owner_matches else '9999')+') Command='+
                          str(release/'deploy/api-common/cluster.sbatch')+' JobState='+('PENDING' if pending else 'FAILED'))
            if args==['scontrol','show','partition'] and long_policy:stdout='fixture-long-policy '*2000
            if args==['scontrol','show','job','609676'] and archived:
                return types.SimpleNamespace(returncode=1,stdout='',stderr='Invalid job id specified')
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr='')
        output = io.StringIO()
        original_read = Path.read_bytes
        def read(path):
            if unreadable and path.name=='ledger.json':raise PermissionError('fixture unreadable ledger')
            return original_read(path)
        with patch('subprocess.run', side_effect=query), patch.object(Path,'home',return_value=root), \
                patch('sys.argv',['remote','609676']+(['--resources'] if resources else [])+(['--disable-requeue'] if disable_requeue else [])), \
                patch('os.getuid',return_value=1078), \
                patch.object(Path,'read_bytes',read), contextlib.redirect_stdout(output):
            exec(compile(code,'<offline-remote-fixture>','exec'), {})
        return json.loads(output.getvalue()), calls

    def test_pending_with_missing_state_and_logs_is_collected_without_failure(self):
        value, calls = self.remote_fixture()
        self.assertEqual(len(calls),3)
        self.assertIn('PENDING',value['queue']['stdout'])
        self.assertFalse(any(s['exists'] for s in value['states']))
        self.assertFalse(any(f['exists'] for f in value['logs']))
        self.assertIsNone(c.summary(value)['states'][0]['totals'])

    def test_existing_failed_ledger_and_redacted_log_are_retained(self):
        value, _ = self.remote_fixture(pending=False)
        self.assertEqual(c.summary(value)['states'][0]['phase'],'failed_closed')
        self.assertEqual(c.summary(value)['states'][0]['totals']['reserved'],1)
        encoded = json.dumps(value)
        self.assertNotIn('sk-sensitivefixturevalue',encoded)
        self.assertIn('[REDACTED]',encoded)

    def test_resources_add_six_read_only_queries_and_preserve_unknown_limits(self):
        value, calls = self.remote_fixture(resources=True)
        self.assertEqual(len(calls),9)
        self.assertEqual(value['resources']['partition_query_target'],'128C_02')
        self.assertIn('associations',value['resources'])
        self.assertIn('qos',value['resources'])
        self.assertEqual(c.summary(value)['job_fields']['Requeue'],'1')
        self.assertEqual(len(c.summary(value)['resource_checks']),6)
        self.assertIsNone(c.summary(value)['states'][0]['totals'])

    def test_unreadable_ledger_retains_scheduler_evidence_without_zero_cost_claim(self):
        value, calls = self.remote_fixture(pending=False,unreadable=True)
        self.assertEqual(len(calls),3)
        self.assertIn('FAILED',value['accounting']['stdout'])
        ledger=next(f for f in value['states'][0]['files'] if f['path'].endswith('/ledger.json'))
        self.assertEqual(ledger['read_error_type'],'PermissionError')
        self.assertIsNone(c.summary(value)['states'][0]['totals'])

    def test_truncated_partition_material_is_explicitly_marked(self):
        value,_=self.remote_fixture(resources=True,long_policy=True)
        policy=value['resources']['partition_policy']
        self.assertTrue(policy['stdout_truncated'])
        self.assertEqual(len(policy['stdout']),20000)
        self.assertTrue(c.summary(value)['resource_checks']['partition_policy']['stdout_truncated'])

    def test_explicit_requeue_disable_updates_only_verified_existing_job(self):
        value,calls=self.remote_fixture(resources=True,disable_requeue=True)
        self.assertEqual(len(calls),12)
        self.assertEqual(value['requeue_policy_update']['status'],'verified')
        self.assertEqual(c.summary(value)['job_fields']['Requeue'],'0')
        self.assertEqual(sum('update' in cmd for cmd in calls),1)

    def test_requeue_disable_refuses_owner_or_plan_mismatch(self):
        for kwargs in [{'owner_matches':False},{'plan_matches':False}]:
            with self.subTest(**kwargs):
                value,calls=self.remote_fixture(disable_requeue=True,**kwargs)
                self.assertEqual(value['requeue_policy_update']['status'],'blocked')
                self.assertFalse(any('update' in cmd for cmd in calls))

    def test_requeue_disable_failure_does_not_retry_or_claim_verified(self):
        value,calls=self.remote_fixture(disable_requeue=True,update_fails=True)
        self.assertEqual(value['requeue_policy_update']['status'],'not_verified')
        self.assertEqual(sum('update' in cmd for cmd in calls),1)
        self.assertEqual(c.summary(value)['job_fields']['Requeue'],'1')

    def test_terminal_job_is_preserved_without_requeue_update(self):
        value,calls=self.remote_fixture(pending=False,disable_requeue=True)
        self.assertEqual(value['requeue_policy_update']['status'],'terminal_no_update')
        self.assertFalse(any('update' in cmd for cmd in calls))

    def test_archived_completed_parent_is_not_a_failed_policy_operation(self):
        value,calls=self.remote_fixture(pending=False,disable_requeue=True,archived=True)
        update=value['requeue_policy_update']
        self.assertEqual(update['status'],'terminal_no_update')
        self.assertEqual(update['job_state'],'COMPLETED')
        self.assertEqual(update['source'],'sacct exact parent job')
        self.assertFalse(any('update' in cmd for cmd in calls))

    def test_missing_active_job_without_terminal_parent_remains_blocked(self):
        for kwargs in [{'accounting_parent':False},{'accounting_terminal':False}]:
            with self.subTest(**kwargs):
                value,calls=self.remote_fixture(pending=False,disable_requeue=True,archived=True,**kwargs)
                self.assertEqual(value['requeue_policy_update']['status'],'blocked')
                self.assertFalse(any('update' in cmd for cmd in calls))

    def test_check_only_never_connects_or_creates_output(self):
        with patch.object(c.subprocess,'run',side_effect=AssertionError('NO SSH')), \
                patch.object(c.Path,'mkdir',side_effect=AssertionError('NO OUTPUT')), \
                patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(c.main(['--check-only','--resources','--disable-requeue']),0)

    def test_ssh_failure_does_not_retry_or_save_unparsed_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'reports/api-common-20261111').mkdir(parents=True)
            result = types.SimpleNamespace(returncode=255,stdout='untrusted banner')
            with patch.object(c,'ROOT',root),patch.object(c.subprocess,'run',return_value=result) as run, \
                    patch('sys.stderr',new_callable=io.StringIO):
                self.assertEqual(c.main([]),2)
            self.assertEqual(run.call_count,1)
            files=list(root.rglob('*.json'))
            self.assertEqual(len(files),1)
            self.assertNotIn('untrusted banner',files[0].read_text())
            self.assertEqual(json.loads(files[0].read_text())['requests_added'],0)

    def test_success_saves_collection_once_with_no_slurm_submission(self):
        value, _ = self.remote_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'reports/api-common-20261111').mkdir(parents=True)
            result = types.SimpleNamespace(returncode=0,stdout=json.dumps(value))
            with patch.object(c,'ROOT',root),patch.object(c.subprocess,'run',return_value=result) as run, \
                    patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(c.main([]),0)
            self.assertEqual(run.call_count,1)
            command=run.call_args.args[0]
            self.assertEqual(command[0],'ssh')
            self.assertEqual(len(list(root.rglob('remote.json'))),1)

    def test_resources_flag_is_forwarded_in_same_single_ssh_connection(self):
        value, _ = self.remote_fixture(resources=True)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'reports/api-common-20261111').mkdir(parents=True)
            result=types.SimpleNamespace(returncode=0,stdout=json.dumps(value))
            with patch.object(c,'ROOT',root),patch.object(c.subprocess,'run',return_value=result) as run, \
                    patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(c.main(['--resources']),0)
            self.assertEqual(run.call_count,1)
            self.assertTrue(run.call_args.args[0][-1].endswith('609676 --resources'))

    def test_flow_profile_flag_is_forwarded_without_job_update(self):
        value,_=self.remote_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'reports/flow-check-20261112').mkdir(parents=True)
            result=types.SimpleNamespace(returncode=0,stdout=json.dumps(value))
            with patch.object(c,'ROOT',root),patch.object(c.subprocess,'run',return_value=result) as run,patch('sys.stdout',new_callable=io.StringIO):
                self.assertEqual(c.main(['--flow-profile']),0)
            self.assertTrue(run.call_args.args[0][-1].endswith('609676 --flow-profile'))
            self.assertEqual(len(list((root/'reports/flow-check-20261112').glob('collected-*/remote.json'))),1)

    def test_flow_profile_cannot_modify_job_policy(self):
        with patch.object(c.subprocess,'run',side_effect=AssertionError('NO SSH')),patch('sys.stderr',new_callable=io.StringIO),self.assertRaises(SystemExit):
            c.main(['--flow-profile','--disable-requeue'])

    def test_remote_flow_profile_reads_its_checkpoint_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();release=root/'release';state=root/'hdl-flow-validation/fjsp-state-a-flow-20261112/cluster'
            state.mkdir(parents=True);(release/'deploy/flow-check').mkdir(parents=True)
            (state/'checkpoint.json').write_text('{"phase":"completed"}')
            (state/'export.json').write_text('{}');(release/'deploy/flow-check/plan.json').write_text('{}')
            code=c.REMOTE.replace('/public2/home/qiuqian/hdl-deploy/fjsp-state-a-flow-20261112',str(release)).replace('/public2/home/qiuqian/hdl-flow-validation/fjsp-state-a-flow-20261112/cluster',str(state))
            output=io.StringIO();result=types.SimpleNamespace(returncode=0,stdout='',stderr='')
            with patch('subprocess.run',return_value=result) as run,patch.object(Path,'home',return_value=root),patch('sys.argv',['remote','123','--flow-profile']),contextlib.redirect_stdout(output):
                exec(compile(code,'offline-flow-collection','exec'),{})
            value=json.loads(output.getvalue());names={Path(f['path']).name for f in value['states'][0]['files']}
            self.assertIn('checkpoint.json',names);self.assertNotIn('ledger.json',names)
            self.assertEqual(c.summary(value)['states'][0]['phase'],'completed')
            self.assertEqual(run.call_count,3)


if __name__ == '__main__':
    unittest.main()
