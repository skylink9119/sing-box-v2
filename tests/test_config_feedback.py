"""Silent core success must produce visible feedback without changing services."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ConfigurationFeedbackTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'config.json').write_text('{}')
        (self.root/'state.json').write_text('{}')
        self.binary = self.root/'core'
        self.binary.write_text('#!/bin/sh\nexit 0\n')
        self.binary.chmod(0o700)

    def run_check(self, language, code='service_manager 6', inputs=None):
        script = 'source "$1"; BASE="$TEST_ROOT"; META="$BASE/state.json"; CONF="$BASE/config.json"; BIN="$BASE/core"; BACKUP="$BASE/backups"; LANGUAGE_CHOICE=$TEST_LANGUAGE; load_language(){ :; }; flock(){ :; }; systemctl(){ echo UNEXPECTED_SERVICE >&2; return 99; }; '+code
        return subprocess.run(['bash','-c',script,'test',str(ROOT/'singbox-v2.sh')],
            input=inputs,capture_output=True,text=True,timeout=5,
            env={**os.environ,'TEST_ROOT':str(self.root),'TEST_LANGUAGE':language,'NO_COLOR':'1'})

    def test_silent_success_has_explicit_result_in_both_languages(self):
        for language,label in [('zh_CN', '[通过]'), ('en_US', '[PASS]')]:
            result=self.run_check(language)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(label,result.stdout)
            self.assertIn(str(self.root/'config.json'),result.stdout)
            self.assertNotIn('UNEXPECTED_SERVICE',result.stderr)

    def test_failed_core_preserves_error_and_nonzero_exit(self):
        self.binary.write_text('#!/bin/sh\necho CORE_FAILURE >&2\nexit 7\n')
        result=self.run_check('en_US')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('CORE_FAILURE',result.stderr)
        self.assertIn('[FAIL]',result.stderr)
        self.assertNotIn('[PASS]',result.stdout)

    def test_missing_binary_or_configuration_never_reports_success(self):
        self.binary.unlink()
        result=self.run_check('en_US')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('[Not checked]',result.stderr)
        (self.root/'config.json').unlink()
        result=self.run_check('en_US')
        self.assertNotEqual(result.returncode,0)
        self.assertNotIn('[PASS]',result.stdout)

    def test_repeated_checks_show_each_result_and_return_without_service_changes(self):
        result=self.run_check('en_US','run_submenu service_manager','6\n6\n0\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.count('[PASS]'),2)
        self.assertNotIn('UNEXPECTED_SERVICE',result.stderr)
