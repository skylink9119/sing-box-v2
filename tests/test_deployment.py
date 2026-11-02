"""Automatic setup preserves nodes and never enables UFW before SSH/node allows."""
import importlib.util
import json
from pathlib import Path
import unittest
import test_manager as manager

spec=importlib.util.spec_from_file_location('deployment_checks',manager.ROOT/'src/deployment_checks.py')
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)

class FirewallGateTests(unittest.TestCase):
    def test_empty_accept_only_rules_are_allowed_but_unknown_state_is_refused(self):
        self.assertTrue(gate.nft_clean(json.dumps({'nftables':[{'metainfo':{}},{'table':{'family':'ip','name':'filter'}},{'chain':{'policy':'accept'}}]})))
        for value in [{'rule':{}},{'set':{}},{'chain':{'policy':'drop'}},{'unknown':{}}]:
            self.assertFalse(gate.nft_clean(json.dumps({'nftables':[value]})))
        self.assertFalse(gate.nft_clean('{}'))
        self.assertTrue(gate.iptables_clean('*filter\n:INPUT ACCEPT [0:0]\nCOMMIT\n'))
        for text in (':INPUT DROP [0:0]','-A INPUT -j ACCEPT',':DOCKER - [0:0]'):
            self.assertFalse(gate.iptables_clean(text))

class DeploymentTests(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell
    configure=manager.ManagerTest.configure

    def firewall_mocks(self):
        self.configure('3')
        defaults=self.root/'ufw-defaults';defaults.write_text('IPV6=yes\n')
        return '''need_root(){ :; };detect_ssh_ports(){ SSH_PORTS=2222; }
UFW_DEFAULTS='''+str(defaults)+'''
ACTIVE=false
ufw(){ echo "UFW $*" >&2;case $* in status) if [[ $ACTIVE == true ]];then echo 'Status: active';else echo 'Status: inactive';fi;; '--force enable') ACTIVE=true;; esac; }
deployment_firewall_gate(){ :; }
ss(){ printf '%s\\n' 'tcp LISTEN 0 128 0.0.0.0:2222 0.0.0.0:*' 'tcp LISTEN 0 128 0.0.0.0:443 0.0.0.0:*' 'udp UNCONN 0 0 0.0.0.0:443 0.0.0.0:*'; }
'''

    def test_ssh_and_actual_protocol_ports_are_allowed_before_enable(self):
        result=self.shell(self.firewall_mocks()+'deployment_firewall')
        for rule in ('2222/tcp','443/tcp','443/udp'):
            self.assertLess(result.stderr.index('UFW allow '+rule),result.stderr.index('UFW --force enable'))

    def test_failed_ssh_rule_unknown_port_or_conflicting_rules_never_enable(self):
        for code in [
            'ufw(){ [[ $1 != allow ]] || return 9;echo "UFW $*" >&2;[[ $1 != status ]] || echo "Status: inactive"; };',
            'detect_ssh_ports(){ SSH_PORTS=""; };',
            'deployment_firewall_gate(){ return 1; };',
            'ss(){ echo "udp UNCONN 0 0 0.0.0.0:2222 0.0.0.0:*"; };',
        ]:
            result=self.shell(self.firewall_mocks()+code+'deployment_firewall',ok=False)
            self.assertNotEqual(result.returncode,0)
            self.assertNotIn('UFW --force enable',result.stderr)

    def test_active_ufw_retains_policies_and_only_adds_allowed_ports(self):
        result=self.shell(self.firewall_mocks()+'ACTIVE=true;deployment_firewall_gate(){ echo BAD;return 1; };deployment_firewall')
        self.assertNotIn('BAD',result.stdout)
        self.assertNotIn('UFW default',result.stderr)
        self.assertNotIn('UFW --force enable',result.stderr)

    def test_cancellation_does_not_run_setup_operations(self):
        result=self.shell('need_root(){ :; };check_owned(){ :; };detect_ssh_ports(){ SSH_PORTS=2222; };confirm(){ return 1; };apt_install(){ echo BAD; };deployment_bbr(){ echo BAD; };deployment_firewall(){ echo BAD; };automatic_setup')
        self.assertNotIn('BAD',result.stdout)

    def test_partial_setup_failure_is_reported_and_node_configuration_is_kept(self):
        self.configure('2');before=(self.config/'config.json').read_bytes()
        result=self.shell('need_root(){ :; };detect_ssh_ports(){ SSH_PORTS=2222; };confirm(){ return 0; };qrencode(){ :; };ufw(){ :; };deployment_bbr(){ return 1; };deployment_firewall(){ return 1; };automatic_setup',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('[PASS] qrencode',result.stdout)
        self.assertIn('[INCOMPLETE] BBR',result.stderr)
        self.assertIn('[INCOMPLETE] Firewall',result.stderr)
        self.assertEqual(before,(self.config/'config.json').read_bytes())

    def test_hy2_automatic_hopping_uses_actual_listener_and_refreshes_exports(self):
        self.configure('2')
        result=self.shell("""nft(){ [[ $1 != list ]]; };iptables(){ return 1; };systemctl(){ :; }
ss(){ echo 'udp UNCONN 0 0 0.0.0.0:443 0.0.0.0:*'; }
exports(){ echo EXPORT_REFRESHED; }
deployment_hopping""")
        state=json.loads((self.base/'state.json').read_text())
        self.assertTrue(state['hop']);self.assertEqual((state['hop_start'],state['hop_end'],state['hop_target']),(20000,30000,443))
        self.assertIn('redirect to :443',(self.base/'hop.nft').read_text())
        self.assertIn('EXPORT_REFRESHED',result.stdout)

    def test_hopping_conflict_or_ipv6_keeps_existing_configuration(self):
        self.configure('2');before=(self.base/'state.json').read_bytes()
        result=self.shell("ss(){ echo 'udp UNCONN 0 0 0.0.0.0:24443 0.0.0.0:*'; };hop(){ echo BAD; };deployment_hopping",ok=False)
        self.assertNotEqual(result.returncode,0);self.assertNotIn('BAD',result.stdout)
        self.assertEqual(before,(self.base/'state.json').read_bytes())
        result=self.shell("state(){ [[ $1 != ip ]] || echo 2606:4700::1; };hop(){ echo BAD; };deployment_hopping",ok=False)
        self.assertEqual(result.returncode,2);self.assertIn('[SKIP]',result.stdout);self.assertNotIn('BAD',result.stdout)

    def test_existing_hopping_range_is_not_replaced(self):
        self.configure('2');p=self.base/'state.json';state=json.loads(p.read_text());state.update(hop=True,hop_start=31000,hop_end=32000);p.write_text(json.dumps(state))
        result=self.shell('hop_guard(){ :; };systemctl(){ :; };hop(){ echo BAD; };deployment_hopping')
        self.assertIn('range retained',result.stdout);self.assertNotIn('BAD',result.stdout)
        self.assertEqual(json.loads(p.read_text())['hop_start'],31000)

    def test_bbr_failure_restores_values_and_does_not_overwrite_external_file(self):
        result=self.shell('sysctl(){ if [[ $1 == -n ]];then echo cubic;else echo "RESTORE $*";fi; };bbr_apply(){ return 1; };deployment_bbr',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('RESTORE -w net.ipv4.tcp_congestion_control=cubic',result.stdout)
        (self.root/'bbr.conf').write_text('external config\n')
        result=self.shell('bbr_apply(){ echo BAD; };deployment_bbr',ok=False)
        self.assertNotIn('BAD',result.stdout)
        self.assertEqual((self.root/'bbr.conf').read_text(),'external config\n')

    def test_bundle_uses_one_confirmation_and_hopping_follows_firewall(self):
        self.configure('2')
        result=self.shell('''need_root(){ :; };detect_ssh_ports(){ SSH_PORTS=2222; }
confirm(){ echo CONFIRMED;return 0; };qrencode(){ :; };ufw(){ :; }
deployment_bbr(){ echo BBR; };deployment_firewall(){ echo FIREWALL; }
deployment_hopping(){ echo HOPPING; };automatic_setup''')
        self.assertEqual(result.stdout.count('CONFIRMED'),1)
        self.assertLess(result.stdout.index('FIREWALL'),result.stdout.index('HOPPING'))
