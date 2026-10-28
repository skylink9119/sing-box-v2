"""Menu snapshots must not wait on quota mutations or unbounded system probes."""
import fcntl
import shutil
import subprocess
import time
import unittest
import test_manager as manager


class MenuPerformanceTests(unittest.TestCase):
    setUp = manager.ManagerTest.setUp
    script = manager.ManagerTest.script
    shell = manager.ManagerTest.shell

    def test_account_summary_does_not_wait_for_exclusive_worker_lock(self):
        self.shell('users_engine init 2')
        ledger = self.base / 'users.json'
        before = ledger.read_bytes()
        with (self.base / 'users.lock').open('a') as worker:
            fcntl.flock(worker, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([manager.BASH, '-c', self.script('users_engine summary')],
                                    capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Accounts: 0/2; ready: 0', result.stdout)
        self.assertEqual(ledger.read_bytes(), before)

    def test_account_summary_does_not_create_a_lock_file(self):
        self.shell('users_engine init 2')
        (self.base / 'users.lock').unlink()
        self.shell('users_engine summary')
        self.assertFalse((self.base / 'users.lock').exists())

    def test_unchanged_shortcut_and_payload_are_not_rewritten(self):
        self.shell('manager_shortcut_install')
        targets = [self.root / 'manager-command', self.root / 'manager-lib', self.root / 'sb-command']
        targets = [p for p in targets if p.exists()]
        self.assertEqual(len(targets), 2)
        before = [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in targets]
        self.shell('manager_shortcut_install')
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in targets])
        wrapper = self.root / 'sb-command'
        wrapper.chmod(0o600)
        self.shell('manager_shortcut_install')
        self.assertEqual(wrapper.stat().st_mode & 0o777, 0o755)
        wrapper.chmod(0o4755)
        self.shell('manager_shortcut_install')
        self.assertEqual(wrapper.stat().st_mode & 0o7777, 0o755)

    def test_failed_service_probe_is_unknown_rather_than_stopped(self):
        result = self.shell('startup_probe(){ return 124; }; startup_service_info sing-box true sing-box.service')
        self.assertIn('Installed, status unknown', result.stdout)
        self.assertNotIn('inactive', result.stdout)

    def test_system_probe_uses_deadline_and_skips_when_timeout_missing(self):
        result = self.shell('timeout(){ printf "ARGS=%s\\n" "$*"; }; startup_probe systemctl show')
        self.assertIn('ARGS=--kill-after=1s 2s systemctl show', result.stdout)
        result = self.shell('command(){ return 1; }; startup_probe false', ok=False)
        self.assertEqual(result.returncode, 124)

    @unittest.skipUnless(shutil.which('timeout'), 'GNU timeout is exercised by Linux CI')
    def test_real_slow_system_query_is_terminated(self):
        started = time.monotonic()
        result = subprocess.run([manager.BASH, '-c', self.script("startup_probe sh -c 'sleep 20'")],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 124)
        self.assertLess(time.monotonic() - started, 4.5)

