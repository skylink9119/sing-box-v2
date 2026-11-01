"""Source composition must be reproducible, contained and standalone at runtime."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = 'singbox-v2.sh'


class ModularBuildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for directory in ('src', 'lib', 'modules', 'scripts', 'data'):
            if (ROOT / directory).exists():
                shutil.copytree(ROOT / directory, self.root / directory,
                                ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('README.md', 'README_EN.md', 'install.sh', 'bootstrap.sh', PAYLOAD):
            shutil.copyfile(ROOT / name, self.root / name)

    def build(self, *arguments):
        return subprocess.run([sys.executable, str(self.root / 'scripts/build.py'), *arguments],
                              cwd=self.root, capture_output=True, text=True, timeout=15)

    def include(self, name):
        entry = self.root / 'src/manager.sh'
        entry.write_text(entry.read_text() + '# @include ' + name + '\n')

    def test_rebuild_is_reproducible_and_payload_runs_without_source_tree(self):
        before = (self.root / PAYLOAD).read_bytes()
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, (self.root / PAYLOAD).read_bytes())
        detached = self.root / 'detached'
        detached.mkdir()
        shutil.copyfile(self.root / PAYLOAD, detached / PAYLOAD)
        result = subprocess.run(['bash', str(detached / PAYLOAD), '--self-check'],
                                cwd=detached, capture_output=True, text=True, timeout=15,
                                env={**os.environ, 'NO_COLOR': '1'})
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_modified_module_is_detected_as_stale(self):
        path = self.root / 'lib/common.sh'
        path.write_text(path.read_text() + '\n# Updated module\n')
        result = self.build('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('stale', result.stderr.lower())

    def test_nested_feature_module_is_embedded(self):
        self.include('modules/build_probe.sh')
        (self.root / 'modules/build_probe.sh').write_text('# @include lib/build_probe.sh\n')
        (self.root / 'lib/build_probe.sh').write_text('build_probe(){ :; }\n')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('build_probe(){ :; }', (self.root / PAYLOAD).read_text())

    def test_missing_module_fails_before_replacing_payload(self):
        before = (self.root / PAYLOAD).read_bytes()
        (self.root / 'lib/common.sh').unlink()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing', result.stderr)
        self.assertEqual(before, (self.root / PAYLOAD).read_bytes())

    def test_recursive_includes_are_rejected(self):
        self.include('modules/build_probe.sh')
        (self.root / 'modules/build_probe.sh').write_text('# @include modules/build_probe.sh\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Recursive', result.stderr)

    def test_outside_path_is_rejected(self):
        self.include('../outside.sh')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid source include', result.stderr)

    def test_symlinked_module_is_rejected(self):
        target = self.root / 'outside.sh'
        target.write_text('outside_probe(){ :; }\n')
        self.include('modules/build_probe.sh')
        (self.root / 'modules/build_probe.sh').symlink_to(target)
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlinked', result.stderr)

    def test_final_include_without_newline_is_not_silently_ignored(self):
        entry = self.root / 'src/manager.sh'
        entry.write_text(entry.read_text() + '# @include modules/missing.sh')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing', result.stderr)

    def test_module_without_final_newline_does_not_join_next_statement(self):
        self.include('modules/build_probe.sh')
        entry = self.root / 'src/manager.sh'
        entry.write_text(entry.read_text() + 'after_probe(){ :; }\n')
        (self.root / 'modules/build_probe.sh').write_text('build_probe(){ :; }')
        result = self.build()
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(['bash', '-n', str(self.root / PAYLOAD)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_backend_fragment_change_is_detected(self):
        fragment = self.root / 'src/warp_relay.py'
        fragment.write_text(fragment.read_text() + '\n# backend change\n')
        result = self.build('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('backend is stale', result.stderr)

    def test_missing_backend_fragment_preserves_existing_outputs(self):
        payload = (self.root / PAYLOAD).read_bytes()
        backend = (self.root / 'src/warp.py').read_bytes()
        (self.root / 'src/warp_relay.py').unlink()
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Missing', result.stderr)
        self.assertEqual(payload, (self.root / PAYLOAD).read_bytes())
        self.assertEqual(backend, (self.root / 'src/warp.py').read_bytes())

    def test_invalid_backend_syntax_is_rejected_before_writing(self):
        payload = (self.root / PAYLOAD).read_bytes()
        backend = (self.root / 'src/warp.py').read_bytes()
        fragment = self.root / 'src/warp_relay.py'
        fragment.write_text(fragment.read_text() + '\ndef broken(:\n')
        result = self.build()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SyntaxError', result.stderr)
        self.assertEqual(payload, (self.root / PAYLOAD).read_bytes())
        self.assertEqual(backend, (self.root / 'src/warp.py').read_bytes())
