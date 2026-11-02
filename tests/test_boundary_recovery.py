"""Regression scenarios from the v2.10.2 audit; private files and loopback services only."""
import copy,hashlib,http.client,json,os,runpy,shlex,shutil,socket,subprocess,sys,tempfile,threading,time,tracemalloc,unittest
from pathlib import Path
from unittest.mock import patch
import test_manager as manager
import test_navigation as navigation
import test_reliability as reliability
online=reliability.online
from test_xhttp_backend import core
from test_reality import reality

class BoundaryRecoveryTests(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell
    configure=manager.ManagerTest.configure
    user_setup=manager.ManagerTest.user_setup
    add_user=manager.ManagerTest.add_user
    user_db=manager.ManagerTest.user_db
    save_user_db=manager.ManagerTest.save_user_db

    def hopping(self):
        p=self.base/'state.json';state=json.loads(p.read_text());state.update(hop=True,hop_start=20000,hop_end=30000);p.write_text(json.dumps(state))

    def inactive(self):return 'systemctl(){ return 1; };warp_resume(){ :; };'

    def test_non_port_edits_keep_hopping_and_refresh_client_exports(self):
        self.configure('3');self.hopping()
        for action in ['address node.example','sni node.example','hy2 10 20 false none',
                       'tls 127.0.0.1 '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key)),
                       'nat_exports 8.8.8.8 443 443']:
            with self.subTest(action=action):
                r=self.shell(self.inactive()+'hop_disable(){ echo BAD_DISABLE;return 1; };configuration_apply '+action)
                self.assertNotIn('BAD_DISABLE',r.stdout)
                self.assertTrue(json.loads((self.base/'state.json').read_text())['hop'])
                client=json.loads((self.base/'sing-box-client.json').read_text())
                self.assertTrue(any(o.get('server_ports') for o in client['outbounds'] if o['type']=='hysteria2'))

    def test_failed_metadata_edit_restores_hopping_exactly(self):
        self.configure('3');self.hopping();before=(self.base/'state.json').read_bytes()
        r=self.shell(self.inactive()+'configuration_resume(){ return 1; };configuration_apply address node.example',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertEqual((self.base/'state.json').read_bytes(),before)

    def test_manual_hopping_disable_updates_exports(self):
        self.configure('2');self.hopping();self.shell('exports >/dev/null')
        self.shell('systemctl(){ :; };hop 2',input='y\n')
        self.assertFalse(json.loads((self.base/'state.json').read_text())['hop'])
        client=json.loads((self.base/'sing-box-client.json').read_text())
        self.assertFalse(any(o.get('server_ports') for o in client['outbounds'] if o['type']=='hysteria2'))

    def test_argo_only_has_no_hy2_and_no_tracebacks(self):
        self.configure('1');p=self.config/'config.json';cfg=json.loads(p.read_text());cfg['inbounds']=[];p.write_text(json.dumps(cfg))
        state=self.base/'state.json';data=json.loads(state.read_text());data.update(mode='0',deployment='argo-only');state.write_text(json.dumps(data))
        self.assertEqual(self.shell('protocol_mode').stdout.strip(),'0')
        r=self.shell('need_root(){ :; };ufw(){ echo "Status: active"; };firewall_audit;deployment_apply_selected 0 0 0')
        self.assertNotIn('Traceback',r.stderr)
        r=self.shell('hop --menu',ok=False);self.assertIn('HY2 not installed',r.stderr);self.assertNotIn('Traceback',r.stderr)

    def test_firewall_inventory_includes_accounts_subscription_and_stopped_haproxy(self):
        self.user_setup();self.add_user();user_port=self.user_db()['users'][0]['port']
        relay=self.base/'haproxy';relay.mkdir();(relay/'state.json').write_text(json.dumps({'owner':'SKYBYTE HAProxy TCP v1','schema':1,'rules':[{'port':18443}]}))
        (self.base/'subscriptions.json').write_text(json.dumps({'owner':online.OWNER,'schema':1,'host':'node.example','port':18444,'cert':str(self.cert),'key':str(self.key),'tokens':{}}))
        r=self.shell('haproxy_guard(){ :; };ufw(){ echo "ALLOW=$*"; };firewall_allow_protocols')
        for rule in ['18443/tcp','18444/tcp',str(user_port)+'/tcp',str(user_port)+'/udp']:
            self.assertIn('ALLOW=allow '+rule,r.stdout)

    def test_automatic_firewall_accepts_known_services_and_link_local_listener(self):
        self.user_setup();self.add_user();port=self.user_db()['users'][0]['port']
        defaults=self.root/'ufw-defaults';defaults.write_text('IPV6=yes\n')
        code='UFW_DEFAULTS='+shlex.quote(str(defaults))+'''\ndetect_ssh_ports(){ SSH_PORTS=22; };deployment_firewall_gate(){ :; }
ufw(){ case "$*" in status) if [[ -f "$BASE/enabled" ]];then echo 'Status: active';else echo 'Status: inactive';fi;;'--force enable') touch "$BASE/enabled";;esac; }
ss(){ printf '%s\\n' 'tcp LISTEN 0 0 0.0.0.0:'''+str(port)+''' 0.0.0.0:*' 'udp UNCONN 0 0 [fe80::1%eth0]:546 [::]:*'; }
deployment_firewall'''
        self.shell(code);self.assertTrue((self.base/'enabled').exists())

    def test_trusted_certificate_missing_baseline_reloads_instead_of_silently_accepting(self):
        self.configure('2','2')
        r=self.shell('certificate_info(){ :; };certificate_reload(){ echo RELOADED; };certificate_check')
        self.assertIn('RELOADED',r.stdout)

    def test_bad_cloudflare_token_does_not_leave_a_directory(self):
        r=self.shell('need_root(){ :; };apt_install(){ echo BAD_INSTALL; };acme_issue',input='node.example\nowner@example.com\n2\ny\nbad\n',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertFalse((self.base/'acme').exists());self.assertNotIn('BAD_INSTALL',r.stdout)

    def test_owned_selfsigned_hy2_can_be_removed_and_added_again(self):
        self.configure('1');port=manager.port(socket.SOCK_DGRAM)
        add='configuration_apply add hysteria2 '+str(port)+' 127.0.0.1 selfsigned'
        self.shell(self.inactive()+add);first=(self.config/'hy2-added.crt').read_bytes()
        self.shell(self.inactive()+'configuration_apply remove hysteria2');self.shell(self.inactive()+add)
        self.assertNotEqual((self.config/'hy2-added.crt').read_bytes(),first)
        self.assertEqual(json.loads((self.config/'config.json').read_text())['inbounds'][-1]['type'],'hysteria2')

    def test_reset_unreachable_api_retains_usage_and_has_actionable_error(self):
        self.user_setup();uid=self.add_user();data=self.user_db();data['users'][0].update(running=True,generation='test',api_port=manager.port(),upload=1234);self.save_user_db(data)
        r=self.shell('users_engine reset '+uid,ok=False)
        self.assertNotEqual(r.returncode,0);self.assertIn('usage retained',r.stderr);self.assertNotIn('Traceback',r.stderr)
        self.assertEqual(self.user_db()['users'][0]['upload'],1234)

    def test_deleted_user_without_directory_restores_without_resurrection(self):
        self.user_setup();uid=self.add_user();self.shell('users_engine delete '+uid);shutil.rmtree(self.base/'users'/uid)
        destination=self.base/'snapshot';destination.mkdir();self.shell('users_engine backup '+shlex.quote(str(destination)))
        self.shell('users_engine restore '+shlex.quote(str(destination)))
        self.assertTrue(self.user_db()['users'][0]['deleted']);self.assertFalse((self.base/'users'/uid).exists())

    def test_restored_user_config_matches_retained_ports_secret_and_policy(self):
        self.user_setup();uid=self.add_user();destination=self.base/'snapshot';destination.mkdir();self.shell('users_engine backup '+shlex.quote(str(destination)))
        data=self.user_db();record=data['users'][0];record.update(port=manager.port(),api_port=manager.port(),api_secret='rotated-private-controller-secret',upload=12345,quota_bytes=99999999);self.save_user_db(data)
        self.shell('users_engine restore '+shlex.quote(str(destination)))
        cfg=json.loads((self.base/'users'/uid/'server.json').read_text());current=self.user_db()['users'][0]
        self.assertTrue(all(i['listen_port']==current['port'] for i in cfg['inbounds']))
        self.assertEqual(cfg['experimental']['clash_api'],{'external_controller':'127.0.0.1:'+str(current['api_port']),'secret':current['api_secret']})
        self.assertEqual(current['upload'],12345);self.assertEqual(current['quota_bytes'],99999999)

    @unittest.skipUnless(manager.SB,'real core required')
    def test_bad_user_file_isolated_without_stopping_healthy_user(self):
        self.user_setup(3,real=True);uid=self.add_user('Fault');healthy=self.add_user('Healthy')
        proc=subprocess.Popen([manager.BASH,'-c',self.script('users_engine watch')],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
        try:
            until=time.monotonic()+12
            while time.monotonic()<until:
                if all(u.get('running') for u in self.user_db()['users']):break
                self.assertIsNone(proc.poll());time.sleep(.1)
            else:self.fail('Users never became ready')
            target=self.root/'outside';target.write_text('preserve');log=self.base/'users'/uid/'core.log';log.unlink();log.symlink_to(target)
            until=time.monotonic()+8
            while time.monotonic()<until:
                data={u['id']:u for u in self.user_db()['users']}
                if data[uid].get('failure_reason')=='files' and not data[uid].get('running'):break
                time.sleep(.1)
            else:self.fail('Fault was not isolated')
            self.assertIsNone(proc.poll());self.assertTrue(data[healthy]['running']);self.assertTrue(data[uid]['metering_blocked']);self.assertEqual(target.read_text(),'preserve')
        finally:
            if proc.poll() is None:proc.terminate()
            proc.communicate(timeout=10)

    def test_invalid_numeric_domain_and_ip_sni_rejected_but_ip_targets_work(self):
        for name in ['999.999.999.999','1.1.1.1','host.123','singlelabel']:
            with self.subTest(name=name),self.assertRaises(ValueError):core.domain(name)
        with self.assertRaises(ValueError):core.address('999.999.999.999')
        with self.assertRaises(ValueError):reality.hostname('999.999.999.999')
        self.assertEqual(core.address('1.1.1.1'),'1.1.1.1');self.assertEqual(reality.target_parts('1.1.1.1:443')[0],'1.1.1.1')

    def test_cancelled_actions_are_noops_not_red_failures(self):
        self.configure('2')
        for action,prefix in [('haproxy_menu 5','haproxy_guard(){ :; };'),('warp_rules_menu 2','warp_guard(){ :; };'),('hop 2',''),('acme_menu 6','acme_guard(){ :; };')]:
            with self.subTest(action=action):
                r=self.shell(prefix+'flock(){ :; };run_menu_action '+action+';echo STATUS=$MENU_ACTION_STATUS',input='n\n')
                self.assertIn('STATUS=0',r.stdout);self.assertNotIn('Operation failed',r.stderr)

    def test_failed_backup_removed_and_interrupted_marker_is_refused(self):
        self.configure('1');(self.base/'users.json').write_text('{}')
        r=self.shell('users_guard(){ :; };users_engine(){ return 1; };backup',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertEqual(list(self.backups.iterdir()),[])
        (self.base/'users.json').unlink();snapshot=Path(self.shell('backup').stdout.strip());(snapshot/'.incomplete').write_text('interrupted')
        self.assertNotEqual(self.shell('backup_engine preflight '+shlex.quote(str(snapshot)),ok=False).returncode,0)

    def test_cancel_xhttp_only_uninstall_stays_in_main(self):
        root=self.base/'xhttp';root.mkdir();(root/'.owner').write_text('SKYBYTE-SB-XHTTP/1\n');(root/'state.json').write_text('{"schema":1,"nodes":{}}')
        r=self.shell(navigation.NavigationTests.mocks(self)+'xhttp_command(){ :; };main',input='g\n3\nn\n0\nq\n')
        self.assertEqual(r.stdout.count('SKYBYTE Manager v'),2);self.assertTrue((root/'state.json').exists())

    def test_multi_ssh_default_uses_first_and_all_detected_ports_are_allowed(self):
        r=self.shell("need_root(){ :; };detect_ssh_ports(){ SSH_PORTS=$'22\\n2222'; };ufw(){ echo RULE=\"$*\"; };firewall_allow_protocols(){ :; };firewall 2",input='\ny\n')
        self.assertIn('RULE=allow 22/tcp',r.stdout);self.assertIn('RULE=allow 2222/tcp',r.stdout);self.assertIn('RULE=--force enable',r.stdout)

    def test_guided_existing_node_fails_before_questions(self):
        r=self.shell('choose_node_name(){ echo SHOULD_NOT_ASK >&2; };guided_install 2',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertNotIn('SHOULD_NOT_ASK',r.stderr)

    def test_text_helpers_do_not_invoke_translation_subshells_and_language_without_newline_works(self):
        r=self.shell("L(){ echo BAD_SUBSHELL >&2;return 1; };say zh en;prompt_options zh en")
        self.assertEqual(r.stdout,'en\nen\n');self.assertNotIn('BAD_SUBSHELL',r.stderr)
        (self.base/'language.conf').write_text('zh_CN');self.assertEqual(self.shell('load_language;say zh en').stdout,'zh\n')

    def test_large_backup_hash_uses_bounded_memory(self):
        target=self.backups/'large';target.mkdir()
        with open(target/'sing-box.bin','wb') as f:f.truncate(16*1024**2)
        argv=['backup.py',str(self.base),str(self.backups),str(self.config/'config.json'),str(self.bin),'manifest',str(target)]
        tracemalloc.start()
        try:
            with patch.object(sys,'argv',argv):runpy.run_path(str(manager.ROOT/'src/backup.py'))
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,8*1024**2)
        expected=hashlib.sha256()
        for _ in range(16):expected.update(bytes(1024**2))
        self.assertEqual(json.loads((target/'backup-manifest.json').read_text())['files']['sing-box.bin'],expected.hexdigest())

    def test_invalid_subscription_tokens_do_not_fill_rate_table(self):
        server=online.Server(('127.0.0.1',0),online.handler(self.base,'unused',lambda _:None));thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.object(online,'authorize',return_value=None):
                client=http.client.HTTPConnection(*server.server_address,timeout=3);client.request('GET','/s/'+('a'*43)+'/singbox');response=client.getresponse();response.read();self.assertEqual(response.status,404);client.close()
            self.assertEqual(server.rates,{})
            for i in range(60):self.assertTrue(server.allow('2001:db8:'+str(i)+'::1','same-account'))
            self.assertFalse(server.allow('2001:db8:999::1','same-account'));self.assertEqual(len(server.rates),1)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_interactive_installer_cleans_manifest_before_exec(self):
        payload=self.root/'payload';payload.write_text('#!/usr/bin/env bash\n# SKYBYTE Manager V2.1 community manager; fixture\nexit 0\n')
        directory=self.root/'installer-exec'
        code='source '+shlex.quote(str(manager.ROOT/'install.sh'))+'\nMANAGER_DIR='+shlex.quote(str(directory))+'\nMANAGER_TARGET=$MANAGER_DIR/singbox-v2.sh\nMANAGER_LOCK='+shlex.quote(str(self.root/'install.lock'))+'\n'
        code+='installer_root(){ :; };installer_guard(){ :; };installer_dependencies(){ :; };installer_verify(){ :; };flock(){ :; };curl(){ cp '+shlex.quote(str(payload))+' "${@: -1}"; };install_manager'
        self.shell(code);self.assertEqual(list(directory.glob('.install.*')),[])

    def test_missing_curl_is_installed_before_xhttp_address_lookup(self):
        events=self.root/'events'
        code='source modules/xhttp_automatic.sh;EVENTS='+shlex.quote(str(events))+""";XHTTP_KIND=xhttp-reality;XHTTP_NAME=test;XHTTP_SNI=addons.mozilla.org
command(){ if [[ $1 == -v && $2 == curl ]];then return 1;else builtin command "$@";fi; }
apt_install(){ echo DEPS >> "$EVENTS"; }
curl(){ echo CURL >> "$EVENTS";echo 8.8.8.8; }
helper(){ return 1; };xhttp_install_automatic"""
        self.shell(code,ok=False);self.assertEqual(events.read_text().splitlines(),['DEPS','CURL'])

    @unittest.skipUnless(manager.SB,'real core required')
    def test_relative_manual_certificate_becomes_absolute_and_checks_from_root(self):
        with tempfile.TemporaryDirectory(prefix='cert-boundary-',dir=manager.ROOT/'work') as directory:
            target=Path(directory);shutil.copyfile(self.cert,target/'cert.pem');shutil.copyfile(self.key,target/'key.pem')
            cert=os.path.relpath(target/'cert.pem');key=os.path.relpath(target/'key.pem')
            self.shell(reliability.ReliabilityTest.install_mocks(self)+'install_protocol 2',input='y\n\n2\nnode.example\n'+cert+'\n'+key+'\n')
            cfg=self.config/'config.json';tls=json.loads(cfg.read_text())['inbounds'][0]['tls']
            self.assertTrue(Path(tls['certificate_path']).is_absolute());self.assertTrue(Path(tls['key_path']).is_absolute())
            check=subprocess.run([manager.SB,'check','-c',str(cfg)],cwd='/',capture_output=True)
            self.assertEqual(check.returncode,0,check.stderr.decode())
            self.assertTrue((self.base/'certificate-status.json').is_file())

    def test_argo_status_uses_one_snapshot_not_per_field_processes(self):
        (self.base/'argo-state.json').write_text(json.dumps({'mode':'quick','domain':'demo.trycloudflare.com','port':8080,'connected':True,'edge_ip_version':'auto','transport':'http2'}))
        r=self.shell('argo_state(){ echo BAD_FIELD_READ >&2;return 1; };systemctl(){ return 1; };argo_status')
        self.assertIn('demo.trycloudflare.com',r.stdout);self.assertIn('http2',r.stdout);self.assertNotIn('BAD_FIELD_READ',r.stderr)

    def test_ecs_respects_english_language(self):
        media=reliability.module('media');arguments=media.ecs_arguments('route','en_US')
        self.assertEqual(arguments[arguments.index('-l')+1],'en')

    def test_qr_labels_are_parsed_in_one_batch(self):
        trace=self.root/'python-calls'
        (self.base/'state.json').write_text('{}');(self.config/'config.json').write_text('{}')
        (self.base/'shadowrocket-native-nodes.txt').write_text('hysteria2://demo@127.0.0.1:443#First\nhysteria2://demo@127.0.0.1:444#Second\n')
        r=self.shell('TRACE='+shlex.quote(str(trace))+';exports(){ :; };python3(){ echo call >> "$TRACE";command python3 "$@"; };qrencode(){ cat >/dev/null;echo QR; };shadowrocket_qr')
        self.assertEqual(len(trace.read_text().splitlines()),1);self.assertIn('First',r.stdout);self.assertIn('Second',r.stdout);self.assertEqual(r.stdout.count('QR\n'),2)

    def test_restore_refuses_retained_user_port_conflicting_with_restored_admin(self):
        self.user_setup();uid=self.add_user();destination=self.base/'snapshot';destination.mkdir();self.shell('users_engine backup '+shlex.quote(str(destination)))
        data=self.user_db();port=data['users'][0]['port']
        p=self.config/'config.json';cfg=json.loads(p.read_text());cfg['inbounds'][0]['listen_port']=port;p.write_text(json.dumps(cfg))
        user_config=self.base/'users'/uid/'server.json';before=user_config.read_bytes()
        r=self.shell('users_engine restore '+shlex.quote(str(destination)),ok=False)
        self.assertNotEqual(r.returncode,0);self.assertIn('conflicts',r.stderr);self.assertEqual(user_config.read_bytes(),before)

    @unittest.skipUnless(manager.SB,'real core required')
    def test_certificate_absolute_paths_keep_live_renewal_symlinks(self):
        with tempfile.TemporaryDirectory(prefix='live-cert-',dir=manager.ROOT/'work') as directory:
            target=Path(directory);(target/'live.pem').symlink_to(self.cert);(target/'live.key').symlink_to(self.key)
            cert=os.path.relpath(target/'live.pem');key=os.path.relpath(target/'live.key')
            self.shell(reliability.ReliabilityTest.install_mocks(self)+'install_protocol 2',input='y\n\n2\nnode.example\n'+cert+'\n'+key+'\n')
            tls=json.loads((self.config/'config.json').read_text())['inbounds'][0]['tls']
            self.assertEqual(tls['certificate_path'],os.path.abspath(cert));self.assertEqual(tls['key_path'],os.path.abspath(key))
            self.assertNotEqual(tls['certificate_path'],str(self.cert))

if __name__=='__main__':unittest.main()
