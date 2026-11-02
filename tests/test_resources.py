"""Resource estimates use measured cores, preserve headroom and respect cgroups."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('resource_report',ROOT/'src/resources.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)

class ResourceTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.proc=self.root/'proc';self.proc.mkdir()
        self.cgroup=self.root/'cgroup';self.cgroup.mkdir()
        (self.proc/'self').mkdir()
        (self.proc/'meminfo').write_text('MemTotal: 2097152 kB\nMemAvailable: 1048576 kB\n')
        self.rows=[{'pid':10,'rss':65536,'account':'/manager/users/a/server.json'},
                   {'pid':11,'rss':49152,'account':None}]

    def test_only_managed_processes_are_counted_and_arguments_are_not_reported(self):
        text='10 65536 /bin/sing-box run -c /manager/users/a/server.json\n11 49152 /bin/sing-box run -c /admin.json\n12 99999 /bin/other secret-password\nbad 999 /bin/sing-box run -c /admin.json\n'
        rows=report.processes(text,Path('/manager'),Path('/bin/sing-box'))
        self.assertEqual(rows,self.rows)
        output=report.render(rows,2097152,1048576,False,None,True)
        self.assertIn('Running quota accounts: 1',output)
        self.assertNotIn('secret-password',output)
        self.assertNotIn('/manager/users',output)

    def test_budget_reserves_headroom_and_doubles_largest_user_rss(self):
        self.assertEqual(report.capacity(self.rows,2097152,1048576),(524288,131072,4))
        self.assertEqual(report.capacity(self.rows,524288,200000),(262144,131072,0))
        self.assertIsNone(report.capacity([],2097152,1048576))
        self.assertIsNone(report.capacity(self.rows,None,None))

    def test_v2_parent_limit_reduces_effective_available_memory(self):
        (self.proc/'self/cgroup').write_text('0::/slice/child\n')
        parent=self.cgroup/'slice';child=parent/'child';child.mkdir(parents=True)
        (child/'memory.max').write_text('max')
        (parent/'memory.max').write_text(str(512*1024**2))
        (parent/'memory.current').write_text(str(400*1024**2))
        total,available,limited=report.memory_snapshot(self.proc,self.cgroup)
        self.assertEqual((total,available,limited),(524288,114688,True))
        self.assertEqual(report.capacity(self.rows,total,available)[2],0)

    def test_v1_memory_controller_limit_is_also_respected(self):
        (self.proc/'self/cgroup').write_text('2:cpu,cpuacct:/ignored\n3:memory:/group\n')
        path=self.cgroup/'memory/group';path.mkdir(parents=True)
        (path/'memory.limit_in_bytes').write_text(str(512*1024**2))
        (path/'memory.usage_in_bytes').write_text(str(400*1024**2))
        self.assertEqual(report.memory_snapshot(self.proc,self.cgroup),(524288,114688,True))

    def test_limit_with_missing_usage_does_not_guess_available_memory(self):
        (self.cgroup/'memory.max').write_text(str(512*1024**2))
        total,available,limited=report.memory_snapshot(self.proc,self.cgroup)
        self.assertEqual(total,524288);self.assertIsNone(available);self.assertTrue(limited)
        self.assertIsNone(report.capacity(self.rows,total,available))

    def test_unlimited_or_missing_cgroup_uses_memavailable(self):
        (self.cgroup/'memory.max').write_text('max')
        self.assertEqual(report.memory_snapshot(self.proc,self.cgroup),(2097152,1048576,False))
        (self.proc/'meminfo').unlink()
        self.assertEqual(report.memory_snapshot(self.proc,self.cgroup),(None,None,False))

    def test_pss_apportions_shared_pages_and_requires_all_core_samples(self):
        for pid,value in [(10,12000),(11,10000)]:
            path=self.proc/str(pid);path.mkdir();(path/'smaps_rollup').write_text(f'Pss: {value} kB\n')
        self.assertEqual(report.pss_snapshot(self.rows,self.proc),22000)
        (self.proc/'11/smaps_rollup').unlink()
        self.assertIsNone(report.pss_snapshot(self.rows,self.proc))

    def test_bilingual_reports_do_not_promise_capacity_and_show_shortage(self):
        for english,warning in [(True,'Insufficient headroom'),(False,'余量不足')]:
            output=report.render(self.rows,524288,200000,True,22000,english)
            self.assertIn(warning,output)
            self.assertIn('2',output)
            self.assertIn('not guaranteed' if english else '不能保证',output)
        output=report.render([],None,None,False,None,True)
        self.assertNotIn('additional-account estimate: 0',output)
        self.assertIn('insufficient data',output)
