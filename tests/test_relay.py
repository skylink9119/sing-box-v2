"""Residential landing relay: import privacy, routing ownership and real two-hop forwarding."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import socket
import socketserver
import ssl
import struct
import subprocess
import threading
import time
import types
import unittest
import urllib.parse
import uuid
from unittest.mock import patch

import test_manager as manager
import test_network_features as network
warp=network.warp


class RelayTest(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell
    configure=manager.ManagerTest.configure
    user_setup=manager.ManagerTest.user_setup
    add_user=manager.ManagerTest.add_user
    user_db=manager.ManagerTest.user_db
    save_user_db=manager.ManagerTest.save_user_db
    prepare_argo=manager.ManagerTest.prepare_argo
    prepare_uninstall=manager.ManagerTest.prepare_uninstall
    start_engine=network.FeaturesTest.start_engine
    http_fixture=network.FeaturesTest.http_fixture
    request=network.FeaturesTest.request

    def profile(self,kind='hysteria2',port=24443):
        tls={'enabled':True,'insecure':False,'server_name':'127.0.0.1'}
        d={'type':kind,'server':'127.0.0.1','server_port':port,'tls':tls}
        if kind=='hysteria2':d['password']='landing-only-'+self.password;tls['certificate']=[self.cert.read_text()]
        else:
            d.update(uuid=str(uuid.uuid4()),flow='xtls-rprx-vision')
            tls.update(server_name='node.example',reality={'enabled':True,'public_key':self.public or base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip('='),'short_id':'abcdef12'},utls={'enabled':True,'fingerprint':'chrome'})
        return warp.relay_normalize(d)

    def file(self,outbound):
        p=self.root/'profile.json';p.write_text(json.dumps({'owner':warp.RELAY_OWNER,'schema':1,'outbound':outbound}));return p

    def switch(self,outbound,mode='global',domains='example.com'):
        p=self.file(outbound)
        return self.shell('warp_engine relay_switch '+mode+' '+shlex.quote(str(p))+' '+shlex.quote(domains))

    def test_standard_and_native_reality_links_import_same_verified_profile(self):
        d=self.profile('vless');q={'security':'reality','flow':d['flow'],'type':'tcp','sni':'node.example','fp':'chrome','pbk':d['tls']['reality']['public_key'],'sid':'abcdef12'}
        standard='vless://'+d['uuid']+'@127.0.0.1:24443?'+urllib.parse.urlencode(q)+'#landing'
        authority=base64.b64encode(('auto:'+d['uuid']+'@127.0.0.1:24443').encode()).decode()
        native='vless://'+authority+'?'+urllib.parse.urlencode({'tls':'1','xtls':'2','peer':'node.example','pbk':q['pbk'],'sid':q['sid'],'fp':'chrome','allowInsecure':'0','remarks':'住宅落地'})
        source=self.root/'node.txt'
        for link in (standard,native):
            source.write_text(link);self.assertEqual(warp.relay_import(source),d)

    def test_hy2_ipv6_password_pinning_hopping_and_obfuscation_import(self):
        pin=hashlib.sha256(ssl.PEM_cert_to_DER_cert(self.cert.read_text())).hexdigest()
        source=self.root/'node.txt';source.write_text('hy2://'+urllib.parse.quote(self.password,safe='')+'@[2001:db8::2]:443?'+urllib.parse.urlencode({'sni':'node.example','insecure':'0','pinSHA256':pin,'mport':'20000-20010','obfs':'salamander','obfs-password':'obfuscation-secret'}))
        with self.assertRaises(ValueError):warp.relay_import(source)
        d=warp.relay_import(source,str(self.cert));self.assertEqual(d['password'],self.password);self.assertEqual(d['server'],'2001:db8::2');self.assertEqual(d['server_ports'],['20000:20010']);self.assertFalse(d['tls']['insecure'])
        self.assertEqual(d['tls']['certificate'],[self.cert.read_text().strip()])
        source.write_text(source.read_text().replace(pin,'0'*64))
        with self.assertRaises(ValueError):warp.relay_import(source,str(self.cert))

    def test_import_requires_one_supported_node_and_rejects_external_paths(self):
        source=self.root/'client.json';d=self.profile()
        source.write_text(json.dumps({'outbounds':[{'type':'direct'},d]}));self.assertEqual(warp.relay_import(source),d)
        for value in ({'outbounds':[d,d]},dict(d,detour='other'),dict(d,tls=dict(d['tls'],certificate_path='/etc/shadow')),dict(d,type='http')):
            source.write_text(json.dumps(value))
            with self.assertRaises(ValueError):warp.relay_import(source)

    def test_unsafe_tls_unknown_fields_and_control_input_are_rejected_without_leaks(self):
        source=self.root/'node.txt';output=self.root/'normalized.json'
        for link in ('hy2://secret@127.0.0.1:443?insecure=1','hy2://secret@127.0.0.1:443?insecure=0&insecure=1','hy2://secret@127.0.0.1:443?custom=oops','hy2://secret@127.0.0.1:443\nsecond','hy2://bad%XX@127.0.0.1:443'):
            source.write_text(link)
            r=self.shell('warp_engine relay_prepare '+shlex.quote(str(source))+' '+shlex.quote(str(output))+' ""',ok=False)
            self.assertNotEqual(r.returncode,0);self.assertNotIn('secret',r.stdout+r.stderr);self.assertFalse(output.exists())
        d=self.profile();d['tls']['insecure']=True;source.write_text(json.dumps(d))
        with self.assertRaises(ValueError):warp.relay_import(source)

    def test_private_key_symlink_sources_and_symlink_output_are_rejected(self):
        source=self.root/'node.json';source.write_text(json.dumps(self.profile()));alias=self.root/'alias';alias.symlink_to(source)
        with self.assertRaises(ValueError):warp.relay_import(alias)
        with self.assertRaises(ValueError):warp.relay_import(source,str(self.key))
        out=self.root/'output';out.symlink_to(self.cert);before=self.cert.read_bytes()
        self.assertNotEqual(self.shell('warp_engine relay_prepare '+shlex.quote(str(source))+' '+shlex.quote(str(out))+' ""',ok=False).returncode,0)
        self.assertEqual(before,self.cert.read_bytes())

    def test_global_and_selected_routing_preserve_credentials_and_baseline(self):
        original=self.configure();d=self.profile();self.switch(d)
        cfg=json.loads((self.config/'config.json').read_text());self.assertEqual(cfg['inbounds'],original['inbounds']);self.assertEqual(cfg['route']['final'],'skybyte-relay');self.assertEqual(cfg['outbounds'][-1],d)
        self.switch(d,'restricted','netflix.com');cfg=json.loads((self.config/'config.json').read_text());self.assertEqual(cfg['route']['final'],'direct');self.assertEqual(cfg['route']['rules'][-1]['outbound'],'skybyte-relay')
        self.switch(d,'direct');cfg=json.loads((self.config/'config.json').read_text());self.assertEqual(cfg,original)
        self.assertEqual((self.base/'warp-state.json').stat().st_mode&0o777,0o600)

    def test_existing_and_new_accounts_keep_quota_ledger_and_private_landing_credentials(self):
        self.user_setup(3);a=self.add_user();ledger=self.user_db();d=self.profile();self.switch(d);b=self.add_user('Bob')
        self.assertEqual(self.user_db()['users'][0],ledger['users'][0])
        for uid in (a,b):
            p=self.base/'users'/uid;cfg=json.loads((p/'server.json').read_text());self.assertEqual(cfg['outbounds'][-1],d)
            self.shell('users_export '+uid+' >/dev/null')
            for name in ('nodes.txt','sing-box-client.json','clash-verge.yaml'):
                self.assertNotIn(d['password'],(p/name).read_text())
        self.shell('exports >/dev/null');self.assertNotIn(d['password'],(self.base/'nodes.txt').read_text())

    def test_switching_warp_and_relay_restores_original_policy_and_keeps_saved_profile(self):
        original=self.configure();d=self.profile();self.shell('warp_engine switch restricted 40001 false netflix.com');self.switch(d)
        self.shell('warp_engine switch global 40001 true netflix.com')
        self.shell('warp_engine relay_forget')
        s=warp.read_state(self.base);self.assertEqual(s['port'],40001);self.assertEqual(s['provider'],'warp')
        self.assertEqual(json.loads((self.config/'config.json').read_text())['route']['final'],'skybyte-warp')
        self.switch(d,'direct');self.assertEqual(json.loads((self.config/'config.json').read_text()),original)

    def test_active_relay_cannot_forget_credentials_and_is_not_labelled_warp(self):
        self.configure();d=self.profile();self.switch(d);before=(self.base/'warp-state.json').read_bytes()
        self.assertNotEqual(self.shell('warp_engine relay_forget',ok=False).returncode,0);self.assertEqual(before,(self.base/'warp-state.json').read_bytes())
        self.assertNotEqual(self.shell('warp_engine port',ok=False).returncode,0)
        status=self.shell('warp_engine relay_status;warp_engine status').stdout
        self.assertIn('TLS verification: on',status);self.assertIn('inactive (relay selected)',status);self.assertNotIn(d['password'],status)

    def test_self_loop_and_candidate_failure_leave_all_configs_unchanged(self):
        self.user_setup();a=self.add_user();original=(self.config/'config.json').read_bytes();user=(self.base/'users'/a/'server.json').read_bytes()
        d=self.profile(port=443)
        self.assertNotEqual(self.shell('warp_engine relay_switch global '+shlex.quote(str(self.file(d)))+' example.com',ok=False).returncode,0)
        d=self.profile();self.bin.write_text('#!/bin/sh\nexit 1\n')
        self.assertNotEqual(self.shell('warp_engine relay_switch global '+shlex.quote(str(self.file(d)))+' example.com',ok=False).returncode,0)
        self.assertEqual(original,(self.config/'config.json').read_bytes());self.assertEqual(user,(self.base/'users'/a/'server.json').read_bytes());self.assertFalse((self.base/'warp-state.json').exists())

    def test_custom_direct_baseline_cannot_silently_bypass_global_relay(self):
        cfg=self.configure();cfg['route']['rules']=[{'domain_suffix':['example.com'],'action':'route','outbound':'direct'}];p=self.config/'config.json';p.write_text(json.dumps(cfg));before=p.read_bytes()
        self.assertNotEqual(self.shell('warp_engine relay_switch global '+shlex.quote(str(self.file(self.profile())))+' example.com',ok=False).returncode,0)
        self.assertEqual(before,p.read_bytes());self.assertFalse((self.base/'warp-state.json').exists())

    def test_failed_probe_and_restart_roll_back_without_resetting_users(self):
        self.user_setup();a=self.add_user();self.switch(self.profile(),'restricted','netflix.com')
        original=(self.config/'config.json').read_bytes();state=(self.base/'warp-state.json').read_bytes();ledger=(self.base/'users.json').read_bytes();user=(self.base/'users'/a/'server.json').read_bytes()
        p=self.file(self.profile(port=25443));arg=shlex.quote(str(p))
        self.assertNotEqual(self.shell('relay_verify(){ return 1; };relay_switch global '+arg,ok=False).returncode,0)
        mock='''relay_verify(){ :; };systemctl(){ if [[ $1 == is-active ]];then return 0;fi;if [[ $1 == restart && $2 == sing-box.service ]] && grep -q '"final": "skybyte-relay"' "$CONF";then return 1;fi; };service_healthy(){ :; };relay_switch global '''+arg
        self.assertNotEqual(self.shell(mock,ok=False).returncode,0)
        self.assertEqual(original,(self.config/'config.json').read_bytes());self.assertEqual(state,(self.base/'warp-state.json').read_bytes());self.assertEqual(user,(self.base/'users'/a/'server.json').read_bytes());self.assertEqual(ledger,(self.base/'users.json').read_bytes())

    def test_backup_restore_reconciles_new_accounts_to_saved_landing(self):
        self.user_setup(3);a=self.add_user();d=self.profile();self.switch(d);snap=Path(self.shell('backup').stdout.strip())
        self.switch(self.profile(port=25443));b=self.add_user('Bob');ledger=(self.base/'users.json').read_bytes()
        self.shell('warp_engine restore '+shlex.quote(str(snap)))
        for uid in (a,b):self.assertEqual(json.loads((self.base/'users'/uid/'server.json').read_text())['outbounds'][-1],d)
        self.assertEqual(ledger,(self.base/'users.json').read_bytes());self.assertEqual(warp.read_state(self.base)['relay'],d)

    def test_new_argo_node_reconciles_to_relay_without_overwriting_landing(self):
        self.configure();d=self.profile();self.switch(d)
        self.shell('argo_write_config "$BASE" named node.example 8080 SKYBYTE;warp_reconcile');cfg=json.loads((self.base/'argo-server.json').read_text());self.assertEqual(cfg['outbounds'][-1],d);self.assertEqual(cfg['route']['final'],'skybyte-relay')

    def test_bilingual_menu_and_import_cancel_leave_no_private_temp_files(self):
        self.configure()
        before={str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for lang in ('zh_CN','en_US'):
            r=self.shell('LANGUAGE_CHOICE='+lang+';sub_menu 4;printf "action=%s" "$MAIN_ACTION"',input='10\n');self.assertIn('action=relay',r.stdout)
            guide=self.shell('LANGUAGE_CHOICE='+lang+';relay_menu',input='6\n')
            self.assertIn('6. 使用说明' if lang=='zh_CN' else '6. Usage guide',guide.stdout)
            self.assertIn('/root/landing-hy2-ca.pem',guide.stdout);self.assertIn('fingerprint -sha256',guide.stdout)
            self.assertEqual(before,{str(p.relative_to(self.root)):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
            self.assertFalse(list(self.base.glob('relay-action.*')))
        self.shell('relay_import_menu',input='0\n');self.assertFalse(list(self.base.glob('relay-import.*')))
        self.shell('relay_menu',input='0\n');self.assertFalse(list(self.base.glob('relay-action.*')))
        d=self.profile();self.switch(d);state=(self.base/'warp-state.json').read_bytes();cfg=(self.config/'config.json').read_bytes()
        guide=self.shell('relay_menu',input='6\n');self.assertNotIn(d['password'],guide.stdout+guide.stderr)
        self.assertEqual(state,(self.base/'warp-state.json').read_bytes());self.assertEqual(cfg,(self.config/'config.json').read_bytes())

    def test_pasted_uri_is_not_a_process_argument_or_terminal_output(self):
        self.configure();log=self.root/'args';secret='landing-private-'+uuid.uuid4().hex
        mock='warp_engine(){ printf "%s\\n" "$*" > '+shlex.quote(str(log))+';return 1; };relay_import_menu'
        r=self.shell(mock,input='1\nhy2://'+secret+'@127.0.0.1:24443?insecure=0\n\n',ok=False)
        self.assertNotIn(secret,log.read_text());self.assertNotIn(secret,r.stdout+r.stderr);self.assertFalse(list(self.base.glob('relay-import.*')))

    @unittest.skipUnless(manager.SB,'real protocol engine required')
    def test_probe_process_uses_loopback_and_verified_https_and_always_stops(self):
        d=self.profile();commands=[];original=warp.subprocess.run
        def run(cmd,**kwargs):
            commands.append(cmd)
            if cmd[0]=='curl':return types.SimpleNamespace(returncode=0,stdout='ip=203.0.113.9\n',stderr='')
            return original(cmd,**kwargs)
        with patch.object(warp.subprocess,'run',side_effect=run):self.assertEqual(warp.relay_probe(d,manager.SB),'203.0.113.9')
        curl=commands[-1];self.assertIn('--proto',curl);self.assertIn('=https',curl);self.assertNotIn('-k',curl);self.assertNotIn(d['password'],' '.join(curl))

    def landing(self,kind):
        d=self.profile(kind,manager.port(socket.SOCK_DGRAM if kind=='hysteria2' else socket.SOCK_STREAM))
        if kind=='hysteria2':
            inbound={'type':kind,'listen':'127.0.0.1','listen_port':d['server_port'],'users':[{'password':d['password']}],'tls':{'enabled':True,'certificate_path':str(self.cert),'key_path':str(self.key)}}
        else:
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_3;context.set_alpn_protocols(['h2','http/1.1']);context.load_cert_chain(self.cert,self.key)
            try:context.set_ecdh_curve('X25519')
            except ssl.SSLError:pass
            class Decoy(socketserver.BaseRequestHandler):
                def handle(self):
                    try:
                        self.request.settimeout(3)
                        with context.wrap_socket(self.request,server_side=True) as conn:conn.recv(1024)
                    except (OSError,ssl.SSLError):pass
            class Server(socketserver.ThreadingTCPServer):daemon_threads=True
            decoy=Server(('127.0.0.1',0),Decoy);threading.Thread(target=decoy.serve_forever,daemon=True).start();self.addCleanup(decoy.server_close);self.addCleanup(decoy.shutdown)
            inbound={'type':'vless','listen':'127.0.0.1','listen_port':d['server_port'],'users':[{'uuid':d['uuid'],'flow':d['flow']}],'tls':{'enabled':True,'server_name':'node.example','reality':{'enabled':True,'private_key':self.private,'short_id':['abcdef12'],'handshake':{'server':'127.0.0.1','server_port':decoy.server_address[1]}}}}
        p=self.root/('landing-'+kind+'.json');p.write_text(json.dumps({'log':{'disabled':True},'inbounds':[inbound],'outbounds':[{'type':'direct','tag':'direct'}],'route':{'final':'direct'}}));proc=self.start_engine(p);time.sleep(.15);return d,proc

    def udp_roundtrip(self,proxy):
        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                data,sock=self.request;sock.sendto(data,self.client_address)
        echo=socketserver.UDPServer(('127.0.0.1',0),Echo);threading.Thread(target=echo.serve_forever,daemon=True).start();self.addCleanup(echo.server_close);self.addCleanup(echo.shutdown)
        def exact(sock,n):
            data=b''
            while len(data)<n:
                part=sock.recv(n-len(data))
                if not part:raise EOFError
                data+=part
            return data
        with socket.create_connection(('127.0.0.1',proxy),timeout=5) as control:
            control.sendall(b'\x05\x01\x00');self.assertEqual(exact(control,2),b'\x05\x00');control.sendall(b'\x05\x03\x00\x01'+b'\x00'*6)
            header=exact(control,4);self.assertEqual(header[:2],b'\x05\x00')
            if header[3]==1:address=socket.inet_ntoa(exact(control,4))
            elif header[3]==4:address=socket.inet_ntop(socket.AF_INET6,exact(control,16))
            else:address=exact(control,exact(control,1)[0]).decode()
            port=int.from_bytes(exact(control,2),'big')
            if address in ('0.0.0.0','::'):address='127.0.0.1'
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                client.settimeout(5);data=b'SKYBYTE TWO HOP UDP'
                client.sendto(b'\x00\x00\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('!H',echo.server_address[1])+data,(address,port))
                self.assertTrue(client.recv(4096).endswith(data))

    @unittest.skipUnless(manager.SB,'real protocol engine required')
    def test_real_two_hop_hy2_and_reality_landings_forward_and_fail_closed(self):
        for kind in ('hysteria2','vless'):
            with self.subTest(kind=kind):
                (self.base/'warp-state.json').unlink(missing_ok=True)
                target,payload=self.http_fixture();self.configure('2');self.bin=Path(manager.SB);d,landing=self.landing(kind);entry_port=manager.port(socket.SOCK_DGRAM)
                cfg=json.loads((self.config/'config.json').read_text());cfg['inbounds'][0].update(listen='127.0.0.1',listen_port=entry_port);(self.config/'config.json').write_text(json.dumps(cfg));self.switch(d)
                entry=self.start_engine(self.config/'config.json');mixed=manager.port();p=self.root/('client-'+kind+'.json')
                client={'inbounds':[{'type':'socks','listen':'127.0.0.1','listen_port':mixed}],'outbounds':[dict(self.profile(port=entry_port),password=self.password)],'route':{'final':'skybyte-relay'}};p.write_text(json.dumps(client));self.start_engine(p)
                result=self.request(mixed,'http://127.0.0.1:'+str(target));self.assertEqual(result.stdout,payload,result.stderr)
                self.udp_roundtrip(mixed)
                landing.terminate();landing.wait(timeout=5)
                failed=subprocess.run(['curl','-q','-s','--max-time','2','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(mixed),'http://127.0.0.1:'+str(target)],capture_output=True)
                self.assertNotEqual(failed.returncode,0);self.assertNotEqual(failed.stdout,payload);self.assertIsNone(entry.poll())

    @unittest.skipUnless(manager.SB,'real protocol engine required')
    def test_real_hy2_landing_rejects_untrusted_wrong_name_and_wrong_password(self):
        target,payload=self.http_fixture();d,_=self.landing('hysteria2')
        variations=[]
        bad=copy.deepcopy(d);bad['tls'].pop('certificate');variations.append(bad)
        bad=copy.deepcopy(d);bad['tls']['server_name']='wrong.example';variations.append(bad)
        bad=copy.deepcopy(d);bad['password']='incorrect-password';variations.append(bad)
        for bad in variations:
            with self.subTest(reason='name/trust/authentication'):
                port=manager.port();p=self.root/('negative-'+str(port)+'.json');p.write_text(json.dumps({'log':{'disabled':True},'inbounds':[{'type':'socks','listen':'127.0.0.1','listen_port':port}],'outbounds':[bad],'route':{'final':'skybyte-relay'}}));proc=self.start_engine(p)
                deadline=time.monotonic()+5
                while True:
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.2):break
                    except OSError:
                        if time.monotonic()>deadline:self.fail('negative test listener did not start')
                        time.sleep(.1)
                r=subprocess.run(['curl','-q','-s','--max-time','1','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(port),'http://127.0.0.1:'+str(target)],capture_output=True)
                self.assertNotEqual(r.returncode,0);self.assertNotEqual(r.stdout,payload);proc.terminate();proc.wait(timeout=5)

    @unittest.skipUnless(manager.SB,'real protocol engine required')
    def test_real_account_traffic_via_landing_still_counts_per_user(self):
        target,payload=self.http_fixture();self.user_setup(2,'2',real=True);d,_=self.landing('hysteria2');self.switch(d);a=self.add_user('Alice');b=self.add_user('Bob');self.shell('users_export '+a+' >/dev/null')
        worker=subprocess.Popen([manager.BASH,'-c',self.script('users_engine watch')],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        def cleanup():
            worker.terminate()
            try:worker.wait(timeout=15)
            except subprocess.TimeoutExpired:worker.kill();worker.wait(timeout=5)
        self.addCleanup(cleanup)
        cfg=json.loads((self.base/'users'/a/'sing-box-client.json').read_text());mixed=manager.port();cfg['inbounds'][0]['listen_port']=mixed;p=self.root/'account-client.json';p.write_text(json.dumps(cfg));self.start_engine(p)
        result=self.request(mixed,'http://127.0.0.1:'+str(target));self.assertEqual(result.stdout,payload,result.stderr)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and self.user_db()['users'][0]['download']<len(payload):time.sleep(.1)
        self.assertGreaterEqual(self.user_db()['users'][0]['download'],len(payload));self.assertEqual(self.user_db()['users'][1]['download'],0);self.assertEqual(self.user_db()['users'][1]['id'],b)
