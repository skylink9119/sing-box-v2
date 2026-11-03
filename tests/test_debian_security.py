"""Exercise the interactive security updater without modifying system packages."""
from pathlib import Path
import shlex
import unittest

import test_manager as manager


class DebianSecurityTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell

    def run_update(self, answer='', scenario='pending', distro='debian', codename='trixie', ok=True):
        (self.root / 'os-release').write_text(f'ID={distro}\nVERSION_CODENAME={codename}\n')
        keyring = self.root / 'debian-archive-keyring.gpg'
        keyring.touch()
        fixture = 'need_root(){ :; }; require_cmd(){ :; };\n'
        fixture += 'keyring_fixture=' + shlex.quote(str(keyring)) + '\n'
        fixture += r"""
definition=$(declare -f debian_security_update)
eval "${definition//\/usr\/share\/keyrings\/debian-archive-keyring.gpg/$keyring_fixture}"
apt-get(){
 local IFS=" " last="${!#}" arg source='' simulation=false
 for arg in "$@"; do
  case "$arg" in
   Dir::Etc::sourcelist=*) source=${arg#*=};;
   -s) simulation=true;;
  esac
 done
 [[ -n $source && " $* " == *' Dir::Etc::sourceparts=- '* ]] || return 2
 if [[ $last == update ]]; then
  printf 'SOURCE=%s\n' "$source"
  cat "$source"
  [[ $scenario != refresh-fails ]]
 elif [[ $simulation == true ]]; then
  echo PREVIEW
  if [[ $scenario == pending ]]; then echo 'Inst openssl [old] (new Debian-Security)'; fi
 else
  [[ " $* " == *' --no-remove '* && " $* " == *' -y upgrade ' ]] || return 2
  echo APPLIED
 fi
}
"""
        return self.shell(fixture + f'\nscenario={shlex.quote(scenario)}\ndispatch_action debian_security_update',
                          input=answer, ok=ok)

    def test_menu_and_security_archive_confirmation(self):
        menu = self.shell('sub_menu 5; echo "$MAIN_ACTION"', input='8\n')
        self.assertIn('8. Debian security updates', menu.stdout)
        self.assertTrue(menu.stdout.endswith('debian_security_update\n'))
        for codename, answer in [('trixie', 'y\n'), ('bookworm', '\n')]:
            with self.subTest(codename=codename):
                result = self.run_update(answer=answer, codename=codename)
                self.assertIn(f'deb.debian.org/debian-security {codename}-security ', result.stdout)
                self.assertIn('Inst openssl', result.stdout)
                self.assertEqual('APPLIED' in result.stdout, answer == 'y\n')
                source = next(line[7:] for line in result.stdout.splitlines() if line.startswith('SOURCE='))
                self.assertFalse(Path(source).parent.exists())

    def test_empty_plan_unsupported_system_and_failed_refresh_do_not_install(self):
        result = self.run_update(answer='y\n', scenario='empty')
        self.assertIn('No security updates can be installed now', result.stdout)
        self.assertNotIn('APPLIED', result.stdout)
        result = self.run_update(answer='y\n', distro='ubuntu', codename='noble')
        self.assertNotIn('SOURCE=', result.stdout)
        result = self.run_update(answer='y\n', scenario='refresh-fails', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('PREVIEW', result.stdout)
