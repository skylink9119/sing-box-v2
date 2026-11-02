"""Pre-install failures stop before core downloads and preserve existing nodes."""
import json
import unittest
import test_manager as manager
import test_reliability as reliability


class InstallationCheckTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell
    configure = manager.ManagerTest.configure
    install_mocks = reliability.ReliabilityTest.install_mocks

    def test_owned_hy2_inspection_is_only_enabled_for_diagnostics(self):
        result = self.shell('install_check_engine(){ printf "%s\\n" "$*"; };install_port_check 2 443 443')
        self.assertNotIn('--managed-hy2', result.stdout)
        result = self.shell('install_check_engine(){ printf "%s\\n" "$*"; };install_port_check 2 443 443 0.0.0.0 diagnostic')
        self.assertIn('--managed-hy2', result.stdout)
        self.assertIn('--udp-port 443', result.stdout)
        self.assertFalse((self.config/'config.json').exists())
        self.assertFalse((self.base/'state.json').exists())

    def test_firewall_failure_is_not_reported_as_success(self):
        for operation in ('default deny incoming', 'default allow outgoing', '--force enable'):
            code = """need_root(){ :; };require_cmd(){ :; };confirm(){ return 0; }
detect_ssh_ports(){ SSH_PORTS=22; };firewall_allow_protocols(){ :; }
ufw(){ echo "UFW $*"; [[ $* != '"""+operation+"""' ]]; }
if firewall 2; then echo UNEXPECTED_SUCCESS; else echo EXPECTED_FAILURE; fi"""
            result = self.shell(code, input='22\n')
            self.assertIn('EXPECTED_FAILURE', result.stdout)
            self.assertNotIn('UNEXPECTED_SUCCESS', result.stdout)
            if operation != '--force enable':
                self.assertNotIn('UFW --force enable', result.stdout)
        result = self.shell('need_root(){ :; };require_cmd(){ :; };confirm(){ return 0; };ufw(){ return 7; };if firewall 3; then echo BAD; else echo FAILED; fi')
        self.assertIn('FAILED', result.stdout)
        self.assertNotIn('BAD', result.stdout)

    def test_service_and_traffic_errors_reach_menu_caller(self):
        result = self.shell('check_owned(){ :; };confirm(){ return 0; };systemctl(){ return 9; };if service_manager 2; then echo BAD; else echo FAILED; fi')
        self.assertIn('FAILED', result.stdout)
        result = self.shell('require_cmd(){ :; };vnstat(){ return 9; };if traffic 2; then echo BAD; else echo FAILED; fi')
        self.assertIn('FAILED', result.stdout)

    def test_cancelled_controls_remain_successful_noops(self):
        for action in ('firewall 3', 'service_manager 2', 'traffic 1'):
            result=self.shell('need_root(){ :; };require_cmd(){ :; };check_owned(){ :; };confirm(){ return 1; };'+action)
            self.assertEqual(result.returncode,0)

    def assert_no_node(self):
        self.assertFalse(self.bin.exists())
        self.assertFalse((self.config/'config.json').exists())
        self.assertFalse((self.base/'state.json').exists())
        self.assertFalse(list(self.base.glob('install.*')))

    def test_failed_environment_or_port_checks_stop_before_dependencies(self):
        for phase in ('environment', 'ports'):
            code = self.install_mocks()+'''install_check_engine(){
 echo "CHECK $*"
 [[ $* != *"--phase '''+phase+'''"* ]]
}
apt_install(){ echo UNEXPECTED_APT;return 1; }
download_binary(){ echo UNEXPECTED_DOWNLOAD;return 1; }
install_protocol 1'''
            result = self.shell(code, input='y\n', ok=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('UNEXPECTED_', result.stdout)
            self.assert_no_node()

    def test_dependency_failure_has_context_without_partial_node_files(self):
        code = self.install_mocks()+'''apt_install(){ echo 'E: lock-frontend held';return 100; }
download_binary(){ echo UNEXPECTED_DOWNLOAD;return 1; }
install_protocol 1'''
        result = self.shell(code, input='y\n\n\n', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Dependency installation failed before node generation', result.stderr)
        self.assertNotIn('UNEXPECTED_DOWNLOAD', result.stdout)
        self.assert_no_node()

    def test_target_or_download_failure_does_not_download_or_write_nodes(self):
        for phase in ('target', 'download'):
            code = self.install_mocks()+'''download_binary(){ echo UNEXPECTED_DOWNLOAD;return 1; }
'''+('install_reality_target(){ echo TARGET_FAILED;return 1; }\n' if phase == 'target' else
      'install_download_check(){ echo DOWNLOAD_CHECK_FAILED;return 1; }\n')+'install_protocol 1'
            result = self.shell(code, input='y\n\n\n', ok=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('TARGET_FAILED' if phase == 'target' else 'DOWNLOAD_CHECK_FAILED', result.stdout)
            self.assertNotIn('UNEXPECTED_DOWNLOAD', result.stdout)
            self.assert_no_node()

    def test_append_reality_failure_preserves_hy2_and_does_not_create_backup(self):
        self.configure('2')
        before = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.shell('reality_install_check(){ echo TARGET_FAILED;return 1; };configuration_apply add vless 24443 addons.mozilla.org', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('TARGET_FAILED', result.stdout)
        after = {str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse(list(self.backups.iterdir()))

    def test_removed_menu_keeps_automatic_checks_without_implicit_installation(self):
        code = '''install_check_engine(){ echo "CHECK $*"; }
reality_engine(){ echo "TARGET $*"; }
apt_install(){ echo UNEXPECTED_APT; }
download_binary(){ echo UNEXPECTED_DOWNLOAD; }
! declare -F installation_check_menu
install_environment_check 1
install_port_check 1 443 443
install_reality_target addons.mozilla.org
install_download_check'''
        result = self.shell(code)
        for phase in ('environment', 'ports', 'download'):
            self.assertIn('--phase '+phase, result.stdout)
        self.assertIn('--target addons.mozilla.org:443 --sni addons.mozilla.org', result.stdout)
        self.assertNotIn('UNEXPECTED_', result.stdout)
        self.assertFalse((self.base/'state.json').exists())
        result = self.shell('sub_menu 1;echo "$MAIN_ACTION"', input='7\n')
        self.assertIn('rescue', result.stdout)
        self.assertNotIn('Node installation checks (no installation)',result.stdout)
