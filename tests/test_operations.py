"""Operations tests keep update and service mutations inside temporary fixtures."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest

import test_manager as manager
CANDIDATE_VERSION='.'.join(manager.VERSION.split('.')[:2]+[str(int(manager.VERSION.split('.')[2])+1)])


class OperationsTest(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell
    configure = manager.ManagerTest.configure
    user_setup = manager.ManagerTest.user_setup
    add_user = manager.ManagerTest.add_user
    user_db = manager.ManagerTest.user_db
    save_user_db = manager.ManagerTest.save_user_db

    def candidate(self, version=CANDIDATE_VERSION):
        path=self.root/'candidate'
        path.write_text((manager.ROOT/'singbox-v2.sh').read_text().replace('MANAGER_VERSION='+manager.VERSION,'MANAGER_VERSION='+version))
        return path

    def update_mocks(self, manifest, candidate):
        return '''curl(){ local url= out=; while (($#)); do if [[ $1 == -o ]]; then out=$2; shift 2; else url=$1; shift; fi; done
if [[ $url == */latest ]]; then cp '''+shlex.quote(str(manifest))+''' "$out"; else cp '''+shlex.quote(str(candidate))+''' "$out"; fi; }
'''

    def test_bundle_is_current_and_self_check_needs_no_root_or_bootstrap(self):
        subprocess.run(['python3',str(manager.ROOT/'scripts/build.py'),'--check'],check=True)
        r=subprocess.run([manager.BASH,str(manager.ROOT/'singbox-v2.sh'),'--self-check'],capture_output=True,text=True,check=True)
        self.assertEqual(r.stdout.strip(),manager.VERSION)
        candidate=self.candidate();candidate.write_text(candidate.read_text().replace("import concurrent.futures,",'import !!! concurrent.futures,'))
        r=subprocess.run([manager.BASH,str(candidate),'--self-check'],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0)

    def test_manager_update_verifies_digest_and_preserves_node_data(self):
        self.user_setup();self.add_user()
        old=(manager.ROOT/'singbox-v2.sh').read_bytes()
        lib=self.root/'manager-lib';lib.write_bytes(old)
        command=self.root/'manager-command';command.write_bytes(old)
        cfg=(self.config/'config.json').read_bytes();ledger=(self.base/'users.json').read_bytes()
        candidate=self.candidate();manifest=self.root/'release.json'
        data={'tag_name':'v'+CANDIDATE_VERSION,'draft':False,'prerelease':False,'assets':[{'name':'singbox-v2.sh','digest':'sha256:'+hashlib.sha256(candidate.read_bytes()).hexdigest()}]}
        manifest.write_text(json.dumps(data))
        mocks=self.update_mocks(manifest,candidate)+'systemctl(){ return 1; }; '
        self.shell(mocks+'manager_update',input='Y\n')
        self.assertEqual(lib.read_bytes(),candidate.read_bytes());self.assertEqual(command.read_bytes(),candidate.read_bytes())
        self.assertEqual(cfg,(self.config/'config.json').read_bytes());self.assertEqual(ledger,(self.base/'users.json').read_bytes())
        self.assertTrue(list((self.base/'manager-backups').glob('*/manager-lib')))
        data['assets'][0]['digest']='sha256:'+'0'*64;manifest.write_text(json.dumps(data))
        lib.write_bytes(old);command.write_bytes(old)
        self.assertNotEqual(self.shell(mocks+'manager_update',input='y\n',ok=False).returncode,0)
        self.assertEqual(lib.read_bytes(),old);self.assertEqual(command.read_bytes(),old)

    def test_manager_update_refuses_foreign_scripts_symlinks_and_missing_digest(self):
        candidate=self.candidate();lib=self.root/'manager-lib';lib.write_text('other tool')
        cmd='manager_update_apply '+shlex.quote(str(candidate))+' '+CANDIDATE_VERSION+' '+shlex.quote(str(self.root/'snapshot'))
        self.assertNotEqual(self.shell(cmd,ok=False).returncode,0);self.assertEqual(lib.read_text(),'other tool')
        lib.unlink();lib.symlink_to(candidate)
        self.assertNotEqual(self.shell(cmd,ok=False).returncode,0)
        manifest=self.root/'release.json';manifest.write_text(json.dumps({'tag_name':'v'+CANDIDATE_VERSION,'assets':[{'name':'singbox-v2.sh'}]}))
        self.assertNotEqual(self.shell(self.update_mocks(manifest,candidate)+'manager_latest '+shlex.quote(str(self.root/'manifest-copy')),ok=False).returncode,0)

    def test_manager_update_rolls_back_active_supervisor_on_restart_failure(self):
        self.user_setup();self.add_user();self.shell('systemctl(){ :; }; users_setup_service')
        command=self.root/'manager-command';old=command.read_bytes()
        lib=self.root/'manager-lib';lib.write_bytes(old)
        candidate=self.candidate();snap=self.root/'snapshot'
        code='''systemctl(){
 if [[ $1 == is-active ]]; then return 0; fi
 if [[ $1 == start && $2 == skybyte-users.service ]] && grep -q 'MANAGER_VERSION=FIXTURE_VERSION' "$MANAGER_BIN"; then return 1; fi
 echo "$*" >> '''+shlex.quote(str(self.root/'events'))+'''; }
manager_update_apply '''+shlex.quote(str(candidate))+' '+CANDIDATE_VERSION+' '+shlex.quote(str(snap))
        code=code.replace('FIXTURE_VERSION',CANDIDATE_VERSION)
        self.assertNotEqual(self.shell(code,ok=False).returncode,0)
        self.assertEqual(command.read_bytes(),old);self.assertEqual(lib.read_bytes(),old)
        self.assertIn('start skybyte-users.service',(self.root/'events').read_text())

    def test_quota_and_validity_updates_preserve_other_fields_and_show_expiry(self):
        self.user_setup();uid=self.add_user();d=self.user_db();d['users'][0]['upload']=1234;self.save_user_db(d)
        before=self.user_db()['users'][0]
        r=self.shell('users_engine quota '+uid+' 7')
        after=self.user_db()['users'][0]
        self.assertEqual(after['expires_at'],before['expires_at']);self.assertEqual(after['upload'],1234)
        self.assertEqual(after['quota_bytes'],7*1024**3);self.assertIn('Resulting expiry:',r.stdout)
        self.shell('users_engine validity '+uid+' 90');after=self.user_db()['users'][0]
        self.assertEqual(after['quota_bytes'],7*1024**3);self.assertEqual(after['upload'],1234)
        self.assertGreater(after['expires_at'],before['expires_at'])
        self.assertNotEqual(self.shell('users_engine validity '+uid+' 0',ok=False).returncode,0)
        self.assertEqual(after,self.user_db()['users'][0])

    def test_diagnostics_show_safe_reason_and_recovery_validates_config(self):
        self.user_setup();uid=self.add_user();d=self.user_db();u=d['users'][0]
        u.update(metering_blocked=True,failure_reason='api_auth',failure_at=1);self.save_user_db(d)
        r=self.shell('users_engine diagnose')
        self.assertIn('Controller authentication failed',r.stdout);self.assertNotIn(u['api_secret'],r.stdout)
        self.assertIn('core.log',r.stdout)
        self.shell('users_engine enable '+uid);self.assertNotIn('failure_reason',self.user_db()['users'][0])
        d=self.user_db();d['users'][0].update(metering_blocked=True,api_secret='bad');self.save_user_db(d)
        self.assertNotEqual(self.shell('users_engine enable '+uid,ok=False).returncode,0)
        self.assertTrue(self.user_db()['users'][0]['metering_blocked'])

    def test_user_management_is_available_directly_from_main_menu(self):
        self.user_setup(3);self.add_user()
        for language,label in [('en_US','Users and quotas'),('zh_CN','用户与配额管理')]:
            code='need_root(){ :; }; flock(){ :; }; users_manager(){ echo USER_MENU; }; LANGUAGE_CHOICE='+language+'; main'
            r=self.shell(code,input='7\n0\n')
            self.assertIn(label,r.stdout);self.assertIn('USER_MENU',r.stdout);self.assertIn('1/3',r.stdout)
        for group,choice,action in [('5','4','manager_update'),('5','5','certificate'),('4','7','resources'),('4','8','media'),('4','9','warp')]:
            r=self.shell('sub_menu '+group+'; echo "$MAIN_ACTION"',input=choice+'\n')
            self.assertTrue(r.stdout.rstrip().endswith(action))

    def test_resource_snapshot_counts_only_managed_cores_without_printing_commands(self):
        mocks=self.root/'tools';mocks.mkdir();ps=mocks/'ps'
        ps.write_text('#!/bin/sh\ncat <<EOF\n1 2048 '+str(self.bin)+' run -c '+str(self.config/'config.json')+'\n2 4096 '+str(self.bin)+' run -c '+str(self.base/'users'/'abcd'/'server.json')+'\n3 90000 other-secret-process\nEOF\n');ps.chmod(0o700)
        r=self.shell('PATH='+shlex.quote(str(mocks))+':"$PATH"; resource_info')
        self.assertIn('2 / 6.0 MiB',r.stdout);self.assertIn('1 / 4.0 MiB',r.stdout)
        self.assertNotIn('other-secret-process',r.stdout)

    def test_certificate_expiry_warning_and_invalid_certificate(self):
        self.configure('2')
        r=self.shell('certificate_info');self.assertIn('within 30 days',r.stdout)
        self.cert.write_text('broken')
        r=self.shell('certificate_info');self.assertIn('unreadable',r.stdout)
        self.assertNotEqual(self.shell('certificate_check',ok=False).returncode,0)
        self.assertFalse((self.base/'certificate-status.json').exists())

    def test_certificate_check_only_reloads_changed_valid_domain_certificates(self):
        self.configure('2','2');self.shell('certificate_check')
        status=self.base/'certificate-status.json'
        self.assertEqual(status.stat().st_mode & 0o777,0o600)
        r=self.shell('certificate_reload(){ echo RELOADED; }; certificate_check');self.assertNotIn('RELOADED',r.stdout)
        status.write_text(json.dumps({'fingerprint':'old'}))
        r=self.shell('certificate_reload(){ echo RELOADED; }; certificate_check');self.assertIn('RELOADED',r.stdout)
        meta=json.loads((self.base/'state.json').read_text());meta['cert_mode']='1';(self.base/'state.json').write_text(json.dumps(meta))
        r=self.shell('certificate_reload(){ echo RELOADED; }; certificate_check');self.assertNotIn('RELOADED',r.stdout);self.assertIn('reload manually',r.stdout)
        status.unlink();status.symlink_to(self.cert)
        self.assertNotEqual(self.shell('certificate_check',ok=False).returncode,0)

    def renew(self):
        subprocess.run([manager.OPENSSL,'req','-x509','-newkey','rsa:2048','-nodes','-days','40','-subj','/CN=127.0.0.1','-addext','subjectAltName=IP:127.0.0.1','-keyout',str(self.key),'-out',str(self.cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def test_certificate_reload_updates_copies_and_exports_without_credentials_in_output(self):
        self.user_setup(mode='2');uid=self.add_user();self.renew()
        r=self.shell('systemctl(){ return 1; }; certificate_reload')
        self.assertEqual((self.base/'users'/uid/'certificate.crt').read_bytes(),self.cert.read_bytes())
        self.assertEqual((self.base/'users'/uid/'private.key').read_bytes(),self.key.read_bytes())
        self.assertTrue((self.base/'users'/uid/'shadowrocket-native-nodes.txt').exists())
        self.assertNotIn('hysteria2://',r.stdout);self.assertNotIn('PRIVATE KEY',r.stdout)
        self.assertEqual((self.base/'users'/uid/'private.key').stat().st_mode & 0o777,0o600)

    def test_certificate_reload_refuses_mismatched_key_without_changing_users(self):
        self.user_setup(mode='2');uid=self.add_user();old=(self.base/'users'/uid/'certificate.crt').read_bytes()
        self.renew();self.key.write_text('broken')
        r=self.shell('systemctl(){ return 1; }; certificate_reload',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertEqual((self.base/'users'/uid/'certificate.crt').read_bytes(),old)

    def test_daily_certificate_monitor_is_opt_in_and_owned(self):
        self.configure('2');self.shell('systemctl(){ :; }; certificate_menu',input='3\n')
        unit=self.root/'systemd'/'skybyte-certificate.service';timer=self.root/'systemd'/'skybyte-certificate.timer'
        self.assertIn('--certificate-check',unit.read_text());self.assertIn('OnCalendar=daily',timer.read_text())
        unit.write_text('Description=another service\n')
        self.assertNotEqual(self.shell('systemctl(){ :; }; certificate_menu',input='4\n',ok=False).returncode,0)
        self.assertTrue(timer.exists())
