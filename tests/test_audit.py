"""Whole-source audit regressions, using private files and mocked OS operations."""
import json
import os
from pathlib import Path
import runpy
import shlex
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import test_manager as manager


class AuditTest(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell
    configure = manager.ManagerTest.configure
    user_setup = manager.ManagerTest.user_setup
    add_user = manager.ManagerTest.add_user
    user_db = manager.ManagerTest.user_db

    def installer(self, extra='', candidate=None):
        directory = self.root/'installer'
        candidate = candidate or manager.ROOT/'singbox-v2.sh'
        return ('source '+shlex.quote(str(manager.ROOT/'install.sh'))+'\n'
                'MANAGER_DIR='+shlex.quote(str(directory))+'\nMANAGER_TARGET="$MANAGER_DIR/singbox-v2.sh"\n'
                'MANAGER_LOCK='+shlex.quote(str(self.root/'installer.lock'))+'\n'
                'installer_root(){ :; };flock(){ :; };installer_launch(){ bash "$MANAGER_TARGET" --self-check; };\n'
                'curl(){ cp '+shlex.quote(str(candidate))+' "${@: -1}"; };\n'+extra+'\ninstall_manager')

    def test_installer_atomic_publication_and_invalid_download_cleanup(self):
        self.shell(self.installer())
        directory=self.root/'installer';target=directory/'singbox-v2.sh';before=target.read_bytes()
        self.assertEqual(target.stat().st_mode&0o777,0o700)
        candidate=self.root/'bad-manager';candidate.write_bytes(before.replace(b"import argparse",b"import broken",1)+b'\nif [[\n')
        self.assertNotEqual(self.shell(self.installer(candidate=candidate),ok=False).returncode,0)
        self.assertEqual(target.read_bytes(),before);self.assertFalse(list(directory.glob('.install.*')))
        self.assertNotEqual(self.shell(self.installer('curl(){ printf partial > "${@: -1}";return 1; };'),ok=False).returncode,0)
        self.assertEqual(target.read_bytes(),before);self.assertFalse(list(directory.glob('.install.*')))
        self.assertNotEqual(self.shell(self.installer('flock(){ return 1; };'),ok=False).returncode,0)
        self.assertEqual(target.read_bytes(),before)

    def test_installer_preserves_foreign_files_and_refuses_symlink_paths(self):
        directory=self.root/'installer';directory.mkdir();target=directory/'singbox-v2.sh';target.write_text('foreign script')
        self.assertNotEqual(self.shell(self.installer(),ok=False).returncode,0);self.assertEqual(target.read_text(),'foreign script')
        target.unlink();external=self.root/'external';external.write_text('keep');target.symlink_to(external)
        self.assertNotEqual(self.shell(self.installer(),ok=False).returncode,0);self.assertEqual(external.read_text(),'keep')
        target.unlink();directory.rmdir();outside=self.root/'outside';outside.mkdir();directory.symlink_to(outside)
        self.assertNotEqual(self.shell(self.installer(),ok=False).returncode,0);self.assertEqual(list(outside.iterdir()),[])

    def test_bootstrap_refuses_directory_and_language_symlinks_before_chmod(self):
        outside=self.root/'outside';outside.mkdir(mode=0o755);outside.chmod(0o755);link=self.root/'linked';link.symlink_to(outside)
        result=self.shell('need_root(){ :; };flock(){ :; };BASE='+shlex.quote(str(link))+';REPORT="$BASE/reports";BACKUP="$BASE/backups";bootstrap',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Unsafe manager directory',result.stderr)
        self.assertEqual(outside.stat().st_mode&0o777,0o755);self.assertEqual(list(outside.iterdir()),[])
        foreign=self.root/'foreign';foreign.write_text('preserve');(self.base/'language.conf').symlink_to(foreign)
        result=self.shell('need_root(){ :; };flock(){ :; };bootstrap',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Language/lock file is unsafe',result.stderr)
        self.assertEqual(foreign.read_text(),'preserve')

    def test_installer_refuses_non_regular_lock_without_opening_it(self):
        os.mkfifo(self.root/'installer.lock')
        result=self.shell(self.installer(),ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Unsafe installer path',result.stderr)
        self.assertFalse((self.root/'installer').exists())

    def test_backup_snapshots_symlinked_external_tls_without_copying_unrelated_files(self):
        self.configure('2');cert=self.config/'external.crt';key=self.config/'external.key';cert.symlink_to(self.cert);key.symlink_to(self.key)
        cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds'][0]['tls'].update(certificate_path=str(cert),key_path=str(key));(self.config/'config.json').write_text(json.dumps(cfg))
        unrelated=self.config/'unrelated';unrelated.symlink_to(self.root/'missing-user-file')
        snapshot=Path(self.shell('backup').stdout.strip())
        self.assertEqual({p.name for p in (snapshot/'config').iterdir()},{'config.json','hy2-backup.crt','hy2-backup.key'})
        self.assertEqual((snapshot/'config/hy2-backup.crt').read_bytes(),self.cert.read_bytes())
        self.assertEqual((snapshot/'config/hy2-backup.key').read_bytes(),self.key.read_bytes())
        self.assertTrue(unrelated.is_symlink());self.shell('backup_engine preflight '+shlex.quote(str(snapshot)))

    def test_restore_publish_failure_rolls_back_partial_files_exactly(self):
        self.configure('2');snapshot=Path(self.shell('backup').stdout.strip());stage=self.base/'restore.fixture';stage.mkdir()
        (self.base/'state.json').write_text((self.base/'state.json').read_text()+'\n')
        before={p:p.read_bytes() for p in (self.config/'config.json',self.base/'state.json',self.bin)}
        self.shell('backup_engine restore_plan '+shlex.quote(str(snapshot))+' '+shlex.quote(str(stage)))
        argv=['backup.py',str(self.base),str(self.backups),str(self.config/'config.json'),str(self.bin),'list']
        with patch.object(sys,'argv',argv):namespace=runpy.run_path(str(manager.ROOT/'src/backup.py'))
        restore=namespace['restore_files'];original=restore.__globals__['replace_file']
        def fail_binary(path,*args):
            if path==self.bin:raise OSError('simulated binary publication failure')
            return original(path,*args)
        with patch.dict(restore.__globals__,replace_file=fail_binary):
            with self.assertRaises(OSError):restore(str(stage))
        restore(str(stage),True)
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
        self.assertFalse((self.config/'hy2-backup.key').exists())

    def test_restore_failure_resumes_original_services_and_keeps_unknown_files(self):
        self.configure('2');snapshot=Path(self.shell('backup').stdout.strip())
        cfg=json.loads((self.config/'config.json').read_text());cfg['log']['level']='debug';(self.config/'config.json').write_text(json.dumps(cfg))
        before={p:p.read_bytes() for p in (self.config/'config.json',self.base/'state.json',self.bin)}
        unknown=self.config/'keep.txt';unknown.write_text('keep current')
        code='''systemctl(){ echo "$*" >> "$BASE/events"; };setup_service
eval "$(declare -f backup_engine | sed '1s/backup_engine/audit_backup_engine/')"
backup_engine(){ if [[ $1 == restore_apply ]];then audit_backup_engine "$@";return 1;fi;audit_backup_engine "$@"; }
restore'''
        result=self.shell(code,input=str(snapshot)+'\ny\n',ok=False)
        self.assertNotEqual(result.returncode,0)
        for path,data in before.items():self.assertEqual(path.read_bytes(),data)
        self.assertEqual(unknown.read_text(),'keep current');self.assertIn('restart sing-box.service',(self.base/'events').read_text())
        self.assertFalse(list(self.base.glob('restore.*')))

    def test_restore_refreshes_exports_without_overwriting_unrelated_configuration(self):
        self.configure('2');unknown=self.config/'keep.txt';unknown.write_text('saved unrelated')
        saved=json.loads((self.base/'state.json').read_text());saved['node_name']='Saved';(self.base/'state.json').write_text(json.dumps(saved))
        snapshot=Path(self.shell('backup').stdout.strip());unknown.write_text('current unrelated')
        saved['node_name']='Current';(self.base/'state.json').write_text(json.dumps(saved));self.shell('exports >/dev/null')
        self.shell('systemctl(){ :; };service_healthy(){ :; };restore',input=str(snapshot)+'\ny\n')
        self.assertIn('Saved-HY2',(self.base/'nodes.txt').read_text());self.assertNotIn('Current-HY2',(self.base/'nodes.txt').read_text())
        self.assertEqual(unknown.read_text(),'current unrelated');self.assertFalse(list(self.base.glob('restore.*')))

    def test_node_edit_failure_restarts_admin_with_restored_config(self):
        self.user_setup();self.add_user();before=(self.config/'config.json').read_bytes()
        code=r'''systemctl(){
if [[ $1 == restart && $2 == sing-box.service ]];then
 python3 - "$CONF" "$BASE/restarts" <<'PY'
import json,sys
with open(sys.argv[2],'a') as f:f.write(json.load(open(sys.argv[1]))['inbounds'][0]['tls']['server_name']+'\n')
PY
 if grep -q node.example "$CONF";then return 1;fi
fi; };service_healthy(){ :; };configuration_apply sni node.example'''
        self.assertNotEqual(self.shell(code,ok=False).returncode,0)
        self.assertEqual((self.config/'config.json').read_bytes(),before)
        self.assertEqual((self.base/'restarts').read_text().splitlines(),['node.example','addons.mozilla.org'])

    def test_user_allocation_reserves_ports_of_inactive_managed_services(self):
        self.user_setup(mode='2');cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds'][0]['listen_port']=25001;(self.config/'config.json').write_text(json.dumps(cfg))
        for filename,number in [('argo-server.json',25002),('warp-gateway.json',25003)]:
            (self.base/filename).write_text(json.dumps({'inbounds':[{'listen_port':number}]}))
        for filename,number in [('subscriptions.json',25004),('warp-client.json',25005)]:
            (self.base/filename).write_text(json.dumps({'port':number}))
        (self.base/'haproxy').mkdir();(self.base/'haproxy/state.json').write_text(json.dumps({'owner':'SKYBYTE HAProxy TCP v1','schema':1,'rules':[{'port':25006}]}))
        script="import runpy,secrets,sys\nvalues=iter(range(5001,5010));secrets.randbelow=lambda _:next(values)\nsys.argv="+repr(['users.py',str(self.base),str(self.config/'config.json'),str(self.base/'state.json'),str(self.bin),'en_US','add','Alice','1','30'])+"\nrunpy.run_path("+repr(str(manager.ROOT/'src/users.py'))+")"
        subprocess.run([sys.executable,'-c',script],check=True,capture_output=True,text=True)
        record=self.user_db()['users'][0];self.assertEqual((record['port'],record['api_port']),(25007,25008))

    @unittest.skipUnless(socket.has_ipv6,'IPv6 required')
    def test_user_listener_family_follows_template_with_advertised_hostname(self):
        try:
            with socket.socket(socket.AF_INET6,socket.SOCK_DGRAM) as sock:sock.bind(('::1',0))
        except OSError:self.skipTest('IPv6 loopback unavailable')
        self.user_setup(mode='2');cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds'][0]['listen']='::1';(self.config/'config.json').write_text(json.dumps(cfg))
        state=json.loads((self.base/'state.json').read_text());state.update(ip='node.example',listen='::');(self.base/'state.json').write_text(json.dumps(state))
        uid=self.add_user();user=json.loads((self.base/'users'/uid/'server.json').read_text());self.assertEqual(user['inbounds'][0]['listen'],'::1')

    def test_admin_port_edit_refuses_inactive_user_controller(self):
        self.user_setup();self.add_user();record=self.user_db()['users'][0];before=(self.config/'config.json').read_bytes()
        result=self.shell('systemctl(){ return 1; };configuration_apply ports '+str(record['api_port'])+' 443',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertEqual((self.config/'config.json').read_bytes(),before)

    def test_configuration_generation_does_not_expose_credentials_in_process_arguments(self):
        arguments=[self.config/'config.json',self.base/'state.json','127.0.0.1',self.cert,self.key,
                   'addons.mozilla.org',self.uuid,self.private,self.public,'12345678',self.password,'127.0.0.1','3','1']
        code='python3(){ printf "%s\\n" "$@" > "$BASE/python-arguments";command python3 "$@"; };write_config '+' '.join(shlex.quote(str(x)) for x in arguments)
        self.shell(code);record=(self.base/'python-arguments').read_text()
        for secret in (self.uuid,self.password,self.private):
            if secret:self.assertNotIn(secret,record)
        cfg=json.loads((self.config/'config.json').read_text());self.assertEqual(cfg['inbounds'][0]['users'][0]['uuid'],self.uuid)
        self.assertEqual(cfg['inbounds'][0]['tls']['reality']['private_key'],self.private)
        self.assertEqual(cfg['inbounds'][1]['users'][0]['password'],self.password)

    def test_admin_port_edit_reserves_inactive_argo_warp_and_subscription_ports(self):
        self.configure('1');before=(self.config/'config.json').read_bytes()
        for filename in ('argo-server.json','warp-gateway.json','subscriptions.json','warp-client.json'):
            with self.subTest(filename=filename):
                payload={'inbounds':[{'type':'socks','listen_port':25011}]} if filename.endswith(('server.json','gateway.json')) else {'port':25011}
                path=self.base/filename;path.write_text(json.dumps(payload));stage=self.base/'edit.fixture';stage.mkdir()
                result=self.shell('configuration_engine '+shlex.quote(str(stage))+' ports 25011 443',ok=False)
                self.assertNotEqual(result.returncode,0);self.assertIn('Port reserved by a managed TCP service',result.stderr)
                self.assertEqual((self.config/'config.json').read_bytes(),before);path.unlink();stage.rmdir()

    def test_adding_protocol_reserves_inactive_account_port_for_the_new_protocol(self):
        self.user_setup(mode='2');self.add_user();record=self.user_db()['users'][0];stage=self.base/'edit.fixture';stage.mkdir()
        result=self.shell('configuration_engine '+shlex.quote(str(stage))+' add vless '+str(record['port'])+' node.example',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('Port overlaps an account',result.stderr)
        self.assertEqual(list(stage.iterdir()),[])

    def test_offline_selection_survives_next_main_menu_action_only_in_session(self):
        directory=self.root/'offline';directory.mkdir()
        code='''need_root(){ :; };flock(){ :; };startup_info(){ :; };retire_auto_update(){ :; };users_summary(){ :; };
install_protocol(){ printf 'OFFLINE=%s\n' "${SKYBYTE_ASSET_DIR:-missing}"; };unset SKYBYTE_ASSET_DIR;exec 9>"$BASE/test-lock";main'''
        result=self.shell(code,input='a\n6\n8\n'+str(directory)+'\n0\n1\n0\nq\n')
        self.assertIn('OFFLINE='+str(directory),result.stdout);self.assertFalse(list(self.base.glob('.session.*')))

    def test_acme_certificate_can_be_kept_on_standalone_argo_without_hy2_prompt(self):
        self.configure('1');cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds']=[];(self.config/'config.json').write_text(json.dumps(cfg))
        (self.base/'acme-state.json').write_text(json.dumps({'owner':'SKYBYTE ACME v1','schema':1,'method':'http','domain':'node.example'}))
        result=self.shell('configuration_apply(){ echo SHOULD_NOT_APPLY;return 1; };acme_use_hy2',input='y\n')
        self.assertIn('HY2 is not installed',result.stdout);self.assertNotIn('SHOULD_NOT_APPLY',result.stdout)


if __name__=='__main__':unittest.main()
