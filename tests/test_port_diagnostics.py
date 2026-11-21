"""Listener classification and real TCP probes without changing host services."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_manager as manager
import test_navigation as navigation

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'src' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

ports = module('port_diagnostics')
reality = module('reality')


class PortProbeTests(unittest.TestCase):
    def test_plain_tcp_listener_passes_without_tls_or_credentials(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            target = '127.0.0.1:' + str(server.getsockname()[1])
            with patch.object(reality.ssl, 'create_default_context', side_effect=AssertionError('TLS requested')):
                result = reality.probe(target, tcp_only=True)
            self.assertTrue(result['ok'])
            self.assertEqual(result['checks']['tls']['status'], 'skip')
            self.assertIn('elapsed_ms', result)
            self.assertTrue(ports.local_tcp('0.0.0.0', server.getsockname()[1]))

    def test_closed_port_and_failed_dns_are_not_reported_as_connected(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            number = server.getsockname()[1]
        self.assertFalse(reality.probe('127.0.0.1:' + str(number), tcp_only=True)['ok'])
        with patch.object(reality, 'resolve', side_effect=socket.gaierror()):
            result = reality.probe('example.test:443', tcp_only=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks']['dns']['detail'], 'dns_failed')

    def test_cli_works_without_root_bootstrap(self):
        with socket.socket() as server:
            server.bind(('127.0.0.1', 0))
            server.listen()
            result = subprocess.run(['bash', str(ROOT / 'singbox-v2.sh'), '--check-port',
                                     '127.0.0.1', str(server.getsockname()[1])], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS', result.stdout)
        self.assertNotIn('TLS 1.3', result.stdout)

    def test_listener_transport_address_family_and_missing_command(self):
        with patch.object(ports, 'command', return_value=(0, 'UNCONN 0 0 0.0.0.0:443 0.0.0.0:*')) as command:
            self.assertTrue(ports.listener_status('0.0.0.0', 443, 'udp'))
            self.assertIn('-lnu', command.call_args.args[0])
            self.assertFalse(ports.listener_status('127.0.0.1', 443, 'udp'))
        with patch.object(ports, 'command', return_value=(0, 'LISTEN 0 512 [::]:443 [::]:*')) as command:
            self.assertTrue(ports.listener_status('::', 443, 'tcp'))
            self.assertIn('-6', command.call_args.args[0])
        with patch.object(ports, 'command', return_value=(None, '')):
            self.assertIsNone(ports.listener_status('0.0.0.0', 443, 'tcp'))

    def test_hy2_listener_is_not_classified_as_public_udp_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'state.json').write_text(json.dumps({'ip': '192.0.2.1', 'password': 'SECRET'}))
            config = root / 'config.json'
            config.write_text(json.dumps({'inbounds': [{'type': 'hysteria2', 'listen': '0.0.0.0', 'listen_port': 443}]}))
            before = config.read_bytes()
            with patch.object(ports, 'command', return_value=(0, '')), patch.object(ports, 'listener_status', return_value=True), patch.object(ports, 'local_tcp', side_effect=AssertionError('UDP connect')), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(ports.main([str(root), str(config), 'en_US']), 0)
            self.assertIn('UDP public ingress: unverified', output.getvalue())
            self.assertNotIn('SECRET', output.getvalue())
            self.assertEqual(config.read_bytes(), before)

    def test_xhttp_only_and_corrupt_state_hide_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            xhttp = root / 'xhttp'
            xhttp.mkdir()
            (xhttp / '.owner').write_text('SKYBYTE-SB-XHTTP/1\n')
            state = xhttp / 'state.json'
            state.write_text(json.dumps({'schema': 1, 'nodes': {'xhttp-tls': {'port': 2053, 'listen': '::', 'address': 'example.test', 'uuid': 'SECRET'}}}))
            self.assertEqual(ports.node_list(root, root / 'absent')[0][:4], ('xhttp-tls', 'tcp', '::', 2053))
            state.write_text('SECRET broken state')
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(ports.main([str(root), str(root / 'absent'), 'en_US']), 1)
            self.assertNotIn('SECRET', error.getvalue())


class PortMenuTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell

    def test_new_menu_routes_both_checks_and_returns_without_idle_lock(self):
        code = navigation.NavigationTests.mocks(self) + '''xhttp_command(){ :; }
port_diagnostics_engine(){ echo LOCAL_PORT_CHECK; }
port_check_tcp(){ echo "REMOTE_PORT_CHECK $*"; }
main'''
        result = self.shell(code, input='b\n12\n1\n2\nexample.test\n443\n0\n0\nq\n')
        self.assertIn('LOCAL_PORT_CHECK', result.stdout)
        self.assertIn('REMOTE_PORT_CHECK example.test 443', result.stdout)
        self.assertNotIn('SELECT_LOCK=1', result.stdout)

    def test_port_editor_dispatches_xhttp_only_or_mixed_deployments(self):
        xhttp = self.base / 'xhttp'
        xhttp.mkdir()
        (xhttp / 'state.json').write_text('{}')
        code = 'xhttp_command(){ echo "XHTTP $*"; };edit_node_ports(){ echo SINGBOX; };change_node_ports'
        result = self.shell(code)
        self.assertIn('XHTTP edit 5', result.stdout)
        (self.base / 'state.json').write_text('{}')
        (self.config / 'config.json').write_text('{}')
        for selection, expected in [('1', 'SINGBOX'), ('2', 'XHTTP edit 5')]:
            self.assertIn(expected, self.shell(code, input=selection+'\n').stdout)
