"""Check native address filtering, port conflicts, dual-stack readiness and no network mutations."""
import importlib.util,json,pathlib,socket,subprocess,unittest
from unittest import mock
spec=importlib.util.spec_from_file_location('ipv6_checks',pathlib.Path(__file__).resolve().parents[1]/'src/ipv6.py')
v6=importlib.util.module_from_spec(spec);spec.loader.exec_module(v6)
PUBLIC='2001:4860:4860::8888'
class NativeIPv6Tests(unittest.TestCase):
 def test_reject_private_mapped_multicast_and_malformed_addresses(self):
  self.assertEqual(v6.public_ipv6(PUBLIC),PUBLIC)
  for value in ('::1','fe80::1','fd00::1','::ffff:8.8.8.8','ff0e::1','[2001:4860::1]','2001:db8::1','2001:4860::1%eth0','8.8.8.8'):
   with self.subTest(value=value),self.assertRaises(ValueError):v6.public_ipv6(value)
 def test_detect_only_ready_stable_public_addresses(self):
  items=[{'family':'inet6','scope':'global','local':PUBLIC},
         {'family':'inet6','scope':'global','local':'2001:4860::1','flags':['tentative']},
         {'family':'inet6','scope':'global','local':'2001:4860::2','temporary':True},
         {'family':'inet6','scope':'global','local':'2001:4860::3','preferred_life_time':0},
         {'family':'inet6','scope':'global','local':'fd00::1'}]
  data=[{'flags':['UP'],'addr_info':items},{'flags':[],'addr_info':[{'family':'inet6','scope':'global','local':'2001:4860::4'}]}]
  with mock.patch.object(v6.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(data))):
   self.assertEqual(v6.ipv6_candidates(),[PUBLIC])
 def test_local_check_rejects_unassigned_address_without_routing_changes(self):
  with mock.patch.object(v6,'ipv6_candidates',return_value=[]),mock.patch.object(v6.subprocess,'run') as run:
   with self.assertRaises(ValueError):v6.ipv6_local(PUBLIC)
   run.assert_not_called()
 def test_ipv6_port_collision_is_detected_while_ipv4_service_stays_up(self):
  try:listener=socket.socket(socket.AF_INET6);listener.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1);listener.bind(('::',0));listener.listen()
  except OSError as error:self.skipTest(str(error))
  with listener:
   with self.assertRaises(OSError):v6.ipv6_bind_check([{'listen':'0.0.0.0','port':listener.getsockname()[1],'protocol':'tcp'}])
  with socket.socket() as ipv4:
   ipv4.bind(('0.0.0.0',0));ipv4.listen()
   v6.ipv6_bind_check([{'listen':'0.0.0.0','port':ipv4.getsockname()[1],'protocol':'tcp'}])
   with socket.create_connection(("127.0.0.1",ipv4.getsockname()[1]),timeout=1):pass
 def test_real_dual_stack_tcp_readiness(self):
  try:listener=socket.socket(socket.AF_INET6);listener.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0);listener.bind(('::',0));listener.listen()
  except OSError as error:self.skipTest(str(error))
  with listener:v6.ipv6_ready([{'port':listener.getsockname()[1],'protocol':'tcp'}])
 def test_loopback_and_ipv6_only_are_not_exposed(self):
  for item in ({'listen':'127.0.0.1'},{'listen':'::','ipv6_only':True}):
   with self.assertRaises(ValueError):v6.ipv6_bind_check([dict(port=443,protocol='tcp',**item)])
 def test_ufw_active_without_ipv6_fails_before_enable(self):
  with mock.patch('shutil.which',return_value='/usr/sbin/ufw'),mock.patch.object(v6.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'Status: active')),mock.patch.object(pathlib.Path,'read_text',return_value='IPV6=no\n'):
   with self.assertRaisesRegex(ValueError,'IPV6=yes'):v6.ipv6_firewall()

 def test_warp_wireguard_and_tun_egress_addresses_are_not_backup_candidates(self):
  address={'family':'inet6','scope':'global','local':PUBLIC}
  for kind,link_type in (('wireguard','none'),('tun','none'),('tun','ether'),('sit','sit')):
   data=[{'flags':['UP'],'link_type':link_type,'linkinfo':{'info_kind':kind},'addr_info':[address]},
         {'flags':['UP'],'link_type':'ether','addr_info':[dict(address,local='2606:4700:4700::1111')]}]
   with self.subTest(kind=kind,link_type=link_type),mock.patch.object(v6.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(data))):
    self.assertEqual(v6.ipv6_candidates(),['2606:4700:4700::1111'])
