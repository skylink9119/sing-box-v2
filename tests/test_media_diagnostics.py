"""Upstream tool integration: no public probes or host configuration changes."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('diagnostics',ROOT/'src/media.py')
media=importlib.util.module_from_spec(spec);spec.loader.exec_module(media)

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.reports=self.root/'reports'

    def metadata(self,data,tool='unlock'):
        name=media.asset_name(tool)
        repo=media.TOOLS[tool][0]
        return {'tag_name':'output','assets':[{'name':name,'digest':'sha256:'+hashlib.sha256(data).hexdigest(),
                 'browser_download_url':'https://github.com/'+repo+'/releases/download/output/'+name}]}

    def fixture(self,rows=None,error='',exit_status=0,raw=None):
        result={'schema_version':'goecs.unlocktests/v1','results':rows or [{'name':'Netflix','status':'Unknown', 'info':'HTTP 200 only','ip_version':'ipv4'}]}
        if error:result['error']=error
        # Local executable captures only arguments and sanitized child environment.
        code='import json,os,sys\nfrom pathlib import Path\n'
        code+='p=Path('+repr(str(self.root/'calls'))+');p.open("a").write(json.dumps({"args":sys.argv[1:],"env":dict(os.environ)})+"\\n")\n'
        code+='print('+repr(raw if raw is not None else json.dumps(result))+')\nsys.exit('+str(exit_status)+')\n'
        return ('#!'+sys.executable+'\n'+code).encode()

    def run_fixture(self,payload,paths=['4'],**kwargs):
        with patch.object(media,'ensure_tool',return_value=(payload,{'repository':'fixture','release':'test'})),contextlib.redirect_stdout(io.StringIO()) as output:
            value=media.run(paths,self.reports,**kwargs)
        return value,output.getvalue()

    def test_architecture_selection_and_unsupported_system(self):
        for arch,expected in [('x86_64','amd64'),('aarch64','arm64'),('armv7l','arm'),('i686','386')]:
            self.assertEqual(media.asset_name('unlock','Linux',arch),'ut-linux-'+expected)
            self.assertEqual(media.asset_name('ecs','Linux',arch),'goecs_linux_'+expected+'.zip')
        with self.assertRaises(ValueError):media.asset_name('unlock','Windows','x86_64')

    def test_verified_asset_cached_and_rehashed_on_every_execution(self):
        data=self.fixture();metadata=self.metadata(data);calls=[]
        def fetch(url,limit):
            calls.append(url);return json.dumps(metadata).encode() if 'api.github' in url else data
        with patch.object(media,'fetch',side_effect=fetch):
            first,_=media.ensure_tool(self.reports,'unlock');second,_=media.ensure_tool(self.reports,'unlock')
            self.assertEqual(first,second);self.assertEqual(sum('releases/download' in x for x in calls),1)
            next((self.root/'diagnostic-tools/unlock').glob('*.asset')).write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):media.ensure_tool(self.reports,'unlock')

    def test_missing_digest_unexpected_url_preview_or_duplicate_asset_refused(self):
        for mode in ('digest','url','preview','duplicate'):
            d=self.metadata(b'payload')
            if mode=='digest':d['assets'][0].pop('digest')
            if mode=='url':d['assets'][0]['browser_download_url']='https://example.com/untrusted'
            if mode=='preview':d['prerelease']=True
            if mode=='duplicate':d['assets']*=2
            with patch.object(media,'fetch',return_value=json.dumps(d).encode()) as fetch:
                with self.assertRaises(ValueError):media.ensure_tool(self.reports,'unlock')
                self.assertEqual(fetch.call_count,1)

    def test_bad_download_digest_never_publishes_cache(self):
        with patch.object(media,'fetch',side_effect=[json.dumps(self.metadata(b'expected')).encode(),b'bad']):
            with self.assertRaises(ValueError):media.ensure_tool(self.reports,'unlock')
        self.assertFalse(list(self.root.rglob('*.asset')))

    def test_archive_only_reads_binary_and_never_extracts_other_files(self):
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            z.writestr('goecs',b'fixture executable');z.writestr('../escape',b'must not be extracted')
        data=archive.getvalue()
        with patch.object(media,'fetch',side_effect=[json.dumps(self.metadata(data,'ecs')).encode(),data]):
            payload,_=media.ensure_tool(self.reports,'ecs')
        self.assertEqual(payload,b'fixture executable');self.assertFalse((self.root/'escape').exists())

    def test_report_and_cache_symlinks_refused_without_modifying_target(self):
        outside=self.root/'outside';outside.mkdir();(self.root/'reports').symlink_to(outside)
        with self.assertRaises(ValueError):media.run(['4'],self.reports)
        self.assertEqual(list(outside.iterdir()),[])

    def test_explicit_path_arguments_proxy_validation_and_default_platforms(self):
        self.assertIn('6',media.unlock_arguments('6'));self.assertIn('0,21',media.unlock_arguments('4'))
        self.assertIn('20',media.unlock_arguments('4',all_platforms=True))
        self.assertIn('socks5://127.0.0.1:40000',media.unlock_arguments('warp',40000))
        for bad in ('direct','socks://anything'):
            with self.assertRaises(ValueError):media.unlock_arguments(bad)
        for port in (0,80,65536,'40000'):
            with self.assertRaises(ValueError):media.unlock_arguments('warp',port)

    def test_real_child_process_preserves_unknown_and_restricts_environment(self):
        with patch.dict(os.environ,{'HTTPS_PROXY':'http://invalid','ALL_PROXY':'socks5://invalid','UNLOCKTESTS_SECRET':'do-not-inherit'}):
            rows,output=self.run_fixture(self.fixture(),['4','warp'],port=40000)
        calls=[json.loads(x) for x in (self.root/'calls').read_text().splitlines()]
        self.assertEqual(len(calls),2);self.assertIn('-socks-proxy',calls[1]['args']);self.assertNotIn('-socks-proxy',calls[0]['args'])
        self.assertNotIn('HTTPS_PROXY',calls[0]['env']);self.assertNotIn('UNLOCKTESTS_SECRET',calls[1]['env'])
        self.assertEqual(rows[0]['results'][0]['status'],'Unknown')
        report=next(self.reports.glob('*.json'));self.assertEqual(report.stat().st_mode&0o777,0o600)
        self.assertFalse(json.loads(report.read_text())['playback_verified'])
        self.assertIn('HTTP 200 only',output)
        self.assertFalse(list(self.root.glob('.unlock-*')))

    def test_unknown_json_schema_or_invalid_response_reports_failure(self):
        for raw in ('<html>error</html>','[]','{"schema_version":"future","results":[]}'):
            with patch.object(media,'ensure_tool',return_value=(self.fixture(raw=raw),{})),contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(ValueError,'incomplete'):media.run(['4'],self.reports)

    def test_partial_results_retained_and_nonzero_status_propagated(self):
        payload=self.fixture(error='deadline',exit_status=1)
        with patch.object(media,'ensure_tool',return_value=(payload,{})),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):media.run(['4','warp'],self.reports,40000)
        report=json.loads(next(self.reports.glob('*.json')).read_text())
        self.assertEqual(len(report['runs']),2);self.assertEqual(report['runs'][0]['error'],'deadline')
        self.assertTrue(report['runs'][0]['results'])

    def test_provider_control_sequences_are_removed(self):
        self.assertNotIn('\n',media.safe_text('Netflix\nFAKE SUCCESS'))
        self.assertNotIn('\x1b',media.safe_text('\x1b[31m'))

    def test_ecs_disables_upload_and_stress_and_only_selected_network_tests(self):
        for mode in ('route','speed','full'):
            args=media.ecs_arguments(mode)
            for flag in ('-upload=false','-log=false','-cpu=false','-memory=false','-disk=false'):self.assertIn(flag,args)
        self.assertIn('-speed=false',media.ecs_arguments('route'))
        self.assertIn('-nt3=false',media.ecs_arguments('speed'))
        self.assertIn('-backtrace=true',media.ecs_arguments('full'))
        with self.assertRaises(ValueError):media.ecs_arguments('bad')

    @unittest.skipUnless(os.name=='posix','process group cleanup requires POSIX')
    def test_timeout_terminates_diagnostic_process_group(self):
        with self.assertRaises(subprocess.TimeoutExpired):media.execute([sys.executable,'-c','import time;time.sleep(30)'],self.root,0.1)

    def test_download_is_https_only_bounded_and_has_no_proxy_environment(self):
        captured=[]
        def fake(args,**kwargs):
            captured.append((args,kwargs));Path(args[args.index('-o')+1]).write_bytes(b'ok')
            return type('Result',(),{'returncode':0})()
        with patch.object(media.subprocess,'run',side_effect=fake):self.assertEqual(media.fetch('https://github.com/test',100),b'ok')
        args,options=captured[0]
        self.assertEqual(args[1],'-q');self.assertIn('--proto-redir',args);self.assertIn('--max-time',args)
        self.assertNotIn('HTTP_PROXY',options['env']);self.assertLess(options['timeout'],70)
        with self.assertRaises(ValueError):media.fetch('http://untrusted',100)

if __name__=='__main__':unittest.main()
