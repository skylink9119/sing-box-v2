"""Drive real menu input sequences without touching host packages or services."""
import unittest
import test_manager as manager


class NavigationTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell

    def mocks(self):
        return '''need_root(){ :; };startup_info(){ :; };retire_auto_update(){ :; };users_summary(){ :; };load_language(){ :; }
held=0
flock(){ case $1 in -n) held=1;; -u) held=0;; esac; }
original_prompt_read=$(declare -f prompt_read)
eval "${original_prompt_read/prompt_read/original_read}"
prompt_read(){
 if [[ $1 == '> ' ]]; then printf 'SELECT_LOCK=%s\\n' "$held"; fi
 original_read "$@"
}
apt_install(){ echo INSTALL_UFW; }
ufw(){ echo "UFW $*"; }
detect_ssh_ports(){ SSH_PORTS=22; }
firewall_allow_protocols(){ :; }
firewall_audit(){ echo AUDIT_PARENT; }
'''

    def test_install_enable_status_and_return_one_level_in_both_languages(self):
        for language in ('zh_CN', 'en_US'):
            result = self.shell(self.mocks()+'LANGUAGE_CHOICE='+language+';main',
                                input='D\n2\n1\ny\n2\n22\ny\n4\n0\n3\n0\nq\n')
            self.assertLess(result.stdout.index('INSTALL_UFW'), result.stdout.index('UFW --force enable'))
            self.assertLess(result.stdout.index('UFW --force enable'), result.stdout.index('UFW status verbose'))
            self.assertIn('AUDIT_PARENT', result.stdout)
            self.assertNotIn('SELECT_LOCK=1', result.stdout)
            self.assertEqual(result.stdout.count('SKYBYTE Manager v'), 2)
            self.assertIn('d. ', result.stdout)
            self.assertIn('q. ', result.stdout)

    def test_failure_invalid_choice_and_cancel_keep_current_menu(self):
        code = self.mocks()+'''apt_install(){ echo INSTALL_FAILED;false;echo MUST_NOT_RUN; }
main'''
        result = self.shell(code, input='d\n2\n999\n1\ny\n3\nn\n4\n0\n0\nQ\n')
        self.assertIn('INSTALL_FAILED', result.stdout)
        self.assertNotIn('MUST_NOT_RUN', result.stdout)
        self.assertIn('Operation failed', result.stderr)
        self.assertIn('UFW status verbose', result.stdout)
        self.assertNotIn('UFW --force disable', result.stdout)
        self.assertEqual(result.stdout.count('SKYBYTE Manager v'), 2)

    def test_category_stays_open_for_multiple_operations(self):
        result = self.shell(self.mocks()+'''resource_info(){ echo RESOURCES; }
main''', input='d\n7\n3\n7\n0\nq\n')
        self.assertEqual(result.stdout.count('RESOURCES'), 2)
        self.assertIn('AUDIT_PARENT', result.stdout)
        self.assertEqual(result.stdout.count('SKYBYTE Manager v'), 2)

    def test_nested_warp_rules_return_to_warp_without_idle_lock(self):
        code = self.mocks()+'''check_owned(){ :; };warp_guard(){ :; }
warp_engine(){ echo "ENGINE $*"; }
warp_verify(){ echo VERIFIED; };warp_loopback(){ :; }
warp_dualstack(){ echo DUALSTACK; }
run_submenu warp_menu'''
        result = self.shell(code, input='6\n999\n0\n7\n0\n')
        self.assertIn('DUALSTACK', result.stdout)
        self.assertNotIn('SELECT_LOCK=1', result.stdout)
        self.assertEqual(result.stdout.count('WARP Manager'), 3)

    def test_eof_in_each_menu_exits_without_spinning(self):
        for inputs in ('', 'd\n', 'd\n2\n', 'd\n2\n4\n'):
            result = self.shell(self.mocks()+'main', input=inputs)
            self.assertLess(len(result.stdout), 15000)
            self.assertFalse(list(self.base.glob('.session.*')))

    def test_reality_checks_stay_open_after_failure_and_accept_custom_sni(self):
        for language in ('zh_CN', 'en_US'):
            code = self.mocks()+'''reality_engine(){ printf 'REALITY %s\\n' "$*";return 1; }
LANGUAGE_CHOICE='''+language+''';main'''
            result = self.shell(code, input='d\n12\n1\n2\ntarget.example:8443\nsni.example\n2\n0\n0\n0\nq\n')
            self.assertIn('--project sing-box --language '+language+' --config ', result.stdout)
            self.assertIn('--target target.example:8443 --sni sni.example', result.stdout)
            self.assertEqual(result.stdout.count('REALITY '), 2)
            self.assertEqual(result.stdout.count('SKYBYTE Manager v'), 2)
            self.assertNotIn('SELECT_LOCK=1', result.stdout)

    def test_each_main_letter_selects_its_category_and_uppercase_works(self):
        for letter, choice, expected in [('a','1','install_reality'), ('B','1','nodes'),
                                         ('c','2','logs'), ('D','7','resources'),
                                         ('e','2','backup'), ('F','4','help')]:
            code=self.mocks()+'dispatch_action(){ echo "ACTION=$1"; };main'
            result=self.shell(code,input=letter+'\n'+choice+'\n0\nq\n')
            self.assertIn('ACTION='+expected,result.stdout)
        result=self.shell(self.mocks()+'users_manager(){ echo USERS; };main',input='G\nq\n')
        self.assertIn('USERS',result.stdout)

    def test_core_version_selection_reloads_current_version_before_execution(self):
        code=self.mocks()+'''check_owned(){ :; }
BIN=fixture_core
fixture_core(){ echo 'sing-box version 1.0.0'; }
apply_update(){ echo "UPDATE=$1"; }
run_submenu core_versions'''
        result=self.shell(code,input='1\ny\n0\n')
        self.assertIn('UPDATE=1.14.3',result.stdout)

    def test_account_operations_stay_open_and_wait_without_lock(self):
        code=self.mocks()+'''check_owned(){ :; };users_guard(){ :; }
users_engine(){ echo "USERS $*"; }
resource_info(){ echo ACCOUNT_RESOURCES; }
users_manager'''
        (self.config/'config.json').write_text('{"inbounds":[{"type":"vless"}]}')
        (self.base/'users.json').write_text('{}')
        result=self.shell(code,input='3\n15\n999\n3\n0\n')
        self.assertEqual(result.stdout.count('USERS list'),2)
        self.assertIn('ACCOUNT_RESOURCES',result.stdout)
        self.assertNotIn('SELECT_LOCK=1',result.stdout)
