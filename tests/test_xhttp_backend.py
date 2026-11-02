# Copyright (C) 2026 SKYBYTE (skylink9119)
# SPDX-License-Identifier: GPL-3.0-only
import argparse
import base64
import copy
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import ssl
import subprocess
import tarfile
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.parse
import urllib.error
import uuid
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('integrated_xhttp_core', PROJECT / 'src/xhttp_backend.py')
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
ENGINE = os.environ.get('XRAY_BIN', '')
WORK = PROJECT / 'work'
WORK.mkdir(exist_ok=True)


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def options(kind='vision', **changes):
    result = argparse.Namespace(kind=kind, port=str(free_port()), address='127.0.0.1',
        listen='127.0.0.1', name='SKYBYTE 测试', sni='localhost', target='localhost:443',
        path='/test/path', mode='auto', cert='', key='', cdn=False, ca_file=None)
    result.__dict__.update(changes)
    return result


def example_node(kind='vision'):
    private = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    public = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('=')
    node = {'name':'SKYBYTE 测试', 'uuid':str(uuid.uuid4()), 'port':free_port(),
            'address':'127.0.0.1', 'listen':'127.0.0.1', 'sni':'localhost'}
    if kind == 'xhttp-tls':
        node.update(cert=f"tls/{node['uuid']}.crt", key=f"tls/{node['uuid']}.key", cdn=False)
    else:
        node.update(private=private, public=public, short_id=os.urandom(8).hex(), target='localhost:443')
    if kind.startswith('xhttp'):
        node.update(path='/sample/path', mode='auto')
    return node



class TemporaryFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=WORK)
        self.base=Path(self.temp.name)
        self.root=self.base/'managed'
        self.unit=self.base/'skybyte-xray.service'

    def tearDown(self): self.temp.cleanup()

class EditTests(unittest.TestCase):
    def test_edit_preserves_credentials_other_nodes_and_original(self):
        for kind in core.KINDS:
            with self.subTest(kind=kind):
                state = {'schema': 1, 'nodes': {k: example_node(k) for k in core.KINDS}}
                original = copy.deepcopy(state)
                changed_port = free_port()
                while changed_port in [n['port'] for n in state['nodes'].values()]:
                    changed_port = free_port()
                path = '/changed/path' if kind.startswith('xhttp') else None
                edited = core.edit_state(state, kind, 'node.example.com', changed_port, path)
                expected = copy.deepcopy(original)
                expected['nodes'][kind].update(address='node.example.com', port=changed_port)
                if path: expected['nodes'][kind]['path'] = path
                self.assertEqual(edited, expected)
                self.assertEqual(state, original)

    def test_unchanged_port_is_not_probed(self):
        state = {'schema': 1, 'nodes': {'vision': example_node()}}
        with mock.patch.object(core, 'check_port', side_effect=AssertionError('current port')):
            edited = core.edit_state(state, 'vision', '2001:db8::1', state['nodes']['vision']['port'])
        self.assertEqual(edited['nodes']['vision']['address'], '2001:db8::1')

    def test_reject_invalid_edits_and_missing_node(self):
        state = {'schema': 1, 'nodes': {'vision': example_node(), 'xhttp-reality': example_node('xhttp-reality')}}
        for kind, changes in [('vision', {'client_address': 'bad;id'}),
                              ('vision', {'client_address': ''}),
                              ('vision', {'node_port': '0'}),
                              ('vision', {'node_port': state['nodes']['xhttp-reality']['port']}),
                              ('vision', {'path': '/path'}),
                              ('xhttp-reality', {'path': '/bad?query'}),
                              ('xhttp-tls', {'client_address': 'example.com'})]:
            with self.subTest(kind=kind, changes=changes), self.assertRaises(ValueError):
                core.edit_state(state, kind, **changes)

    def test_reject_occupied_port(self):
        state = {'schema': 1, 'nodes': {'vision': example_node()}}
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen()
            with self.assertRaisesRegex(ValueError, '已被占用'):
                core.edit_state(state, 'vision', node_port=listener.getsockname()[1])

class FileTests(TemporaryFixture):
    def test_private_atomic_write(self):
        destination=self.base/'file'
        core.write_private(destination,'private')
        self.assertEqual(destination.stat().st_mode & 0o777,0o600)
        self.assertEqual(destination.read_text(),'private')

    def test_symlinks_and_ancestors_refused(self):
        real=self.base/'real';real.mkdir()
        link=self.base/'link';link.symlink_to(real,target_is_directory=True)
        with self.assertRaises(ValueError): core.write_private(link/'file','data')

    def test_foreign_configuration_preserved(self):
        self.root.mkdir();p=self.root/'config.json';p.write_text('foreign')
        with self.assertRaises(ValueError): core.ensure_owned(self.root,True)
        self.assertEqual(p.read_text(),'foreign')

    def test_foreign_service_preserved(self):
        self.unit.write_text('[Service]\nExecStart=/someone/else\n')
        with self.assertRaises(ValueError): core.unit_guard(self.unit)
        self.assertIn('/someone/else',self.unit.read_text())

    def test_owned_root_private(self):
        core.ensure_owned(self.root,True)
        self.assertEqual(self.root.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.root/'.owner').stat().st_mode & 0o777,0o600)

    def test_language_symlink_refused(self):
        core.ensure_owned(self.root,True)
        outside=self.base/'outside';outside.write_text('do not modify')
        (self.root/'language').symlink_to(outside)
        with self.assertRaises(ValueError): core.ensure_owned(self.root)
        self.assertEqual(outside.read_text(),'do not modify')

    def test_commit_and_rollback_preserve_unknown_file(self):
        core.ensure_owned(self.root,True)
        unknown=self.root/'notes.txt';unknown.write_text('user notes')
        stage=core.make_stage(self.root,{'schema':1,'nodes':{'vision':example_node()}})
        core.write_private(stage/'state.json',core.json_text({'schema':1,'nodes':{'vision':example_node()}}))
        with mock.patch.object(core,'engine_check'):
            core.commit(self.root,stage,Path('/engine'),self.unit,False,False)
        self.assertTrue((self.root/'nodes.txt').exists())
        self.assertEqual(unknown.read_text(),'user notes')
        flags=core.rollback(self.root,self.unit)
        self.assertFalse(flags['active'])
        self.assertFalse((self.root/'state.json').exists())
        self.assertFalse(self.unit.exists())
        self.assertEqual(unknown.read_text(),'user notes')

    def test_failed_validation_does_not_replace_existing_state(self):
        core.ensure_owned(self.root,True)
        old={'schema':1,'nodes':{'vision':example_node()}}
        for path,data in core.render_files(old,self.root).items(): core.write_private(self.root/path,data)
        stage=core.make_stage(self.root,{'schema':1,'nodes':{}})
        core.write_private(stage/'state.json',core.json_text({'schema':1,'nodes':{}}))
        with mock.patch.object(core,'engine_check',side_effect=ValueError('bad engine')):
            with self.assertRaises(ValueError): core.commit(self.root,stage,Path('/engine'),self.unit,True,True)
        self.assertEqual(core.load_state(self.root),old)
        self.assertFalse((self.root/'.transaction').exists())

    def test_unknown_managed_filename_collision_refused(self):
        core.ensure_owned(self.root,True)
        (self.root/'config.json').write_text('foreign custom config')
        stage=core.make_stage(self.root,{'schema':1,'nodes':{}})
        core.write_private(stage/'state.json',core.json_text({'schema':1,'nodes':{}}))
        with self.assertRaises(ValueError): core.commit(self.root,stage,Path('/engine'),self.unit,False,False)
        self.assertEqual((self.root/'config.json').read_text(),'foreign custom config')

    def test_backup_is_private_and_does_not_overwrite(self):
        core.ensure_owned(self.root,True)
        destination=self.base/'backup.tar.gz'
        core.backup(self.root,destination)
        self.assertEqual(destination.stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError): core.backup(self.root,destination)

    def test_archive_rejects_traversal_links_duplicates(self):
        core.ensure_owned(self.root,True)
        for attack in ['traversal','link','duplicate']:
            archive=self.base/(attack+'.tar.gz')
            with tarfile.open(archive,'w:gz') as output:
                item=tarfile.TarInfo('../outside' if attack=='traversal' else 'state.json')
                if attack=='link': item.type=tarfile.SYMTYPE;item.linkname='/etc/passwd';output.addfile(item)
                else:
                    item.size=2;output.addfile(item,io.BytesIO(b'{}'))
                    if attack=='duplicate': output.addfile(item,io.BytesIO(b'{}'))
            with self.subTest(attack=attack),self.assertRaises(ValueError):
                core.restore_stage(self.root,Path('/engine'),archive)

    def test_download_checks_official_digest(self):
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as output: output.writestr('xray',b'test engine')
        data=archive.getvalue()
        asset='Xray-linux-64.zip'
        metadata={'tag_name':core.CORE_VERSION,'draft':False,'prerelease':False,'assets':[{'name':asset,
            'browser_download_url':f'https://github.com/XTLS/Xray-core/releases/download/{core.CORE_VERSION}/{asset}',
            'digest':'sha256:'+hashlib.sha256(data).hexdigest()}]}
        with mock.patch.dict(os.environ,SKYBYTE_GITHUB_TOKEN='test-metadata-token'), mock.patch.object(core.urllib.request,'urlopen',side_effect=[io.BytesIO(json.dumps(metadata).encode()),io.BytesIO(data)]) as fetch:
            core.download_binary(self.base/'xray',asset)
        metadata_request=fetch.call_args_list[0].args[0]
        self.assertEqual(metadata_request.get_header('Authorization'),'Bearer test-metadata-token')
        self.assertIsInstance(fetch.call_args_list[1].args[0],str)
        self.assertEqual((self.base/'xray').read_bytes(),b'test engine')
        self.assertEqual((self.base/'xray').stat().st_mode & 0o777,0o700)

    def test_download_digest_mismatch_rejected(self):
        asset='Xray-linux-64.zip'
        metadata={'tag_name':core.CORE_VERSION,'draft':False,'assets':[{'name':asset,
            'browser_download_url':f'https://github.com/XTLS/Xray-core/releases/download/{core.CORE_VERSION}/{asset}',
            'digest':'sha256:'+'0'*64}]}
        with mock.patch.object(core.urllib.request,'urlopen',side_effect=[io.BytesIO(json.dumps(metadata).encode()),io.BytesIO(b'tampered')]):
            with self.assertRaises(ValueError): core.download_binary(self.base/'xray',asset)
        self.assertFalse((self.base/'xray').exists())

    def test_download_unknown_url_rejected(self):
        asset='Xray-linux-64.zip'
        metadata={'tag_name':core.CORE_VERSION,'assets':[{'name':asset,'browser_download_url':'http://untrusted/xray',
            'digest':'sha256:'+'0'*64}]}
        with mock.patch.object(core.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(metadata).encode())):
            with self.assertRaises(ValueError): core.download_binary(self.base/'xray',asset)

@unittest.skipUnless(ENGINE,'Set XRAY_BIN to the verified official Xray binary')
class EngineTests(TemporaryFixture):
    @classmethod
    def setUpClass(cls):
        cls.cert_temp=tempfile.TemporaryDirectory(dir=WORK)
        cls.cert_base=Path(cls.cert_temp.name)
        cls.cert=cls.cert_base/'cert.pem';cls.private_key=cls.cert_base/'key.pem'
        config=cls.cert_base/'openssl.cnf'
        config.write_text('[req]\nprompt=no\ndistinguished_name=dn\nx509_extensions=extensions\n[dn]\nCN=localhost\n[extensions]\nsubjectAltName=DNS:localhost\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,digitalSignature,keyEncipherment,keyCertSign\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n')
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','3',
            '-config',str(config),'-keyout',str(cls.private_key),'-out',str(cls.cert)],
            check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    @classmethod
    def tearDownClass(cls): cls.cert_temp.cleanup()

    def make_protocol(self,kind,**changes):
        settings=options(kind,**changes)
        if kind=='xhttp-tls': settings.cert=str(self.cert);settings.key=str(self.private_key);settings.ca_file=str(self.cert)
        stage=core.prepare(self.root,Path(ENGINE),settings)
        core.commit(self.root,stage,Path(ENGINE),self.unit,False,False)
        core.finalize(self.root,stage)
        return core.load_state(self.root)['nodes'][kind]

    def test_all_three_configs_accepted_by_official_core(self):
        for kind in core.KINDS:
            node=self.make_protocol(kind)
            filename=self.root/('client-'+kind+'.json')
            core.engine_check(Path(ENGINE),filename)
            self.assertIn(node['uuid'],filename.read_text())
        self.assertEqual(len(core.load_state(self.root)['nodes']),3)

    def test_cli_edit_regenerates_valid_exports_and_preserves_certificates(self):
        for kind in core.KINDS:
            self.make_protocol(kind)
        old = core.load_state(self.root)
        tls = {n: (self.root/n).read_bytes() for n in core.tls_names(old)}
        for kind in core.KINDS:
            new_port = free_port()
            while new_port in [n['port'] for n in core.load_state(self.root)['nodes'].values()]:
                new_port = free_port()
            args = ['--address', 'new.example.com', '--port', str(new_port)]
            if kind.startswith('xhttp'): args += ['--path', '/new/path']
            result = subprocess.run([os.sys.executable, str(PROJECT/'src/xhttp_backend.py'), 'edit',
                '--root', str(self.root), '--unit', str(self.unit), '--binary', ENGINE, '--kind', kind, *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            stage = Path(result.stdout.strip())
            self.assertEqual(core.load_state(self.root)['nodes'][kind], old['nodes'][kind])
            core.commit(self.root, stage, Path(ENGINE), self.unit, False, False)
            core.finalize(self.root, stage)
            node = core.load_state(self.root)['nodes'][kind]
            for field in set(old['nodes'][kind]) - {'address', 'port', 'path'}:
                self.assertEqual(node[field], old['nodes'][kind][field])
            self.assertEqual(node['address'], 'new.example.com')
            self.assertEqual(node['port'], new_port)
            if kind.startswith('xhttp'): self.assertEqual(node['path'], '/new/path')
            core.engine_check(Path(ENGINE), self.root/('client-'+kind+'.json'))
            self.assertIn(core.node_uri(kind, node), (self.root/'nodes.txt').read_text())
            self.assertEqual(base64.b64decode((self.root/'subscription-base64.txt').read_text()).decode(),
                             (self.root/'nodes.txt').read_text())
            for relative, data in tls.items(): self.assertEqual((self.root/relative).read_bytes(), data)

    def test_existing_protocol_not_overwritten(self):
        node=self.make_protocol('vision')
        with self.assertRaises(ValueError): core.prepare(self.root,Path(ENGINE),options())
        self.assertEqual(core.load_state(self.root)['nodes']['vision'],node)

    def test_port_collision_not_overwritten(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen()
            with self.assertRaisesRegex(ValueError, '已被占用'):
                core.prepare(self.root,Path(ENGINE),options(port=str(listener.getsockname()[1])))
        self.assertFalse((self.root/'state.json').exists())

    def test_certificate_key_and_hostname_validation(self):
        core.certificate(self.cert,self.private_key,'localhost',str(self.cert))
        with self.assertRaises(ValueError): core.certificate(self.cert,self.private_key,'other.example',str(self.cert))
        with self.assertRaises(ValueError): core.certificate(self.cert,self.private_key,'localhost')
        alternate=self.cert_base/'other.key'
        subprocess.run(['openssl','genrsa','-out',str(alternate),'2048'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        with self.assertRaises(ssl.SSLError): core.certificate(self.cert,alternate,'localhost',str(self.cert))

    def test_certificate_sources_preserved(self):
        before=self.private_key.read_bytes()
        self.make_protocol('xhttp-tls')
        self.assertEqual(self.private_key.read_bytes(),before)
        node=core.load_state(self.root)['nodes']['xhttp-tls']
        self.assertEqual((self.root/node['key']).stat().st_mode & 0o777,0o600)

    def test_encrypted_key_fails_without_interactive_password_prompt(self):
        encrypted = self.base / 'encrypted.key'
        subprocess.run(['openssl', 'pkey', '-in', str(self.private_key), '-aes-256-cbc',
                        '-passout', 'pass:test-fixture-only', '-out', str(encrypted)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        original = encrypted.read_bytes()
        result = subprocess.run([os.environ.get('PYTHON_BIN', 'python3'), str(PROJECT / 'src/xhttp_backend.py'),
                                 'tls-input', '--sni', 'localhost', '--cert', str(self.cert), '--key', str(encrypted)],
                                input='', capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Encrypted private keys are not supported', result.stderr)
        self.assertNotIn('Enter PEM', result.stderr)
        self.assertEqual(encrypted.read_bytes(), original)
        self.assertFalse(self.root.exists())

    def test_backup_restore_preserves_uuid_keys_and_exports(self):
        for kind in core.KINDS: self.make_protocol(kind)
        original=core.load_state(self.root)
        uri_before=(self.root/'nodes.txt').read_text()
        archive=self.base/'backup.tar.gz';core.backup(self.root,archive)
        stage=core.restore_stage(self.root,Path(ENGINE),archive,str(self.cert))
        self.assertEqual(core.load_state(stage),original)
        core.commit(self.root,stage,Path(ENGINE),self.unit,False,False)
        core.finalize(self.root,stage)
        self.assertEqual((self.root/'nodes.txt').read_text(),uri_before)

    def test_real_vision_connection(self): self.real_connection('vision')
    def test_real_xhttp_reality_connection(self): self.real_connection('xhttp-reality')
    def test_real_xhttp_tls_verified_connection(self): self.real_connection('xhttp-tls')
    def test_real_cdn_packet_up_origin_connection(self): self.real_connection('xhttp-tls',cdn=True,mode='packet-up')
    def test_private_ip_rejected(self): self.real_connection('vision',block_private=True)
    def test_private_hostname_rejected(self): self.real_connection('vision',block_private=True,destination_host='localhost')

    def test_edited_nodes_forward_with_preserved_credentials(self):
        for kind in core.KINDS:
            with self.subTest(kind=kind):
                self.real_connection(kind, edit_before_connect=True)

    def real_connection(self,kind,block_private=False,destination_host=None,edit_before_connect=False,**changes):
        # Private lab: trusted local CA, HTTPS camouflage target, and local HTTP endpoint.
        tls_listener=socket.socket();tls_listener.bind(('127.0.0.1',0));tls_listener.listen();tls_listener.settimeout(0.25)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(str(self.cert),str(self.private_key));context.set_alpn_protocols(['h2'])
        stopped=threading.Event()
        def tls_worker():
            while not stopped.is_set():
                try:
                    connection,_=tls_listener.accept();connection.settimeout(3)
                    try:
                        with context.wrap_socket(connection,server_side=True) as secure:
                            try: secure.recv(4096)
                            except (OSError,ssl.SSLError): pass
                    except (OSError,ssl.SSLError): connection.close()
                except socket.timeout: pass
                except OSError: break
        thread=threading.Thread(target=tls_worker,daemon=True);thread.start()
        import http.server
        reached=threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                reached.set()
                body=b'SKYBYTE authenticated proxy test'
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def log_message(self,*args): pass
        endpoint=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        http_thread=threading.Thread(target=endpoint.serve_forever,daemon=True);http_thread.start()
        processes=[]
        try:
            node=self.make_protocol(kind,target='localhost:'+str(tls_listener.getsockname()[1]),**changes)
            if edit_before_connect:
                new_port = free_port()
                while new_port in [n['port'] for n in core.load_state(self.root)['nodes'].values()]:
                    new_port = free_port()
                state = core.edit_state(core.load_state(self.root), kind, 'localhost', new_port,
                                        '/edited/forwarding' if kind.startswith('xhttp') else None)
                stage = core.make_stage(self.root, state)
                core.finish_stage(stage, state, Path(ENGINE))
                core.commit(self.root, stage, Path(ENGINE), self.unit, False, False)
                core.finalize(self.root, stage)
                edited = core.load_state(self.root)['nodes'][kind]
                for field in set(node) - {'address', 'port', 'path'}:
                    self.assertEqual(edited[field], node[field])
                node = edited
            server=core.server_config(core.load_state(self.root),self.root)
            if not block_private:
                server['routing']['rules']=[]  # Allow only the isolated lab's endpoint in connection tests.
                # v26.10.29 also enforces private-target protection in Freedom.
                # This exception exists only in the disposable test config.
                server['outbounds'][0]['settings']={'finalRules':[{'action':'allow','network':'tcp',
                    'ip':['127.0.0.1/32'],'port':endpoint.server_address[1]}]}
            server_path=self.base/'lab-server.json';core.write_private(server_path,core.json_text(server))
            socks_port=free_port();client=core.client_config(kind,node,socks_port)
            if kind=='xhttp-tls':
                client['outbounds'][0]['streamSettings']['tlsSettings']['certificates']=[{
                    'certificateFile':str(self.cert),'usage':'verify'}]
            client_path=self.base/'lab-client.json';core.write_private(client_path,core.json_text(client))
            core.engine_check(Path(ENGINE),server_path);core.engine_check(Path(ENGINE),client_path)
            for config_path in [server_path,client_path]:
                processes.append(subprocess.Popen([ENGINE,'run','-config',str(config_path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
            for _ in range(50):
                try:
                    with socket.create_connection(('127.0.0.1',socks_port),timeout=.2): break
                except OSError: time.sleep(.1)
            for process in processes: self.assertIsNone(process.poll(),'Lab process failed to start')
            with socket.create_connection(('127.0.0.1',socks_port),timeout=15) as connection:
                connection.settimeout(20)
                def receive(count):
                    data=b''
                    while len(data)<count:
                        chunk=connection.recv(count-len(data))
                        if not chunk: raise AssertionError('Proxy closed before authenticated response')
                        data+=chunk
                    return data
                connection.sendall(b'\x05\x01\x00');self.assertEqual(receive(2),b'\x05\x00')
                number=endpoint.server_address[1]
                target=b'\x01\x7f\x00\x00\x01' if destination_host is None else b'\x03'+bytes([len(destination_host)])+destination_host.encode()
                connection.sendall(b'\x05\x01\x00'+target+number.to_bytes(2,'big'))
                header=receive(4);self.assertEqual(header[1],0)
                if header[3]==1: receive(6)
                elif header[3]==4: receive(18)
                else: receive(receive(1)[0]+2)
                connection.sendall(b'GET / HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n')
                response=b''
                if block_private: connection.settimeout(2)
                while b'SKYBYTE authenticated proxy test' not in response:
                    try: chunk=connection.recv(4096)
                    except (socket.timeout,ConnectionResetError):
                        if block_private: break
                        raise
                    if not chunk: break
                    response+=chunk
                if block_private:
                    self.assertFalse(reached.is_set(),'Private HTTP endpoint was reached through the proxy')
                    self.assertNotIn(b'SKYBYTE authenticated proxy test',response)
                else: self.assertIn(b'SKYBYTE authenticated proxy test',response)
        finally:
            for process in processes:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait()
            stopped.set();tls_listener.close();endpoint.shutdown();endpoint.server_close();thread.join(timeout=4);http_thread.join(timeout=2)
