"""Network features use isolated files, local protocol servers and explicit response fixtures."""
import base64
import http.server
import importlib.util
import json
import os
from pathlib import Path
import select
import shlex
import socket
import socketserver
import subprocess
import threading
import time
import types
import unittest
from unittest.mock import patch

import test_manager as manager


def module(name):
    spec=importlib.util.spec_from_file_location('skybyte_'+name,manager.ROOT/'src'/ (name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


media=module('media')
warp=module('warp')


class FeaturesTest(unittest.TestCase):
    setUp=manager.ManagerTest.setUp
    script=manager.ManagerTest.script
    shell=manager.ManagerTest.shell
    configure=manager.ManagerTest.configure
    user_setup=manager.ManagerTest.user_setup
    add_user=manager.ManagerTest.add_user
    user_db=manager.ManagerTest.user_db
    save_user_db=manager.ManagerTest.save_user_db
    prepare_legacy_timer=manager.ManagerTest.prepare_legacy_timer
    prepare_uninstall=manager.ManagerTest.prepare_uninstall
    prepare_argo=manager.ManagerTest.prepare_argo

    def switch(self,mode='restricted',udp=False,port=40000):
        self.shell('warp_engine switch '+mode+' '+str(port)+' '+str(udp).lower()+' '+shlex.quote(' '.join(warp.MEDIA+warp.AI)))

    def response(self,body='',code=200,error=False,url='https://www.example.com/'):
        return {'body':body,'code':code,'error':error,'url':url}

    def profile(self,listen=0,peer=2408):
        key=base64.b64encode(os.urandom(32)).decode();public=base64.b64encode(os.urandom(32)).decode()
        f=self.root/'warp.conf';f.write_text('[Interface]\nPrivateKey = '+key+'\nAddress = 172.16.0.2/32, fd77::1/128\nListenPort = '+str(listen)+'\n[Peer]\nPublicKey = '+public+'\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = 127.0.0.1:'+str(peer)+'\n')
        return f,key

    def test_streaming_200_or_region_hint_is_never_full_unlock(self):
        for service in media.PROBES:
            result=media.classify(service,[self.response('<html>OK</html>')])
            self.assertEqual(result['status'],'unknown')
        r=media.classify('Amazon Prime Video',[self.response('"currentTerritory":"JP"')])
        self.assertEqual(r['region'],'JP');self.assertEqual(r['status'],'unknown')
        r=media.classify('YouTube Premium',[self.response('"countryCode":"US"')])
        self.assertEqual(r['status'],'unknown');self.assertEqual(r['region'],'US')
        self.assertEqual(r['region_source'],'countryCode')

    def test_streaming_region_fields_escaped_json_and_url_locale_are_reported(self):
        cases=(
            ('Netflix',r'{\"requestCountry\":{\"id\":\"HK\"}}','HK','requestCountry.id'),
            ('Disney+',r'{\"country_code\":\"us\"}','US','country_code'),
            ('YouTube Premium',r'{\"gl\":\"jp\"}','JP','gl'),
            ('Amazon Prime Video',r'{\"currentTerritory\":\"GB\"}','GB','currentTerritory'),
            ('TikTok',r'{\"data\":{\"store_region\":\"sc\"}}','SC','store_region'))
        for service,body,region,source in cases:
            with self.subTest(service=service):
                result=media.classify(service,[self.response(body)])
                self.assertEqual((result['region'],result['region_source']),(region,source))
                self.assertNotIn(result['status'],('catalog','offer','supported'))
        result=media.classify('Disney+',[self.response('',url='https://www.disneyplus.com/en-gb')])
        self.assertEqual((result['region'],result['region_source']),('GB','final URL locale'))
        self.assertEqual(media.region_label('US/HK','zh_CN'),'美国 (US)/香港 (HK)')
        result=media.classify('Netflix',[self.response(r'{\"requestCountry\":{\"id\":\"HK\"},\"countryCode\":\"US\"}')])
        self.assertEqual(result['region'],'HK/US')
        self.assertEqual(result['region_source'],'requestCountry.id, countryCode')
        result=media.classify('Amazon Prime Video',[self.response('{"countryCode":"US","details":{"countryCode":"HK"}}')])
        self.assertEqual((result['region'],result['region_source']),('US/HK','countryCode'))
        result=media.classify('Disney+',[self.response('{"countryCode":"US"}',code=403)])
        self.assertEqual((result['region'],result['status']),('-','verification'))

    def test_streaming_location_restrictions_require_explicit_page_evidence(self):
        for service,body in (
            ('Netflix','This title is not available to watch in your area.'),
            ('Amazon Prime Video','This video is currently unavailable to watch in your location.'),
            ('TikTok','This content is not available in your region.')):
            with self.subTest(service=service):
                result=media.classify(service,[self.response(body)])
                self.assertEqual(result['status'],'restricted')
        result=media.classify('Netflix',[self.response('A title is unavailable')])
        self.assertEqual(result['status'],'unknown')
        result=media.classify('Netflix',[self.response('Help: catalogs vary by country because of licensing')])
        self.assertEqual(result['status'],'unknown')
        result=media.classify('Disney+',[self.response(r'{\"inSupportedLocation\":false}')])
        self.assertEqual(result['status'],'restricted')
        self.assertEqual(media.status_color('restricted'),'\033[1;31m')
        self.assertEqual(media.status_color('network'),'\033[1;31m')
        self.assertEqual(media.status_color('unknown'),'\033[1;33m')

    def test_streaming_positive_evidence_and_explicit_restriction(self):
        r=media.classify('Netflix',[self.response('<meta property="og:video" content="preview"> "requestCountry":{"id":"HK"}')])
        self.assertEqual(r['status'],'catalog');self.assertEqual(r['region'],'HK')
        self.assertIn('unverified',media.LABELS[r['status']][1])
        r=media.classify('Disney+',[self.response('"inSupportedLocation":false')]);self.assertEqual(r['status'],'restricted')
        r=media.classify('YouTube Premium',[self.response('Premium is not available in your country')]);self.assertEqual(r['status'],'restricted')
        r=media.classify('YouTube Premium',[self.response('purchaseButtonOverride')]);self.assertEqual(r['status'],'offer')
        r=media.classify('TikTok',[self.response('OK'),self.response('{"data":{"store_region":"gb"}}')])
        self.assertEqual(r['region'],'GB');self.assertEqual(r['status'],'unknown')

    def test_streaming_errors_and_challenges_are_unknown_not_blocked(self):
        for code in (403,429,451):
            r=media.classify('Disney+',[self.response('"inSupportedLocation":false',code)])
            self.assertEqual(r['status'],'verification')
        self.assertEqual(media.classify('Netflix',[self.response('og:video',error=True)])['status'],'network')
        self.assertEqual(media.classify('Netflix',[self.response('verify you are human <meta property="og:video">')])['status'],'verification')
        self.assertEqual(media.classify('Netflix',[self.response('new page',404)])['status'],'changed')

    def test_media_transport_preserves_tls_and_explicit_network_path(self):
        commands=[]
        def run(cmd,**kwargs):
            commands.append(cmd);Path(cmd[cmd.index('--output')+1]).write_text('safe fixture')
            return types.SimpleNamespace(returncode=0,stdout='200\nhttps://www.youtube.com/premium',stderr='')
        with patch.object(media.subprocess,'run',side_effect=run):
            media.fetch('https://www.youtube.com/premium','6')
            media.fetch('https://www.youtube.com/premium','warp',40000)
        self.assertEqual(commands[0][1],'-q');self.assertIn('-6',commands[0]);self.assertIn('*',commands[0])
        self.assertIn('socks5h://127.0.0.1:40000',commands[1]);self.assertNotIn('-6',commands[1])
        for cmd in commands:
            self.assertNotIn('-k',cmd);self.assertNotIn('--insecure',cmd);self.assertIn('--max-time',cmd);self.assertIn('--proto-redir',cmd)
            self.assertFalse(any('Authorization' in x for x in cmd))

    def test_media_reports_are_private_and_contain_no_raw_page(self):
        with patch.object(media,'probe',side_effect=lambda service,path,port:media.classify(service,[self.response('sensitive-page-body')])):
            rows=media.run(['4'],self.base/'reports',language='en_US')
        self.assertEqual(len(rows),7)
        report=next((self.base/'reports').glob('*.json'))
        self.assertEqual(report.stat().st_mode&0o777,0o600)
        text=report.read_text();self.assertNotIn('sensitive-page-body',text);self.assertFalse(json.loads(text)['playback_verified'])
        report_dir=self.base/'symlink-report';report_dir.symlink_to(self.base/'reports')
        with patch.object(media,'probe',side_effect=lambda service,path,port:media.classify(service,[self.response()])):
            with self.assertRaises(ValueError):media.run(['4'],report_dir)

    def test_warp_modes_preserve_credentials_and_direct_baseline(self):
        original=self.configure('3');self.switch()
        cfg=json.loads((self.config/'config.json').read_text())
        self.assertEqual(cfg['inbounds'],original['inbounds']);self.assertEqual(cfg['route']['final'],'direct')
        self.assertEqual(cfg['outbounds'][-1]['server'],'127.0.0.1')
        self.assertEqual(cfg['outbounds'][-1]['network'],'tcp')
        rule=next(r for r in cfg['route']['rules'] if r.get('outbound')=='skybyte-warp')
        for domain in ('netflix.com','claude.ai','chatgpt.com'):self.assertIn(domain,rule['domain_suffix'])
        self.switch('global',True);cfg=json.loads((self.config/'config.json').read_text())
        self.assertEqual(cfg['route']['final'],'skybyte-warp');self.assertNotIn('network',cfg['outbounds'][-1])
        self.switch('direct');self.assertEqual(json.loads((self.config/'config.json').read_text()),original)

    def test_warp_existing_and_new_users_share_gateway_without_quota_changes(self):
        self.user_setup(3);a=self.add_user();before=self.user_db()
        self.switch();b=self.add_user('Bob')
        for uid in (a,b):
            cfg=json.loads((self.base/'users'/uid/'server.json').read_text())
            self.assertEqual(cfg['outbounds'][-1]['server_port'],40000)
            self.assertEqual(cfg['experimental']['clash_api']['external_controller'].split(':')[0],'127.0.0.1')
        self.assertEqual(self.user_db()['users'][0],before['users'][0])
        self.switch('direct')
        self.assertEqual(json.loads((self.base/'users'/b/'server.json').read_text())['outbounds'],[{'type':'direct','tag':'direct'}])
        self.assertNotEqual(self.user_db()['users'][0]['api_secret'],self.user_db()['users'][1]['api_secret'])

    def test_warp_refuses_custom_routing_and_symlink_state_without_writes(self):
        self.configure('2');self.switch();p=self.config/'config.json';cfg=json.loads(p.read_text());cfg['route']['final']='custom';p.write_text(json.dumps(cfg))
        before=p.read_bytes();state=(self.base/'warp-state.json').read_bytes()
        self.assertNotEqual(self.shell('warp_engine switch global 40000 true netflix.com',ok=False).returncode,0)
        self.assertEqual(before,p.read_bytes());self.assertEqual(state,(self.base/'warp-state.json').read_bytes())
        (self.base/'warp-state.json').unlink();(self.base/'warp-state.json').symlink_to(p)
        self.assertNotEqual(self.shell('warp_engine guard',ok=False).returncode,0)

    def test_warp_validates_every_candidate_before_any_config_commit(self):
        self.user_setup();a=self.add_user();cfg=(self.config/'config.json').read_bytes();user=(self.base/'users'/a/'server.json').read_bytes()
        self.bin.write_text('#!/bin/sh\nexit 1\n')
        self.assertNotEqual(self.shell('warp_engine switch restricted 40000 false netflix.com',ok=False).returncode,0)
        self.assertEqual(cfg,(self.config/'config.json').read_bytes());self.assertEqual(user,(self.base/'users'/a/'server.json').read_bytes())
        self.assertFalse((self.base/'warp-state.json').exists())

    def test_warp_domain_list_rejects_commands_and_control_characters(self):
        self.configure('2')
        for domains in ('example.com; rm -rf /','bad\x1b.com','*.example.com','127.0.0.1','localhost'):
            self.assertNotEqual(self.shell('warp_engine switch restricted 40000 false '+shlex.quote(domains),ok=False).returncode,0)
        self.assertFalse((self.base/'warp-state.json').exists())

    def test_warp_switch_rolls_back_after_node_restart_failure(self):
        original=self.configure('2')
        code='''warp_loopback(){ :; };warp_verify(){ :; };service_healthy(){ :; }
systemctl(){ if [[ $1 == restart && $2 == sing-box.service ]] && grep -q skybyte-warp "$CONF"; then return 1; fi; }
warp_switch restricted 40000 false netflix.com'''
        self.assertNotEqual(self.shell(code,ok=False).returncode,0)
        self.assertEqual(original,json.loads((self.config/'config.json').read_text()))
        self.assertFalse((self.base/'warp-state.json').exists())

    def test_warp_verifies_trace_and_never_disables_tls(self):
        self.shell('curl(){ printf "warp=on\\nip=1.1.1.1\\nloc=US\\n"; }; warp_verify 40000')
        self.assertNotEqual(self.shell('curl(){ printf "warp=off\\n"; }; warp_verify 40000',ok=False).returncode,0)
        self.assertNotEqual(self.shell('curl(){ return 1; }; warp_verify 40000',ok=False).returncode,0)
        log=self.root/'curl-args'
        self.shell('curl(){ printf "%s\\n" "$@" > '+shlex.quote(str(log))+'; printf "warp=on\\nip=1.1.1.1\\nloc=US\\n"; }; warp_verify 40000')
        self.assertNotIn('--insecure',log.read_text());self.assertIn('socks5h://127.0.0.1:40000',log.read_text())
        for trace in ['warp=on', 'warp=on\\nip=127.0.0.1\\nloc=US', 'warp=on\\nip=1.1.1.1\\nloc=invalid']:
            self.assertNotEqual(self.shell('curl(){ printf '+shlex.quote(trace)+'; }; warp_verify 40000',ok=False).returncode,0)

    def test_warp_waits_for_readiness_and_stops_after_bounded_failures(self):
        code='''probe_calls=0
warp_loopback(){ probe_calls=$((probe_calls+1)); [[ $probe_calls -ge 2 ]]; }
warp_verify(){ :; }
sleep(){ :; }
warp_wait_ready 40000
printf 'ATTEMPTS=%s\\n' "$probe_calls"
'''
        self.assertIn('ATTEMPTS=2',self.shell(code).stdout)
        result=self.shell('warp_loopback(){ return 1; }; sleep(){ :; }; warp_wait_ready 40000',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('WARP is not ready',result.stderr+result.stdout)

    def test_platform_presets_preserve_credentials_and_allow_direct_restore(self):
        original=self.configure('2')
        for profile,required,excluded in [('netflix','netflix.com','chatgpt.com'),('disney','disneyplus.com','netflix.com'),('chatgpt','chatgpt.com','disneyplus.com'),('gemini','gemini.google.com','google.com')]:
            suffixes=self.shell('warp_engine profile '+profile).stdout.split()
            self.assertIn(required,suffixes);self.assertNotIn(excluded,suffixes)
            self.shell('warp_engine switch restricted 40000 false '+shlex.quote(' '.join(suffixes)))
            cfg=json.loads((self.config/'config.json').read_text())
            self.assertEqual(cfg['inbounds'],original['inbounds'])
            self.assertEqual(cfg['route']['final'],'direct')
        self.switch('direct')
        self.assertEqual(json.loads((self.config/'config.json').read_text()),original)

    def test_chatgpt_anonymous_probe_distinguishes_explicit_location_and_challenge(self):
        self.assertIn('ChatGPT',media.PROBES)
        for body,code,status in [('Welcome',200,'unknown'),('{"code":"unsupported_country_region_territory"}',403,'restricted'),('verify you are human',403,'verification')]:
            self.assertEqual(media.classify('ChatGPT',[self.response(body,code)])['status'],status)
        self.assertIn('Gemini',media.PROBES)
        self.assertEqual(media.classify('Gemini',[self.response('Gemini is not available in your country',403)])['status'],'restricted')
        self.assertEqual(media.classify('Gemini',[self.response('<script>const msg="not available in your country";</script>Welcome')])['status'],'unknown')
        self.assertEqual(media.classify('ChatGPT',[self.response('<script>const code="unsupported_country";</script>Welcome')])['status'],'unknown')

    def test_warp_install_refuses_residual_registration_before_packages_or_services(self):
        self.configure('2')
        residual=self.root/'old-warp';residual.mkdir()
        code='''need_root(){ :; }
command(){ if [[ $1 == -v && $2 == warp-cli ]]; then return 1; fi; builtin command "$@"; }
apt_install(){ echo UNEXPECTED_INSTALL; return 1; }
systemctl(){ echo UNEXPECTED_SERVICE; return 1; }
WARP_DATA_DIR='''+shlex.quote(str(residual))+'''
warp_install_client
'''
        result=self.shell(code,ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Existing WARP data found',result.stdout+result.stderr)
        self.assertNotIn('UNEXPECTED',result.stdout+result.stderr)

    def test_warp_loopback_check_rejects_public_proxy_listener(self):
        self.shell('ss(){ echo "LISTEN 0 4096 127.0.0.1:40000 0.0.0.0:*"; }; warp_loopback 40000')
        self.assertNotEqual(self.shell('ss(){ echo "LISTEN 0 4096 0.0.0.0:40000 0.0.0.0:*"; }; warp_loopback 40000',ok=False).returncode,0)
        self.assertNotEqual(self.shell('ss(){ :; }; warp_loopback 40000',ok=False).returncode,0)

    def test_native_profile_is_private_and_scripts_are_not_executed(self):
        f,key=self.profile();self.shell('warp_engine gateway '+shlex.quote(str(f))+' 40000')
        cfg=json.loads((self.base/'warp-gateway.json').read_text())
        self.assertEqual(cfg['endpoints'][0]['private_key'],key);self.assertEqual(cfg['inbounds'][0]['listen'],'127.0.0.1')
        self.assertEqual((self.base/'warp-gateway.json').stat().st_mode&0o777,0o600)
        f.write_text(f.read_text().replace('[Peer]','PreUp = touch '+str(self.root/'executed')+'\n[Peer]'))
        before=(self.base/'warp-gateway.json').read_bytes()
        self.assertNotEqual(self.shell('warp_engine gateway '+shlex.quote(str(f))+' 40000',ok=False).returncode,0)
        self.assertFalse((self.root/'executed').exists());self.assertEqual(before,(self.base/'warp-gateway.json').read_bytes())

    @unittest.skipUnless(manager.SB,'sing-box required for native gateway validation')
    def test_native_gateway_validates_with_official_engine(self):
        self.bin=Path(manager.SB);f,_=self.profile()
        self.shell('warp_engine gateway '+shlex.quote(str(f))+' '+str(manager.port()))

    def test_uninstall_removes_owned_gateway_keeps_profile_and_backup(self):
        self.prepare_uninstall();f,key=self.profile();self.shell('warp_engine gateway '+shlex.quote(str(f))+' 40000')
        unit=self.root/'systemd'/'skybyte-warp-gateway.service';unit.write_text('Description=SKYBYTE managed WARP gateway\nExecStart='+str(self.bin)+' run -c '+str(self.base/'warp-gateway.json')+'\n')
        self.switch()
        self.shell('need_root(){ :; }; systemctl(){ :; }; uninstall_manager',input='y\n')
        self.assertFalse(unit.exists());self.assertFalse((self.base/'warp-state.json').exists());self.assertTrue(f.exists())
        snap=next(self.backups.iterdir());self.assertIn(key,(snap/'warp-gateway.json').read_text())
        self.assertEqual((snap/'warp-gateway.json').stat().st_mode&0o777,0o600)

    def test_unowned_gateway_is_preserved(self):
        self.configure('2');(self.base/'warp-gateway.json').write_text('unrelated')
        self.assertNotEqual(self.shell('warp_guard',ok=False).returncode,0)
        self.assertEqual((self.base/'warp-gateway.json').read_text(),'unrelated')
        (self.root/'systemd'/'skybyte-warp-gateway.service').write_text('Description=other\n')
        self.assertNotEqual(self.shell('warp_remove',ok=False).returncode,0)

    def test_hopping_iptables_uses_actual_hy2_port_and_owned_chain(self):
        cfg=self.configure('2');cfg['inbounds'][0]['listen_port']=8443;(self.config/'config.json').write_text(json.dumps(cfg))
        self.shell('nft(){ return 1; }; iptables(){ return 1; };systemctl(){ :; };ufw(){ echo "Status: inactive"; }; hop',input='1\n2\n20000\n40000\ny\n')
        text=(self.base/'hop-iptables.sh').read_text()
        self.assertIn('--to-ports 8443',text);self.assertIn('--dport 20000:40000',text);self.assertNotIn('-F PREROUTING',text)
        self.assertEqual(json.loads((self.base/'state.json').read_text())['hop_target'],8443)
        self.assertIn('hop-iptables.sh stop',(self.root/'systemd'/'singbox-v2-hop.service').read_text())
        subprocess.run([manager.BASH,'-n',str(self.base/'hop-iptables.sh')],check=True)

    def test_hopping_preserves_unowned_chain_and_failed_enable_metadata(self):
        self.configure('2')
        self.assertNotEqual(self.shell('nft(){ return 1; }; iptables(){ return 0; };systemctl(){ :; };hop',input='1\n2\n20000\n20100\ny\n',ok=False).returncode,0)
        self.assertFalse((self.base/'hop-iptables.sh').exists())
        code='nft(){ return 1; }; iptables(){ return 1; };systemctl(){ [[ $1 != enable ]]; };hop'
        self.assertNotEqual(self.shell(code,input='1\n1\n20000\n20100\ny\n',ok=False).returncode,0)
        self.assertFalse(json.loads((self.base/'state.json').read_text())['hop'])

    def test_removed_menu_items_and_legacy_foreign_timer_are_preserved(self):
        r=self.shell('sub_menu 4',input='0\n')
        for label in ('IP information','Basic network checks','HY2 / Shadowrocket checks'):self.assertNotIn(label,r.stdout)
        r=self.shell('sub_menu 5',input='0\n');self.assertNotIn('Weekly',r.stdout)
        self.prepare_legacy_timer();(self.root/'systemd'/'singbox-v2-update.service').write_text('Description=foreign\n')
        self.shell('systemctl(){ echo BAD; };retire_auto_update')
        self.assertTrue((self.root/'systemd'/'singbox-v2-update.timer').exists())

    def test_youtube_invitation_follows_link_in_both_languages(self):
        for language,phrase in [('zh_CN','如果这个脚本对你有帮助'),('en_US','If you find this script helpful')]:
            r=self.shell('need_root(){ :; };flock(){ :; };LANGUAGE_CHOICE='+language+';main',input='0\n')
            self.assertIn('YouTube: https://www.youtube.com/@SKYBYTE9119\n'+phrase,r.stdout)
            self.assertIn('Install nodes' if language=='en_US' else '节点安装',r.stdout)

    def test_ipv6_exports_and_certificate_ip_verification(self):
        self.configure('1');s=json.loads((self.base/'state.json').read_text());s['ip']='2001:db8::1';(self.base/'state.json').write_text(json.dumps(s))
        self.shell('exports');link=(self.base/'nodes.txt').read_text()
        self.assertIn('@[2001:db8::1]:443?',link)
        import urllib.parse
        parsed=urllib.parse.urlsplit((self.base/'shadowrocket-native-nodes.txt').read_text())
        self.assertIn('@[2001:db8::1]:443',base64.b64decode(parsed.netloc).decode())
        subprocess.run([manager.OPENSSL,'req','-x509','-newkey','rsa:2048','-nodes','-days','2','-subj','/CN=::1','-addext','subjectAltName=IP:::1','-keyout',str(self.key),'-out',str(self.cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.shell('validate_certificate '+shlex.quote(str(self.cert))+' '+shlex.quote(str(self.key))+' ::1')

    def start_engine(self,path):
        proc=subprocess.Popen([manager.SB,'run','-c',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def cleanup():
            if proc.poll() is None:proc.terminate()
            try:proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=5)
        self.addCleanup(cleanup)
        return proc

    def http_fixture(self):
        payload=b'SKYBYTE local forwarding fixture'*512
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(payload)
            def log_message(self,*_):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server.server_port,payload

    def socks_fixture(self):
        destinations=[]
        def exact(sock,n):
            data=b''
            while len(data)<n:
                part=sock.recv(n-len(data))
                if not part:raise EOFError
                data+=part
            return data
        class Relay(socketserver.BaseRequestHandler):
            def handle(self):
                sock=self.request;sock.settimeout(5)
                try:
                    version,count=exact(sock,2);exact(sock,count);sock.sendall(b'\x05\x00')
                    version,cmd,reserved,kind=exact(sock,4)
                    if cmd!=1:sock.sendall(b'\x05\x07\x00\x01'+b'\x00'*6);return
                    if kind==1:host=socket.inet_ntoa(exact(sock,4))
                    elif kind==3:host=exact(sock,exact(sock,1)[0]).decode()
                    elif kind==4:host=socket.inet_ntop(socket.AF_INET6,exact(sock,16))
                    else:return
                    port=int.from_bytes(exact(sock,2),'big');destinations.append(host)
                    # The local fixture never sends data to external hosts.
                    if host not in ('127.0.0.1','::1','media.test'):return
                    upstream=socket.create_connection(('127.0.0.1',port),timeout=5)
                    with upstream:
                        sock.sendall(b'\x05\x00\x00\x01'+socket.inet_aton('127.0.0.1')+port.to_bytes(2,'big'))
                        while True:
                            ready=select.select([sock,upstream],[],[],5)[0]
                            if not ready:return
                            for src in ready:
                                data=src.recv(65536)
                                if not data:return
                                (upstream if src is sock else sock).sendall(data)
                except (OSError,EOFError):pass
        class Server(socketserver.ThreadingTCPServer):allow_reuse_address=True;daemon_threads=True
        server=Server(('127.0.0.1',0),Relay);threading.Thread(target=server.serve_forever,daemon=True).start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return server.server_address[1],destinations

    def request(self,proxy,url,resolve=None):
        deadline=time.monotonic()+5;result=None
        while time.monotonic()<deadline:
            cmd=['curl','-q','--silent','--show-error','--max-time','2','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(proxy)]
            if resolve:cmd+=['--connect-to',resolve]
            result=subprocess.run(cmd+[url],capture_output=True)
            if result.returncode==0:return result
            time.sleep(.1)
        return result

    @unittest.skipUnless(manager.SB,'sing-box required for real routing')
    def test_real_domain_routing_only_selected_host_uses_shared_proxy(self):
        target,payload=self.http_fixture();upstream,hits=self.socks_fixture();self.configure('1');self.bin=Path(manager.SB)
        cfg=json.loads((self.config/'config.json').read_text());listen=manager.port()
        cfg['inbounds']=[{'type':'mixed','listen':'127.0.0.1','listen_port':listen}]
        (self.config/'config.json').write_text(json.dumps(cfg))
        self.shell('warp_engine switch restricted '+str(upstream)+' false media.test')
        proc=self.start_engine(self.config/'config.json')
        a=self.request(listen,'http://media.test:'+str(target));self.assertEqual(a.stdout,payload,a.stderr)
        self.assertIn('media.test',hits);before=len(hits)
        b=self.request(listen,'http://127.0.0.1:'+str(target));self.assertEqual(b.stdout,payload,b.stderr)
        self.assertEqual(len(hits),before)
        self.assertIsNone(proc.poll())

    @unittest.skipUnless(manager.SB,'sing-box required for per-user WARP routing')
    def test_real_hy2_users_are_metered_while_using_shared_proxy(self):
        target,payload=self.http_fixture();upstream,hits=self.socks_fixture();self.user_setup(2,'2',real=True)
        self.switch('global',False,upstream);a=self.add_user('Alice');b=self.add_user('Bob')
        self.shell('users_export '+a+' >/dev/null')
        worker=subprocess.Popen([manager.BASH,'-c',self.script('users_engine watch')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        def cleanup():
            if worker.poll() is None:worker.terminate()
            try:worker.communicate(timeout=15)
            except subprocess.TimeoutExpired:worker.kill();worker.communicate(timeout=5)
        self.addCleanup(cleanup)
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and not all(u.get('running') for u in self.user_db()['users']):time.sleep(.1)
        self.assertTrue(all(u.get('running') for u in self.user_db()['users']))
        cfg=json.loads((self.base/'users'/a/'sing-box-client.json').read_text());listen=manager.port();cfg['inbounds'][0]['listen_port']=listen
        path=self.root/'hy2-client.json';path.write_text(json.dumps(cfg));self.start_engine(path)
        result=self.request(listen,'http://127.0.0.1:'+str(target));self.assertEqual(result.stdout,payload,result.stderr)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and self.user_db()['users'][0]['download']<len(payload):time.sleep(.1)
        self.assertGreaterEqual(self.user_db()['users'][0]['download'],len(payload));self.assertEqual(self.user_db()['users'][1]['download'],0)
        self.assertIn('127.0.0.1',hits)

    @unittest.skipUnless(manager.SB,'sing-box required for real WireGuard gateway')
    def test_native_wireguard_shared_gateway_forwards_local_http(self):
        target,payload=self.http_fixture()
        def pair():
            output=subprocess.check_output([manager.SB,'generate','wg-keypair'],text=True)
            return dict(line.split(': ',1) for line in output.strip().splitlines())
        local,remote=pair(),pair();local_udp=manager.port(socket.SOCK_DGRAM);remote_udp=manager.port(socket.SOCK_DGRAM);proxy=manager.port()
        profile=self.root/'real-warp.conf';profile.write_text('[Interface]\nPrivateKey = '+local['PrivateKey']+'\nAddress = 10.77.0.1/32, fd77::1/128\nListenPort = '+str(local_udp)+'\n[Peer]\nPublicKey = '+remote['PublicKey']+'\nAllowedIPs = 0.0.0.0/0, ::/0\nEndpoint = 127.0.0.1:'+str(remote_udp)+'\n')
        self.bin=Path(manager.SB);self.shell('warp_engine gateway '+shlex.quote(str(profile))+' '+str(proxy))
        peer={'log':{'level':'warn'},'inbounds':[],'outbounds':[{'type':'direct','tag':'direct'}],
              'endpoints':[{'type':'wireguard','tag':'peer','system':False,'address':['10.77.0.2/32','fd77::2/128'],'private_key':remote['PrivateKey'],'listen_port':remote_udp,
                            'peers':[{'address':'127.0.0.1','port':local_udp,'public_key':local['PublicKey'],'allowed_ips':['0.0.0.0/0','::/0']}]}], 'route':{'final':'direct','rules':[{'action':'route-options','override_address':'127.0.0.1'}]}}
        f=self.root/'wireguard-peer.json';f.write_text(json.dumps(peer));self.start_engine(f);gateway=self.start_engine(self.base/'warp-gateway.json')
        result=self.request(proxy,'http://198.18.0.1:'+str(target));self.assertEqual(result.stdout,payload,result.stderr)
        result=self.request(proxy,'http://[2001:db8:77::1]:'+str(target));self.assertEqual(result.stdout,payload,result.stderr)
        self.assertIsNone(gateway.poll())
        self.assertEqual(self.shell('warp_proxy_capability '+str(proxy)).stdout.strip(),'true')

        class Echo(socketserver.BaseRequestHandler):
            def handle(self):
                data,sock=self.request;sock.sendto(data,self.client_address)
        udp=socketserver.UDPServer(('127.0.0.1',0),Echo)
        threading.Thread(target=udp.serve_forever,daemon=True).start()
        self.addCleanup(udp.server_close);self.addCleanup(udp.shutdown)
        def exact(sock,n):
            data=b''
            while len(data)<n:
                part=sock.recv(n-len(data))
                if not part:raise EOFError
                data+=part
            return data
        with socket.create_connection(('127.0.0.1',proxy),timeout=5) as control:
            control.sendall(b'\x05\x01\x00');self.assertEqual(exact(control,2),b'\x05\x00')
            control.sendall(b'\x05\x03\x00\x01'+b'\x00'*6)
            head=exact(control,4);self.assertEqual(head[:2],b'\x05\x00')
            if head[3]==1:address=socket.inet_ntoa(exact(control,4))
            elif head[3]==4:address=socket.inet_ntop(socket.AF_INET6,exact(control,16))
            else:address=exact(control,exact(control,1)[0]).decode()
            relay_port=int.from_bytes(exact(control,2),'big')
            if address in ('0.0.0.0','::'):address='127.0.0.1'
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
                client.settimeout(5)
                packet=b'\x00\x00\x00\x01'+socket.inet_aton('198.18.0.1')+udp.server_address[1].to_bytes(2,'big')+b'WG-UDP'
                client.sendto(packet,(address,relay_port))
                self.assertTrue(client.recv(4096).endswith(b'WG-UDP'))

    def test_warp_backup_restore_reconciles_accounts_created_after_snapshot(self):
        self.user_setup(3);a=self.add_user();snapshot=Path(self.shell('systemctl(){ return 1; };backup').stdout.strip())
        self.switch('global');b=self.add_user('Bob');before=self.user_db()
        self.shell('warp_engine restore '+shlex.quote(str(snapshot)))
        self.assertFalse((self.base/'warp-state.json').exists())
        for uid in (a,b):self.assertEqual(json.loads((self.base/'users'/uid/'server.json').read_text())['route']['final'],'direct')
        self.assertEqual(before,self.user_db())

    def test_hopping_generated_iptables_script_cleans_only_its_chain(self):
        self.configure('2')
        self.shell('nft(){ return 1; };iptables(){ return 1; };systemctl(){ :; };ufw(){ echo "Status: inactive"; };hop',input='1\n2\n21000\n21100\ny\n')
        tools=self.root/'fake-tools';tools.mkdir();log=self.root/'iptables.log';exe=tools/'iptables'
        exe.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> '+shlex.quote(str(log))+'\ncase "$*" in *REDIRECT*) exit 1;; esac\n');exe.chmod(0o700)
        env=os.environ.copy();env['PATH']=str(tools)+':'+env['PATH']
        result=subprocess.run([manager.BASH,str(self.base/'hop-iptables.sh'),'start'],env=env,capture_output=True)
        self.assertNotEqual(result.returncode,0)
        text=log.read_text();self.assertIn('-F SKYBYTE_HY2_HOP',text);self.assertIn('-X SKYBYTE_HY2_HOP',text);self.assertNotIn('-F PREROUTING',text)

    def test_argo_created_after_warp_inherits_policy_and_removal_forgets_tracking(self):
        self.configure('2');self.switch('global')
        self.shell('argo_write_config "$BASE" named node.example 8080 SKYBYTE;warp_reconcile')
        cfg=json.loads((self.base/'argo-server.json').read_text());self.assertEqual(cfg['route']['final'],'skybyte-warp')
        self.shell('systemctl(){ :; };argo_remove_internal')
        state=json.loads((self.base/'warp-state.json').read_text());self.assertNotIn(str(self.base/'argo-server.json'),state['configs'])

    def test_native_import_rolls_back_previous_profile_when_verification_fails(self):
        self.configure('2');f,key=self.profile()
        self.shell('warp_engine gateway '+shlex.quote(str(f))+' 40000')
        unit=self.root/'systemd'/'skybyte-warp-gateway.service';unit.write_text('Description=SKYBYTE managed WARP gateway\nExecStart='+str(self.bin)+' run -c '+str(self.base/'warp-gateway.json')+'\n')
        original=(self.base/'warp-gateway.json').read_bytes();f,key=self.profile()
        code='systemctl(){ :; };ss(){ :; };warp_verify(){ return 1; };warp_loopback(){ :; };sleep(){ :; };warp_import_gateway'
        r=self.shell(code,input=str(f)+'\n40000\ny\n',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertEqual(original,(self.base/'warp-gateway.json').read_bytes())
        self.assertIn('Gateway verification failed',r.stderr)

    def test_official_client_install_uses_signed_repository_and_proxy_mode(self):
        self.configure('2');(self.root/'os-release').write_text('ID=debian\nVERSION_CODENAME=bookworm\n')
        log=self.root/'commands';installed=self.root/'installed';registered=self.root/'registered'
        tools=self.root/'client-tools';tools.mkdir();client=tools/'warp-cli'
        client.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> '+shlex.quote(str(log))+'''\ncase "$*" in
 *'registration show'*) test -e '''+shlex.quote(str(registered))+''' || exit 1;echo fixture-registration;;
 *'registration new'*) touch '''+shlex.quote(str(registered))+''' ;;esac
''');client.chmod(0o700)
        code='''need_root(){ :; };command(){ if [[ $1 == -v && $2 == warp-cli ]] && [[ ! -f '''+shlex.quote(str(installed))+''' ]]; then return 1; fi; builtin command "$@"; }
apt-get(){ echo "$*" >> '''+shlex.quote(str(log))+'''; if [[ $* == 'install -y cloudflare-warp' ]]; then touch '''+shlex.quote(str(installed))+'''; fi; }
curl(){ local out=;while (($#));do if [[ $1 == -o ]];then out=$2;shift 2;else shift;fi;done;echo key > "$out"; }
gpg(){ local out=;while (($#));do if [[ $1 == --output ]];then out=$2;shift 2;else shift;fi;done;echo key > "$out"; }
systemctl(){ :; };ss(){ :; };sleep(){ :; };warp_loopback(){ :; };warp_verify(){ :; };warp_proxy_capability(){ echo false; };warp_switch(){ echo SWITCHED; }
PATH='''+shlex.quote(str(tools))+''':"$PATH";warp_install_client'''
        r=self.shell(code,input='y\n40000\n');self.assertIn('SWITCHED',r.stdout)
        repo=(self.root/'warp.list').read_text();self.assertIn('signed-by='+str(self.root/'warp.gpg'),repo);self.assertIn('https://pkg.cloudflareclient.com/',repo)
        text=log.read_text();self.assertIn('--accept-tos mode proxy',text);self.assertIn('--accept-tos proxy port 40000',text)
        self.assertLess(text.index('mode proxy'),text.index('--accept-tos connect'))
        self.assertEqual((self.base/'warp-client.json').stat().st_mode&0o777,0o600)

    def test_socks_capability_accepts_fragmented_reply_and_tcp_only(self):
        for supported in (True,False):
            class Handler(socketserver.BaseRequestHandler):
                def handle(self):
                    self.request.recv(3)
                    for byte in b'\x05\x00':
                        self.request.sendall(bytes([byte]));time.sleep(.02)
                    self.request.recv(10)
                    for byte in b'\x05'+(b'\x00' if supported else b'\x07')+b'\x00\x01':
                        self.request.sendall(bytes([byte]));time.sleep(.02)
            with socketserver.TCPServer(('127.0.0.1',0),Handler) as server:
                thread=threading.Thread(target=server.handle_request);thread.start()
                try:r=self.shell('warp_proxy_capability '+str(server.server_address[1]))
                finally:thread.join(timeout=5)
            self.assertEqual(r.stdout.strip(),str(supported).lower())

    def test_dualstack_requires_actual_trace_address_family(self):
        self.configure('2');self.switch()
        mock='''warp_verify(){ :; };curl(){
case "$*" in
 *'dns-query?name=www.cloudflare.com&type=A '*|*'dns-query?name=www.cloudflare.com&type=A') echo '{"Answer":[{"type":1,"data":"104.16.132.229"}]}' ;;
 *'dns-query?name=www.cloudflare.com&type=AAAA'*) echo '{"Answer":[{"type":28,"data":"2606:4700::6810:84e5"}]}' ;;
 *) printf 'warp=on\\nip=104.16.132.229\\n';;esac
};warp_dualstack'''
        r=self.shell(mock)
        self.assertIn('A: WARP egress passed',r.stdout)
        self.assertIn('AAAA: Not verified as WARP egress',r.stdout)
        mock=mock.replace("*) printf 'warp=on", "*'--connect-to www.cloudflare.com:443:['*) printf 'warp=plus\\nip=2606:4700::1\\n';;\n *) printf 'warp=on")
        r=self.shell(mock);self.assertIn('AAAA: WARP egress passed',r.stdout)

    def test_uninstall_iptables_does_not_delete_unowned_nft_table(self):
        self.prepare_uninstall()
        self.shell('nft(){ return 1; };iptables(){ return 1; };systemctl(){ :; };ufw(){ echo "Status: inactive"; };hop',input='1\n2\n21000\n21100\ny\n')
        r=self.shell('need_root(){ :; };systemctl(){ :; };nft(){ echo UNOWNED_NFT; };uninstall_manager',input='y\n')
        self.assertNotIn('UNOWNED_NFT',r.stdout)

    def test_hopping_guard_refuses_changed_exec_path(self):
        self.configure('2');unit=self.root/'systemd'/'singbox-v2-hop.service'
        unit.write_text('Description=singbox V2 HY2 IPv4 port hopping\nExecStart=/other/script\n')
        r=self.shell('systemctl(){ echo BAD_STOP; };hop_disable',ok=False)
        self.assertNotEqual(r.returncode,0);self.assertNotIn('BAD_STOP',r.stdout);self.assertTrue(unit.exists())

    def test_restore_native_gateway_snapshot_keeps_new_user_usage(self):
        self.user_setup(3);a=self.add_user();f,_=self.profile()
        self.shell('warp_engine gateway '+shlex.quote(str(f))+' 40000')
        unit=self.root/'systemd'/'skybyte-warp-gateway.service'
        unit.write_text('Description=SKYBYTE managed WARP gateway\nExecStart='+str(self.bin)+' run -c '+str(self.base/'warp-gateway.json')+'\n')
        self.switch();original=(self.base/'warp-gateway.json').read_bytes()
        snap=Path(self.shell('systemctl(){ return 0; };backup').stdout.strip())
        self.switch('global');b=self.add_user('Bob');before=self.user_db()
        f,_=self.profile();self.shell('warp_engine gateway '+shlex.quote(str(f))+' 40001')
        r=self.shell('systemctl(){ echo "$*"; };warp_restore_snapshot '+shlex.quote(str(snap)))
        self.assertIn('enable --now skybyte-warp-gateway.service',r.stdout)
        self.assertEqual(original,(self.base/'warp-gateway.json').read_bytes())
        self.assertEqual(before,self.user_db())
        for uid in (a,b):
            cfg=json.loads((self.base/'users'/uid/'server.json').read_text())
            self.assertEqual(cfg['route']['final'],'direct');self.assertEqual(cfg['outbounds'][-1]['server_port'],40000)
