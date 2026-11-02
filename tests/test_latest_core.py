"""Online node installation resolves stable releases without an older fallback."""
import json
import shlex
import unittest
import test_manager as manager
import test_reliability as reliability


class LatestCoreTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell

    def metadata(self, value, status=0):
        return 'curl(){ printf "%s" '+shlex.quote(json.dumps(value))+';return '+str(status)+'; };'

    def test_latest_accepts_only_explicitly_stable_numeric_release_metadata(self):
        valid = {'tag_name': 'v1.14.4', 'draft': False, 'prerelease': False}
        result = self.shell(self.metadata(valid)+'latest')
        self.assertEqual(result.stdout.strip(), '1.14.4')
        for changes in ({'draft': True}, {'prerelease': True}, {'prerelease': 'false'},
                        {'tag_name': 'v1.15.0-beta.1'}, {'tag_name': 'v1.14.4;bad'},
                        {'tag_name': None}, {'tag_name': 1144}, {'draft': None}):
            with self.subTest(changes=changes):
                result = self.shell(self.metadata({**valid, **changes})+'latest', ok=False)
                self.assertNotEqual(result.returncode, 0)
        result = self.shell(self.metadata(valid, 22)+'latest', ok=False)
        self.assertNotEqual(result.returncode, 0)

    def test_online_install_queries_official_latest_and_downloads_that_version(self):
        code = '''curl(){
 [[ ${*: -1} == https://api.github.com/repos/SagerNet/sing-box/releases/latest ]] || return 1
 printf '%s' '{"tag_name":"v1.99.2","draft":false,"prerelease":false}'
}
download_binary(){ echo "DOWNLOAD=$1:$2"; }
download_install_core "$BIN"'''
        result = self.shell(code)
        self.assertIn('DOWNLOAD=1.99.2:'+str(self.bin), result.stdout)
        self.assertNotIn('DOWNLOAD=1.14.4:', result.stdout)

    def test_online_failure_does_not_download_pinned_version(self):
        original = self.bin.read_bytes()
        for latest in ('return 1', 'echo 1.15.0-beta.1'):
            result = self.shell('latest(){ '+latest+'; };download_binary(){ echo BAD_DOWNLOAD; };download_install_core "$BIN"', ok=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('BAD_DOWNLOAD', result.stdout)
            self.assertEqual(self.bin.read_bytes(), original)

    def test_offline_install_stays_offline_and_reports_explicit_package_version(self):
        result = self.shell('SKYBYTE_ASSET_DIR=/offline;latest(){ echo BAD_LOOKUP;return 1; };download_binary(){ echo "DOWNLOAD=$1"; };download_install_core "$BIN"')
        self.assertIn('Offline install:', result.stdout)
        self.assertIn('DOWNLOAD=1.14.4', result.stdout)
        self.assertNotIn('BAD_LOOKUP', result.stdout)

    @unittest.skipUnless(manager.SB, 'official engine required')
    def test_failed_latest_lookup_leaves_no_partial_guided_node(self):
        code = reliability.ReliabilityTest.install_mocks(self)+'''latest(){ return 1; }
download_binary(){ echo BAD_DOWNLOAD; };notice(){ :; };guided_install 2'''
        result = self.shell(code, input='Latest Node\nn\nn\nn\ny\n', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('BAD_DOWNLOAD', result.stdout)
        self.assertFalse(self.bin.exists())
        self.assertFalse((self.base/'state.json').exists())
        self.assertFalse((self.config/'config.json').exists())
        self.assertFalse(list(self.base.glob('install.*')))
