"""Deployment transactions, private delivery and certificate/backup lifecycle regression tests."""
import base64,hashlib,http.client,importlib.util,json,os,pathlib,shlex,socket,ssl,subprocess,tarfile,tempfile,threading,time,unittest
from unittest.mock import patch
import test_manager as manager

def module(name):
 spec=importlib.util.spec_from_file_location('skybyte_'+name,manager.ROOT/'src'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
online=module('online')

class ReliabilityTest(unittest.TestCase):
 setUp=manager.ManagerTest.setUp
 script=manager.ManagerTest.script
 shell=manager.ManagerTest.shell
 configure=manager.ManagerTest.configure
 user_setup=manager.ManagerTest.user_setup
 add_user=manager.ManagerTest.add_user
 user_db=manager.ManagerTest.user_db
 save_user_db=manager.ManagerTest.save_user_db
 prepare_uninstall=manager.ManagerTest.prepare_uninstall
 def inactive(self):return 'systemctl(){ return 1; }; '
 def install_mocks(self,extra=''):
  self.bin.unlink(missing_ok=True)
  return '''need_root(){ :; };systemctl(){ case $1 in list-unit-files) return 1;;*) return 0;;esac; };ss(){ :; };apt-get(){ :; };getent(){ :; };sleep(){ :; }
cat(){ if [[ ${1:-} == /proc/sys/kernel/random/uuid ]];then printf '%s' '''+shlex.quote(self.uuid)+''';else command cat "$@";fi; }
curl(){ printf 8.8.8.8; }
download_binary(){ cp '''+shlex.quote(manager.SB)+''' "$2";chmod 755 "$2"; }
'''+extra
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_install_precommit_failure_leaves_no_formal_files_and_retry_works(self):
  code=self.install_mocks('curl(){ return 1; };install_protocol 2')
  r=self.shell(code,input='y\n\n1\n',ok=False);self.assertNotEqual(r.returncode,0)
  self.assertFalse(self.bin.exists());self.assertFalse((self.config/'config.json').exists());self.assertFalse(list(self.base.glob('install.*')))
  self.shell(self.install_mocks()+'install_protocol 2',input='y\n\n1\n')
  cfg=json.loads((self.config/'config.json').read_text());self.assertEqual(cfg['inbounds'][0]['tls']['certificate_path'],str(self.config/'hy2-selfsigned.crt'))
  self.assertFalse(list(self.base.glob('install.*')));self.assertTrue((self.base/'shadowrocket-native-nodes.txt').exists())
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_failed_service_start_cleans_only_created_files_and_keeps_unknown_notes(self):
  note=self.config/'keep.txt';note.write_text('preserve')
  code=self.install_mocks('systemctl(){ [[ $1 != enable ]]; };install_protocol 2')
  self.assertNotEqual(self.shell(code,input='y\n\n1\n',ok=False).returncode,0)
  self.assertFalse(self.bin.exists());self.assertFalse((self.config/'config.json').exists());self.assertFalse((self.root/'systemd/sing-box.service').exists());self.assertEqual(note.read_text(),'preserve')
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_hy2_certificate_ignores_conflicting_system_request_extensions(self):
  request=self.root/'system-req.cnf';text='[req]\ndistinguished_name=dn\nx509_extensions=custom\n[dn]\n[custom]\nbasicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:wrong.example\n'
  request.write_text(text)
  self.shell(self.install_mocks()+'OPENSSL_CONF='+shlex.quote(str(request))+' install_protocol 2',input='y\n\n1\n')
  cert=self.config/'hy2-selfsigned.crt'
  details=subprocess.check_output([manager.OPENSSL,'x509','-in',str(cert),'-noout','-text'],text=True)
  self.assertEqual(details.count('X509v3 Basic Constraints'),1)
  self.assertEqual(details.count('X509v3 Subject Alternative Name'),1)
  self.assertIn('CA:TRUE',details);self.assertIn('IP Address:8.8.8.8',details);self.assertNotIn('wrong.example',details)
  self.assertEqual(request.read_text(),text);self.assertEqual((self.config/'hy2-selfsigned.key').stat().st_mode&0o777,0o600)
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_install_exclusive_commit_preserves_file_created_during_preparation(self):
  code=self.install_mocks('curl(){ echo foreign > "$final_meta";printf 8.8.8.8; };install_protocol 2')
  self.assertNotEqual(self.shell(code,input='y\n\n1\n',ok=False).returncode,0)
  self.assertEqual((self.base/'state.json').read_text(),'foreign\n');self.assertFalse(self.bin.exists());self.assertFalse((self.config/'hy2-selfsigned.key').exists())
 def test_node_address_sni_ports_preserve_credentials_and_usage(self):
  self.user_setup(2);uid=self.add_user();d=self.user_db();d['users'][0].update(upload=1234,download=789);self.save_user_db(d)
  original=json.loads((self.config/'config.json').read_text());user=json.loads((self.base/'users'/uid/'server.json').read_text());ledger=(self.base/'users.json').read_bytes()
  self.shell(self.inactive()+'configuration_apply address line.example')
  self.assertIn('@line.example:',(self.base/'nodes.txt').read_text());self.assertIn('@line.example:',(self.base/'users'/uid/'nodes.txt').read_text())
  self.shell(self.inactive()+'configuration_apply sni node.example');p=manager.port();q=manager.port()
  self.shell(self.inactive()+'configuration_apply ports '+str(p)+' '+str(q))
  new=json.loads((self.config/'config.json').read_text());self.assertEqual(new['inbounds'][0]['users'],original['inbounds'][0]['users']);self.assertEqual(new['inbounds'][1]['users'],original['inbounds'][1]['users'])
  self.assertEqual([i['listen_port'] for i in new['inbounds']],[p,q]);new_user=json.loads((self.base/'users'/uid/'server.json').read_text())
  self.assertEqual([i['listen_port'] for i in new_user['inbounds']],[i['listen_port'] for i in user['inbounds']]);self.assertEqual(ledger,(self.base/'users.json').read_bytes())
 def test_invalid_and_occupied_node_ports_do_not_change_configuration(self):
  self.configure();before=(self.config/'config.json').read_bytes()
  for command in ('configuration_apply ports 01 443','configuration_apply address "bad;hostname"','configuration_apply hy2 10 20 true none'):
   self.assertNotEqual(self.shell(self.inactive()+command,ok=False).returncode,0);self.assertEqual(before,(self.config/'config.json').read_bytes())
  with socket.socket() as sock:
   sock.bind(('127.0.0.1',0));sock.listen();p=sock.getsockname()[1]
   self.assertNotEqual(self.shell(self.inactive()+'configuration_apply ports '+str(p)+' 443',ok=False).returncode,0)
  self.assertEqual(before,(self.config/'config.json').read_bytes())
 def test_node_restart_failure_rolls_back_all_user_and_admin_files(self):
  self.user_setup();uid=self.add_user();before=(self.config/'config.json').read_bytes();u=(self.base/'users'/uid/'server.json').read_bytes()
  code='''systemctl(){ if [[ $1 == is-active ]];then return 0;fi;if [[ $1 == restart && $2 == sing-box.service ]] && grep -q node.example "$CONF";then return 1;fi; };service_healthy(){ :; };configuration_apply sni node.example'''
  self.assertNotEqual(self.shell(code,ok=False).returncode,0);self.assertEqual(before,(self.config/'config.json').read_bytes());self.assertEqual(u,(self.base/'users'/uid/'server.json').read_bytes())
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_protocol_add_remove_preserves_existing_user_credentials_and_quotas(self):
  self.user_setup(2,mode='1');uid=self.add_user();self.bin=pathlib.Path(manager.SB);before=self.user_db();u=json.loads((self.base/'users'/uid/'server.json').read_text())
  self.shell(self.inactive()+'configuration_apply add hysteria2 '+str(manager.port())+' 127.0.0.1 '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key)))
  cfg=json.loads((self.base/'users'/uid/'server.json').read_text());self.assertEqual(cfg['inbounds'][0]['users'],u['inbounds'][0]['users']);self.assertEqual(cfg['inbounds'][1]['users'][0]['password'],json.loads((self.base/'users'/uid/'state.json').read_text())['hy2_password'])
  self.shell(self.inactive()+'configuration_apply remove vless');cfg=json.loads((self.base/'users'/uid/'server.json').read_text());password=cfg['inbounds'][0]['users'][0]['password'];self.assertEqual(cfg['inbounds'][0]['type'],'hysteria2')
  self.shell(self.inactive()+'configuration_apply add vless '+str(manager.port())+' node.example');cfg=json.loads((self.base/'users'/uid/'server.json').read_text());self.assertEqual(cfg['inbounds'][0]['users'][0]['password'],password);self.assertEqual(cfg['inbounds'][1]['users'][0]['uuid'],u['inbounds'][0]['users'][0]['uuid']);self.assertEqual(before,self.user_db())
  self.shell(self.inactive()+'configuration_apply remove hysteria2')
  self.assertNotEqual(self.shell(self.inactive()+'configuration_apply remove vless',ok=False).returncode,0)
 @unittest.skipUnless(manager.SB and manager.MIHOMO,'real engines required')
 def test_hy2_obfuscation_and_bandwidth_exports_validate_with_both_engines(self):
  self.user_setup(mode='2');uid=self.add_user();self.bin=pathlib.Path(manager.SB)
  self.shell(self.inactive()+'configuration_apply hy2 50 100 false salamander')
  for base in (self.base,self.base/'users'/uid):
   client=json.loads((base/'sing-box-client.json').read_text());self.assertEqual(client['outbounds'][0]['obfs']['type'],'salamander');self.assertEqual(client['outbounds'][0]['up_mbps'],50)
   self.assertIn('obfs-password=',(base/'nodes.txt').read_text())
   subprocess.run([manager.SB,'check','-c',str(base/'sing-box-client.json')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   subprocess.run([manager.MIHOMO,'-t','-d',str(self.root),'-f',str(base/'clash-verge.yaml')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  self.shell(self.inactive()+'configuration_apply hy2 0 0 true none');self.assertNotIn('obfs-password=',(self.base/'nodes.txt').read_text())
 def test_backup_manifest_detects_tamper_before_restore(self):
  self.configure('2');snap=pathlib.Path(self.shell('backup').stdout.strip());manifest=json.loads((snap/'backup-manifest.json').read_text());self.assertEqual(manifest['owner'],'SKYBYTE backup v1')
  self.shell('backup_engine preflight '+shlex.quote(str(snap)));before=(self.config/'config.json').read_bytes();(snap/'state.json').write_text('{}')
  r=self.shell('systemctl(){ echo SHOULD_NOT_STOP; };restore',input=str(snap)+'\ny\n',ok=False);self.assertNotEqual(r.returncode,0);self.assertEqual(before,(self.config/'config.json').read_bytes());self.assertNotIn('SHOULD_NOT_STOP',r.stdout)
 def test_backup_archive_roundtrip_and_traversal_rejection(self):
  self.configure('2');snap=pathlib.Path(self.shell('backup').stdout.strip());archive=self.root/'backup.tar.gz'
  self.shell('backup_engine archive '+shlex.quote(str(snap))+' '+shlex.quote(str(archive)))
  restored=pathlib.Path(self.shell('backup_engine import '+shlex.quote(str(archive))).stdout.strip());self.assertEqual((restored/'state.json').read_bytes(),(snap/'state.json').read_bytes())
  bad=self.root/'bad.tar.gz'
  with tarfile.open(bad,'w:gz') as tar:info=tarfile.TarInfo('../escape');info.size=0;tar.addfile(info)
  before=set(self.backups.iterdir());self.assertNotEqual(self.shell('backup_engine import '+shlex.quote(str(bad)),ok=False).returncode,0);self.assertEqual(before,set(self.backups.iterdir()));self.assertFalse((self.base/'escape').exists())
 def test_retention_only_deletes_owned_validated_backups_after_confirmation(self):
  self.configure();snapshots=[pathlib.Path(self.shell('backup').stdout.strip()) for _ in range(3)];unknown=self.backups/'unknown';unknown.mkdir();(unknown/'keep').write_text('keep')
  self.shell('backup_engine prune 1 preview');self.assertTrue(all(p.exists() for p in snapshots))
  self.shell('backup_engine prune 1 apply');self.assertEqual(sum(p.exists() for p in snapshots),1);self.assertTrue((unknown/'keep').exists())
 def online_setup_fixture(self):
  self.user_setup();uid=self.add_user();self.shell('users_export '+uid+' >/dev/null')
  self.shell('online_engine init node.example 8443 '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key)))
  self.shell('online_engine issue '+uid);return uid
 def test_subscription_tokens_are_independent_rotatable_and_revocable(self):
  a=self.online_setup_fixture();b=self.add_user('Bob');self.shell('online_engine issue '+b)
  d=online.read(self.base);old=d['tokens'][a];self.assertNotEqual(old,d['tokens'][b]);self.assertNotIn(self.uuid,old);self.assertEqual((self.base/'subscriptions.json').stat().st_mode&0o777,0o600)
  self.assertEqual(online.authorize(self.base,old)[0],a)
  self.shell('online_engine issue '+a);self.assertIsNone(online.authorize(self.base,old));self.assertEqual(online.authorize(self.base,d['tokens'][b])[0],b)
  self.shell('online_engine revoke '+a);self.assertIsNone(online.read(self.base)['tokens'][a])
 def test_disabled_expired_exhausted_deleted_and_failed_accounts_cannot_download(self):
  uid=self.online_setup_fixture();token=online.read(self.base)['tokens'][uid];original=self.user_db()
  for change in ({'enabled':False},{'expires_at':1},{'upload':original['users'][0]['quota_bytes']},{'deleted':True},{'metering_blocked':True}):
   d=json.loads(json.dumps(original));d['users'][0].update(change);self.save_user_db(d)
   if change.get('deleted'):
    with self.assertRaises(ValueError):online.authorize(self.base,token)
   else:self.assertIsNone(online.authorize(self.base,token))
  original['supervisor_enabled']=False;self.save_user_db(original);self.assertIsNone(online.authorize(self.base,token))
 def test_real_tls_subscription_only_serves_personal_exports_and_usage_header(self):
  uid=self.online_setup_fixture();d=self.user_db();d['users'][0].update(upload=111,download=222);self.save_user_db(d);token=online.read(self.base)['tokens'][uid];calls=[]
  def export(value):calls.append(value);self.shell('users_export '+value+' >/dev/null')
  server=online.Server(('127.0.0.1',0),online.handler(self.base,'unused',export));context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(self.cert,self.key);server.context=context
  thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
  client=ssl.create_default_context(cafile=str(self.cert))
  def request(path):
   c=http.client.HTTPSConnection('127.0.0.1',server.server_port,context=client,timeout=10);c.request('GET',path);r=c.getresponse();body=r.read();headers=dict(r.getheaders());c.close();return r.status,body,headers
  status,body,headers=request('/s/'+token+'/singbox');self.assertEqual(status,200);self.assertIn('upload=111; download=222;',headers['subscription-userinfo']);self.assertNotIn(d['users'][0]['api_secret'].encode(),body);self.assertNotIn(b'private_key',body);self.assertEqual(calls,[uid])
  for path in ('/','/s/'+token+'/server.json','/s/'+token+'/../../users.json','/s/'+token+'/singbox?x=1','/s/'+('a'*43)+'/singbox'):
   self.assertEqual(request(path)[0],404)
  self.shell('online_engine revoke '+uid);self.assertEqual(request('/s/'+token+'/singbox')[0],404)
 def test_subscription_export_symlink_and_rate_limits_are_rejected(self):
  uid=self.online_setup_fixture();p=self.base/'users'/uid/'sing-box-client.json';p.unlink();p.symlink_to(self.base/'users.json')
  self.assertNotEqual(self.shell('users_export '+uid,ok=False).returncode,0)
  with online.Server(('127.0.0.1',0),online.handler(self.base,'unused',lambda uid:None)) as server:
   self.assertTrue(all(server.allow('127.0.0.1') for _ in range(60)));self.assertFalse(server.allow('127.0.0.1'))
 def test_online_setup_rejects_untrusted_self_signed_without_creating_listener(self):
  self.user_setup()
  r=self.shell('ss(){ :; };online_setup',input='node.example\n8443\n'+str(self.cert)+'\n'+str(self.key)+'\ny\n',ok=False)
  self.assertNotEqual(r.returncode,0);self.assertFalse((self.base/'subscriptions.json').exists());self.assertFalse((self.root/'systemd/skybyte-subscriptions.service').exists())
 def test_foreign_subscription_and_acme_units_are_never_removed(self):
  self.configure();unit=self.root/'systemd/skybyte-subscriptions.service';unit.write_text('Description=foreign\n')
  self.assertNotEqual(self.shell('online_remove',ok=False).returncode,0);self.assertTrue(unit.exists())
  foreign=self.base/'acme';foreign.mkdir();(foreign/'keep').write_text('keep')
  self.assertNotEqual(self.shell('acme_remove',ok=False).returncode,0);self.assertTrue((foreign/'keep').exists())
 def test_acme_http_refuses_occupied_port_without_stopping_site(self):
  r=self.shell('need_root(){ :; };ss(){ echo OCCUPIED; };systemctl(){ echo BAD_STOP; };acme_issue',input='node.example\nowner@example.com\n1\n',ok=False)
  self.assertNotEqual(r.returncode,0);self.assertNotIn('BAD_STOP',r.stdout);self.assertFalse((self.base/'acme').exists())
 def test_acme_dns_uses_private_token_file_and_isolated_certbot_arguments(self):
  log=self.root/'certbot-args';tools=self.root/'tools';tools.mkdir();exe=tools/'certbot'
  exe.write_text('#!/bin/sh\nprintf "%s\\n" "$*" > '+shlex.quote(str(log))+'\nexit 1\n');exe.chmod(0o700)
  token='a'*32
  code='need_root(){ :; };apt-get(){ :; };PATH='+shlex.quote(str(tools))+':"$PATH";acme_issue'
  r=self.shell(code,input='node.example\nowner@example.com\n2\ny\n'+token+'\n',ok=False);self.assertNotEqual(r.returncode,0)
  text=log.read_text();self.assertIn('--config-dir '+str(self.base/'acme/config'),text);self.assertIn('--dns-cloudflare-credentials '+str(self.base/'acme/cloudflare.ini'),text);self.assertNotIn(token,text);self.assertNotIn(token,r.stdout+r.stderr)
  self.assertEqual((self.base/'acme/cloudflare.ini').stat().st_mode&0o777,0o600)
  self.shell('acme_menu',input='6\ny\n');self.assertFalse((self.base/'acme').exists())
 def test_rule_catalog_update_validates_and_preserves_custom_live_routing(self):
  self.configure();self.shell('warp_engine switch restricted 40000 false custom.example');before=(self.config/'config.json').read_bytes();catalog=json.loads((manager.ROOT/'data/warp-rules.json').read_text());catalog['version']+='.1';catalog['media'].append('media.example');p=self.root/'catalog.json';p.write_text(json.dumps(catalog))
  self.shell('warp_engine catalog_update '+shlex.quote(str(p)));self.assertIn('media.example',self.shell('warp_engine defaults').stdout);self.assertEqual(before,(self.config/'config.json').read_bytes())
  old=(self.base/'warp-rules.json').read_bytes();catalog['media']=['bad;command'];p.write_text(json.dumps(catalog));self.assertNotEqual(self.shell('warp_engine catalog_update '+shlex.quote(str(p)),ok=False).returncode,0);self.assertEqual(old,(self.base/'warp-rules.json').read_bytes())
 def test_bilingual_new_menu_entries_and_rootless_help(self):
  for language in ('en_US','zh_CN'):
   for group,choice,action in ((1,5,'settings'),(2,6,'online'),(5,6,'acme'),(5,7,'backup_tools'),(6,4,'help')):
    r=self.shell('LANGUAGE_CHOICE='+language+';sub_menu '+str(group)+';echo "$MAIN_ACTION"',input=str(choice)+'\n');self.assertTrue(r.stdout.rstrip().endswith(action))
   r=self.shell('LANGUAGE_CHOICE='+language+';usage_help');self.assertIn('HTTPS',r.stdout);self.assertIn('ACME',r.stdout)
  r=subprocess.run([manager.BASH,str(manager.ROOT/'singbox-v2.sh'),'--help'],capture_output=True,text=True);self.assertEqual(r.returncode,0);self.assertIn('SKYBYTE',r.stdout)
 def test_core_version_selector_supports_tested_latest_specific_and_cancellation(self):
  self.configure()
  self.bin.write_text('#!/bin/sh\necho "sing-box version 1.14.3"\n');self.bin.chmod(0o700)
  code='latest(){ echo 1.14.4; };apply_update(){ echo SWITCHED-"$1"; };core_versions'
  r=self.shell(code,input='1\n');self.assertNotIn('SWITCHED',r.stdout)
  r=self.shell(code,input='2\ny\n');self.assertIn('SWITCHED-1.14.4',r.stdout)
  r=self.shell(code,input='3\n1.13.0\ny\n');self.assertIn('SWITCHED-1.13.0',r.stdout)
  r=self.shell(code,input='3\n1.13.0\nno\n',ok=False);self.assertNotIn('SWITCHED',r.stdout)
  self.assertNotEqual(self.shell(code,input='3\n1.2;evil\n',ok=False).returncode,0)
 def test_tls_edit_rejects_mismatched_identity_without_touching_original(self):
  self.configure('2');before=(self.config/'config.json').read_bytes()
  r=self.shell(self.inactive()+'configuration_apply tls wrong.example '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key)),ok=False)
  self.assertNotEqual(r.returncode,0);self.assertEqual(before,(self.config/'config.json').read_bytes())
 def acme_fixture(self):
  acme=self.base/'acme';acme.mkdir();(acme/'.skybyte-owner').write_text('SKYBYTE ACME v1\n');live=acme/'config/live/skybyte';live.mkdir(parents=True)
  import shutil
  shutil.copyfile(self.cert,live/'fullchain.pem');shutil.copyfile(self.key,live/'privkey.pem')
  (self.base/'acme-state.json').write_text(json.dumps({'owner':'SKYBYTE ACME v1','schema':1,'domain':'node.example','method':'cloudflare'}));return live
 def test_acme_renewal_failure_does_not_reload_or_overwrite_certificate(self):
  live=self.acme_fixture();original=(live/'fullchain.pem').read_bytes()
  code='certbot(){ return 1; };certificate_check(){ echo BAD_RELOAD; };online_reload(){ echo BAD_ONLINE; };acme_renew'
  r=self.shell(code,ok=False);self.assertNotEqual(r.returncode,0);self.assertEqual(original,(live/'fullchain.pem').read_bytes());self.assertNotIn('BAD_',r.stdout)
 def test_acme_timer_is_opt_in_owned_and_uses_isolated_renewal_flag(self):
  self.acme_fixture();self.shell('systemctl(){ :; };acme_timer')
  service=self.root/'systemd/skybyte-acme.service';timer=self.root/'systemd/skybyte-acme.timer'
  self.assertIn('--acme-renew',service.read_text());self.assertIn('03,15:00:00',timer.read_text())
  service.write_text('Description=foreign\n');self.assertNotEqual(self.shell('systemctl(){ echo BAD; };acme_remove',ok=False).returncode,0);self.assertTrue(timer.exists())
 def test_acme_and_subscription_uninstall_retains_private_integrity_checked_backup(self):
  self.prepare_uninstall();self.acme_fixture();self.shell('online_engine init node.example 8443 '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key)))
  unit=self.root/'systemd/skybyte-subscriptions.service';unit.write_text('Description=SKYBYTE managed HTTPS subscriptions\nExecStart=/bin/bash '+str(self.root/'manager-command')+' --subscription-serve\n')
  self.shell('need_root(){ :; };systemctl(){ :; };uninstall_manager',input='y\n')
  self.assertFalse(unit.exists());self.assertFalse((self.base/'acme').exists());snap=next(self.backups.iterdir());self.assertTrue((snap/'acme/config/live/skybyte/privkey.pem').exists());self.assertTrue((snap/'subscriptions.json').exists());self.shell('backup_engine preflight '+shlex.quote(str(snap)),ok=False)
  # Integrity remains valid even though the current core was deliberately uninstalled.
  manifest=json.loads((snap/'backup-manifest.json').read_text())
  for name,digest in manifest['files'].items():self.assertEqual(hashlib.sha256((snap/name).read_bytes()).hexdigest(),digest)
 def test_preflight_never_executes_a_binary_from_an_imported_archive(self):
  self.configure('2');snap=pathlib.Path(self.shell('backup').stdout.strip());marker=self.root/'executed'
  (snap/'sing-box.bin').write_text('#!/bin/sh\ntouch '+shlex.quote(str(marker))+'\n');self.shell('backup_engine reseal '+shlex.quote(str(snap)))
  self.shell('backup_engine preflight '+shlex.quote(str(snap)));self.assertFalse(marker.exists())
 def test_rule_download_digest_failure_preserves_current_catalog(self):
  self.configure();catalog=manager.ROOT/'data/warp-rules.json';manifest=self.root/'release.json';manifest.write_text(json.dumps({'tag_name':'v2.5.0','draft':False,'prerelease':False,'assets':[{'name':'warp-rules.json','digest':'sha256:'+'0'*64}]}))
  code='''curl(){ local out= url=;while (($#));do if [[ $1 == -o ]];then out=$2;shift 2;else url=$1;shift;fi;done;if [[ $url == */latest ]];then cp '''+shlex.quote(str(manifest))+''' "$out";else cp '''+shlex.quote(str(catalog))+''' "$out";fi; };warp_rules_update'''
  self.assertNotEqual(self.shell(code,ok=False).returncode,0);self.assertFalse((self.base/'warp-rules.json').exists());self.assertFalse(list(self.base.glob('rules-update.*')))
 @unittest.skipUnless(__import__('shutil').which('gpg'),'GnuPG required; Ubuntu/Debian CI installs it')
 def test_real_gpg_encrypted_backup_roundtrip(self):
  self.configure();snap=pathlib.Path(self.shell('backup').stdout.strip());encrypted=self.root/'private.gpg';phrase='temporary-test-passphrase'
  home=self.root/'gpg-home';home.mkdir(mode=0o700);code='export GNUPGHOME='+shlex.quote(str(home))+';backup_tools'
  r=self.shell(code,input='4\n'+str(snap)+'\n'+str(encrypted)+'\n'+phrase+'\n');self.assertNotIn(phrase,r.stdout+r.stderr);self.assertNotIn(b'PRIVATE KEY',encrypted.read_bytes());self.assertEqual(encrypted.stat().st_mode&0o777,0o600)
  before=set(self.backups.iterdir());self.shell(code,input='5\n'+str(encrypted)+'\n'+phrase+'\n');new=list(set(self.backups.iterdir())-before);self.assertEqual(len(new),1);self.assertEqual((new[0]/'state.json').read_bytes(),(snap/'state.json').read_bytes())
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_ten_real_account_cores_are_sampled_and_disabled_without_stopping_peers(self):
  self.user_setup(10,mode='2',real=True)
  for n in range(10):self.add_user('load-'+str(n))
  worker=subprocess.Popen([manager.BASH,'-c',self.script('users_engine watch')],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  def stop():
   if worker.poll() is None:worker.terminate()
   worker.communicate(timeout=20)
  self.addCleanup(stop)
  deadline=time.monotonic()+15
  while time.monotonic()<deadline:
   db=self.user_db()
   if all(u.get('running') for u in db['users']):break
   time.sleep(.1)
  self.assertTrue(all(u.get('running') for u in self.user_db()['users']))
  db=self.user_db();db['users'][0]['enabled']=False;db['users'][1]['expires_at']=1;self.save_user_db(db)
  deadline=time.monotonic()+5
  while time.monotonic()<deadline:
   db=self.user_db()
   if not db['users'][0].get('running') and not db['users'][1].get('running'):break
   time.sleep(.1)
  self.assertFalse(db['users'][0]['running']);self.assertFalse(db['users'][1]['running']);self.assertTrue(all(u['running'] for u in db['users'][2:]));self.assertTrue(all(time.time()-u['sampled_at']<4 for u in db['users'][2:]))
 def test_release_package_contains_only_public_assets_and_valid_digests(self):
  output=self.root/'release';subprocess.run(['python3',str(manager.ROOT/'scripts/package_release.py'),'--output',str(output)],check=True,stdout=subprocess.DEVNULL)
  self.assertEqual({p.name for p in output.iterdir()},{'bootstrap.sh','install.sh','singbox-v2.sh','warp-rules.json','SHA256SUMS'})
  for line in (output/'SHA256SUMS').read_text().splitlines():
   digest,name=line.split('  ');self.assertEqual(hashlib.sha256((output/name).read_bytes()).hexdigest(),digest)
 def test_successful_acme_issuance_saves_owned_state_and_certificate_without_auto_timer(self):
  tools=self.root/'tools';tools.mkdir();exe=tools/'certbot';live=self.base/'acme/config/live/skybyte'
  exe.write_text('#!/bin/sh\nmkdir -p '+shlex.quote(str(live))+'\ncp '+shlex.quote(str(self.cert))+' '+shlex.quote(str(live/'fullchain.pem'))+'\ncp '+shlex.quote(str(self.key))+' '+shlex.quote(str(live/'privkey.pem'))+'\n');exe.chmod(0o700)
  self.shell('need_root(){ :; };apt-get(){ :; };ss(){ :; };PATH='+shlex.quote(str(tools))+':"$PATH";acme_issue',input='node.example\nowner@example.com\n1\ny\n')
  state=json.loads((self.base/'acme-state.json').read_text());self.assertEqual(state['domain'],'node.example');self.assertEqual(state['owner'],'SKYBYTE ACME v1');self.assertFalse((self.root/'systemd/skybyte-acme.timer').exists());self.assertEqual((self.base/'acme-state.json').stat().st_mode&0o777,0o600)
 def test_idle_menu_releases_operation_lock_and_reacquires_for_action(self):
  self.configure();events=self.root/'lock-events'
  code='need_root(){ :; };flock(){ echo "$*" >> '+shlex.quote(str(events))+'; };dispatch_action(){ echo ACTION; };main'
  self.shell(code,input='4\n7\n0\n');lines=events.read_text().splitlines();self.assertEqual(lines[0],'-u 9');self.assertIn('-n 9',lines);self.assertEqual(lines[-1],'-u 9')
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_add_hy2_self_signed_preserves_existing_reality_and_provides_client_trust(self):
  self.user_setup(2,mode='1');uid=self.add_user();self.bin=pathlib.Path(manager.SB);before=self.user_db();original=json.loads((self.config/'config.json').read_text())['inbounds'][0]
  self.shell(self.inactive()+'configuration_apply add hysteria2 '+str(manager.port())+' 127.0.0.1 selfsigned')
  cfg=json.loads((self.config/'config.json').read_text());self.assertEqual(cfg['inbounds'][0],original);self.assertEqual(cfg['inbounds'][1]['tls']['certificate_path'],str(self.config/'hy2-added.crt'));self.assertEqual(before,self.user_db())
  for p in (self.base,self.base/'users'/uid):
   client=json.loads((p/'sing-box-client.json').read_text());self.assertIn('certificate',client['outbounds'][1]['tls']);self.assertNotIn('insecure',client['outbounds'][1]['tls']);self.assertTrue((p/'hy2-client-ca.pem').exists())
   subprocess.run([manager.SB,'check','-c',str(p/'sing-box-client.json')],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 def test_auxiliary_restore_fills_missing_certificates_and_tokens_but_preserves_live_tokens(self):
  uid=self.online_setup_fixture();self.acme_fixture();token=online.read(self.base)['tokens'][uid];snapshot=pathlib.Path(self.shell('systemctl(){ return 1; };backup').stdout.strip())
  self.shell('online_engine issue '+uid);current=online.read(self.base)['tokens'][uid]
  self.shell('auxiliary_restore_snapshot '+shlex.quote(str(snapshot)));self.assertEqual(online.read(self.base)['tokens'][uid],current)
  self.shell('online_remove;acme_remove')
  self.shell('online_chain_check(){ :; };systemctl(){ :; };auxiliary_restore_snapshot '+shlex.quote(str(snapshot)))
  self.assertEqual(online.read(self.base)['tokens'][uid],token);self.assertTrue((self.base/'subscription-backup.key').exists());self.assertTrue((self.base/'acme/.skybyte-owner').exists());self.assertFalse((self.root/'systemd/skybyte-acme.timer').exists())
 def test_failed_auxiliary_restore_cleans_new_state_and_keeps_unrelated_files(self):
  self.online_setup_fixture();self.acme_fixture();self.shell('online_chain_check(){ :; };systemctl(){ :; };online_setup_service_stub(){ :; }')
  unit=self.root/'systemd/skybyte-subscriptions.service';unit.write_text('Description=SKYBYTE managed HTTPS subscriptions\nExecStart=/bin/bash '+str(self.root/'manager-command')+' --subscription-serve\n')
  snapshot=pathlib.Path(self.shell('systemctl(){ :; };backup').stdout.strip());self.shell('systemctl(){ :; };online_remove;acme_remove');note=self.base/'keep.txt';note.write_text('keep')
  r=self.shell('online_chain_check(){ :; };systemctl(){ [[ $1 != enable ]]; };auxiliary_restore_snapshot '+shlex.quote(str(snapshot)),ok=False)
  self.assertNotEqual(r.returncode,0);self.assertFalse((self.base/'subscriptions.json').exists());self.assertFalse((self.base/'acme').exists());self.assertFalse(unit.exists());self.assertEqual(note.read_text(),'keep')
 def test_firewall_enable_uses_custom_node_and_https_ports(self):
  self.configure();cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds'][0]['listen_port']=24443;cfg['inbounds'][1]['listen_port']=34443;(self.config/'config.json').write_text(json.dumps(cfg))
  self.shell('online_engine init node.example 8443 '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key)))
  code='need_root(){ :; };detect_ssh_ports(){ SSH_PORTS=22; };ufw(){ echo "UFW $*"; };firewall'
  r=self.shell(code,input='2\n22\ny\n');self.assertIn('UFW allow 24443/tcp',r.stdout);self.assertIn('UFW allow 34443/udp',r.stdout);self.assertIn('UFW allow 8443/tcp',r.stdout);self.assertNotIn('UFW allow 443/',r.stdout)
 def test_status_reports_actual_protocol_listeners(self):
  self.configure();cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds'][0]['listen_port']=24443;cfg['inbounds'][1]['listen_port']=34443;(self.config/'config.json').write_text(json.dumps(cfg))
  r=self.shell('systemctl(){ :; };ss(){ echo "$*"; };nft(){ :; };firewall_audit(){ :; };status')
  self.assertIn('sport = :24443',r.stdout);self.assertIn('sport = :34443',r.stdout);self.assertNotIn('sport = :443',r.stdout)
 def test_zero_exit_openssl_identity_mismatch_is_rejected(self):
  self.configure('2');before=(self.config/'config.json').read_bytes();exe=self.root/'fake-openssl'
  exe.write_text('#!/bin/sh\ncase "$*" in *-checkhost*|*-checkip*) echo "Hostname does NOT match certificate";;esac\nexit 0\n');exe.chmod(0o700)
  code='export OPENSSL_BIN='+shlex.quote(str(exe))+';'+self.inactive()+'configuration_apply tls wrong.example '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key))
  self.assertNotEqual(self.shell(code,ok=False).returncode,0);self.assertEqual(before,(self.config/'config.json').read_bytes())

class RealityReplacementTest(unittest.TestCase):
 setUp=ReliabilityTest.setUp
 script=ReliabilityTest.script
 shell=ReliabilityTest.shell
 configure=ReliabilityTest.configure
 user_setup=ReliabilityTest.user_setup
 add_user=ReliabilityTest.add_user
 user_db=ReliabilityTest.user_db
 save_user_db=ReliabilityTest.save_user_db
 inactive=ReliabilityTest.inactive
 def probe_stub(self,status=0):
  return '''eval "$(declare -f reality_engine | sed '1s/reality_engine/original_reality_engine/')"
reality_engine(){
 if [[ " $* " != *" --target "* || " $* " == *" --normalize "* ]];then original_reality_engine "$@";else return '''+str(status)+''';fi
};'''
 def snapshot(self):
  return {p:p.read_bytes() for parent in (self.base,self.config) for p in parent.rglob('*') if p.is_file() and not p.name.endswith('.lock')}
 @unittest.skipUnless(manager.SB,'real engine required')
 def test_replacement_syncs_user_exports_and_preserves_credentials_usage_and_hopping(self):
  self.user_setup(2);uid=self.add_user();self.bin=pathlib.Path(manager.SB)
  ledger=(self.base/'users.json').read_bytes();old=json.loads((self.config/'config.json').read_text());user=json.loads((self.base/'users'/uid/'server.json').read_text())
  meta=json.loads((self.base/'state.json').read_text());meta['hop']=True;(self.base/'state.json').write_text(json.dumps(meta))
  code=self.inactive()+self.probe_stub()+'''hop_guard(){ :; };hop_disable(){ echo BAD_HOP;return 1; };reality_menu 3'''
  result=self.shell(code,input='7\nnode.example\nendpoint.example:8443\ny\n')
  self.assertNotIn('BAD_HOP',result.stdout)
  for path,expected in ((self.config/'config.json',old),(self.base/'users'/uid/'server.json',user)):
   expected['inbounds'][0]['tls']['server_name']='node.example';expected['inbounds'][0]['tls']['reality']['handshake']={'server':'endpoint.example','server_port':8443}
   self.assertEqual(json.loads(path.read_text()),expected)
  self.assertEqual((self.base/'users.json').read_bytes(),ledger)
  self.assertTrue(json.loads((self.base/'state.json').read_text())['hop'])
  for parent in (self.base,self.base/'users'/uid):
   self.assertIn('sni=node.example',(parent/'nodes.txt').read_text())
   client=json.loads((parent/'sing-box-client.json').read_text());self.assertEqual(client['outbounds'][0]['tls']['server_name'],'node.example')
 def test_failed_probe_and_cancel_leave_all_files_and_backups_unchanged(self):
  self.configure();self.shell('exports >/dev/null');before=self.snapshot()
  for status,answer in ((1,'y'),(0,'n')):
   result=self.shell(self.probe_stub(status)+'reality_menu 3',input='2\n\n'+answer+'\n',ok=False)
   if status:self.assertNotEqual(result.returncode,0)
   self.assertEqual(self.snapshot(),before)
 def test_no_reality_or_cancel_at_selection_does_not_add_a_node(self):
  self.configure(mode='2');before=self.snapshot();result=self.shell('reality_menu 3')
  self.assertIn('No Reality node',result.stdout);self.assertEqual(self.snapshot(),before)
  self.configure();before=self.snapshot();self.shell('reality_menu 3',input='0\n');self.assertEqual(self.snapshot(),before)
 def test_replacement_restart_failure_restores_configs_and_exports(self):
  self.user_setup();uid=self.add_user();self.shell('exports >/dev/null;users_export '+uid+' >/dev/null')
  files=[self.config/'config.json',self.base/'state.json',self.base/'nodes.txt',self.base/'users'/uid/'server.json',self.base/'users'/uid/'state.json',self.base/'users'/uid/'nodes.txt']
  old={p:p.read_bytes() for p in files}
  code=self.probe_stub()+'''systemctl(){ if [[ $1 == is-active ]];then return 0;fi;if [[ $1 == restart && $2 == sing-box.service ]] && grep -q node.example "$CONF";then return 1;fi; };service_healthy(){ :; };reality_menu 3'''
  result=self.shell(code,input='7\nnode.example\n\ny\n',ok=False);self.assertNotEqual(result.returncode,0)
  self.assertEqual({p:p.read_bytes() for p in files},old)
 def test_partial_export_failure_rolls_back_configs_and_all_exports(self):
  self.user_setup();uid=self.add_user();self.shell('exports >/dev/null;users_export '+uid+' >/dev/null')
  before=self.snapshot()
  code=self.inactive()+self.probe_stub()+'''exports(){ printf broken > "$BASE/nodes.txt";return 1; };reality_menu 3'''
  result=self.shell(code,input='7\nnode.example\n\ny\n',ok=False);self.assertNotEqual(result.returncode,0)
  after=self.snapshot()
  # A recovery backup is retained; every original live file must be restored.
  for path,data in before.items():self.assertEqual(after[path],data,str(path))
