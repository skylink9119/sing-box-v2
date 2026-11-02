"""Collect deployment choices before mutations, then run defaults without more input."""
import json
import unittest
import test_manager as manager
import test_reliability as reliability

class WizardTests(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell
    install_mocks=reliability.ReliabilityTest.install_mocks

    def test_front_choices_reach_installer_once_with_exact_selected_flags(self):
        code='''notice(){ :; };detect_ssh_ports(){ echo SSH_PLAN; }
install_protocol(){ printf 'INSTALL=%s/%s NAME=%s BBR=%s FW=%s QR=%s\\n' "$1" "$2" "$WIZARD_NODE_NAME" "$WIZARD_BBR" "$WIZARD_FIREWALL" "$WIZARD_QR"; }
guided_install'''
        result=self.shell(code,input='2\nMy Node\ny\nn\ny\ny\n')
        self.assertIn('INSTALL=2/guided NAME=My Node BBR=1 FW=0 QR=1',result.stdout)
        self.assertEqual(result.stdout.count('INSTALL='),1)
        self.assertNotIn('SSH_PLAN',result.stdout)
        self.assertFalse((self.config/'config.json').exists())

    def test_final_cancellation_or_eof_makes_no_installation_changes(self):
        for inputs in ('Name\ny\ny\ny\nn\n','Name\ny\n'):
            result=self.shell('notice(){ :; };detect_ssh_ports(){ :; };install_protocol(){ echo BAD; };guided_install 2',input=inputs)
            self.assertNotIn('BAD',result.stdout)
            self.assertFalse((self.config/'config.json').exists())

    def test_manual_channel_keeps_custom_installation_and_existing_parameter_editing(self):
        result=self.shell('install_protocol(){ echo "MANUAL=$*"; };manual_install',input='3\n')
        self.assertIn('MANUAL=3 custom',result.stdout)
        result=self.shell('sub_menu 1;echo "$MAIN_ACTION"',input='6\n')
        self.assertTrue(result.stdout.rstrip().endswith('manual_install'))

    def test_unselected_features_do_not_install_packages_or_change_system_settings(self):
        self.shell('write_config "$CONF" "$META" 127.0.0.1 "" "" addons.mozilla.org 11111111-1111-4111-8111-111111111111 "" "" 01234567 password 127.0.0.1 1 0')
        result=self.shell('need_root(){ :; };apt_install(){ echo BAD; };deployment_bbr(){ echo BAD; };deployment_firewall(){ echo BAD; };deployment_hopping(){ echo BAD; };deployment_apply_selected 0 0 0')
        self.assertNotIn('BAD',result.stdout)
        self.assertEqual(result.stdout.count('[SKIP]'),3)

    @unittest.skipUnless(manager.SB,'official engine required')
    def test_guided_install_uses_defaults_without_additional_prompts(self):
        for mode in ('1','2','3'):
            with self.subTest(mode=mode):
                # Each mode runs in its own fixture; no real services/packages.
                fixture=manager.ManagerTest();fixture.setUp()
                try:
                    code=reliability.ReliabilityTest.install_mocks(fixture)+'''deployment_apply_selected(){ echo "APPLIED=$*"; }
notice(){ :; };guided_install '''+mode
                    result=fixture.shell(code,input='Guided Node\ny\nn\ny\ny\n')
                    state=json.loads((fixture.base/'state.json').read_text())
                    self.assertEqual(state['node_name'],'Guided Node')
                    self.assertEqual(state['mode'],mode)
                    self.assertIn('APPLIED=1 0 1',result.stdout)
                    if mode!='2':self.assertEqual(state['sni'],'addons.mozilla.org')
                    if mode!='1':self.assertEqual(state['cert_mode'],'1')
                    self.assertNotIn('optional setup is incomplete',result.stdout)
                finally:fixture.doCleanups()

    def test_manual_installation_includes_both_xhttp_variants(self):
        for selection,kind in [('4','2'),('5','3')]:
            result=self.shell('xhttp_command(){ echo "MANUAL=$*"; };manual_install',input=selection+'\n')
            self.assertIn('MANUAL=install '+kind,result.stdout)
