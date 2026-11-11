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
    def remote_fixture(self, pending=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        release = root/'release'
        release.mkdir()
        state = root/'hdl-api-validation/mac-cluster-api-v5-20261111/cluster'
        code = c.REMOTE.replace('/public2/home/qiuqian/hdl-deploy/api-common-v5-20261111', str(release))
        code = code.replace('/public2/home/qiuqian/hdl-api-validation/mac-cluster-api-v5-20261111/cluster', str(state))
        if not pending:
            state.mkdir(parents=True)
            (state/'ledger.json').write_text(json.dumps({'status':'failed_closed','totals':{'reserved':1}}))
            (release/'logs').mkdir()
            (release/'logs/api-v5-609676.err').write_text('fixture sk-sensitivefixturevalue\n')
        calls = []
        def query(args, **kw):
            calls.append(args)
            self.assertIn(args[0], ['squeue','sacct','scontrol'])
            if args[0] == 'squeue':
                stdout = '609676 hdl-api-v5 PENDING Resources\n' if pending else ''
            elif args[0] == 'sacct':
                stdout = '609676 PENDING 0:0\n' if pending else '609676 FAILED 2:0\n'
            else:
                stdout = 'JobId=609676 JobState='+('PENDING' if pending else 'FAILED')
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr='')
        output = io.StringIO()
        with patch('subprocess.run', side_effect=query), patch.object(Path,'home',return_value=root), \
                patch('sys.argv',['remote','609676']), contextlib.redirect_stdout(output):
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

    def test_check_only_never_connects_or_creates_output(self):
        with patch.object(c.subprocess,'run',side_effect=AssertionError('NO SSH')), \
                patch.object(c.Path,'mkdir',side_effect=AssertionError('NO OUTPUT')), \
                patch('sys.stdout',new_callable=io.StringIO):
            self.assertEqual(c.main(['--check-only']),0)

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


if __name__ == '__main__':
    unittest.main()
