"""Run the pasteable curl bootstrap with isolated download/package simulators."""
import os
from pathlib import Path
import shlex
import subprocess
import shutil
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get('BASH_BIN', 'bash')


class CurlBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.staging = self.root/'staging'; self.staging.mkdir()
        self.log = self.root/'events'

    def run_case(self, present=False, failure='', uid='0', distribution='debian', dependencies=False, quickstart=False):
        available = self.root/'curl-present'
        available.unlink(missing_ok=True); self.log.unlink(missing_ok=True)
        if present: available.touch()
        release = self.root/'os-release'; release.write_text('ID='+distribution+'\n')
        definitions = r'''
id(){ [[ ${1:-} == -u ]] && printf '%s\n' "$TEST_UID"; }
command(){
 if [[ ${1:-} == -v ]];then
  case ${2:-} in curl) [[ -f $TEST_ROOT/curl-present ]];return;; flock|python3) return 0;; esac
 fi
 builtin command "$@"
}
apt-get(){
 printf 'apt:%s\n' "$*" >> "$TEST_ROOT/events"
 if [[ ${*: -1} == update ]];then [[ $TEST_FAILURE != update ]];return;fi
 if [[ ${1:-} == install ]];then
  [[ $TEST_FAILURE != install ]] || return 100
  [[ $TEST_FAILURE == unavailable ]] || : > "$TEST_ROOT/curl-present"
  return 0
 fi
 return 1
}
apt_install(){
 printf 'packages:%s\n' "$*" >> "$TEST_ROOT/events"
 [[ $TEST_FAILURE != install ]] || return 100
 [[ $TEST_FAILURE == unavailable ]] || : > "$TEST_ROOT/curl-present"
}
curl(){
 printf 'download:%s\n' "$*" >> "$TEST_ROOT/events"
 [[ -f $TEST_ROOT/curl-present ]] || return 127
 local output=''
 while (($#));do if [[ $1 == -o ]];then output=$2;shift 2;else shift;fi;done
 if [[ -z $output ]];then
  [[ $TEST_FAILURE != empty ]] || return 0
  printf '%s\n' 'IFS= read -r answer || exit 1' 'printf "stdin:%s\n" "$answer" >> "$TEST_ROOT/events"'
  [[ $TEST_FAILURE != download ]];return
 fi
 case $TEST_FAILURE in
  empty) : > "$output";;
  syntax) printf '#!/usr/bin/env bash\nif ((\n' > "$output";;
  html) printf '<html>upstream error</html>\n' > "$output";;
  *) printf '#!/usr/bin/env bash\n# downloaded fixture\n' > "$output";;
 esac
 [[ $TEST_FAILURE != download ]]
}
bash(){
 if [[ $1 == -n ]];then "$TEST_BASH" "$@" || return $?;return 0;fi
 if [[ $1 == -c ]];then
  printf 'launch\n' >> "$TEST_ROOT/events"
  "$TEST_BASH" "$@";return
 fi
 [[ -f $1 ]] || return 1
 printf 'launch\n' >> "$TEST_ROOT/events"
 local answer
 IFS= read -r answer || return 1
 printf 'stdin:%s\n' "$answer" >> "$TEST_ROOT/events"
}
'''
        source = ''
        if dependencies:
            source = 'source '+shlex.quote(str(ROOT/'install.sh'))+'\n'
            action = 'installer_dependencies'
        else:
            action = (ROOT/'src/quickstart.sh' if quickstart else ROOT/'bootstrap.sh').read_text()
        result = subprocess.run([BASH, '-c', source+definitions+'\n'+action],
            input='menu input preserved\n', capture_output=True, text=True, timeout=10, cwd=self.root,
            env={**os.environ, 'TEST_ROOT':str(self.root), 'TEST_FAILURE':failure, 'TEST_UID':uid,
                 'OS_RELEASE':str(release), 'TMPDIR':str(self.staging), 'NO_COLOR':'1', 'TEST_BASH':shutil.which(BASH)})
        events = self.log.read_text().splitlines() if self.log.exists() else []
        self.assertEqual(list(self.staging.iterdir()), [], 'Temporary installer must be cleaned up')
        return result, events

    def test_empty_html_and_malformed_installers_are_never_launched(self):
        for failure in ('empty', 'html', 'syntax'):
            with self.subTest(failure=failure):
                result, events = self.run_case(present=True, failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid installer download', result.stderr)
                self.assertFalse(any(event == 'launch' for event in events))

    def test_existing_curl_skips_apt_and_preserves_interactive_input(self):
        result, events = self.run_case(present=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(event.startswith('apt:') for event in events))
        self.assertEqual(events[-2:], ['launch', 'stdin:menu input preserved'])
        download = events[0]
        self.assertIn("--proto =https --proto-redir =https", download)
        self.assertIn('https://github.com/skylink9119/sing-box-v2/releases/download/v2.8.16/install.sh', download)
        self.assertNotIn(' -k ', download)

    def test_missing_curl_is_installed_before_download_on_supported_systems(self):
        for distribution in ['debian', 'ubuntu']:
            with self.subTest(distribution=distribution):
                result, events = self.run_case(distribution=distribution)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('curl not found', result.stdout)
                self.assertTrue(events[0].endswith(' update'))
                self.assertIn('APT::Update::Error-Mode=any', events[0])
                self.assertEqual(events[1], 'apt:install -y curl ca-certificates')
                self.assertTrue(events[2].startswith('download:'))
                self.assertEqual(events[-2:], ['launch', 'stdin:menu input preserved'])

    def test_apt_index_failure_stops_before_install_download_or_launch(self):
        result, events = self.run_case(failure='update')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('APT refresh failed', result.stderr)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].endswith(' update'))

    def test_package_failure_stops_before_download_or_launch(self):
        result, events = self.run_case(failure='install')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('curl installation failed', result.stderr)
        self.assertEqual(len(events), 2)
        self.assertFalse(any(event.startswith('download:') or event == 'launch' for event in events))

    def test_curl_presence_is_rechecked_after_package_installation(self):
        result, events = self.run_case(failure='unavailable')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('curl is still unavailable', result.stderr)
        self.assertEqual(len(events), 2)

    def test_failed_download_does_not_run_or_overwrite_an_old_installer(self):
        old = self.root/'install.sh'; old.write_text('keep existing file\n')
        result, events = self.run_case(present=True, failure='download')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(old.read_text(), 'keep existing file\n')
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith('download:'))

    def test_non_root_or_unsupported_system_stops_before_changes(self):
        for uid, distribution, message in [('1000', 'debian', 'Please run as root'), ('0', 'fedora', 'Ubuntu/Debian only')]:
            with self.subTest(uid=uid, distribution=distribution):
                result, events = self.run_case(uid=uid, distribution=distribution)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(events, [])

    def test_installer_with_existing_tools_skips_package_operations(self):
        result, events = self.run_case(present=True, dependencies=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, [])

    def test_installer_with_missing_curl_reports_and_installs_dependencies(self):
        result, events = self.run_case(dependencies=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Missing tools: curl', result.stderr)
        self.assertEqual(events, ['packages:curl ca-certificates python3 util-linux'])

    def test_installer_stops_when_packages_fail_or_curl_remains_unavailable(self):
        for failure in ['install', 'unavailable']:
            with self.subTest(failure=failure):
                result, events = self.run_case(failure=failure, dependencies=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(events, ['packages:curl ca-certificates python3 util-linux'])

    def test_empty_bootstrap_is_not_executed(self):
        result, events = self.run_case(present=True, failure='empty', quickstart=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(events), 1)
        self.assertFalse(any(event == 'launch' for event in events))

    def test_compact_command_with_curl_preserves_input_without_apt(self):
        result, events = self.run_case(present=True, quickstart=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events[-2:], ['launch', 'stdin:menu input preserved'])
        self.assertEqual(len(events), 3)
        self.assertIn('https://sky9119.cc/sb.sh', events[0])

    def test_compact_command_installs_curl_before_fetching_bootstrap(self):
        result, events = self.run_case(quickstart=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events[:2], ['apt:update', 'apt:install -y curl ca-certificates'])
        self.assertTrue(events[2].startswith('download:'))
        self.assertEqual(events[-2:], ['launch', 'stdin:menu input preserved'])

    def test_compact_command_stops_on_apt_failure(self):
        for failure in ['update', 'install']:
            with self.subTest(failure=failure):
                result, events = self.run_case(failure=failure, quickstart=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(all(event.startswith('apt:') for event in events))

    def test_compact_command_does_not_execute_partial_failed_download(self):
        result, events = self.run_case(present=True, failure='download', quickstart=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith('download:'))



class PinnedInstallerTest(unittest.TestCase):
    def run_install(self, failure='', installed=''):
        import hashlib
        import re
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve()
            version=re.search(r'^MANAGER_VERSION=(.+)$',(ROOT/'src/manager.sh').read_text(),re.M)[1]
            marker='# SKYBYTE Manager V2.1 community manager; fixture\n'
            payload='#!/usr/bin/env bash\n'+marker+'MANAGER_VERSION='+version+'\necho SELF_CHECK >> "$TEST_ROOT/events"\nprintf "%s\\n" "$MANAGER_VERSION"\n'
            if failure=='version':payload=payload.replace('MANAGER_VERSION='+version,'MANAGER_VERSION=0.0.1')
            if failure=='syntax':payload+='if ((\n'
            source=root/'payload';source.write_text(payload)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            manifest=digest+'  singbox-v2.sh\n'
            if failure=='checksum':manifest='0'*64+'  singbox-v2.sh\n'
            if failure=='duplicate':manifest+=manifest
            (root/'manifest').write_text(manifest)
            target=root/'lib/singbox-v2.sh';target.parent.mkdir()
            previous=''
            if installed:
                previous='#!/usr/bin/env bash\n'+marker+'MANAGER_VERSION='+installed+'\n'
                target.write_text(previous)
            code=r'''source "$1"
MANAGER_DIR=$TEST_ROOT/lib
MANAGER_TARGET=$MANAGER_DIR/singbox-v2.sh
MANAGER_LOCK=$TEST_ROOT/lock
installer_root(){ :; }
installer_dependencies(){ :; }
flock(){ :; }
installer_launch(){ echo LAUNCH >> "$TEST_ROOT/events"; }
curl(){
 local output='' url=''
 while (($#));do
  case $1 in -o) output=$2;shift 2;; https://*) url=$1;shift;; *) shift;; esac
 done
 printf '%s\n' "$url" >> "$TEST_ROOT/urls"
 case $url in */SHA256SUMS) cp "$TEST_ROOT/manifest" "$output";; *) cp "$TEST_ROOT/payload" "$output";; esac
}
install_manager
'''
            result=subprocess.run([BASH,'-c',code,'test',str(ROOT/'install.sh')],capture_output=True,text=True,
                                  env={**os.environ,'TEST_ROOT':str(root)},timeout=10)
            events=(root/'events').read_text() if (root/'events').exists() else ''
            contents=target.read_text() if target.exists() else ''
            self.assertFalse(list(target.parent.glob('.install.*')))
            urls=(root/'urls').read_text().splitlines()
            self.assertTrue(all('/releases/download/v'+version+'/' in u for u in urls))
            return result,events,contents,previous

    def test_verified_pinned_install_and_same_version_reinstall(self):
        import re
        version=re.search(r'^MANAGER_VERSION=(.+)$',(ROOT/'src/manager.sh').read_text(),re.M)[1]
        for installed in ('', '2.0.0', version):
            result,events,contents,_=self.run_install(installed=installed)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('LAUNCH',events)
            self.assertIn('MANAGER_VERSION='+version,contents)

    def test_corrupt_ambiguous_wrong_version_or_invalid_payload_keeps_old_manager(self):
        for failure in ('checksum','duplicate','version','syntax'):
            result,events,contents,previous=self.run_install(failure,installed='2.0.0')
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(events,'')
            self.assertEqual(contents,previous)

    def test_old_installer_cannot_downgrade_newer_or_unidentified_manager(self):
        for installed in ('99.0.0','unknown'):
            result,events,contents,previous=self.run_install(installed=installed)
            self.assertNotEqual(result.returncode,0)
            self.assertEqual(events,'')
            self.assertEqual(contents,previous)


if __name__ == '__main__':
    unittest.main()
