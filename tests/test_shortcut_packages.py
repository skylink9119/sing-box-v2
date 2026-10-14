"""Shortcut ownership and Debian APT compatibility, without host package changes."""
import os
from pathlib import Path
import shlex
import subprocess
import unittest
import test_manager as manager


class ShortcutPackagesTest(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell

    def source_files(self,version='11',legacy='',deb822=''):
        (self.root/'os-release').write_text('ID=debian\nVERSION_ID="'+version+'"\n')
        apt=self.root/'apt';apt.mkdir(exist_ok=True)
        parts=apt/'sources.list.d';parts.mkdir(exist_ok=True)
        if legacy:(apt/'sources.list').write_text(legacy)
        if deb822:(parts/'debian.sources').write_text(deb822)
        return apt

    def test_sb_opens_manager_and_preserves_sender_with_arguments(self):
        source=self.root/'source-manager'
        source.write_text('#!/usr/bin/env bash\n# SKYBYTE Manager V2.1 community manager; test fixture\nprintf "main menu\\n"\n')
        sender=self.root/'system-sb';sender.write_text('#!/usr/bin/env bash\nprintf "sender:<%s>\\n" "$@"\n');sender.chmod(0o755)
        self.shell('SCRIPT_PATH='+shlex.quote(str(source))+';manager_shortcut_install')
        command=self.root/'sb-command';installed=self.root/'manager-lib'
        self.assertEqual(command.stat().st_mode&0o777,0o755)
        self.assertEqual(installed.stat().st_mode&0o777,0o700)
        result=subprocess.run([str(command)],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout,'main menu\n')
        result=subprocess.run([str(command),'file name.txt','another'],capture_output=True,text=True,check=True)
        self.assertEqual(result.stdout,'sender:<file name.txt>\nsender:<another>\n')
        self.assertIn('sender',sender.read_text())

    def test_shortcut_does_not_replace_foreign_command_or_manager(self):
        command=self.root/'sb-command';command.write_text('foreign command')
        result=self.shell('manager_shortcut_install',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertEqual(command.read_text(),'foreign command')
        self.assertFalse((self.root/'manager-lib').exists())
        command.unlink();target=self.root/'manager-lib';target.write_text('foreign manager')
        result=self.shell('manager_shortcut_install',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertEqual(target.read_text(),'foreign manager')

    def test_shortcut_rejects_symlink_without_modifying_target(self):
        outside=self.root/'outside';outside.write_text('keep')
        (self.root/'sb-command').symlink_to(outside)
        self.assertNotEqual(self.shell('manager_shortcut_install',ok=False).returncode,0)
        self.assertEqual(outside.read_text(),'keep')

    def test_shortcut_uninstall_removes_only_owned_wrapper(self):
        self.shell('manager_shortcut_install; manager_shortcut_remove')
        self.assertFalse((self.root/'sb-command').exists())
        (self.root/'sb-command').write_text('foreign')
        self.shell('manager_shortcut_remove')
        self.assertEqual((self.root/'sb-command').read_text(),'foreign')

    def test_archive_list_preserves_options_third_party_and_comments(self):
        legacy='''# user comment
deb [arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian bullseye main contrib
deb http://security.debian.org/debian-security bullseye-security main # security
deb https://vendor.example/repo stable main
'''
        apt=self.source_files(legacy=legacy)
        self.shell('apt_prepare_archive')
        new=(apt/'sources.list').read_text()
        self.assertIn('http://archive.debian.org/debian bullseye main contrib',new)
        self.assertIn('http://archive.debian.org/debian-security bullseye-security main # security',new)
        self.assertIn('arch=amd64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg',new)
        self.assertIn('check-valid-until=no',new)
        self.assertIn('deb https://vendor.example/repo stable main\n',new)
        snapshots=list(apt.glob('skybyte-source-backup.*'))
        self.assertEqual(len(snapshots),1)
        self.assertEqual((snapshots[0]/'sources.list').read_text(),legacy)
        self.assertEqual(snapshots[0].stat().st_mode&0o777,0o700)
        self.shell('apt_prepare_archive')
        self.assertEqual(len(list(apt.glob('skybyte-source-backup.*'))),1)

    def test_archive_deb822_preserves_signed_by_and_disabled_sources(self):
        original='''Types: deb
URIs: http://deb.debian.org/debian
Suites: bullseye bullseye-updates
Components: main contrib
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: http://security.debian.org/debian-security
Suites: bullseye-security
Components: main
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg

Types: deb
URIs: https://vendor.example/repo
Suites: stable
Components: main

Types: deb
URIs: http://deb.debian.org/debian
Suites: bullseye
Components: main
Enabled: no
'''
        apt=self.source_files(deb822=original)
        self.shell('apt_prepare_archive')
        new=(apt/'sources.list.d/debian.sources').read_text()
        self.assertEqual(new.count('Check-Valid-Until: no'),2)
        self.assertIn('Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg',new)
        self.assertIn('URIs: https://vendor.example/repo',new)
        self.assertIn('URIs: http://deb.debian.org/debian\nSuites: bullseye\nComponents: main\nEnabled: no',new)
        backup=next(apt.glob('skybyte-source-backup.*'))
        self.assertEqual((backup/'parts/debian.sources').read_text(),original)

    def test_archive_does_not_modify_debian12_or_custom_mirrors(self):
        original='deb https://deb.debian.org/debian bookworm main\n'
        apt=self.source_files(version='12',legacy=original)
        self.shell('apt_prepare_archive')
        self.assertEqual((apt/'sources.list').read_text(),original)
        self.assertFalse(list(apt.glob('skybyte-source-backup.*')))
        original='deb https://my-mirror.example/debian bullseye main\n'
        (apt/'sources.list').write_text(original)
        (self.root/'os-release').write_text('ID=debian\nVERSION_ID=11\n')
        self.shell('apt_prepare_archive')
        self.assertEqual((apt/'sources.list').read_text(),original)
        self.assertFalse(list(apt.glob('skybyte-source-backup.*')))

    def test_archive_preserves_https_transport_and_signature_settings(self):
        original='deb [signed-by=/keyring.gpg] https://deb.debian.org/debian bullseye main\n'
        apt=self.source_files(legacy=original)
        self.shell('apt_prepare_archive')
        new=(apt/'sources.list').read_text()
        self.assertIn('https://archive.debian.org/debian bullseye main',new)
        self.assertIn('signed-by=/keyring.gpg',new)
        self.assertNotIn('trusted=yes',new)

    def test_archive_preserves_mixed_main_and_security_deb822_record(self):
        original='Types: deb\nURIs: http://deb.debian.org/debian http://security.debian.org/debian-security\nSuites: bullseye\nComponents: main\n'
        apt=self.source_files(deb822=original)
        self.shell('apt_prepare_archive')
        self.assertEqual((apt/'sources.list.d/debian.sources').read_text(),original)
        self.assertFalse(list(apt.glob('skybyte-source-backup.*')))

    def test_archive_rejects_symlinks_before_any_rewrite(self):
        original='deb http://deb.debian.org/debian bullseye main\n'
        apt=self.source_files(legacy=original)
        outside=self.root/'outside-source';outside.write_text('keep')
        (apt/'sources.list.d/bad.list').symlink_to(outside)
        self.assertNotEqual(self.shell('apt_prepare_archive',ok=False).returncode,0)
        self.assertEqual((apt/'sources.list').read_text(),original)
        self.assertEqual(outside.read_text(),'keep')

    def test_empty_source_directory_is_safe_with_bash_nounset(self):
        self.source_files()
        self.shell('apt_prepare_archive')

    def test_index_failure_never_attempts_package_install(self):
        self.source_files(version='12')
        result=self.shell('''apt-get(){ echo "$*" >> "$BASE/apt-events"; return 100; }; apt_install curl''',ok=False)
        self.assertNotEqual(result.returncode,0)
        events=(self.base/'apt-events').read_text()
        self.assertNotIn('install',events)
        self.assertIn('APT::Update::Error-Mode=any',events)
        self.assertIn('--allow-releaseinfo-change-suite',events)
        self.assertNotIn('--allow-unauthenticated',events)

    def test_download_404_refreshes_and_retries_once(self):
        self.source_files(version='12')
        code='''apt-get(){
 echo "$*" >> "$BASE/apt-events"
 if [[ $1 == install && ! -e $BASE/once ]];then touch "$BASE/once";echo "Failed to fetch package 404 Not Found";return 100;fi
};apt_install curl openssl'''
        self.shell(code)
        events=(self.base/'apt-events').read_text().splitlines()
        self.assertEqual(sum('install -y curl openssl' in x for x in events),2)
        self.assertEqual(sum(' update' in x for x in events),2)
        self.assertIn('Acquire::http::No-Cache=true',events[-1])
        self.assertIn('Acquire::https::No-Cache=true',events[-1])
        self.assertNotIn('Verify-Peer=false','\n'.join(events))

    def test_non_download_install_failure_is_not_retried(self):
        self.source_files(version='12')
        code='''apt-get(){ echo "$*" >> "$BASE/apt-events";if [[ $1 == install ]];then echo "dpkg error";return 100;fi;};apt_install curl'''
        self.assertNotEqual(self.shell(code,ok=False).returncode,0)
        self.assertEqual(sum('install -y' in x for x in (self.base/'apt-events').read_text().splitlines()),1)


if __name__=='__main__':unittest.main()
