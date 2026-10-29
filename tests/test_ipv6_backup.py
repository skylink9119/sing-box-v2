"""IPv6 backups preserve credentials and account state; failed edits roll back."""
import base64,copy,json,shlex,unittest,urllib.parse
import test_manager as manager
PUBLIC='2001:4860:4860::8888'
class BackupTests(unittest.TestCase):
 setUp=manager.ManagerTest.setUp
 script=manager.ManagerTest.script
 shell=manager.ManagerTest.shell
 configure=manager.ManagerTest.configure
 user_setup=manager.ManagerTest.user_setup
 add_user=manager.ManagerTest.add_user
 user_db=manager.ManagerTest.user_db
 save_user_db=manager.ManagerTest.save_user_db
 def inactive(self):return 'systemctl(){ return 1; }; '
 def test_enable_edit_disable_keeps_credentials_accounts_and_ipv4_exports(self):
  self.user_setup(2);identity=self.add_user()
  original=json.loads((self.config/'config.json').read_text());metadata=json.loads((self.base/'state.json').read_text())
  ledger=(self.base/'users.json').read_bytes()
  user_path=self.base/'users'/identity;user=json.loads((user_path/'server.json').read_text())
  self.shell('exports >/dev/null');links=(self.base/'nodes.txt').read_text().splitlines()
  self.shell(self.inactive()+'configuration_apply ipv6 '+PUBLIC)
  current=json.loads((self.config/'config.json').read_text())
  self.assertEqual(current,dict(original,inbounds=[dict(i,listen='::') for i in original['inbounds']]))
  self.assertEqual(ledger,(self.base/'users.json').read_bytes())
  for folder in (self.base,user_path):
   text=(folder/'nodes.txt').read_text();parsed=[urllib.parse.urlsplit(x) for x in text.splitlines()]
   self.assertEqual(len(parsed),4);self.assertEqual(parsed[-1].hostname,PUBLIC)
   self.assertEqual(parsed[0].username,parsed[2].username);self.assertEqual(parsed[1].username,parsed[3].username)
   self.assertEqual(parsed[1].query,parsed[3].query)
   self.assertEqual(base64.b64decode((folder/'subscription-base64.txt').read_text()).decode(),text)
   client=json.loads((folder/'sing-box-client.json').read_text())
   backup_client=json.loads((folder/'sing-box-client-ipv6.json').read_text())
   self.assertEqual(backup_client['outbounds'][0]['server'],PUBLIC)
   self.assertEqual(backup_client['route']['final'],backup_client['outbounds'][0]['tag'])
   self.assertEqual(client['outbounds'][2]['server'],PUBLIC)
   self.assertEqual(client['outbounds'][1]['tls'],client['outbounds'][3]['tls'])
  self.assertEqual((self.base/'nodes.txt').read_text().splitlines()[:2],links)
  self.shell(self.inactive()+'configuration_apply ipv6 2606:4700:4700::1111')
  self.shell(self.inactive()+'configuration_apply ipv6 off')
  self.assertEqual(json.loads((self.config/'config.json').read_text()),original)
  self.assertEqual(json.loads((user_path/'server.json').read_text()),user)
  self.assertEqual(json.loads((self.base/'state.json').read_text()),metadata)
  self.assertEqual((self.base/'nodes.txt').read_text().splitlines(),links)
  self.assertFalse((self.base/'sing-box-client-ipv6.json').exists())
  self.assertFalse((user_path/'sing-box-client-ipv6.json').exists())
 def test_failed_dual_stack_readiness_restores_config_and_exports(self):
  self.configure();self.shell('exports >/dev/null')
  before={p:p.read_bytes() for p in [self.config/'config.json',self.base/'state.json',self.base/'nodes.txt']}
  code='''systemctl(){ [[ $1 == is-active && ${*: -1} == sing-box.service ]]; }
warp_resume(){ :; };ipv6_engine(){ return 1; }
configuration_apply ipv6 '''+PUBLIC
  result=self.shell(code,ok=False);self.assertNotEqual(result.returncode,0)
  for p,data in before.items():self.assertEqual(p.read_bytes(),data)
 def test_menu_stays_open_after_detection_failure(self):
  self.configure()
  code='''configuration_guard(){ :; };users_guard(){ :; };ipv6_engine(){ case $1 in detect) return 1;; status) echo STATUS;; esac; }
flock(){ :; };run_submenu ipv6_menu'''
  result=self.shell(code,input='2\n1\n0\n');self.assertIn('STATUS',result.stdout)

@unittest.skipUnless(manager.SB,'Official sing-box required')
class DualStackProtocolTests(unittest.TestCase):
 setUp=manager.ManagerTest.setUp
 script=manager.ManagerTest.script
 shell=manager.ManagerTest.shell
 configure=manager.ManagerTest.configure
 exported=manager.ManagerTest.exported
 hy2_connection=manager.ManagerTest.hy2_connection
 user_setup=manager.ManagerTest.user_setup
 add_user=manager.ManagerTest.add_user
 user_db=manager.ManagerTest.user_db
 save_user_db=manager.ManagerTest.save_user_db
 reality_metered_connection=manager.ManagerTest.reality_metered_connection
 def test_hy2_ipv6_verifies_original_certificate(self):self.hy2_connection(True,'::1')
 def test_hy2_original_ipv4_works_on_dual_stack(self):self.hy2_connection(True)
 def test_reality_ipv6_preserves_account_metering(self):self.reality_metered_connection(True)
