"""Fresh IPv6 installation uses the normal transaction and never queries IPv4 IP services."""
import json,shlex,subprocess,unittest,urllib.parse
import test_manager as manager
import test_reliability as reliability
import test_navigation as navigation
PUBLIC='2001:4860:4860::8888'

class IPv6InstallTests(unittest.TestCase):
 setUp=manager.ManagerTest.setUp
 script=manager.ManagerTest.script
 shell=manager.ManagerTest.shell
 configure=manager.ManagerTest.configure
 install_mocks=reliability.ReliabilityTest.install_mocks
 def network(self,fail=''):
  return '''ip(){ :; }
ipv6_engine(){
 case $1 in
  detect) printf '%s\\n' '''+shlex.quote(PUBLIC)+''';;
  check-install) echo "IPV6_CHECK $2" >&2;[[ $2 == '''+shlex.quote(PUBLIC)+''' && '''+shlex.quote(fail)+''' != check ]];;
  ready) echo IPV6_READY;[[ '''+shlex.quote(fail)+''' != ready ]];;
  *)return 1;;
 esac
}
curl(){ echo UNEXPECTED_IP_QUERY >&2;return 1; }
'''
 def test_install_menu_routes_and_remains_in_child_menu(self):
  code=navigation.NavigationTests.mocks(self)+'''install_protocol(){ echo "INSTALL $*"; }
main'''
  for lang in ('zh_CN','en_US'):
   r=self.shell('LANGUAGE_CHOICE='+lang+';'+code,input='a\n8\n2\n1\n0\n0\nq\n')
   self.assertIn('INSTALL 2 ipv6',r.stdout);self.assertIn('INSTALL 1 ipv6',r.stdout)
   self.assertNotIn('SELECT_LOCK=1',r.stdout)
   self.assertEqual(r.stdout.count('SKYBYTE Manager v'),2)
 def test_cancel_or_invalid_address_stops_before_installation(self):
  for selected,fail in [('0',''),('','check'),('8.8.8.8','')]:
   r=self.shell(self.install_mocks()+self.network(fail)+'apt_install(){ echo UNEXPECTED_APT; };install_protocol 2 ipv6',input='y\n'+selected+'\n',ok=False)
   self.assertEqual(r.returncode==0,selected=='0',r.stderr+r.stdout)
   self.assertNotIn('UNEXPECTED_',r.stdout+r.stderr)
   self.assertFalse(self.bin.exists());self.assertFalse((self.base/'state.json').exists())
 def test_existing_installation_is_preserved_and_points_to_backup_menu(self):
  self.configure('3');before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  r=self.shell('need_root(){ :; };install_protocol 2 ipv6',input='y\n',ok=False)
  self.assertNotEqual(r.returncode,0);self.assertIn('d → 13 → 2',r.stderr)
  self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
 def install(self,mode,fail='',extra=''):
  tcp=manager.port();udp=manager.port()
  inputs='y\n\n'+(str(tcp)+'\n' if mode!='2' else '')+(str(udp)+'\n' if mode!='1' else '')+'\n'+('1\n' if mode!='1' else '')+('\n' if mode!='2' else '')
  r=self.shell(self.install_mocks()+self.network(fail)+extra+'install_protocol '+mode+' ipv6',input=inputs,ok=not(fail or extra))
  self.assertNotIn('UNEXPECTED_IP_QUERY',r.stdout+r.stderr)
  return r,tcp,udp
 def assert_installed(self,mode):
  r,tcp,udp=self.install(mode)
  state=json.loads((self.base/'state.json').read_text());cfg=json.loads((self.config/'config.json').read_text())
  self.assertEqual(state['ip'],PUBLIC);self.assertNotIn('ipv6_backup',state)
  self.assertTrue(state['node_name'].endswith('-IPv6'));self.assertEqual(state['listen'],'::')
  self.assertIn('IPV6_READY',r.stdout)
  for node in cfg['inbounds']:
   self.assertEqual(node['listen'],'::')
   self.assertEqual(node['listen_port'],tcp if node['type']=='vless' else udp)
  links=(self.base/'nodes.txt').read_text().splitlines()
  self.assertTrue(all(urllib.parse.urlsplit(link).hostname==PUBLIC for link in links))
  if mode!='1':
   details=subprocess.check_output([manager.OPENSSL,'x509','-in',str(self.config/'hy2-selfsigned.crt'),'-noout','-ext','subjectAltName'],text=True)
   self.assertIn('2001:4860:4860:0:0:0:0:8888',details)
 @unittest.skipUnless(manager.SB,'Real sing-box required')
 def test_new_hy2_ipv6_and_verified_certificate(self):self.assert_installed('2')
 @unittest.skipUnless(manager.SB,'Real sing-box required')
 def test_new_reality_ipv6(self):self.assert_installed('1')
 @unittest.skipUnless(manager.SB,'Real sing-box required')
 def test_new_dual_protocol_ipv6(self):self.assert_installed('3')
 @unittest.skipUnless(manager.SB,'Real sing-box required')
 def test_failed_ipv6_readiness_removes_only_created_node_files(self):
  note=self.config/'keep.txt';note.write_text('keep')
  r,_,_=self.install('2','ready')
  self.assertNotEqual(r.returncode,0);self.assertEqual(note.read_text(),'keep')
  self.assertFalse(self.bin.exists());self.assertFalse((self.base/'state.json').exists());self.assertFalse((self.config/'config.json').exists())
  self.assertFalse(list(self.base.glob('install.*')))
 @unittest.skipUnless(manager.SB,'Real sing-box required')
 def test_firewall_failure_stops_before_commit(self):
  r,_,_=self.install('2',extra='ufw(){ [[ $1 != allow ]] || return 1;printf "Status: active\\n"; };')
  self.assertNotEqual(r.returncode,0);self.assertFalse(self.bin.exists());self.assertFalse((self.base/'state.json').exists())
 def test_missing_iproute2_is_installed_without_polluting_selected_address(self):
  code='''command(){ if [[ ${1:-} == -v && ${2:-} == ip ]];then declare -F ip >/dev/null;else builtin command "$@";fi; }
apt_install(){ echo INSTALLED_IPROUTE2 >&2;ip(){ :; }; }
ipv6_engine(){ case $1 in detect)echo '''+shlex.quote(PUBLIC)+''';;check-install)echo FIREWALL_NOTE;;esac; }
ipv6_install_address'''
  r=self.shell(code,input='\n');self.assertEqual(r.stdout.strip(),PUBLIC)
  self.assertIn('INSTALLED_IPROUTE2',r.stderr);self.assertIn('FIREWALL_NOTE',r.stderr)
