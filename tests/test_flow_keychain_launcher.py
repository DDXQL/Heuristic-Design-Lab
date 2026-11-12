"""Local stubs only: never touch the real Keychain, launcher, API or solver."""
import os
from pathlib import Path
import pty
import shlex
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class KeychainLauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();folder=self.root/'deploy/flow-check';folder.mkdir(parents=True)
        stub='''import os,pathlib,sys
assert 'LEAFAPI_API_KEY' not in os.environ
assert 'HDL_SAVED_KEY' not in os.environ
assert 'synthetic-key' not in sys.argv
with open(os.environ['TRACE'],'a') as f:f.write(' '.join(sys.argv[1:])+'\\n')
if sys.argv[1]=='add-generic-password':
 assert sys.argv[-1]=='-w'
 assert '-A' not in sys.argv
 assert sys.stdin.isatty()
 sys.exit(0)
if os.environ.get('DENY'):sys.exit(36)
print('bad key' if os.environ.get('MALFORMED') else 'synthetic-key')
'''
        security=self.root/'security-stub';security.write_text('#!'+sys.executable+'\n'+stub);security.chmod(0o700)
        source=(ROOT/'deploy/flow-check/start-with-keychain.sh').read_text()
        source=source.replace('HDL_SECURITY=/usr/bin/security','HDL_SECURITY='+shlex.quote(str(security)))
        self.wrapper=folder/'start-with-keychain.sh';self.wrapper.write_text(source)
        (folder/'start.sh').write_text('''set -eu
[ "$LEAFAPI_API_KEY" = synthetic-key ]
[ -z "${HDL_SAVED_KEY+x}" ]
printf 'TARGET %s\\n' "$*" >> "$TRACE"
exit "${TARGET_RC:-0}"
''')
        self.env={'PATH':os.defpath,'TRACE':str(self.root/'trace')}
        self.flags=['--allow-api','--approve-api','2','--allow-evaluation','--approve-solves','12']

    def call(self,args,*,tty=False):
        descriptors=[]
        if tty:
            master,slave=pty.openpty();descriptors=[master,slave];stdin=slave
        else:stdin=subprocess.DEVNULL
        try:
            return subprocess.run(['/bin/bash',str(self.wrapper),*args],env=self.env,stdin=stdin,
                capture_output=True,text=True,timeout=8)
        finally:
            for descriptor in descriptors:os.close(descriptor)

    def trace(self):
        p=self.root/'trace';return p.read_text() if p.exists() else ''

    def test_default_and_check_only_do_not_access_keychain_or_launch(self):
        for args in [[],['--check-only']]:
            result=self.call(args);self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('keychain_reads=0',result.stdout)
        self.assertEqual(self.trace(),'')

    def test_setup_prompts_in_native_tool_without_secret_argv_and_does_not_launch(self):
        result=self.call(['--setup-only'],tty=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('add-generic-password',self.trace());self.assertIn('find-generic-password',self.trace())
        self.assertNotIn('TARGET',self.trace());self.assertNotIn('synthetic-key',result.stdout+result.stderr+self.trace())

    def test_setup_noninteractive_refuses_before_access(self):
        result=self.call(['--setup-only']);self.assertEqual(result.returncode,2)
        self.assertEqual(self.trace(),'')

    def test_saved_key_is_only_passed_to_original_launcher_with_unchanged_flags(self):
        result=self.call(self.flags);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.trace().count('find-generic-password'),1)
        self.assertIn('TARGET '+' '.join(self.flags),self.trace());self.assertNotIn('synthetic-key',self.trace()+result.stdout+result.stderr)

    def test_missing_or_denied_key_does_not_prompt_store_retry_or_launch(self):
        self.env['DENY']='1';result=self.call(self.flags);self.assertEqual(result.returncode,2)
        self.assertEqual(self.trace().count('find-generic-password'),1)
        self.assertNotIn('TARGET',self.trace());self.assertNotIn('add-generic-password',self.trace())

    def test_malformed_saved_key_never_reaches_original_launcher(self):
        self.env['MALFORMED']='1';result=self.call(self.flags);self.assertEqual(result.returncode,2)
        self.assertNotIn('TARGET',self.trace());self.assertNotIn('bad key',result.stdout+result.stderr)

    def test_explicit_environment_override_is_not_saved_or_queried(self):
        self.env['LEAFAPI_API_KEY']='synthetic-key';result=self.call(self.flags)
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(self.trace().startswith('TARGET'))

    def test_bad_flags_do_not_read_credentials_or_launch(self):
        result=self.call(['--allow-api']);self.assertEqual(result.returncode,2);self.assertEqual(self.trace(),'')

    def test_resume_and_child_failure_propagate_without_retry(self):
        self.env['TARGET_RC']='7';result=self.call(['--resume',*self.flags])
        self.assertEqual(result.returncode,7);self.assertEqual(self.trace().count('TARGET'),1)
        self.assertIn('TARGET --resume',self.trace())


if __name__=='__main__':unittest.main()
