"""One manager, optional Xray, isolated services, automatic installation and recovery."""
import json
import os
from pathlib import Path
import shlex
import shutil
import unittest
import test_manager as manager
import test_navigation as navigation

XRAY=os.environ.get('XRAY_BIN','')
OWNER='SKYBYTE-SB-XHTTP/1\n'

class XHTTPIntegrationTests(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell
    configure=manager.ManagerTest.configure

    def core(self):
        root=self.base/'xhttp';root.mkdir(exist_ok=True);(root/'.owner').write_text(OWNER)
        lib=self.base/'xhttp-core';lib.mkdir(exist_ok=True);(lib/'.owner').write_text(OWNER)
        shutil.copyfile(XRAY,lib/'xray');(lib/'xray').chmod(0o755)
        return root

    def mocks(self,fail=False):
        return '''need_root(){ :; };apt_install(){ echo UNEXPECTED_APT;return 1; };sleep(){ :; }
flock(){ :; };ss(){ :; };install_check_engine(){ :; };reality_engine(){ :; }
systemctl(){ case $1 in is-active|is-enabled) return 1;;restart) '''+('return 1' if fail else 'return 0')+''';;*)return 0;;esac; }
curl(){ echo 8.8.8.8; }
xhttp_latest(){ echo UNEXPECTED_LOOKUP >&2;return 1; }
deployment_apply_selected(){ echo "EXTRAS=$*"; }
'''

    def test_new_menu_and_nested_navigation_stay_without_an_idle_lock(self):
        code=navigation.NavigationTests.mocks(self)+'''xhttp_command(){ echo "XHTTP=$*"; };main'''
        r=self.shell(code,input='a\n10\n6\n5\n0\n7\n1\n0\n3\n0\n0\nq\n')
        self.assertIn('XHTTP=service 5',r.stdout);self.assertIn('XHTTP=edit 1',r.stdout)
        self.assertIn('XHTTP=show',r.stdout);self.assertNotIn('SELECT_LOCK=1',r.stdout)
        self.assertFalse((self.base/'xhttp-core').exists())

    def test_guided_choices_and_cancellation_do_not_download_or_change_nodes(self):
        code='xhttp_command(){ echo "INSTALL=$* NAME=$XHTTP_NAME"; };deployment_apply_selected(){ echo "EXTRAS=$*"; };xhttp_guided_install'
        r=self.shell(code,input='My XHTTP\nn\nn\nn\ny\n')
        self.assertIn('INSTALL=guided NAME=My XHTTP',r.stdout);self.assertIn('EXTRAS=0 0 0 xhttp',r.stdout)
        r=self.shell(code,input='My XHTTP\ny\nn\ny\nn\n')
        self.assertNotIn('INSTALL=',r.stdout);self.assertFalse((self.base/'xhttp-core').exists())

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_automatic_reality_installs_without_more_prompts_and_preserves_singbox(self):
        self.configure('2');before=(self.config/'config.json').read_bytes();root=self.core()
        code=self.mocks()+'''systemctl(){ case $1 in is-active) [[ -f "$SYSTEMD_DIR/skybyte-sb-xhttp.service" ]];;is-enabled)return 1;;*)return 0;;esac; }
xhttp_guided_install xhttp-reality'''
        r=self.shell(code,input='Auto XHTTP\nn\nn\nn\ny\n')
        state=json.loads((root/'state.json').read_text());node=state['nodes']['xhttp-reality']
        self.assertEqual(node['port'],443);self.assertEqual(node['sni'],'addons.mozilla.org')
        self.assertEqual(node['address'],'8.8.8.8');self.assertTrue(node['path'].startswith('/'))
        self.assertEqual(node['name'],'Auto XHTTP');self.assertEqual(node['mode'],'auto')
        self.assertEqual((self.config/'config.json').read_bytes(),before)
        self.assertNotIn('UNEXPECTED',r.stdout+r.stderr)
        cfg=json.loads((root/'config.json').read_text());self.assertNotIn('flow',cfg['inbounds'][0]['settings']['clients'][0])
        unit=(self.root/'systemd/skybyte-sb-xhttp.service').read_text()
        self.assertIn(str(self.base/'xhttp-core/xray'),unit)
        self.assertIn('EXTRAS=0 0 0 xhttp',r.stdout)
        self.assertIn('vless://',self.shell('view_all_nodes').stdout)

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_failed_service_start_removes_new_node_config_and_preserves_other_files(self):
        root=self.core();note=root/'notes.txt';note.write_text('keep')
        r=self.shell(self.mocks(True)+'xhttp_guided_install',input='Auto XHTTP\nn\nn\nn\ny\n',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertEqual(note.read_text(),'keep')
        self.assertFalse((root/'config.json').exists());self.assertFalse((root/'state.json').exists())
        self.assertFalse((self.root/'systemd/skybyte-sb-xhttp.service').exists())
        self.assertFalse((root/'.transaction').exists())

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_stopped_singbox_tcp_port_blocks_xhttp_before_core_lookup(self):
        self.configure('1');cfg=json.loads((self.config/'config.json').read_text())
        cfg['inbounds'][0]['listen_port']=443;(self.config/'config.json').write_text(json.dumps(cfg))
        before=(self.config/'config.json').read_bytes()
        r=self.shell(self.mocks()+'xhttp_guided_install',input='Auto XHTTP\nn\nn\nn\ny\n',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertIn('TCP',r.stderr)
        self.assertNotIn('UNEXPECTED',r.stdout+r.stderr)
        self.assertFalse((self.base/'xhttp/state.json').exists())
        self.assertEqual((self.config/'config.json').read_bytes(),before)

    def test_stopped_xhttp_port_is_reserved_for_singbox_and_haproxy(self):
        root=self.base/'xhttp';root.mkdir();(root/'.owner').write_text(OWNER)
        (root/'state.json').write_text(json.dumps({'schema':1,'nodes':{'xhttp-reality':{'port':443}}}))
        r=self.shell('haproxy_engine check_port 443',ok=False)
        self.assertNotEqual(r.returncode,0)
        self.shell('haproxy_engine check_port 2053')

    def test_frontend_shell_definitions_do_not_leak(self):
        r=self.shell('before=$(declare -f say confirm load_language);xhttp_command show;after=$(declare -f say confirm load_language);[[ $before == "$after" ]];echo NAMESPACE_OK')
        self.assertIn('NAMESPACE_OK',r.stdout)

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_automatic_tls_collects_required_inputs_then_runs_without_more_prompts(self):
        root=self.core()
        code=self.mocks()+'''systemctl(){ case $1 in is-active) [[ -f "$SYSTEMD_DIR/skybyte-sb-xhttp.service" ]];;is-enabled)return 1;;*)return 0;;esac; }
export SSL_CERT_FILE='''+shlex.quote(str(self.cert))+'''
xhttp_guided_install xhttp-tls'''
        inputs='Auto TLS\nnode.example\n'+str(self.cert)+'\n'+str(self.key)+'\nn\nn\nn\nn\ny\n'
        before=self.cert.read_bytes(),self.key.read_bytes()
        r=self.shell(code,input=inputs)
        node=json.loads((root/'state.json').read_text())['nodes']['xhttp-tls']
        self.assertEqual(node['port'],2053);self.assertEqual(node['sni'],'node.example')
        self.assertEqual((self.cert.read_bytes(),self.key.read_bytes()),before)
        self.assertIn('EXTRAS=0 0 0 xhttp',r.stdout)

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_xhttp_backup_and_purge_keep_singbox_unknown_files_and_private_archive(self):
        self.configure('2');before=(self.config/'config.json').read_bytes();root=self.core()
        setup=self.mocks()+'''systemctl(){ case $1 in is-active) [[ -f "$SYSTEMD_DIR/skybyte-sb-xhttp.service" ]];;is-enabled)return 1;;*)return 0;;esac; }
xhttp_guided_install'''
        self.shell(setup,input='Auto XHTTP\nn\nn\nn\ny\n')
        note=root/'my-note.txt';note.write_text('keep')
        result=self.shell(self.mocks()+'xhttp_command purge',input='y\n')
        self.assertEqual(note.read_text(),'keep');self.assertEqual((self.config/'config.json').read_bytes(),before)
        self.assertFalse((root/'state.json').exists());self.assertFalse((self.base/'xhttp-core/xray').exists())
        archives=list((root/'backups').glob('*.tar.gz'));self.assertEqual(len(archives),1)
        self.assertEqual(archives[0].stat().st_mode&0o777,0o600)
        self.assertFalse((self.root/'systemd/skybyte-sb-xhttp.service').exists())

    def test_failed_latest_lookup_does_not_install_a_core_or_a_node(self):
        code=self.mocks()+'''apt_install(){ :; };ss(){ :; };xhttp_latest(){ return 1; };xhttp_guided_install'''
        r=self.shell(code,input='Auto XHTTP\nn\nn\nn\ny\n',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertFalse((self.base/'xhttp-core/xray').exists())
        self.assertFalse((self.base/'xhttp/state.json').exists())

    def test_xray_latest_queries_only_official_stable_metadata(self):
        code='''curl(){ [[ ${*: -1} == https://api.github.com/repos/XTLS/Xray-core/releases/latest ]] || return 1;echo '{"tag_name":"v99.1.2","draft":false,"prerelease":false}'; };xhttp_latest'''
        self.assertEqual(self.shell(code).stdout.strip(),'v99.1.2')
        self.assertNotEqual(self.shell(code.replace('"prerelease":false','"prerelease":true'),ok=False).returncode,0)

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_first_xhttp_deployment_downloads_latest_xray_without_installing_singbox(self):
        backend=manager.ROOT/'src/xhttp_backend.py'
        wrapper='''xhttp_backend(){
 if [[ $1 == download ]];then
  printf '%s\\n' "$*" > "$BASE/download.args"
  local target
  while (( $# ));do if [[ $1 == --file ]];then target=$2;break;fi;shift;done
  cp '''+shlex.quote(XRAY)+''' "$target";chmod 755 "$target"
 else SKYBYTE_SB_BASE="$BASE" SKYBYTE_SB_CONF="$CONF" python3 '''+shlex.quote(str(backend))+''' --root "$BASE/xhttp" --binary "$BASE/xhttp-core/xray" --unit "$SYSTEMD_DIR/skybyte-sb-xhttp.service" "$@";fi
}
xhttp_latest(){ echo v26.10.31; }
systemctl(){ case $1 in is-active) [[ -f "$SYSTEMD_DIR/skybyte-sb-xhttp.service" ]];;is-enabled)return 1;;*)return 0;;esac; }
xhttp_guided_install'''
        self.shell(self.mocks()+wrapper,input='First XHTTP\nn\nn\nn\ny\n')
        self.assertIn('--tag v26.10.31',(self.base/'download.args').read_text())
        self.assertTrue((self.base/'xhttp-core/xray').exists())
        self.assertFalse((self.config/'config.json').exists());self.assertFalse((self.base/'state.json').exists())

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_common_firewall_and_full_backup_include_xhttp(self):
        self.configure('2');root=self.core()
        setup=self.mocks()+'''systemctl(){ case $1 in is-active) [[ -f "$SYSTEMD_DIR/skybyte-sb-xhttp.service" ]];;is-enabled)return 1;;*)return 0;;esac; };xhttp_guided_install'''
        self.shell(setup,input='XHTTP\nn\nn\nn\ny\n')
        r=self.shell('ufw(){ echo "ALLOW=$*"; };firewall_allow_protocols')
        self.assertIn('ALLOW=allow 443/tcp',r.stdout)
        r=self.shell('systemctl(){ return 1; };backup')
        snapshot=Path(r.stdout.strip());self.assertTrue((snapshot/'xhttp.tar.gz').is_file())
        manifest=json.loads((snapshot/'backup-manifest.json').read_text())
        self.assertIn('xhttp.tar.gz',manifest['files'])

    @unittest.skipUnless(XRAY,'official Xray required')
    def test_complete_uninstall_supports_xhttp_only_and_keeps_unmanaged_binary(self):
        root=self.core()
        setup=self.mocks()+'''systemctl(){ case $1 in is-active) [[ -f "$SYSTEMD_DIR/skybyte-sb-xhttp.service" ]];;is-enabled)return 1;;*)return 0;;esac; };xhttp_guided_install'''
        self.shell(setup,input='XHTTP\nn\nn\nn\ny\n')
        self.shell(self.mocks()+'uninstall_manager',input='y\n')
        self.assertTrue(self.bin.exists());self.assertFalse((root/'state.json').exists())
        self.assertFalse((self.base/'xhttp-core/xray').exists())
        self.assertTrue(list((root/'backups').glob('*.tar.gz')))

    def test_failed_install_empty_owned_root_does_not_block_common_firewall(self):
        root=self.base/'xhttp';root.mkdir();(root/'.owner').write_text(OWNER)
        self.assertEqual(self.shell('xhttp_command ports').stdout,'')
        self.shell('ufw(){ echo BAD; };firewall_allow_protocols')

    def test_update_without_xhttp_never_downloads_or_looks_up_core(self):
        result=self.shell('xhttp_latest(){ echo BAD_LOOKUP;return 1; };xhttp_command update',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertNotIn('BAD_LOOKUP',result.stdout+result.stderr)
        self.assertFalse((self.base/'xhttp-core').exists())
