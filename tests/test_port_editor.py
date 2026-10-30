"""Port-only editing, defaults, protocol isolation and rollback regressions."""
import json,shlex,socket,unittest,urllib.parse
import test_manager as manager
class PortEditorTests(unittest.TestCase):
 setUp=manager.ManagerTest.setUp
 script=manager.ManagerTest.script
 shell=manager.ManagerTest.shell
 configure=manager.ManagerTest.configure
 user_setup=manager.ManagerTest.user_setup
 add_user=manager.ManagerTest.add_user
 user_db=manager.ManagerTest.user_db
 save_user_db=manager.ManagerTest.save_user_db
 def inactive(self):return 'systemctl(){ return 1; }; '
 def set_ports(self,vp=24443,hp=34443):
  p=self.config/'config.json';cfg=json.loads(p.read_text())
  for i in cfg['inbounds']:i['listen_port']=vp if i['type']=='vless' else hp
  p.write_text(json.dumps(cfg));return cfg
 def test_hy2_only_blank_keeps_actual_port_and_does_not_ask_reality(self):
  self.configure('2');self.set_ports();before=(self.config/'config.json').read_bytes()
  for call in ('edit_node_ports','node_settings 1'):
   result=self.shell(call,input='\n');self.assertIn('34443',result.stdout)
   self.assertNotIn('Reality TCP',result.stdout);self.assertIn('Ports unchanged',result.stdout)
   self.assertEqual((self.config/'config.json').read_bytes(),before)
 def test_tcp_edit_keeps_hy2_accounts_credentials_and_ipv6_exports(self):
  self.user_setup();identity=self.add_user();self.set_ports()
  self.shell(self.inactive()+'configuration_apply ipv6 2001:4860:4860::8888')
  before=json.loads((self.config/'config.json').read_text());ledger=(self.base/'users.json').read_bytes()
  user=(self.base/'users'/identity/'server.json').read_bytes();number=manager.port()
  result=self.shell(self.inactive()+'edit_node_ports',input=str(number)+'\n\ny\n')
  new=json.loads((self.config/'config.json').read_text());expected=json.loads(json.dumps(before));expected['inbounds'][0]['listen_port']=number
  self.assertEqual(new,expected);self.assertEqual((self.base/'users.json').read_bytes(),ledger)
  self.assertEqual((self.base/'users'/identity/'server.json').read_bytes(),user)
  links=[urllib.parse.urlsplit(s) for s in (self.base/'nodes.txt').read_text().splitlines()]
  self.assertEqual([i.port for i in links],[number,34443,number,34443]);self.assertIn('Ports updated',result.stdout)
 def test_invalid_cancel_and_normalized_unchanged_do_not_write(self):
  self.configure('2');self.set_ports(hp=4443);before=(self.config/'config.json').read_bytes()
  for inputs,ok in [('0\n',False),('65536\n',False),('10443\nn\n',True),('04443\n',True)]:
   result=self.shell(self.inactive()+'edit_node_ports',input=inputs,ok=ok)
   if not ok:self.assertNotEqual(result.returncode,0)
   self.assertEqual((self.config/'config.json').read_bytes(),before)
 def test_ufw_failure_preserves_config_and_running_services(self):
  self.configure('1');self.set_ports();before=(self.config/'config.json').read_bytes();number=manager.port()
  code='''ufw(){ if [[ $1 == status ]];then echo 'Status: active';else echo UFW_FAILED;return 1;fi; }
systemctl(){ echo UNEXPECTED_SERVICE_CHANGE;return 1; }
edit_node_ports'''
  result=self.shell(code,input=str(number)+'\ny\n',ok=False)
  self.assertNotEqual(result.returncode,0);self.assertEqual((self.config/'config.json').read_bytes(),before)
  self.assertIn('UFW_FAILED',result.stdout);self.assertNotIn('UNEXPECTED_SERVICE_CHANGE',result.stdout)
 def hopping(self):
  p=self.base/'state.json';meta=json.loads(p.read_text());meta.update(hop=True,hop_start=20000,hop_end=30000);p.write_text(json.dumps(meta))
 def test_tcp_only_change_retains_hy2_hopping(self):
  self.configure();self.hopping();number=manager.port()
  result=self.shell(self.inactive()+'''hop_disable(){ echo MUST_NOT_DISABLE;return 1; }
configuration_apply ports '''+str(number)+' 443')
  self.assertNotIn('MUST_NOT_DISABLE',result.stdout);self.assertTrue(json.loads((self.base/'state.json').read_text())['hop'])
  out=json.loads((self.base/'outbounds.json').read_text())['outbounds'];self.assertIn('server_ports',out[1])
 def test_export_failure_restores_ports_hopping_metadata_and_service_flags(self):
  self.configure();self.hopping();self.shell('exports >/dev/null')
  unit=self.root/'systemd/singbox-v2-hop.service'
  unit.write_text('Description=singbox V2 HY2 IPv4 port hopping\nExecStart=/usr/sbin/nft -f '+str(self.base/'hop.nft')+'\n')
  before={p:p.read_bytes() for p in [self.config/'config.json',self.base/'state.json',self.base/'nodes.txt']}
  code='''systemctl(){ echo "SYSTEMCTL $*";return 0; }
nft(){ :; };service_healthy(){ :; };configuration_export_all(){ return 1; }
configuration_apply ports 443 10443'''
  result=self.shell(code,ok=False);self.assertNotEqual(result.returncode,0)
  for p,data in before.items():self.assertEqual(p.read_bytes(),data)
  self.assertIn('enable singbox-v2-hop.service',result.stdout);self.assertIn('start singbox-v2-hop.service',result.stdout)

 def test_unknown_ufw_state_keeps_node_port(self):
  self.configure('1');before=(self.config/'config.json').read_bytes()
  result=self.shell('ufw(){ return 1; };'+self.inactive()+'edit_node_ports',input=str(manager.port())+'\ny\n',ok=False)
  self.assertNotEqual(result.returncode,0);self.assertEqual((self.config/'config.json').read_bytes(),before)
