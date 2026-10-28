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

    def test_standalone_checks_remain_open_and_do_not_install(self):
        code = '''install_check_engine(){ echo "CHECK $*"; }
reality_engine(){ echo "TARGET $*"; }
apt_install(){ echo UNEXPECTED_APT; }
download_binary(){ echo UNEXPECTED_DOWNLOAD; }
flock(){ :; };load_language(){ :; }
run_submenu installation_check_menu'''
        result = self.shell(code, input='1\n\n1\n\n0\n')
        for phase in ('environment', 'ports', 'download'):
            self.assertIn('--phase '+phase, result.stdout)
        self.assertIn('--target addons.mozilla.org:443 --sni addons.mozilla.org', result.stdout)
        self.assertNotIn('UNEXPECTED_', result.stdout)
        self.assertFalse((self.base/'state.json').exists())
        result = self.shell('sub_menu 1;echo "$MAIN_ACTION"', input='7\n')
        self.assertIn('install_checks', result.stdout)
