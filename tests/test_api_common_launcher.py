"""Offline launcher regression: all SSH/API/submission programs are local stubs."""
import os
import pty
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir()
        deploy = self.root / 'deploy/api-common'
        deploy.mkdir(parents=True)
        (self.root / 'reports/api-common-20261111').mkdir(parents=True)
        (deploy / 'inspect_remote.py').write_text('# offline fixture only\n')
        fakebin = self.root / 'bin'
        fakebin.mkdir()
        stub = '''import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
with open(os.environ['TRACE'],'a') as f:f.write(name+'\\n')
if name=='caffeinate':
 assert os.environ.get('LEAFAPI_API_KEY'), 'fixture Mac child must receive credential'
 if os.environ.get('FIXTURE_EXPORT')=='1':
  pathlib.Path(os.environ['FIXTURE_STATE'],'export.json').write_text('{}')
 sys.exit(2 if os.environ.get('FIXTURE_EXPORT')!='1' else 0)
assert 'LEAFAPI_API_KEY' not in os.environ, 'fixture SSH/offline child must not receive credential'
print('{}')
'''
        for name in ['ssh', 'caffeinate', 'fixture-python']:
            path = fakebin / name
            path.write_text('#!' + sys.executable + '\n' + stub)
            path.chmod(0o700)
        self.launch = deploy / 'start.sh'
        source = (ROOT / 'deploy/api-common/start.sh').read_text()
        source = source.replace('HDL_ROOT=$(cd "$(dirname "$0")/../.." && pwd)',
                                'HDL_ROOT=' + shlex.quote(str(self.root)))
        source = source.replace('HDL_PY=/Users/DDXQL/Developer/cluster-deployment/mac-portability-env-v2/bin/python',
                                'HDL_PY=' + shlex.quote(str(fakebin / 'fixture-python')))
        source = source.replace('HDL_STATE="$HOME/hdl-api-validation/mac-cluster-api-v5-20261111/mac"',
                                'HDL_STATE=' + shlex.quote(str(self.state)))
        self.launch.write_text(source)
        (deploy / 'submit_cluster.sh').write_text('printf "submit-stub\\n" >> "$TRACE"\n')
        self.env = {'PATH': str(fakebin) + os.pathsep + os.defpath,
                    'TRACE': str(self.root / 'trace'), 'FIXTURE_STATE': str(self.state)}
        self.args = ['/bin/bash', str(self.launch), '--allow-api', '--approve-total', '4']

    def trace(self):
        p = self.root / 'trace'
        return p.read_text().splitlines() if p.exists() else []

    def invoke(self):
        return subprocess.run(self.args, env=self.env, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)

    def test_absent_or_malformed_env_stops_before_ssh_and_api(self):
        for value in [None, '', ' ', 'fixture\nmalformed']:
            with self.subTest(value=value):
                if value is None:
                    self.env.pop('LEAFAPI_API_KEY', None)
                else:
                    self.env['LEAFAPI_API_KEY'] = value
                result = self.invoke()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.trace(), [])
                self.assertNotIn('fixture\nmalformed', result.stdout)

    def test_failed_mac_without_export_never_calls_cluster_helper(self):
        self.env['LEAFAPI_API_KEY'] = 'offline-fixture-value'
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('submit-stub', self.trace())
        self.assertEqual(self.trace().count('caffeinate'), 1)
        self.assertIn('不传输或提交', result.stdout)
        self.assertNotIn('No such file', result.stdout)
        self.assertNotIn('offline-fixture-value', result.stdout)

    def test_existing_claim_is_preserved_and_not_relaunched(self):
        claim = self.state / 'claim.json'
        claim.write_text('{"preserved":true}')
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(claim.read_text(), '{"preserved":true}')
        self.assertEqual(self.trace(), [])

    def test_terminal_input_is_hidden_and_existing_inventory_is_preserved(self):
        report = self.root / 'reports/api-common-20261111'
        old = report / 'remote-before.json'
        old.write_text('{"historical":true}')
        self.env['FIXTURE_EXPORT'] = '1'
        pid, master = pty.fork()
        if pid == 0:
            os.execve('/bin/bash', self.args, self.env)
        output = bytearray()
        sent = False
        status = None
        deadline = time.monotonic() + 6
        try:
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], .1)
                if ready:
                    try:
                        block = os.read(master, 65536)
                    except OSError:
                        block = b''
                    if not block:
                        break
                    output.extend(block)
                    if not sent and '隐藏输入'.encode() in output:
                        # Bash disables terminal echo for this read.
                        time.sleep(.05)
                        os.write(master, b'offline-hidden-fixture\n')
                        sent = True
            done, status = os.waitpid(pid, os.WNOHANG)
            if not done:
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
                self.fail('offline terminal fixture did not finish')
        finally:
            os.close(master)
        self.assertTrue(sent)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode(errors='replace'))
        self.assertNotIn(b'offline-hidden-fixture', output)
        self.assertIn('submit-stub', self.trace())
        self.assertEqual(old.read_text(), '{"historical":true}')
        self.assertEqual(len(list(report.glob('launch-*/remote-before.json'))), 1)
        self.assertNotIn('offline-hidden-fixture', (report / 'user-launch.log').read_text())

    def test_direct_submit_without_mac_export_stops_before_any_ssh(self):
        source = (ROOT / 'deploy/api-common/submit_cluster.sh').read_text()
        source = source.replace('HDL_MAC_EXPORT="$HOME/hdl-api-validation/mac-cluster-api-v5-20261111/mac/export.json"',
                                'HDL_MAC_EXPORT=' + shlex.quote(str(self.state / 'export.json')))
        script = self.root / 'submit-fixture.sh'
        script.write_text(source)
        result = subprocess.run(['/bin/bash', str(script), 'run', '--approve-total', '4'],
                                env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.trace(), [])
        self.assertIn('不提交', result.stdout)


if __name__ == '__main__':
    unittest.main()
