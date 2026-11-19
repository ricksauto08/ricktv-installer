"""Isolated bootstrap regression tests. No real login, clone or installation.

Run only in a disposable Linux container with
RICKTV_BOOTSTRAP_TEST_CONTAINER=1 python3 -m unittest -v test_bootstrap.py
The fake commands exercise the real shell script, including curl-style stdin
and terminal prompts. Test-only paths must never be mounted from a host.
"""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import socket
import subprocess
import tempfile
import termios
import time
import unittest

SCRIPT = Path(__file__).with_name('setup.sh')
MOCK = r'''#!/usr/bin/env python3
import json,os,pathlib,sys
name=pathlib.Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ['TEST_LOG'],'a') as f:f.write(json.dumps([name,*args])+'\n')
if name=='id':print(os.getenv('TEST_UID','1000'))
elif name=='uname':print(os.getenv('TEST_OS','Linux') if args==['-s'] else os.getenv('TEST_ARCH','aarch64'))
elif name=='hostname':print(os.environ['TEST_IP'])
elif name=='gh':
 if args[:2]==['auth','status']:sys.exit(int(os.getenv('TEST_LOGIN_NEEDED','0')))
 if args[:2]==['auth','login']:
  print('MOCK AUTH APPROVAL: ',end='',flush=True)
  assert input()=='approved'
  sys.exit(int(os.getenv('TEST_AUTH_FAILURE','0')))
 if args[0]=='api':
  if os.getenv('TEST_NO_ACCESS'):sys.exit(1)
  print(os.getenv('TEST_PRIVATE','true'))
elif name=='git':
 if 'clone' in args:
  if os.getenv('TEST_CLONE_FAILURE'):sys.exit(1)
  root=pathlib.Path(args[-1]);(root/'install').mkdir(parents=True)
  (root/'install/install.py').write_text('# fake private installer\n')
  for wrapper in ['install-linux.sh','install-docker.sh']:
   (root/wrapper).write_text('#!/bin/sh\nprintf "MOCK PRIVATE INSTALLER %s\\n" "$*"\nexit "${TEST_INSTALL_FAILURE:-0}"\n')
 else:print('test-revision')
elif name=='docker':print(os.getenv('TEST_COMPOSE','2.30.0'))
elif name=='sudo':
 mask=os.umask(0);os.umask(mask)
 assert mask==0o022,'Private download mask leaked into system installer'
 os.execvp(args[0],args)
'''

class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('RICKTV_BOOTSTRAP_TEST_CONTAINER') != '1':
            raise unittest.SkipTest('Disposable container required')
        Path('/run/systemd/system').mkdir(parents=True,exist_ok=True)
        cls.ip=socket.gethostbyname(socket.gethostname())

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.bin=self.root/'bin';self.bin.mkdir()
        self.home=self.root/'home';self.home.mkdir()
        self.log=self.root/'commands.jsonl'
        for name in ['id','uname','hostname','gh','git','docker','sudo']:
            p=self.bin/name;p.write_text(MOCK);p.chmod(0o755)
        self.env={**os.environ,'PATH':str(self.bin)+':'+os.environ['PATH'],
                  'HOME':str(self.home),'TEST_LOG':str(self.log),'TEST_IP':self.ip}

    def run_setup(self,*args,answers=(),**env):
        master,slave=pty.openpty()
        def terminal():
            os.setsid();fcntl.ioctl(slave,termios.TIOCSCTTY,0)
        p=subprocess.Popen(['sh','-s','--',*args],stdin=subprocess.PIPE,
            stdout=slave,stderr=slave,env={**self.env,**env},preexec_fn=terminal)
        os.close(slave)
        p.stdin.write(SCRIPT.read_bytes());p.stdin.close()
        pending=list(answers);output=b'';deadline=time.monotonic()+12
        try:
            while time.monotonic()<deadline:
                if select.select([master],[],[],.1)[0]:
                    try:chunk=os.read(master,65536)
                    except OSError:break
                    if not chunk:break
                    output+=chunk
                    if pending and pending[0][0].encode() in output:
                        _,answer=pending.pop(0);os.write(master,(answer+'\n').encode())
                elif p.poll() is not None:break
            # PTY EOF can precede the kernel reaping the shell by a few ticks.
            try:p.wait(timeout=2)
            except subprocess.TimeoutExpired:
                p.kill();p.wait();self.fail('Script hung: '+output.decode(errors='replace'))
        finally:os.close(master)
        self.assertFalse(pending,output)
        return p.returncode,output.decode(errors='replace')

    def commands(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_native_prompts_and_login_with_script_on_stdin(self):
        code,out=self.run_setup(TEST_LOGIN_NEEDED='1',answers=[
            ('Install type:','1'),("LAN IPv4 address",''),('MOCK AUTH APPROVAL:','approved')])
        self.assertEqual(code,0,out);self.assertIn('installation finished',out)
        self.assertIn('MOCK PRIVATE INSTALLER --server-ip '+self.ip,out)
        self.assertTrue(any(c[0]=='sudo' and c[1]=='bash' and c[2].endswith('install-linux.sh') for c in self.commands()))
        summaries=list(self.home.glob('ricktv-setup.*/SETUP-SUMMARY.txt'))
        self.assertEqual(len(summaries),1)
        self.assertEqual(summaries[0].stat().st_mode & 0o777,0o600)

    def test_docker_selection(self):
        code,out=self.run_setup('--mode','docker','--server-ip',self.ip)
        self.assertEqual(code,0,out)
        self.assertTrue(any(c[0]=='sudo' and c[2].endswith('install-docker.sh') for c in self.commands() if len(c)>2))

    def test_preview_does_not_use_sudo(self):
        code,out=self.run_setup('--mode','native','--server-ip',self.ip,'--plan')
        self.assertEqual(code,0,out);self.assertIn('Preview only',out)
        self.assertFalse(any(c[0]=='sudo' for c in self.commands()))

    def test_private_repo_required(self):
        for env in [{'TEST_PRIVATE':'false'},{'TEST_NO_ACCESS':'1'}]:
            code,out=self.run_setup('--mode','native','--server-ip',self.ip,**env)
            self.assertNotEqual(code,0,out)
        self.assertFalse(any(c[0]=='git' for c in self.commands()))

    def test_clone_failure_does_not_install(self):
        code,out=self.run_setup('--mode','native','--server-ip',self.ip,TEST_CLONE_FAILURE='1')
        self.assertNotEqual(code,0);self.assertIn('Download failed',out)
        self.assertFalse(any(c[0]=='sudo' for c in self.commands()))

    def test_failed_install_retains_source_and_no_success_claim(self):
        code,out=self.run_setup('--mode','native','--server-ip',self.ip,TEST_INSTALL_FAILURE='1')
        self.assertNotEqual(code,0);self.assertNotIn('installation finished.',out)
        self.assertIn('resume instructions',out)
        self.assertEqual(len(list(self.home.glob('ricktv-setup.*/source/install-linux.sh'))),1)

    def test_invalid_ip_does_not_authenticate(self):
        for ip in ['127.0.0.1','bad-address','203.0.113.42','; echo injected']:
            code,out=self.run_setup('--mode','native','--server-ip',ip)
            self.assertNotEqual(code,0,out)
        self.assertFalse(any(c[0]=='gh' for c in self.commands()))

    def test_platform_and_root_guard(self):
        for env in [{'TEST_UID':'0'},{'TEST_OS':'Darwin'},{'TEST_ARCH':'armv7l'}]:
            code,out=self.run_setup('--mode','native','--server-ip',self.ip,**env)
            self.assertNotEqual(code,0,out)
        self.assertFalse(any(c[0]=='gh' for c in self.commands()))

    def test_old_compose_refused(self):
        code,out=self.run_setup('--mode','docker','--server-ip',self.ip,TEST_COMPOSE='2.29.7')
        self.assertNotEqual(code,0);self.assertIn('Compose 2.30+',out)

    def test_existing_destination_untouched(self):
        root=Path('/opt/ricktv');root.mkdir()
        try:
            marker=root/'untouched';marker.write_text('preserve')
            code,out=self.run_setup('--mode','native','--server-ip',self.ip)
            self.assertNotEqual(code,0);self.assertEqual(marker.read_text(),'preserve')
            self.assertFalse(any(c[0]=='gh' for c in self.commands()))
        finally:marker.unlink();root.rmdir()

    def test_auth_failure_stops(self):
        code,out=self.run_setup('--mode','native','--server-ip',self.ip,
            TEST_LOGIN_NEEDED='1',TEST_AUTH_FAILURE='1',answers=[('MOCK AUTH APPROVAL:','approved')])
        self.assertNotEqual(code,0);self.assertFalse(any(c[0]=='git' for c in self.commands()))

    def test_help_and_bad_arguments(self):
        code,out=self.run_setup('--help');self.assertEqual(code,0,out)
        for args in [('--mode',),('--mode','unknown'),('--invalid',)]:
            code,out=self.run_setup(*args);self.assertNotEqual(code,0,out)

    def test_credential_helper_is_ephemeral(self):
        code,out=self.run_setup('--mode','native','--server-ip',self.ip,'--plan')
        self.assertEqual(code,0,out)
        clone=next(c for c in self.commands() if 'clone' in c)
        self.assertIn('credential.helper=!gh auth git-credential',clone)
        self.assertIn('https://github.com/ricksauto08/RickTv.git',clone)
        self.assertNotIn('--global',clone)

if __name__=='__main__':unittest.main()
