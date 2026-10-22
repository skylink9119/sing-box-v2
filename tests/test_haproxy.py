"""TCP relay ownership/rollback and real transparent TLS/Reality/Trojan forwarding."""
import copy
import grp
import json
import os
from pathlib import Path
import pwd
import shlex
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

import test_manager as manager
import test_network_features as network
import test_relay as relay_tests

hp = network.module('haproxy')
REAL = os.environ.get('HAPROXY_BIN') or shutil.which('haproxy')


class HAProxyTest(unittest.TestCase):
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell
    configure = manager.ManagerTest.configure
    user_setup = manager.ManagerTest.user_setup
    user_db = manager.ManagerTest.user_db
    prepare_uninstall = manager.ManagerTest.prepare_uninstall
    start_engine = network.FeaturesTest.start_engine
    http_fixture = network.FeaturesTest.http_fixture
    request = network.FeaturesTest.request
    profile = relay_tests.RelayTest.profile
    landing = relay_tests.RelayTest.landing
    udp_roundtrip = relay_tests.RelayTest.udp_roundtrip

    def setUp(self):
        manager.ManagerTest.setUp(self)
        self.checker = self.root / 'haproxy-checker'
        self.checker.write_text('#!/bin/sh\nexit 0\n'); self.checker.chmod(0o700)
        self.proxy = hp.Relay(self.base, self.root / 'systemd', self.checker, self.config / 'config.json')
        self.active = self.enabled = False
        self.calls = []
        self.fail_restart = False
        def ctl(*args, check=True):
            self.calls.append(args)
            if args[0] == 'is-active': code = 0 if self.active else 3
            elif args[0] == 'is-enabled': code = 0 if self.enabled else 1
            else:
                code = 0
                if args[0] == 'restart':
                    if self.fail_restart:
                        self.fail_restart = False
                        raise subprocess.CalledProcessError(1, ['systemctl', *args])
                    self.active = True
                if args[0] == 'enable': self.enabled = True
                if args[0] == 'disable':
                    self.enabled = False
                    if '--now' in args: self.active = False
                if args[0] == 'stop': self.active = False
            if code and check: raise subprocess.CalledProcessError(code, args)
            return types.SimpleNamespace(returncode=code, stdout='', stderr='')
        self.addCleanup(patch.stopall)
        patch.object(self.proxy, 'ctl', side_effect=ctl).start()
        if REAL:
            self.real = str(Path(REAL).resolve())
            if sys.platform == 'darwin':
                # Production Linux uses the distro haproxy account. Adapt only fixture identity on macOS.
                adapter = self.root / 'real-haproxy'
                adapter.write_text('#!' + sys.executable + '\nimport os,sys,tempfile\nfrom pathlib import Path\n'
                    'args=sys.argv[1:];i=args.index("-f")+1\n'
                    'text=Path(args[i]).read_text().replace("    user haproxy",'+repr('    user '+pwd.getpwuid(os.getuid()).pw_name)+').replace("    group haproxy",'+repr('    group '+grp.getgrgid(os.getgid()).gr_name)+')\n'
                    'fd,path=tempfile.mkstemp(dir='+repr(str(self.root))+');os.write(fd,text.encode());os.close(fd);args[i]=path\n'
                    'os.execv('+repr(self.real)+',['+repr(self.real)+',*args])\n')
                adapter.chmod(0o700); self.real = str(adapter)

    def echo(self, tls=False):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        if tls: context.load_cert_chain(self.cert, self.key)
        class Handler(socketserver.BaseRequestHandler):
            def handle(inner):
                try:
                    conn = context.wrap_socket(inner.request, server_side=True) if tls else inner.request
                    with conn:
                        conn.settimeout(2)
                        data = conn.recv(4096)
                        if data: conn.sendall(data)
                except (OSError, ssl.SSLError): pass
        class Server(socketserver.ThreadingTCPServer): daemon_threads = True
        server = Server(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return server.server_address[1]

    def state(self, peer=None, number=None):
        return dict(owner=hp.OWNER, schema=1, rules=[dict(id='abcdef123456', name='住宅出口', listen='127.0.0.1', port=number or manager.port(), peer='127.0.0.1', peer_port=peer or self.echo())])

    def live_proxy(self, state):
        cfg = self.root / ('tcp-'+str(state['rules'][0]['port'])+'.cfg'); cfg.write_text(hp.render(state))
        subprocess.run([self.real, '-c', '-q', '-f', str(cfg)], check=True, capture_output=True)
        proc = subprocess.Popen([self.real, '-db', '-f', str(cfg)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def stop():
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=5)
        self.addCleanup(stop)
        for _ in range(40):
            if proc.poll() is not None: self.fail('HAProxy exited before listening')
            try:
                with socket.create_connection(('127.0.0.1', state['rules'][0]['port']), timeout=.1): pass
                return proc
            except OSError: time.sleep(.05)
        self.fail('HAProxy did not listen')

    def test_allowlist_rejects_injection_credentials_invalid_ports_and_duplicate_rules(self):
        state = self.state(); self.assertEqual(hp.normalize(state), state)
        for field, value in [('peer', 'example.com\nssl verify none'), ('peer', '0.0.0.0'), ('peer', '224.0.0.1'), ('peer', '999.2.3.4'), ('peer', 'https://node.example'), ('listen', '*'), ('name', '\x1b[31m'), ('port', True), ('port', 65536)]:
            bad = copy.deepcopy(state); bad['rules'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError): hp.normalize(bad)
        for extra in ('password', 'private_key', 'insecure', 'type'):
            bad = copy.deepcopy(state); bad['rules'][0][extra] = 'hysteria2'
            with self.assertRaises(ValueError): hp.normalize(bad)
        bad = copy.deepcopy(state); bad['rules'].append(dict(bad['rules'][0], id='111111111111'))
        with self.assertRaises(ValueError): hp.normalize(bad)
        state['rules'][0].update(listen='::', peer='node.example')
        text = hp.render(state); self.assertIn('[::]:', text); self.assertIn('v6only', text); self.assertIn('parse-resolv-conf', text)
        self.assertNotIn(' ssl ', text); self.assertNotIn('send-proxy', text)

    def test_busy_and_inactive_managed_tcp_ports_are_rejected_without_writes(self):
        state = self.state(number=self.echo())
        with self.assertRaises(OSError): self.proxy.apply(state)
        self.assertFalse(self.proxy.root.exists()); self.assertFalse(self.proxy.unit.exists())
        self.configure('1'); state = self.state(number=443)
        with self.assertRaisesRegex(ValueError, 'reserved'): self.proxy.apply(state)
        self.assertFalse(self.proxy.root.exists())

    def test_local_ip_and_dns_forwarding_loops_are_rejected(self):
        state = self.state(); state['rules'][0]['peer_port'] = state['rules'][0]['port']
        for address in ('127.0.0.1', 'localhost'):
            state['rules'][0]['peer'] = address
            with self.assertRaisesRegex(ValueError, 'loop'): self.proxy.preflight(state, probe=False)

    def test_inactive_tcp_rules_reserve_ports_for_other_managed_features(self):
        self.user_setup(); state = self.state(); self.proxy.apply(state); self.proxy.run('stop', [])
        reserved = state['rules'][0]['port']; before = (self.config / 'config.json').read_bytes()
        tools = self.root / 'tools'; tools.mkdir(); ctl = tools / 'systemctl'; ctl.write_text('#!/bin/sh\nexit 0\n'); ctl.chmod(0o700)
        prefix = 'HAPROXY_BIN='+shlex.quote(str(self.checker))+';export PATH='+shlex.quote(str(tools))+':"$PATH";'
        result = self.shell(prefix+'configuration_apply ports '+str(reserved)+' 443', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertIn('HAProxy', result.stderr)
        self.assertEqual(before, (self.config / 'config.json').read_bytes()); self.assertFalse(list(self.base.glob('edit.*')))
        result = self.shell(prefix+'online_setup', input='node.example\n'+str(reserved)+'\n', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertFalse((self.base / 'subscriptions.json').exists())
        profile = self.root / 'unused-warp.conf'; profile.write_text('not parsed')
        result = self.shell(prefix+'warp_import_gateway', input=str(profile)+'\n'+str(reserved)+'\n', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertFalse((self.base / 'warp-gateway.json').exists())
        result = self.shell(prefix+'need_root(){ :; };systemctl(){ :; };argo_install quick', input='y\n'+str(reserved)+'\n', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertIn('HAProxy', result.stderr); self.assertFalse((self.base / 'argo-server.json').exists())
        good, api = manager.port(), manager.port()
        code = (manager.ROOT / 'src/users.py').read_text()
        marker = 'n=20000+secrets.randbelow(40000)'; self.assertIn(marker, code)
        code = 'TEST_PORTS=iter('+repr([reserved, good, api])+')\n'+code.replace(marker, 'n=next(TEST_PORTS)')
        result = subprocess.run([sys.executable, '-', str(self.base), str(self.config / 'config.json'), str(self.base / 'state.json'), str(self.bin), 'en_US', 'add', 'Alice', '1', '30'], input=code, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        account = self.user_db()['users'][0]; self.assertEqual(account['port'], good); self.assertEqual(account['api_port'], api)
        self.assertFalse(self.active)

    def test_apply_preserves_node_credentials_and_uses_private_owned_files(self):
        self.configure(); original = (self.config / 'config.json').read_bytes()
        self.proxy.apply(self.state()); self.assertTrue(self.active and self.enabled)
        self.assertEqual(original, (self.config / 'config.json').read_bytes())
        for path in self.proxy.root.iterdir(): self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.proxy.root.stat().st_mode & 0o777, 0o700)
        self.assertNotIn(self.password, (self.proxy.root / 'state.json').read_text())
        self.assertNotIn(self.uuid, (self.proxy.root / 'haproxy.cfg').read_text())
        self.assertEqual(self.proxy.guard()['owner'], hp.OWNER)

    def test_binary_validation_and_unreachable_peer_leave_live_rules_unchanged(self):
        self.proxy.apply(self.state()); original = self.proxy.read(self.proxy.root / 'state.json')
        self.checker.write_text('#!/bin/sh\nexit 1\n')
        with self.assertRaisesRegex(ValueError, 'validation'): self.proxy.apply(self.state())
        self.checker.write_text('#!/bin/sh\nexit 0\n')
        with self.assertRaises(OSError): self.proxy.apply(self.state(peer=manager.port()))
        self.assertEqual(original, self.proxy.read(self.proxy.root / 'state.json')); self.assertTrue(self.active)

    def test_restart_failure_rolls_back_files_activity_and_boot_state(self):
        state = self.state(); self.proxy.apply(state)
        files = [self.proxy.root / 'state.json', self.proxy.root / 'haproxy.cfg', self.proxy.unit]
        before = {p:p.read_bytes() for p in files}
        self.fail_restart = True
        with self.assertRaisesRegex(ValueError, 'restored'): self.proxy.apply(self.state())
        self.assertEqual(before, {p:p.read_bytes() for p in files}); self.assertTrue(self.active and self.enabled)
        self.assertTrue(list(self.proxy.backups.iterdir()))

    def test_first_start_failure_removes_only_new_owned_files(self):
        self.fail_restart = True
        with self.assertRaises(ValueError): self.proxy.apply(self.state())
        self.assertFalse(self.proxy.root.exists()); self.assertFalse(self.proxy.unit.exists()); self.assertFalse(self.active or self.enabled)

    def test_unknown_files_modified_units_and_symlinks_are_never_overwritten(self):
        self.proxy.apply(self.state()); before = (self.proxy.root / 'state.json').read_bytes()
        unknown = self.proxy.root / 'my-config'; unknown.write_text('keep')
        with self.assertRaises(ValueError): self.proxy.purge()
        self.assertEqual(unknown.read_text(), 'keep'); unknown.unlink()
        self.proxy.unit.write_text('Description=external\n')
        with self.assertRaises(ValueError): self.proxy.apply(self.state())
        self.assertEqual(before, (self.proxy.root / 'state.json').read_bytes())
        self.proxy.unit.unlink(); self.proxy.unit.symlink_to(self.root / 'unrelated')
        with self.assertRaises(ValueError): self.proxy.guard()

    def test_backup_restore_and_purge_keep_external_config_and_service(self):
        external = self.root / 'external.cfg'; external.write_text('keep external configuration')
        unit = self.root / 'systemd/haproxy.service'; unit.write_text('external service')
        self.proxy.apply(self.state()); saved = self.proxy.snapshot()
        original = (saved / 'state.json').read_bytes()
        self.proxy.run('stop', []); self.assertFalse(self.active or self.enabled)
        self.proxy.restore(str(saved)); self.assertTrue(self.active and self.enabled)
        self.assertEqual(original, (self.proxy.root / 'state.json').read_bytes())
        self.proxy.purge(); self.assertFalse(self.proxy.root.exists())
        self.assertEqual(external.read_text(), 'keep external configuration'); self.assertEqual(unit.read_text(), 'external service')
        self.assertTrue(saved.exists())

    def test_restore_refuses_tampered_snapshot_and_outside_paths(self):
        self.proxy.apply(self.state()); saved = self.proxy.snapshot(); original = self.proxy.guard()
        (saved / 'haproxy.cfg').write_text('global\n lua-load /tmp/evil\n')
        with self.assertRaises(ValueError): self.proxy.restore(str(saved))
        with self.assertRaises(ValueError): self.proxy.restore(str(self.root))
        self.assertEqual(original, self.proxy.guard())

    def test_external_unit_overrides_refuse_first_install_without_writes(self):
        override = self.root / 'systemd' / (hp.UNIT + '.d'); override.mkdir()
        (override / 'custom.conf').write_text('[Service]\nExecStart=/bin/true\n')
        with self.assertRaises(ValueError): self.proxy.apply(self.state())
        self.assertFalse(self.proxy.root.exists()); self.assertTrue((override / 'custom.conf').exists())
        shutil.rmtree(override)
        with patch.object(self.proxy, 'ctl', return_value=types.SimpleNamespace(returncode=0, stdout='/lib/systemd/system/skybyte-haproxy.service\n')):
            with self.assertRaises(ValueError): self.proxy.apply(self.state())
        self.assertFalse(self.proxy.root.exists())

    def test_edit_one_rule_keeps_other_mapping_and_failed_target_keeps_live_config(self):
        state = self.state(); state['rules'].append(dict(id='111111111111', name='second', listen='127.0.0.1', port=manager.port(), peer='127.0.0.1', peer_port=self.echo()))
        self.proxy.apply(state); first = state['rules'][0]; new_peer = self.echo()
        self.proxy.run('edit', [first['id'], 'renamed', first['listen'], str(first['port']), '127.0.0.1', str(new_peer)])
        saved = self.proxy.guard(); self.assertEqual(saved['rules'][1], state['rules'][1]); self.assertEqual(saved['rules'][0]['id'], first['id'])
        self.assertEqual(saved['rules'][0]['peer_port'], new_peer)
        with self.assertRaises(OSError): self.proxy.run('edit', [first['id'], 'bad', first['listen'], str(first['port']), '127.0.0.1', str(manager.port())])
        self.assertEqual(saved, self.proxy.guard()); self.assertTrue(self.active)

    @unittest.skipUnless(REAL, 'real HAProxy required')
    def test_real_multiple_rules_forward_independently(self):
        state = self.state(); state['rules'].append(dict(id='111111111111', name='second', listen='127.0.0.1', port=manager.port(), peer='127.0.0.1', peer_port=self.echo()))
        if socket.has_ipv6:
            try:
                with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe: probe.bind(('::1', 0))
                state['rules'][1]['listen'] = '::1'
            except OSError: pass
        self.live_proxy(state)
        for rule in state['rules']:
            with socket.create_connection((rule['listen'], rule['port']), timeout=3) as conn:
                payload = rule['id'].encode(); conn.sendall(payload); self.assertEqual(conn.recv(4096), payload)

    def test_bilingual_menu_and_help_work_without_sing_box_installation(self):
        for lang in ('zh_CN', 'en_US'):
            result = self.shell('LANGUAGE_CHOICE='+lang+';sub_menu 4;printf "action=%s" "$MAIN_ACTION"', input='11\n')
            self.assertIn('action=haproxy', result.stdout)
            result = self.shell('LANGUAGE_CHOICE='+lang+';haproxy_menu', input='12\n')
            self.assertIn('4 → 11', result.stdout); self.assertIn('HY2', result.stdout)
            self.assertIn('B', result.stdout); self.assertFalse(self.proxy.root.exists())
        result = self.shell('haproxy_menu', input='2\n\n', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertFalse(self.proxy.root.exists())
        result = self.shell('haproxy_install_binary(){ echo BAD_INSTALL; };haproxy_menu', input='2\nabcdef123456\n', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertNotIn('BAD_INSTALL', result.stdout)
        result = self.shell('haproxy_install_binary(){ echo BAD_INSTALL; };haproxy_add', input='\n\n\n'+'vless://'+self.password+'@127.0.0.1:443\n\n', ok=False)
        self.assertNotEqual(result.returncode, 0); self.assertNotIn(self.password, result.stdout+result.stderr)
        self.assertNotIn('BAD_INSTALL', result.stdout); self.assertFalse(self.proxy.root.exists())

    def test_package_install_masks_only_default_service_and_cleans_up_on_failure(self):
        runtime = self.root / 'runtime'; runtime.mkdir()
        missing = self.root / 'new-haproxy'; log = self.root / 'apt-args'
        code = 'HAPROXY_BIN='+shlex.quote(str(missing))+';HAPROXY_RUNTIME_DIR='+shlex.quote(str(runtime))+''';systemctl(){ [[ $1 != is-active && $1 != is-enabled ]]; };apt-get(){ return 1; };haproxy_install_binary'''
        self.shell(code, ok=False); self.assertFalse((runtime / 'haproxy.service').exists()); self.assertFalse((runtime / 'haproxy.service').is_symlink())
        code = 'HAPROXY_BIN='+shlex.quote(str(missing))+';HAPROXY_RUNTIME_DIR='+shlex.quote(str(runtime))+';systemctl(){ [[ $1 != is-active && $1 != is-enabled ]]; };apt-get(){ [[ -L '+shlex.quote(str(runtime / 'haproxy.service'))+' ]] || return 1;printf "%s\\n" "$*" >> '+shlex.quote(str(log))+';if [[ $* == *install* ]];then cp '+shlex.quote(str(self.checker))+' "$HAPROXY_BIN";fi; };haproxy_install_binary'
        self.shell(code); self.assertIn('--force-confold', log.read_text()); self.assertFalse((runtime / 'haproxy.service').is_symlink()); self.assertTrue(missing.exists())
        missing.unlink(); (runtime / 'haproxy.service').symlink_to('/dev/null')
        self.shell(code); self.assertEqual(os.readlink(runtime / 'haproxy.service'), '/dev/null')

    def test_full_manager_backup_and_uninstall_include_owned_tcp_relay(self):
        self.prepare_uninstall(); self.proxy.apply(self.state())
        tools = self.root / 'tools'; tools.mkdir(); ctl = tools / 'systemctl'; ctl.write_text('#!/bin/sh\nexit 0\n'); ctl.chmod(0o700)
        prefix = 'HAPROXY_BIN='+shlex.quote(str(self.checker))+';export PATH='+shlex.quote(str(tools))+':"$PATH";'
        saved = Path(self.shell(prefix+'backup').stdout.strip())
        self.assertTrue((saved / 'haproxy/state.json').exists()); self.assertTrue((saved / 'backup-manifest.json').exists())
        self.shell(prefix+'need_root(){ :; };systemctl(){ :; };uninstall_manager', input='Y\n')
        self.assertFalse(self.proxy.root.exists()); self.assertFalse(self.proxy.unit.exists()); self.assertTrue((saved / 'haproxy/state.json').exists())

    @unittest.skipUnless(REAL, 'real HAProxy required; Linux CI installs it')
    def test_real_tls_passthrough_preserves_certificate_verification(self):
        state = self.state(peer=self.echo(tls=True)); self.live_proxy(state)
        good = ssl.create_default_context(cafile=str(self.cert))
        with socket.create_connection(('127.0.0.1', state['rules'][0]['port']), timeout=3) as conn:
            with good.wrap_socket(conn, server_hostname='node.example') as tls:
                tls.sendall(b'SKYBYTE TLS PASSTHROUGH'); self.assertEqual(tls.recv(4096), b'SKYBYTE TLS PASSTHROUGH')
        with self.assertRaises(ssl.SSLCertVerificationError):
            with socket.create_connection(('127.0.0.1', state['rules'][0]['port']), timeout=3) as conn:
                with ssl.create_default_context().wrap_socket(conn, server_hostname='node.example'): pass

    @unittest.skipUnless(REAL and manager.SB, 'real HAProxy and sing-box required')
    def test_real_reality_and_trojan_forward_and_fail_closed_when_landing_stops(self):
        target, payload = self.http_fixture()
        for kind in ('vless', 'trojan'):
            with self.subTest(kind=kind):
                if kind == 'vless': d, landing = self.landing(kind)
                else:
                    bp = manager.port(); path = self.root / 'trojan-landing.json'
                    inbound = dict(type='trojan', listen='127.0.0.1', listen_port=bp, users=[dict(password=self.password)], tls=dict(enabled=True, certificate_path=str(self.cert), key_path=str(self.key)))
                    path.write_text(json.dumps(dict(inbounds=[inbound], outbounds=[dict(type='direct', tag='direct')]))); landing = self.start_engine(path)
                    d = dict(type='trojan', tag='landing', server='127.0.0.1', server_port=bp, password=self.password, tls=dict(enabled=True, insecure=False, server_name='node.example', certificate=[self.cert.read_text()]))
                # Production preflight requires a reachable landing. Wait for
                # the actual TCP listener before HAProxy starts its checks;
                # process creation alone races HAProxy 2.2 health transitions.
                deadline = time.monotonic()+3
                while time.monotonic()<deadline:
                    if landing.poll() is not None: self.fail('Landing exited before listening')
                    try:
                        with socket.create_connection(('127.0.0.1',d['server_port']),timeout=.1): pass
                        break
                    except OSError: time.sleep(.05)
                else: self.fail('Landing did not become ready')
                state = self.state(peer=d['server_port']); self.live_proxy(state)
                mixed = manager.port(); client = self.root / ('tcp-client-'+kind+'.json')
                d['server_port'] = state['rules'][0]['port']
                client.write_text(json.dumps(dict(inbounds=[dict(type='socks', listen='127.0.0.1', listen_port=mixed)], outbounds=[d])))
                self.start_engine(client)
                result = self.request(mixed, 'http://127.0.0.1:'+str(target)); self.assertEqual(result.stdout, payload, result.stderr)
                if kind == 'vless': self.udp_roundtrip(mixed)
                landing.terminate(); landing.wait(timeout=5)
                failed = subprocess.run(['curl', '-q', '-s', '--max-time', '2', '--noproxy', '', '--proxy', 'socks5h://127.0.0.1:'+str(mixed), 'http://127.0.0.1:'+str(target)], capture_output=True)
                self.assertNotEqual(failed.returncode, 0); self.assertNotEqual(failed.stdout, payload)
