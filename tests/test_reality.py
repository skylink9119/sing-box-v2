"""REALITY diagnostics against local TLS peers; no public network required."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reality_diagnostic', ROOT/'src/reality.py')
reality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reality)


class RealityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.cert, cls.key = cls.root/'ca.crt', cls.root/'ca.key'
        config = cls.root/'openssl.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ids\n[dn]\n[ids]\n'
                          'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n')
        subprocess.run([os.environ.get('OPENSSL_BIN', 'openssl'), 'req', '-config', str(config),
                        '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=localhost',
                        '-addext', 'subjectAltName=DNS:localhost', '-addext', 'basicConstraints=critical,CA:TRUE',
                        '-addext', 'keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign',
                        '-keyout', str(cls.key), '-out', str(cls.cert)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @contextlib.contextmanager
    def peer(self, alpn=('h2',), maximum=None, stall=False):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert), str(self.key))
        context.set_alpn_protocols(list(alpn))
        if maximum is not None:
            context.maximum_version = maximum
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        listener.settimeout(3)
        done = threading.Event()
        def serve():
            try:
                raw, _ = listener.accept()
                with raw:
                    raw.settimeout(2)
                    if stall:
                        done.wait(1)
                    else:
                        try:
                            with context.wrap_socket(raw, server_side=True):
                                pass
                        except (ssl.SSLError, OSError):
                            pass
            except OSError:
                pass
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            yield '127.0.0.1:' + str(listener.getsockname()[1])
        finally:
            done.set()
            listener.close()
            thread.join(timeout=3)

    def test_names_ports_and_ipv6_targets(self):
        for value, expected in [('Example.COM.', ('example.com', 443, 'example.com')),
                                ('example.com:8443', ('example.com', 8443, 'example.com')),
                                ('[::1]:443', ('::1', 443, 'localhost'))]:
            self.assertEqual(reality.target_parts(value, 'localhost' if '[' in value else ''), expected)
        for value in ('https://example.com', 'example.com:0', 'example.com:65536', 'example.com:abc',
                      'example.com;touch /tmp/pwned', '$(id)', 'bad\x1b[31m', 'a..com', '[::1]:-1'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                reality.target_parts(value)

    @unittest.skipUnless(ssl.HAS_TLSv1_3, 'TLS 1.3 required')
    def test_real_tls13_h2_and_verified_certificate_pass(self):
        with self.peer() as target:
            result = reality.probe(target, 'localhost', ca_file=str(self.cert))
        self.assertTrue(result['ok'], result)
        self.assertTrue(all(item['status'] == 'pass' for item in result['checks'].values()))
        self.assertEqual(result['checks']['tls']['detail'], 'TLSv1.3')

    @unittest.skipUnless(ssl.HAS_TLSv1_3, 'TLS 1.3 required')
    def test_tls13_without_h2_is_not_reported_as_success(self):
        with self.peer(alpn=('http/1.1',)) as target:
            result = reality.probe(target, 'localhost', ca_file=str(self.cert))
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks']['tls']['status'], 'pass')
        self.assertEqual(result['checks']['h2'], {'status': 'fail', 'detail': 'no_h2'})

    @unittest.skipUnless(ssl.HAS_TLSv1_3, 'TLS 1.3 required')
    def test_tls12_only_is_refused(self):
        with self.peer(maximum=ssl.TLSVersion.TLSv1_2) as target:
            result = reality.probe(target, 'localhost', ca_file=str(self.cert))
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks']['tls']['detail'], 'tls_failed')

    @unittest.skipUnless(ssl.HAS_TLSv1_3, 'TLS 1.3 required')
    def test_wrong_sni_and_untrusted_certificate_are_not_bypassed(self):
        for name, ca, expected in [('wrong.example', str(self.cert), 'name_mismatch'),
                                   ('localhost', None, 'untrusted')]:
            with self.peer() as target:
                result = reality.probe(target, name, ca_file=ca)
            self.assertFalse(result['ok'])
            self.assertEqual(result['checks']['certificate']['detail'], expected)
            self.assertEqual(result['checks']['h2']['status'], 'skip')

    def test_dns_failure_and_timeout_are_distinguished_and_bounded(self):
        with mock.patch.object(reality.socket, 'getaddrinfo', side_effect=socket.gaierror()):
            result = reality.probe('example.com')
        self.assertEqual(result['checks']['dns']['detail'], 'dns_failed')
        stopped = threading.Event()
        def delayed(*args, **kwargs):
            stopped.wait(2)
            return []
        try:
            with mock.patch.object(reality.socket, 'getaddrinfo', side_effect=delayed):
                result = reality.probe('example.com', timeout=0.1)
        finally:
            stopped.set()
        self.assertLess(result['elapsed_ms'], 800)
        self.assertEqual(result['checks']['dns']['detail'], 'timeout')

    def test_refused_tcp_port_is_not_a_tls_success(self):
        with mock.patch.object(reality.socket.socket, 'connect', side_effect=ConnectionRefusedError):
            result = reality.probe('127.0.0.1:443', 'localhost')
        self.assertEqual(result['checks']['tcp']['detail'], 'connect_failed')
        self.assertEqual(result['checks']['tls']['status'], 'skip')

    def test_legacy_python_socket_timeout_has_a_specific_failure_reason(self):
        # Before Python 3.10 socket.timeout was a distinct OSError subclass.
        class LegacyTimeout(OSError):
            pass
        with mock.patch.object(reality.socket, 'timeout', LegacyTimeout), \
             mock.patch.object(reality, 'resolve', side_effect=LegacyTimeout):
            result = reality.probe('example.com')
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks']['dns']['detail'], 'timeout')

    @unittest.skipUnless(ssl.HAS_TLSv1_3, 'TLS 1.3 required')
    def test_stalled_tls_has_a_total_time_limit(self):
        with self.peer(stall=True) as target:
            result = reality.probe(target, 'localhost', timeout=0.2)
        self.assertFalse(result['ok'])
        self.assertEqual(result['checks']['tls']['detail'], 'timeout')
        self.assertLess(result['elapsed_ms'], 1000)

    @unittest.skipUnless(ssl.HAS_TLSv1_3, 'TLS 1.3 required')
    def test_next_resolved_address_is_tried_if_first_tcp_connection_fails(self):
        with self.peer() as target:
            number = int(target.rsplit(':', 1)[1])
            rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.2', number)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', number))]
            original = socket.socket.connect
            def connect(sock, endpoint):
                if endpoint[0] == '127.0.0.2':
                    raise ConnectionRefusedError()
                return original(sock, endpoint)
            with mock.patch.object(reality, 'resolve', return_value=rows), \
                 mock.patch.object(reality.socket.socket, 'connect', new=connect):
                result = reality.probe(target, 'localhost', ca_file=str(self.cert))
        self.assertTrue(result['ok'], result)

    def test_expiry_and_not_yet_valid_certificates_have_explicit_reasons(self):
        for code, reason in [(9, 'not_yet_valid'), (10, 'expired')]:
            error = ssl.SSLCertVerificationError(1, 'verification failed')
            error.verify_code = code
            with self.peer(stall=True) as target, \
                 mock.patch.object(reality.ssl, 'create_default_context', side_effect=error):
                result = reality.probe(target, 'localhost')
            self.assertFalse(result['ok'])
            self.assertEqual(result['checks']['certificate']['detail'], reason)

    def test_configured_targets_use_runtime_target_and_deduplicate_without_exporting_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            sing = {'type': 'vless', 'tls': {'enabled': True, 'server_name': 'sni.example',
                    'reality': {'enabled': True, 'private_key': 'SECRET',
                                'handshake': {'server': 'target.example', 'server_port': 8443}}}}
            xray = {'streamSettings': {'security': 'reality', 'realitySettings': {
                    'target': 'target.example:8443', 'serverNames': ['sni.example'], 'privateKey': 'SECRET'}}}
            for project, node in [('sing-box', sing), ('xray', xray)]:
                path.write_text(json.dumps({'inbounds': [node, node, {'type': 'hysteria2'}]}))
                before = path.read_bytes()
                targets = reality.configured_targets(path, project)
                self.assertEqual(targets, [('target.example:8443', 'sni.example')])
                self.assertNotIn('SECRET', repr(targets))
                self.assertEqual(path.read_bytes(), before)

    def test_xray_legacy_dest_and_multiple_allowed_names(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'config.json'
            path.write_text(json.dumps({'inbounds': [{'streamSettings': {'security': 'reality',
                'realitySettings': {'dest': 'target.example:443', 'serverNames': ['one.example', 'two.example']}}}]}))
            self.assertEqual(len(reality.configured_targets(path, 'xray')), 2)

    def test_missing_config_no_reality_and_corrupt_config_do_not_trigger_network(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(reality, 'probe') as run:
            path = Path(folder)/'config.json'
            for content in (None, '{}', '{"inbounds":[{"type":"hysteria2"}]}'):
                if content is not None:
                    path.write_text(content)
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(reality.main(['--project', 'sing-box', '--config', str(path)]), 0)
                self.assertIn('未找到', output.getvalue())
            path.write_text('PRIVATE INVALID CONFIG')
            with contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(reality.main(['--project', 'xray', '--config', str(path)]), 2)
            self.assertNotIn('PRIVATE', output.getvalue())
            run.assert_not_called()

    def test_invalid_custom_target_stops_before_network_and_omits_raw_input(self):
        with mock.patch.object(reality, 'probe') as run, contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(reality.main(['--project', 'xray', '--target', 'PRIVATE;id']), 2)
        run.assert_not_called()
        self.assertNotIn('PRIVATE', output.getvalue())

    def test_all_configured_targets_are_checked_even_after_a_failure(self):
        results = [{'ok': False}, {'ok': True}]
        with mock.patch.object(reality, 'configured_targets', return_value=[('one.example:443', 'one.example'),
                                                                          ('two.example:443', 'two.example')]), \
             mock.patch.object(reality, 'probe', side_effect=results) as run, \
             mock.patch.object(reality, 'render'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(reality.main(['--project', 'xray', '--config', '/unused']), 1)
        self.assertEqual(run.call_count, 2)

    def test_clear_summary_and_localized_failure_reason(self):
        with mock.patch.object(reality.socket, 'getaddrinfo', side_effect=socket.gaierror()):
            result = reality.probe('example.com')
        for language, expected in [('zh_CN', '检测未通过'), ('en', 'FAILED:')]:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                reality.render(result, language)
            self.assertIn(expected, output.getvalue())
            self.assertIn('DNS', output.getvalue())
            self.assertNotIn('\x1b', output.getvalue())

    def test_machine_readable_selection_and_normalization_never_probe(self):
        with mock.patch.object(reality, 'configured_targets', return_value=[('one.example:443','one.example')]), mock.patch.object(reality,'probe') as probe:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(reality.main(['--project','sing-box','--config','/unused','--list']),0)
            self.assertEqual(output.getvalue(),'one.example:443\tone.example\n')
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(reality.main(['--project','sing-box','--target','[::1]:8443','--sni','LOCALHOST','--normalize']),0)
            self.assertEqual(output.getvalue(),'::1\t8443\tlocalhost\n')
            probe.assert_not_called()
        with mock.patch.object(reality,'configured_targets',return_value=[]), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(reality.main(['--project','xray','--config','/unused','--list']),0)
        self.assertEqual(output.getvalue(),'')
