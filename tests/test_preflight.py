"""Actual POSIX locks and sockets; bounded diagnostics with no public networking."""
import contextlib
import errno
import importlib.util
import io
import os
from pathlib import Path
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('installation_checks', ROOT/'src/preflight.py')
checks = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checks)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def output(self, report):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            status = report.render()
        return status, out.getvalue()

    def test_existing_unlocked_package_files_are_not_a_conflict_or_changed(self):
        path = self.root/'lock-frontend'
        path.write_text('preserve')
        before = (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode)
        self.assertEqual(checks.package_locks([path, self.root/'absent']), ([], []))
        self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode))
        self.assertFalse((self.root/'absent').exists())

    def test_real_foreign_posix_lock_is_detected_without_deleting_it(self):
        path = self.root/'lock-frontend'
        path.write_text('preserve')
        code = 'import fcntl,sys;f=open(sys.argv[1],"r+");fcntl.lockf(f,fcntl.LOCK_EX);print("locked",flush=True);sys.stdin.read(1)'
        child = subprocess.Popen([sys.executable, '-c', code, str(path)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'locked')
            self.assertEqual(checks.package_locks([path]), ([str(path)], []))
            self.assertEqual(path.read_text(), 'preserve')
        finally:
            child.communicate('x', timeout=5)
        self.assertEqual(checks.package_locks([path]), ([], []))

    def test_package_symlinks_are_not_followed(self):
        target = self.root/'target'
        target.write_text('preserve')
        link = self.root/'lock'
        link.symlink_to(target)
        self.assertEqual(checks.package_locks([link]), ([], [str(link)]))
        self.assertEqual(target.read_text(), 'preserve')

    def test_tcp_occupied_does_not_imply_udp_occupied(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0));listener.listen()
            number = listener.getsockname()[1]
            report = checks.Report(True)
            with mock.patch.object(checks.shutil, 'which', return_value=None):
                checks.ports(report, '127.0.0.1', tcp=number, udp=number)
            tcp, udp = report.items[:2]
            self.assertEqual(tcp[0], 'fail')
            self.assertEqual(udp[0], 'pass')
            status, text = self.output(report)
            self.assertEqual(status, 1)
            self.assertIn('Occupied', text)
            self.assertIn('not proof of public reachability', text)

    def test_free_bind_is_released_and_unsupported_ipv6_has_a_clear_error(self):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0));number = probe.getsockname()[1]
        report = checks.Report()
        with mock.patch.object(checks.shutil, 'which', return_value=None):
            checks.ports(report, '127.0.0.1', tcp=number)
        self.assertEqual(report.items[0][0], 'pass')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', number))
        report = checks.Report(True)
        with mock.patch.object(checks.socket, 'socket', side_effect=OSError(errno.EAFNOSUPPORT, 'unsupported')), mock.patch.object(checks.shutil, 'which', return_value=None):
            checks.ports(report, '::', tcp=number)
        self.assertEqual(report.items[0][0], 'fail')
        self.assertIn('IPv4/IPv6', report.items[0][2])

    def test_tcp_time_wait_does_not_block_a_reusable_server_port(self):
        with socket.socket() as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(('127.0.0.1', 0));server.listen()
            number = server.getsockname()[1]
            with socket.create_connection(('127.0.0.1', number), timeout=2) as client:
                peer, _ = server.accept()
                peer.close()
                self.assertEqual(client.recv(1), b'')
        report = checks.Report(True)
        with mock.patch.object(checks.shutil, 'which', return_value=None):
            checks.ports(report, '127.0.0.1', tcp=number)
        self.assertEqual(report.items[0][0], 'pass', report.items)

    def test_firewall_probes_are_bounded_and_read_only(self):
        report = checks.Report(True)
        response = subprocess.CompletedProcess([], 0, 'Status: active\n', '')
        with mock.patch.object(checks.shutil, 'which', side_effect=lambda x: '/usr/sbin/ufw' if x == 'ufw' else None), mock.patch.object(checks.subprocess, 'run', return_value=response) as run:
            checks.ports(report, '127.0.0.1', tcp=12345)
        self.assertEqual(run.call_args.args[0], ['ufw', 'status'])
        self.assertEqual(run.call_args.kwargs['timeout'], 3)
        self.assertIn('Active: ufw', report.items[-1][2])
        self.assertEqual(report.items[-1][0], 'warn')

    def test_environment_reports_lock_dependencies_and_storage_separately(self):
        release = self.root/'os-release';release.write_text('ID=debian\n')
        report = checks.Report(True)
        info = types.SimpleNamespace(f_flag=0, f_favail=0, f_bavail=1000, f_frsize=4096)
        with mock.patch.object(checks.os, 'geteuid', return_value=0), mock.patch.object(checks.platform, 'system', return_value='Linux'), mock.patch.object(checks.platform, 'machine', return_value='x86_64'), mock.patch.object(checks.Path, 'is_dir', return_value=True), mock.patch.object(checks, 'package_locks', return_value=(['/var/lib/dpkg/lock-frontend'], [])), mock.patch.object(checks.shutil, 'which', side_effect=lambda name: None if name == 'curl' else '/usr/bin/'+name), mock.patch.object(checks.os, 'statvfs', return_value=info):
            checks.environment(report, 'sing-box', str(release), [self.root], reality=True)
        status, text = self.output(report)
        self.assertEqual(status, 1)
        for fragment in ('APT/DPKG', 'Do not delete lock files', 'curl', 'Installation storage', 'inodes exhausted'):
            self.assertIn(fragment, text)
        self.assertEqual(release.read_text(), 'ID=debian\n')

    def test_distribution_architecture_and_python_tls_failures_are_specific(self):
        release = self.root/'os-release';release.write_text('ID=centos\n')
        report = checks.Report(True)
        with mock.patch.object(checks.os, 'geteuid', return_value=1000), mock.patch.object(checks.platform, 'machine', return_value='unsupported'), mock.patch.object(checks.ssl, 'HAS_TLSv1_3', False), mock.patch.object(checks, 'package_locks', return_value=([], [])):
            checks.environment(report, 'xray', str(release), reality=True)
        status, text = self.output(report)
        self.assertEqual(status, 1)
        for fragment in ('Run as root', 'centos', 'unsupported', 'Python TLS 1.3'):
            self.assertIn(fragment, text)

    def test_https_failure_reasons_do_not_echo_exception_secrets(self):
        cases = [(urllib.error.URLError(socket.gaierror('PRIVATE')), 'DNS lookup failed'),
                 (urllib.error.URLError(socket.timeout('PRIVATE')), 'timed out'),
                 (urllib.error.URLError(ssl.SSLCertVerificationError('PRIVATE')), 'Certificate verification failed'),
                 (urllib.error.HTTPError('https://github.com/', 403, 'PRIVATE', {}, None), 'HTTP 403')]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__):
                report = checks.Report(True)
                with mock.patch.object(checks.urllib.request, 'urlopen', side_effect=error):
                    checks.download(report)
                status, text = self.output(report)
                self.assertEqual(status, 0 if isinstance(error, urllib.error.HTTPError) else 1)
                self.assertIn(expected, text)
                self.assertNotIn('PRIVATE', text)

    def test_https_dns_deadline_is_bounded_and_offline_mode_does_not_connect(self):
        ready = threading.Event();response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        report = checks.Report(True)
        def delayed(*args, **kwargs):
            ready.wait(1)
            return response
        started = time.monotonic()
        try:
            with mock.patch.object(checks.urllib.request, 'urlopen', side_effect=delayed):
                checks.download(report, timeout=.02)
            self.assertLess(time.monotonic()-started, .5)
            self.assertEqual(report.items[-1][0], 'fail')
        finally:
            ready.set()
        report = checks.Report(True)
        with mock.patch.object(checks.urllib.request, 'urlopen') as request:
            checks.download(report, offline=True);request.assert_not_called()
        self.assertEqual(report.items[0][0], 'warn')
        report = checks.Report(True)
        with mock.patch.object(checks.urllib.request, 'urlopen') as request:
            checks.download(report, existing_core=True);request.assert_not_called()
        self.assertIn('Existing local core', report.items[0][2])

    def test_https_success_and_bilingual_invalid_arguments(self):
        response = mock.MagicMock();response.__enter__.return_value.status = 200
        report = checks.Report(True)
        with mock.patch.object(checks.urllib.request, 'urlopen', return_value=response) as request:
            checks.download(report)
        self.assertEqual(report.items[0][0], 'pass')
        self.assertEqual(request.call_args.args[0].get_method(), 'HEAD')
        self.assertEqual(request.call_args.args[0].full_url, 'https://github.com/')
        for language in ('zh', 'en'):
            with contextlib.redirect_stdout(io.StringIO()) as out:
                result = checks.main(['--project', 'sing-box', '--phase', 'ports', '--tcp-port', '70000', '--language', language])
            self.assertEqual(result, 1)
            self.assertIn('FAIL' if language == 'en' else '失败', out.getvalue())
