"""Local diagnostic adapters: fixtures only, no host benchmarks or uploads."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
from scripts.build import assemble

q = types.ModuleType('quality')
exec(compile(assemble('media.py') + assemble('quality.py'), 'quality', 'exec'), q.__dict__)

class QualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()

    def test_privacy_arguments_and_separate_route_without_speed(self):
        for kind in ('hardware', 'ip', 'network', 'route'):
            for family in ('4', '6'):
                args = q.quality_arguments(kind, '/tmp/result.json', family, 'en_US')
                self.assertIn('-p', args)
                self.assertIn('-y', args)
                self.assertEqual(args[args.index('-l') + 1], 'en')
                if kind == 'hardware':
                    self.assertNotIn('-4', args); self.assertNotIn('-6', args)
                else: self.assertIn('-' + family, args)
                self.assertNotIn('-M', args)
        self.assertIn('-F', q.quality_arguments('hardware', 'out', quick=True))
        self.assertEqual(q.quality_arguments('route', 'out')[-3:], ['-R', '-S', '123'])
        with self.assertRaises(ValueError): q.quality_arguments('ip', 'out', 'any')

    def test_pinned_hash_mismatch_never_executes(self):
        payload = b'#!/bin/bash\nexit 0\n'
        for kind, source in q.QUALITY_TOOLS.items():
            self.assertEqual(len(source[2]), 40)
            self.assertEqual(len(source[3]), 64)
            with patch.object(q, 'fetch', return_value=payload) as fetch:
                with self.assertRaisesRegex(ValueError, 'SHA256'): q.quality_download(kind)
                self.assertIn('/' + source[2] + '/', fetch.call_args.args[0])
        modified = ('HardwareQuality', 'hardware.sh', 'a' * 40, hashlib.sha256(payload).hexdigest())
        with patch.dict(q.QUALITY_TOOLS, hardware=modified), patch.object(q, 'fetch', return_value=payload):
            self.assertEqual(q.quality_download('hardware')[0], payload)

    def test_json_stream_and_terminal_sanitization_width(self):
        data = {'Head': {}, 'CPU': {'型号': '测试 CPU ' * 12, 'escape': '\033[31mFAIL\033[0m\r\n'}}
        self.assertEqual(len(q.quality_json(json.dumps(data) + '\n' + json.dumps(data))), 2)
        for raw in ('', '[]', '{}', '{"Head":{}}garbage', json.dumps(data) * 3):
            with self.assertRaises(ValueError): q.quality_json(raw)
        for width in (40, 80, 120):
            table = q.quality_table(q.quality_rows(data), columns=width)
            self.assertNotIn('\033', table)
            for line in table.splitlines(): self.assertLessEqual(q.display_width(line), width)
        table = q.quality_table((('field', str(i)) for i in range(400)))
        self.assertIn('其余字段见本地 JSON', table)
        self.assertNotIn('399', table)

    def test_route_layout_groups_actual_hops_and_fits_terminal(self):
        route = """*****
网络质量体检报告：154.17.*.*
bash <(curl -sL https://Check.Place) -N
北京 电信    Unknown -> 163
地理路径：gateway -> 美国    自治系统路径：AS906 -> AS4134
1-2   0.42ms  193.41.*.*   AS906   [DMIT-BB] Anycast gateway
北京 联通    AS906 -> CN2GIA
1     129.11ms  2001:db8:abcd:1234::1  AS4809  中国 北京市
未识别的线路说明
=========
运行次数：123
"""
        for width in (40, 72, 80, 120):
            result = q.quality_route(route, 'zh_CN', width)
            self.assertEqual(result.count('跳点'), 2)
            self.assertIn('北京 电信', result)
            self.assertIn('北京 联通', result)
            self.assertIn('1-2', result)
            self.assertIn('129.11ms', result)
            self.assertIn('AS4809', result)
            self.assertIn('未识别的线路说明', result)
            self.assertNotIn('curl', result)
            self.assertNotIn('运行次数', result)
            self.assertTrue(all(q.display_width(line) <= width for line in result.splitlines()))

    def test_report_path_symlinks_and_size_refused(self):
        p = self.root / 'source'; p.write_text('ok')
        link = self.root / 'link'; link.symlink_to(p)
        with self.assertRaises(ValueError): q.quality_read(link)
        with patch.object(q, 'QUALITY_LIMIT', 1):
            with self.assertRaises(ValueError): q.quality_read(p)
        with self.assertRaises(ValueError): q.private_dir(link)

    def fixture(self, args, home, log, timeout):
        kind = 'route' if '-R' in args else 'hardware' if '-4' not in args and '-6' not in args else 'network' if '-S' in args else 'ip'
        self.assertIn('-p', args)
        self.assertIn('-y', args)
        out = Path(args[args.index('-o') + 1])
        if kind == 'route': out.write_text('三网回程路由\n电信 AS4809\n1 192.0.2.1 1ms\n')
        else: out.write_text(json.dumps({'Head': {}, {'hardware':'CPU','network':'Delay','ip':'Media'}[kind]: {'test': {'Status':'未知', 'Region':'US'}}}))
        log.write_text('fixture output')
        return 0 if kind == 'hardware' else 1

    def test_full_pipeline_writes_private_text_json_no_html(self):
        with patch.object(q, 'quality_download', return_value=(b'fixture', {'license':'AGPL-3.0'})), patch.object(q, 'quality_execute', side_effect=self.fixture), contextlib.redirect_stdout(io.StringIO()) as output:
            q.quality_main(['full', str(self.root / 'reports'), 'zh_CN', '4'])
        report = next(self.root.rglob('report.json'))
        data = json.loads(report.read_text())
        self.assertFalse(data['upload'])
        self.assertEqual([x['kind'] for x in data['runs']], ['hardware','ip','network','route'])
        self.assertTrue(all(x['status'] == '完成 / Completed' for x in data['runs']))
        self.assertIn('AS4809', output.getvalue())
        self.assertIn('│', output.getvalue())
        self.assertFalse(list(self.root.rglob('*.html')))
        for p in report.parent.iterdir(): self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        self.assertEqual(report.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(self.root.rglob('.quality-*')))

    def test_one_failure_does_not_discard_other_sections(self):
        def execute(*args):
            if '-S' in args[0] and '-R' not in args[0]: raise subprocess.TimeoutExpired(args[0], 1)
            return self.fixture(*args)
        with patch.object(q, 'quality_download', return_value=(b'fixture', {})), patch.object(q, 'quality_execute', side_effect=execute), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError): q.quality_main(['full', str(self.root), 'en_US', '4'])
        runs = json.loads(next(self.root.rglob('report.json')).read_text())['runs']
        self.assertEqual(len(runs), 4)
        self.assertIn('Failed', runs[2]['status'])
        self.assertIn('AS4809', runs[3]['route_text'])

    def test_cancel_saves_partial_and_does_not_run_next_section(self):
        def interrupt(args, home, log, timeout):
            self.fixture(args, home, log, timeout)
            raise KeyboardInterrupt
        with patch.object(q, 'quality_download', return_value=(b'fixture', {})), patch.object(q, 'quality_execute', side_effect=interrupt), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError): q.quality_main(['full', str(self.root), 'zh_CN', '4'])
        runs = json.loads(next(self.root.rglob('report.json')).read_text())['runs']
        self.assertEqual(len(runs), 1)
        self.assertIn('Cancelled', runs[0]['status'])
        self.assertTrue(runs[0]['data'])

    def test_real_process_timeout_and_bounded_log(self):
        log = self.root / 'output.log'
        with patch.object(q, 'QUALITY_LIMIT', 16):
            self.assertEqual(q.quality_execute(['bash','-c','printf "%0500d" 1'], str(self.root), log, 2), 0)
        self.assertEqual(log.stat().st_size, 16)
        with self.assertRaises(subprocess.TimeoutExpired):
            q.quality_execute(['bash', '-c', 'sleep 30 & wait'], str(self.root), log, .2)

if __name__ == '__main__': unittest.main()
