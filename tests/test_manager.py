"""Run real manager functions in an isolated directory; never change host services."""
import base64
import contextlib
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shlex
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASH = os.environ.get('BASH_BIN', 'bash')
SB = os.environ.get('SING_BOX_BIN')
MIHOMO = os.environ.get('MIHOMO_BIN')
OPENSSL = os.environ.get('OPENSSL_BIN', 'openssl')


def port(kind=socket.SOCK_STREAM):
    with socket.socket(type=kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def quoted_yaml_dump(data):
    import yaml
    class QuotedStrings(yaml.SafeDumper):
        pass
    QuotedStrings.add_representer(str, lambda dumper,value: dumper.represent_scalar('tag:yaml.org,2002:str',value,style='"'))
    return yaml.dump(data,Dumper=QuotedStrings)


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base = self.root / 'manager'
        self.config = self.root / 'config'
        self.base.mkdir()
        (self.root/'systemd').mkdir()
        (self.root/'os-release').write_text('ID=debian\nPRETTY_NAME=Debian\n')
        self.config.mkdir()
        self.backups = self.base / 'backups'
        self.backups.mkdir()
        self.bin = self.root / 'sing-box'
        self.bin.write_text('#!/bin/sh\nexit 0\n')
        self.bin.chmod(0o700)
        self.cert = self.root / 'server.crt'
        self.key = self.root / 'server.key'
        subprocess.run([OPENSSL, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-days', '2', '-subj', '/CN=127.0.0.1', '-addext',
                        'subjectAltName=IP:127.0.0.1,DNS:node.example', '-addext', 'basicConstraints=critical,CA:TRUE',
                        '-keyout', str(self.key), '-out', str(self.cert)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.password = secrets.token_urlsafe(24) + ':@ /?#'
        self.uuid = str(uuid.uuid4())
        self.private = self.public = ''
        if SB:
            result = subprocess.check_output([SB, 'generate', 'reality-keypair'], text=True)
            keys = dict(line.split(': ', 1) for line in result.strip().splitlines())
            self.private, self.public = keys['PrivateKey'], keys['PublicKey']

    def script(self, command):
        quote = shlex.quote
        variables = dict(BASE=self.base, CONF=self.config / 'config.json',
                         META=self.base / 'state.json', BACKUP=self.backups, BIN=self.bin,
                         LANG_FILE=self.base / 'language.conf', LANGUAGE_CHOICE='en_US',
                         REPORT=self.base / 'reports', SYSTEMD_DIR=self.root/'systemd',
                         OS_RELEASE=self.root/'os-release', MANAGER_BIN=self.root/'manager-command',
                         MANAGER_LIB=self.root/'manager-lib',
                         SYSCTL_FILE=self.root/'bbr.conf')
        script = 'source ' + quote(str(ROOT / 'singbox-v2.sh')) + '\n'
        script += '\n'.join(k + '=' + quote(str(v)) for k, v in variables.items()) + '\n'
        script += 'openssl(){ command ' + quote(OPENSSL) + ' "$@"; }\n'
        return script + command

    def shell(self, command, input=None, ok=True):
        result = subprocess.run([BASH, '-c', self.script(command)], input=input, text=True, errors='replace',
                                capture_output=True)
        if ok and result.returncode:
            self.fail(result.stderr + result.stdout)
        return result

    def configure(self, mode='3', cert_mode='1'):
        args = [self.config / 'config.json', self.base / 'state.json', '127.0.0.1',
                self.cert, self.key, 'addons.mozilla.org', self.uuid, self.private,
                self.public, secrets.token_hex(4), self.password, '127.0.0.1', mode, cert_mode]
        self.shell('write_config ' + ' '.join(shlex.quote(str(x)) for x in args))
        return json.loads((self.config / 'config.json').read_text())

    def exported(self, mode='3', cert_mode='1', hop=False):
        self.configure(mode, cert_mode)
        meta = json.loads((self.base / 'state.json').read_text())
        # Wrong cached mode: protocol detection must use the actual inbounds.
        meta.update(mode='1' if mode != '1' else '3', hop=hop)
        (self.base / 'state.json').write_text(json.dumps(meta))
        self.shell('exports')
        return json.loads((self.base / 'outbounds.json').read_text())

    def test_case_insensitive_confirmation(self):
        for word in ['yes', 'YES', 'Yes', 'yEs', '  YES  ']:
            self.shell('confirm test', input=word + '\n')
        for word in ['y', 'no', '', 'yes please', 'y e s']:
            self.assertNotEqual(self.shell('confirm test', input=word + '\n', ok=False).returncode, 0)

    def test_port_validation(self):
        for value in ['1', '443', '00443', '65535']:
            self.shell('valid_port ' + value)
        for value in ['0', '65536', '-1', 'abc', '999999999999999999999']:
            self.assertNotEqual(self.shell('valid_port ' + shlex.quote(value), ok=False).returncode, 0)

    def test_bilingual_language_persistence(self):
        self.shell('select_language; load_language; L 中文 English', input='2\n')
        self.assertEqual((self.base / 'language.conf').read_text(), 'en_US\n')
        self.assertEqual((self.base / 'language.conf').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.shell('LANGUAGE_CHOICE=zh_CN; L 中文 English').stdout, '中文')
        self.assertEqual(self.shell('LANGUAGE_CHOICE=en_US; L 中文 English').stdout, 'English')

    def test_three_server_modes(self):
        for mode, types in [('1', ['vless']), ('2', ['hysteria2']), ('3', ['vless', 'hysteria2'])]:
            cfg = self.configure(mode)
            self.assertEqual([i['type'] for i in cfg['inbounds']], types)
            if SB:
                subprocess.run([SB, 'check', '-c', str(self.config / 'config.json')], check=True)

    def test_exports_detect_protocol_and_secure_tls(self):
        for mode, count in [('1', 1), ('2', 1), ('3', 2)]:
            out = self.exported(mode)['outbounds']
            self.assertEqual(len(out), count)
            links = (self.base / 'nodes.txt').read_text().splitlines()
            self.assertEqual(len(links), count)
            encoded = (self.base / 'subscription-base64.txt').read_text()
            self.assertEqual(base64.b64decode(encoded).decode(), '\n'.join(links) + '\n')
            for node in out:
                self.assertFalse(node['tls'].get('insecure', False))
                if node['type'] == 'hysteria2':
                    self.assertEqual(node['password'], self.password)
                    self.assertEqual(node['tls']['certificate'], self.cert.read_text().splitlines())
            self.assertNotIn('PRIVATE KEY', (self.base / 'mihomo-proxies.yaml').read_text())
            for file in self.base.iterdir():
                if file.is_file():
                    self.assertEqual(file.stat().st_mode & 0o777, 0o600)
            if SB:
                subprocess.run([SB, 'check', '-c', str(self.base / 'outbounds.json')], check=True)

    def test_hy2_uri_escapes_password_and_pins_cert(self):
        import urllib.parse
        self.exported('2')
        uri = urllib.parse.urlsplit((self.base / 'nodes.txt').read_text().strip())
        self.assertEqual(urllib.parse.unquote(uri.username), self.password)
        query = urllib.parse.parse_qs(uri.query)
        self.assertEqual(query['insecure'], ['0'])
        der = ssl.PEM_cert_to_DER_cert(self.cert.read_text())
        self.assertEqual(query['pinSHA256'], [hashlib.sha256(der).hexdigest()])
        self.assertNotIn('REPLACE_WITH', (self.base / 'mihomo-proxies.yaml').read_text())
        self.assertIn('custom-certifactes:', (self.base / 'mihomo-proxies.yaml').read_text())

    def test_existing_certificate_and_hopping_export(self):
        out = self.exported('2', '2', True)['outbounds'][0]
        self.assertEqual(out['tls']['certificate'],self.cert.read_text().splitlines())
        self.assertEqual(out['server_ports'], ['20000:30000'])
        self.assertEqual(out['hop_interval'], '30s')
        yaml = (self.base / 'mihomo-proxies.yaml').read_text()
        self.assertIn('skip-cert-verify: false', yaml)
        self.assertIn('ports: "20000-30000"', yaml)

    def test_exports_follow_modified_protocol_ports(self):
        config=self.configure('3')
        for inbound in config['inbounds']: inbound['listen_port']=8443
        (self.config/'config.json').write_text(json.dumps(config))
        self.shell('exports')
        out=json.loads((self.base/'outbounds.json').read_text())['outbounds']
        self.assertEqual([i['server_port'] for i in out],[8443,8443])
        self.assertTrue(all(':8443?' in i for i in (self.base/'nodes.txt').read_text().splitlines()))

    def test_each_node_is_separated_and_trust_notes_are_localized(self):
        self.configure('3')
        for lang, label in [('zh_CN','节点：'),('en_US','Node: ')]:
            result=self.shell('LANGUAGE_CHOICE='+lang+'; exports')
            lines=result.stdout.splitlines()
            for title in ['v2rayN','Clash Verge / Mihomo YAML','sing-box JSON', '小火箭 / Shadowrocket 订阅' if lang=='zh_CN' else 'Shadowrocket subscription']:
                self.assertEqual(lines[lines.index(title)-1],'-'*64)
            self.assertEqual(sum(i.startswith(label) for i in lines),2)
            notes=(self.base/'subscription-notes.txt').read_text()
            self.assertIn('无域名模式仍使用 TLS' if lang=='zh_CN' else 'No-domain mode still uses self-signed TLS',notes)

    def test_ios_trust_profile_contains_only_public_certificate(self):
        import plistlib
        self.exported('2')
        profile=plistlib.loads((self.base/'hy2-client-ca.mobileconfig').read_bytes())
        self.assertEqual(profile['PayloadType'],'Configuration')
        self.assertEqual(len(profile['PayloadContent']),1)
        payload=profile['PayloadContent'][0]
        self.assertEqual(payload['PayloadType'],'com.apple.security.root')
        self.assertEqual(payload['PayloadContent'],ssl.PEM_cert_to_DER_cert(self.cert.read_text()))
        self.assertNotIn(self.password.encode(),(self.base/'hy2-client-ca.mobileconfig').read_bytes())
        self.assertNotIn(self.key.read_bytes(),(self.base/'hy2-client-ca.mobileconfig').read_bytes())
        self.assertEqual((self.base/'hy2-client-ca.mobileconfig').stat().st_mode & 0o777,0o600)
        self.assertEqual((self.base/'hy2-client-ca.cer').read_bytes(),payload['PayloadContent'])

    def test_leaf_cert_does_not_get_root_profile_or_leave_stale_profile(self):
        self.exported('2')
        self.assertTrue((self.base/'hy2-client-ca.mobileconfig').exists())
        subprocess.run([OPENSSL,'req','-x509','-key',str(self.key),'-days','2','-subj','/CN=127.0.0.1',
                        '-addext','subjectAltName=IP:127.0.0.1','-addext','basicConstraints=critical,CA:FALSE',
                        '-out',str(self.cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.shell('exports')
        self.assertFalse((self.base/'hy2-client-ca.mobileconfig').exists())
        self.assertIn('not a CA',(self.base/'subscription-notes.txt').read_text())

    def test_hy2_diagnostics_uses_actual_port_and_does_not_print_credentials(self):
        config=self.configure('2');config['inbounds'][0]['listen_port']=8443
        (self.config/'config.json').write_text(json.dumps(config))
        result=self.shell("""systemctl(){ return 0; }
ss(){ printf 'UNCONN 0 0 0.0.0.0:8443 0.0.0.0:*\\n'; }
ufw(){ printf 'Status: active\\n8443/udp ALLOW Anywhere\\n'; }
hy2_diagnostics""")
        self.assertIn('Local UDP 8443 has a listener',result.stdout)
        self.assertIn('Certificate expiry, name and key matching checks passed',result.stdout)
        self.assertNotIn('allow rule not detected',result.stdout)
        self.assertNotIn(self.password,result.stdout+result.stderr)
        self.assertIn('do not prove phone-to-VPS UDP reachability',result.stdout)

    def test_hy2_diagnostics_reports_stopped_service_and_missing_udp(self):
        self.configure('2')
        result=self.shell("""systemctl(){ return 1; }
ss(){ :; }
ufw(){ printf 'Status: inactive\\n'; }
hy2_diagnostics""")
        self.assertIn('sing-box is not active',result.stderr)
        self.assertIn('No local UDP 443 listener',result.stderr)

    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'PyYAML required for YAML export tests')
    def test_client_specific_exports_match_protocols_and_secure_defaults(self):
        import yaml
        for mode in ['1','2','3']:
            self.exported(mode)
            nodes=(self.base/'nodes.txt').read_text()
            for client in ['v2rayn','shadowrocket']:
                self.assertEqual((self.base/(client+'-nodes.txt')).read_text(),nodes)
                encoded=(self.base/(client+'-subscription.txt')).read_text()
                self.assertEqual(base64.b64decode(encoded).decode(),nodes)
            sb=json.loads((self.base/'sing-box-client.json').read_text())
            self.assertEqual(sb['inbounds'][0]['listen'],'127.0.0.1')
            self.assertEqual(sb['route']['final'],sb['outbounds'][0]['tag'])
            self.assertEqual(len(sb['outbounds']),2 if mode!='3' else 3)
            self.assertFalse(any(i.get('tls',{}).get('insecure',False) for i in sb['outbounds']))
            clash=yaml.safe_load((self.base/'clash-verge.yaml').read_text())
            self.assertFalse(clash['allow-lan'])
            self.assertEqual(clash['proxy-groups'][0]['proxies'],[p['name'] for p in clash['proxies']])
            self.assertEqual(clash['rules'],['MATCH,SKYBYTE'])
            for proxy in clash['proxies']:self.assertFalse(proxy.get('skip-cert-verify',False))
            if SB:subprocess.run([SB,'check','-c',str(self.base/'sing-box-client.json')],check=True)
            if MIHOMO:subprocess.run([MIHOMO,'-t','-d',str(self.root/'mihomo-data'),'-f',str(self.base/'clash-verge.yaml')],
                                     check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def test_custom_node_names_propagate_to_all_formats(self):
        import urllib.parse,yaml
        self.configure('3')
        before=(self.config/'config.json').read_bytes()
        name='HK 测试 #1 & /'
        self.shell('rename_node',input=name+'\n')
        self.assertEqual((self.config/'config.json').read_bytes(),before)
        meta=json.loads((self.base/'state.json').read_text())
        self.assertEqual(meta['node_name'],name)
        expected=[name+'-Reality',name+'-HY2']
        uris=(self.base/'nodes.txt').read_text().splitlines()
        self.assertEqual([urllib.parse.unquote(urllib.parse.urlsplit(u).fragment) for u in uris],expected)
        sb=json.loads((self.base/'sing-box-client.json').read_text())
        self.assertEqual([i['tag'] for i in sb['outbounds'][:-1]],expected)
        self.assertEqual(sb['route']['final'],expected[0])
        clash=yaml.safe_load((self.base/'clash-verge.yaml').read_text())
        self.assertEqual([p['name'] for p in clash['proxies']],expected)
        self.assertEqual(clash['proxy-groups'][0]['proxies'],expected)
        for client in ['v2rayn','shadowrocket']:
            self.assertEqual(base64.b64decode((self.base/(client+'-subscription.txt')).read_text()).decode(),(self.base/'nodes.txt').read_text())
        if SB:subprocess.run([SB,'check','-c',str(self.base/'sing-box-client.json')],check=True)
        if MIHOMO:subprocess.run([MIHOMO,'-t','-d',str(self.root/'mihomo-data'),'-f',str(self.base/'clash-verge.yaml')],check=True,stdout=subprocess.DEVNULL)
        self.shell('rename_node',input='\n')
        self.assertIn('#SKYBYTE-Reality',(self.base/'nodes.txt').read_text())

    def test_node_name_input_defaults_and_rejects_control_characters(self):
        self.assertEqual(self.shell('choose_node_name',input='\n').stdout.strip(),'SKYBYTE')
        self.assertEqual(self.shell('choose_node_name',input='香港节点\n').stdout.strip(),'香港节点')
        for name in ['x'*65,'bad\x1bname','bad\tname']:
            self.assertNotEqual(self.shell('choose_node_name',input=name+'\n',ok=False).returncode,0)

    def test_certificate_names_and_key_matching(self):
        command = 'validate_certificate ' + ' '.join(map(shlex.quote, [str(self.cert), str(self.key)]))
        self.shell(command + ' 127.0.0.1')
        self.shell(command + ' node.example')
        for name in ['127.0.0.2', 'wrong.example']:
            self.assertNotEqual(self.shell(command + ' ' + name, ok=False).returncode, 0)
        other = self.root / 'other.key'
        subprocess.run([OPENSSL, 'genrsa', '-out', str(other), '2048'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertNotEqual(self.shell('validate_certificate ' + ' '.join(map(shlex.quote,
                           [str(self.cert), str(other), '127.0.0.1'])), ok=False).returncode, 0)

    def test_backup_external_tls_and_restore(self):
        self.configure('2')
        before = self.shell('backup').stdout.strip()
        backup = Path(before)
        self.assertTrue((backup / 'sing-box.bin').is_file())
        self.assertTrue((backup / 'config' / 'config.json').is_file())
        self.assertEqual((backup / 'config' / 'hy2-backup.key').read_bytes(), self.key.read_bytes())
        self.cert.unlink()
        self.key.unlink()
        # Current backup requires usable files; restore must back up a still-operating deployment first.
        current = json.loads((self.config / 'config.json').read_text())
        current['inbounds'][0]['tls'].update(certificate_path=str(backup/'config'/'hy2-backup.crt'),
                                          key_path=str(backup/'config'/'hy2-backup.key'))
        (self.config/'config.json').write_text(json.dumps(current))
        self.shell('systemctl(){ :; }; service_healthy(){ :; }; nft(){ :; }; restore',
                   input=before + '\nyEs\n')
        restored = json.loads((self.config/'config.json').read_text())
        self.assertTrue(Path(restored['inbounds'][0]['tls']['key_path']).is_file())
        self.assertFalse(json.loads((self.base/'state.json').read_text())['hop'])

    def test_update_rolls_back_on_failed_start(self):
        self.configure('1')
        original = self.bin.read_bytes()
        code = '''download_binary(){ printf '#!/bin/sh\\nexit 0\\n# candidate\\n' > "$2"; chmod 700 "$2"; }
systemctl(){ :; }
service_healthy(){ return 1; }
apply_update 1.14.3'''
        result = self.shell(code, ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.bin.read_bytes(), original)
        self.assertEqual(list(self.base.glob('sing-box.candidate*')),[])

    def test_update_rejects_invalid_candidate(self):
        self.configure('1')
        original = self.bin.read_bytes()
        code = '''download_binary(){ printf '#!/bin/sh\\nexit 1\\n' > "$2"; chmod 700 "$2"; }
apply_update 1.14.3'''
        self.assertNotEqual(self.shell(code, ok=False).returncode, 0)
        self.assertEqual(self.bin.read_bytes(), original)

    def test_ssh_detection_preserves_connection_port(self):
        result = self.shell('''ss(){ printf '%s\\n' 'LISTEN 0 128 [::]:2222 [::]:* users:(("sshd",pid=1))'; }
SSH_CONNECTION='192.0.2.1 1234 192.0.2.2 2200'
detect_ssh_ports
printf '%s' "$SSH_PORTS"''')
        self.assertIn('2200\n2222', result.stdout)

    def test_firewall_warns_missing_hy2_udp(self):
        self.configure('2')
        result = self.shell("ufw(){ printf 'Status: active\\n22/tcp ALLOW Anywhere\\n'; }; firewall_audit")
        self.assertIn('UDP 443 allow rule not detected', result.stdout)
        self.assertIn('provider firewall', result.stdout)

    def test_vnstat_daily_and_monthly(self):
        for choice, argument in [('2','-d'),('3','-m')]:
            result = self.shell('vnstat(){ printf "VNSTAT %s\\n" "$*"; }; traffic', input=choice+'\n')
            self.assertIn('NOT Reality/HY2 separately', result.stdout)
            self.assertIn('VNSTAT '+argument, result.stdout)

    def test_service_config_checked_before_restart(self):
        result = self.shell('systemctl(){ printf "SYSTEMCTL %s\\n" "$*"; }; service_manager', input='3\nyes\n', ok=False)
        self.assertNotIn('SYSTEMCTL restart', result.stdout)
        self.configure('1')
        result = self.shell('systemctl(){ printf "SYSTEMCTL %s\\n" "$*"; }; service_manager', input='3\nyes\n')
        self.assertIn('SYSTEMCTL restart sing-box', result.stdout)

    def test_ascii_brand_and_bilingual_menus(self):
        for language, text in [('en_US','Nodes and subscriptions'), ('zh_CN','节点与订阅')]:
            result = self.shell('need_root(){ :; }; flock(){ :; }; LANGUAGE_CHOICE='+language+'; main', input='0\n')
            self.assertIn('███████╗', result.stdout)
            self.assertIn('SKYBYTE Manager v2.2.0', result.stdout)
            self.assertIn('https://www.youtube.com/@SKYBYTE9119', result.stdout)
            self.assertIn(text, result.stdout)

    def prepare_uninstall(self):
        self.configure('2')
        self.shell('systemctl(){ :; }; setup_service')
        (self.config/'unrelated.conf').write_text('keep user config')
        (self.base/'unrelated.txt').write_text('keep user file')

    def test_uninstall_cancellation_preserves_deployment(self):
        self.prepare_uninstall()
        self.shell('need_root(){ :; }; uninstall_manager', input='no\n')
        self.assertTrue(self.bin.exists())
        self.assertTrue((self.config/'config.json').exists())
        self.assertEqual(list(self.backups.iterdir()),[])

    def test_uninstall_backs_up_and_preserves_external_certs_and_unknown_files(self):
        self.prepare_uninstall()
        self.shell('exports')
        result=self.shell('need_root(){ :; }; systemctl(){ :; }; nft(){ return 1; }; uninstall_manager', input='yEs\n')
        self.assertIn('Uninstalled;',result.stdout)
        self.assertFalse(self.bin.exists())
        self.assertFalse((self.config/'config.json').exists())
        self.assertFalse((self.base/'state.json').exists())
        for name in ['v2rayn-nodes.txt','shadowrocket-subscription.txt','sing-box-client.json','clash-verge.yaml']:
            self.assertFalse((self.base/name).exists())
        self.assertFalse((self.root/'systemd'/'sing-box.service').exists())
        self.assertTrue(self.cert.exists());self.assertTrue(self.key.exists())
        self.assertTrue((self.config/'unrelated.conf').exists())
        self.assertTrue((self.base/'unrelated.txt').exists())
        snapshots=list(self.backups.iterdir());self.assertEqual(len(snapshots),1)
        self.assertTrue((snapshots[0]/'sing-box.bin').exists())
        self.assertEqual((snapshots[0]/'config'/'hy2-backup.key').read_bytes(),self.key.read_bytes())

    def test_uninstall_removes_owned_auxiliary_units_and_manager_copies(self):
        self.prepare_uninstall()
        self.shell('need_root(){ :; }; systemctl(){ :; }; configure_auto',input='1\n')
        (self.root/'manager-lib').write_bytes((ROOT/'singbox-v2.sh').read_bytes())
        (self.root/'systemd'/'singbox-v2-hop.service').write_text('Description=singbox V2 HY2 IPv4 port hopping\n')
        result=self.shell("""need_root(){ :; }
systemctl(){ printf 'SYSTEMCTL %s\\n' "$*"; }
nft(){ printf 'NFT %s\\n' "$*"; }
uninstall_manager""",input='yes\n')
        self.assertFalse((self.root/'manager-lib').exists())
        self.assertFalse((self.root/'manager-command').exists())
        self.assertEqual(list((self.root/'systemd').iterdir()),[])
        self.assertIn('NFT delete table ip singbox_v2_hop',result.stdout)
        self.assertLess(result.stdout.index('disable --now singbox-v2-update.timer'),
                        result.stdout.index('disable --now sing-box.service'))

    def test_uninstall_preserves_unowned_hop_table_and_executable(self):
        self.prepare_uninstall()
        (self.root/'manager-command').write_text('unrelated executable')
        result=self.shell('need_root(){ :; }; systemctl(){ :; }; nft(){ printf UNEXPECTED_NFT; }; uninstall_manager',input='yes\n')
        self.assertNotIn('UNEXPECTED_NFT',result.stdout)
        self.assertEqual((self.root/'manager-command').read_text(),'unrelated executable')

    def test_uninstall_refuses_symlinked_binary(self):
        self.prepare_uninstall()
        target=self.root/'external-binary';self.bin.rename(target);self.bin.symlink_to(target)
        result=self.shell('need_root(){ :; }; uninstall_manager',input='yes\n',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(target.exists());self.assertTrue(self.bin.is_symlink())

    def test_uninstall_preserves_existing_certificates_even_with_reserved_names(self):
        self.configure('2','2')
        self.shell('systemctl(){ :; }; setup_service')
        cert=self.config/'hy2-selfsigned.crt';key=self.config/'hy2-selfsigned.key'
        cert.write_bytes(self.cert.read_bytes());key.write_bytes(self.key.read_bytes())
        cfg=json.loads((self.config/'config.json').read_text())
        cfg['inbounds'][0]['tls'].update(certificate_path=str(cert),key_path=str(key))
        (self.config/'config.json').write_text(json.dumps(cfg))
        self.shell('need_root(){ :; }; systemctl(){ :; }; uninstall_manager',input='yes\n')
        self.assertTrue(cert.exists());self.assertTrue(key.exists())

    def test_uninstall_removes_new_and_legacy_managed_selfsigned_files(self):
        for legacy in [False,True]:
            self.bin.write_text('#!/bin/sh\nexit 0\n');self.bin.chmod(0o700)
            self.configure('2','1')
            self.shell('systemctl(){ :; }; setup_service')
            cert=self.config/'hy2-selfsigned.crt';key=self.config/'hy2-selfsigned.key'
            cert.write_bytes(self.cert.read_bytes());key.write_bytes(self.key.read_bytes())
            cfg=json.loads((self.config/'config.json').read_text())
            cfg['inbounds'][0]['tls'].update(certificate_path=str(cert),key_path=str(key))
            (self.config/'config.json').write_text(json.dumps(cfg))
            meta=json.loads((self.base/'state.json').read_text());meta['cert_path']=str(cert)
            if legacy:meta.pop('managed_certificates',None)
            else:meta['managed_certificates']=[str(cert),str(key)]
            (self.base/'state.json').write_text(json.dumps(meta))
            self.shell('need_root(){ :; }; systemctl(){ :; }; uninstall_manager',input='yes\n')
            self.assertFalse(cert.exists());self.assertFalse(key.exists())

    def test_uninstall_refuses_modified_service(self):
        self.prepare_uninstall()
        (self.root/'systemd'/'sing-box.service').write_text('Description=another deployment\n')
        result=self.shell('need_root(){ :; }; uninstall_manager',input='yes\n',ok=False)
        self.assertNotEqual(result.returncode,0)
        self.assertTrue(self.bin.exists())
        self.assertTrue((self.config/'config.json').exists())

    def test_uninstall_backup_failure_or_stop_failure_preserves_config(self):
        for failure in ['backup(){ return 1; }','systemctl(){ return 1; }']:
            self.prepare_uninstall()
            result=self.shell('need_root(){ :; }; '+failure+'; uninstall_manager',input='yes\n',ok=False)
            self.assertNotEqual(result.returncode,0)
            self.assertTrue(self.bin.exists())
            self.assertTrue((self.config/'config.json').exists())

    def test_installer_refuses_existing_user_config(self):
        self.configure('2')
        before = (self.config/'config.json').read_bytes()
        result = self.shell('need_root(){ :; }; install_protocol 2', input='yes\n', ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('refusing to overwrite', result.stderr)
        self.assertEqual((self.config/'config.json').read_bytes(), before)

    def test_weekly_auto_update_installs_manager_command(self):
        self.configure('1')
        self.shell('need_root(){ :; }; systemctl(){ :; }; configure_auto', input='1\n')
        self.assertEqual((self.root/'manager-command').read_bytes(), (ROOT/'singbox-v2.sh').read_bytes())
        service = (self.root/'systemd'/'singbox-v2-update.service').read_text()
        self.assertIn('--auto-update', service)
        self.assertTrue((self.root/'systemd'/'singbox-v2-update.timer').exists())

    def test_firewall_enable_keeps_ssh_and_hopping(self):
        self.configure('2')
        meta = json.loads((self.base/'state.json').read_text()); meta['hop']=True
        (self.base/'state.json').write_text(json.dumps(meta))
        result = self.shell("""need_root(){ :; }
ss(){ printf 'LISTEN 0 128 0.0.0.0:2222 0.0.0.0:* users:(("sshd",pid=1))\\n'; }
ufw(){ printf 'UFW %s\\n' "$*"; }
firewall""", input='2\n\nyes\n')
        for rule in ['2222/tcp','443/udp','20000:30000/udp']:
            self.assertIn('UFW allow '+rule,result.stdout)
        self.assertIn('UFW --force enable', result.stdout)

    def test_hopping_persistence_and_disable(self):
        self.configure('2')
        mocks = """nft(){ if [[ $1 == list ]]; then return 1; fi; }
systemctl(){ :; }
ufw(){ printf 'Status: inactive\\n'; }
"""
        self.shell(mocks+'hop', input='1\n20000\n20100\nyes\n')
        self.assertIn('udp dport 20000-20100 redirect to :443', (self.base/'hop.nft').read_text())
        self.assertIn('ExecStop=/usr/sbin/nft delete table ip singbox_v2_hop',
                      (self.root/'systemd'/'singbox-v2-hop.service').read_text())
        self.assertTrue(json.loads((self.base/'state.json').read_text())['hop'])
        self.shell(mocks+'hop', input='2\nyes\n')
        self.assertFalse(json.loads((self.base/'state.json').read_text())['hop'])

    def test_initialization_does_not_enable_firewall_or_reboot(self):
        result = self.shell("""need_root(){ :; }
apt-get(){ printf 'APT %s\\n' "$*"; }
systemctl(){ printf 'SYSTEMCTL %s\\n' "$*"; }
timedatectl(){ :; }
getent(){ :; }
curl(){ :; }
ss(){ :; }
ufw(){ printf 'UFW %s\\n' "$*"; }
initialize_server""", input='yes\n')
        self.assertIn('APT upgrade -y',result.stdout)
        self.assertIn('APT install -y',result.stdout)
        self.assertNotIn('UFW --force enable',result.stdout)
        self.assertNotIn('SYSTEMCTL reboot',result.stdout)

    def test_bbr_fq_writes_only_managed_sysctl(self):
        self.shell("""need_root(){ :; }
modprobe(){ :; }
sysctl(){ if [[ $1 == -n ]]; then printf 'reno cubic bbr\\n'; fi; }
bbr""", input='yes\n')
        self.assertEqual((self.root/'bbr.conf').read_text(),
                         'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\n')

    def test_download_requires_matching_release_digest(self):
        import tarfile
        version='1.14.3'
        payload=self.root/('sing-box-'+version+'-linux-amd64')
        payload.mkdir(); (payload/'sing-box').write_text('#!/bin/sh\nexit 0\n')
        archive=self.root/'release.tar.gz'
        with tarfile.open(archive,'w:gz') as tar: tar.add(payload,arcname=payload.name)
        asset=payload.name+'.tar.gz'
        manifest=self.root/'release.json'
        digest=hashlib.sha256(archive.read_bytes()).hexdigest()
        mocks="""uname(){ printf x86_64; }
sha256sum(){ shasum -a 256 "$@"; }
curl(){ local url= out=; while (($#)); do if [[ $1 == -o ]]; then out=$2; shift 2; else url=$1; shift; fi; done
if [[ $url == *.tar.gz ]]; then cp """+shlex.quote(str(archive))+""" "$out"; else cp """+shlex.quote(str(manifest))+""" "$out"; fi; }
"""
        data={'draft':False,'prerelease':False,'assets':[{'name':asset,'digest':'sha256:'+digest}]}
        manifest.write_text(json.dumps(data))
        target=self.root/'downloaded'
        self.shell(mocks+'download_binary '+version+' '+shlex.quote(str(target)))
        original=target.read_bytes()
        data['assets'][0]['digest']='sha256:'+'0'*64; manifest.write_text(json.dumps(data))
        self.assertNotEqual(self.shell(mocks+'download_binary '+version+' '+shlex.quote(str(target)),ok=False).returncode,0)
        self.assertEqual(target.read_bytes(),original)

    @unittest.skipUnless(MIHOMO, 'Set MIHOMO_BIN for Mihomo YAML validation')
    def test_mihomo_yaml_supported_schema(self):
        import yaml
        for mode in ['1','2','3']:
            self.exported(mode)
            parsed=yaml.safe_load((self.base/'mihomo-proxies.yaml').read_text())
            self.assertEqual(len(parsed['proxies']),1 if mode!='3' else 2)
            if mode!='1': self.assertEqual(parsed['tls']['custom-certifactes'],[self.cert.read_text()])
            subprocess.run([MIHOMO,'-t','-d',str(self.root/'mihomo-data'),'-f',str(self.base/'mihomo-proxies.yaml')],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def prepare_argo(self, mode='quick', connected=True):
        self.configure('3')
        self.shell('argo_write_config "$BASE" '+mode+' node.example 8080 SKYBYTE')
        state=json.loads((self.base/'argo-state.json').read_text())
        state.update(connected=connected,domain='node.example' if mode=='named' else 'test-route.trycloudflare.com' if connected else '')
        (self.base/'argo-state.json').write_text(json.dumps(state))
        (self.base/'cloudflared').write_text('#!/bin/sh\nexit 0\n');(self.base/'cloudflared').chmod(0o700)
        if mode=='named':
            (self.base/'argo.token').write_text(secrets.token_urlsafe(48));(self.base/'argo.token').chmod(0o600)

    def test_argo_configs_and_all_exports_keep_existing_protocols(self):
        import yaml,urllib.parse
        for mode in ['quick','named']:
            self.prepare_argo(mode)
            original=(self.config/'config.json').read_bytes()
            self.shell('exports')
            self.assertEqual(original,(self.config/'config.json').read_bytes())
            origin=json.loads((self.base/'argo-server.json').read_text())['inbounds'][0]
            self.assertEqual(origin['listen'],'127.0.0.1')
            self.assertNotIn('flow',origin['users'][0]);self.assertNotIn('tls',origin)
            out=json.loads((self.base/'outbounds.json').read_text())['outbounds']
            self.assertEqual(len(out),3)
            node=out[-1]
            self.assertEqual(node['transport']['type'],'ws')
            self.assertTrue(node['tls']['enabled']);self.assertFalse(node['tls'].get('insecure',False))
            self.assertNotIn('flow',node);self.assertNotIn('reality',node['tls'])
            self.assertEqual(node['transport']['path'],origin['transport']['path'])
            uri=urllib.parse.urlsplit((self.base/'nodes.txt').read_text().splitlines()[-1])
            fields=urllib.parse.parse_qs(uri.query)
            self.assertEqual(fields['security'],['tls']);self.assertEqual(fields['type'],['ws'])
            self.assertEqual(urllib.parse.unquote(uri.username),origin['users'][0]['uuid'])
            clash=yaml.safe_load((self.base/'clash-verge.yaml').read_text())
            self.assertEqual(clash['proxies'][-1]['ws-opts']['path'],origin['transport']['path'])
            if SB:
                for file in ['argo-server.json','sing-box-client.json']:
                    subprocess.run([SB,'check','-c',str(self.base/file)],check=True)
            if MIHOMO:
                subprocess.run([MIHOMO,'-t','-d',str(self.root/'mihomo-data'),'-f',str(self.base/'clash-verge.yaml')],check=True,stdout=subprocess.DEVNULL)

    def test_argo_unready_node_is_not_exported(self):
        self.prepare_argo(connected=False)
        self.shell('exports')
        self.assertEqual(len((self.base/'nodes.txt').read_text().splitlines()),2)
        self.assertIn('not registered',(self.base/'subscription-notes.txt').read_text())

    def test_argo_domain_validation(self):
        for value in ['node.example','a-b.example.net','test-route.trycloudflare.com']:
            self.shell('argo_validate_domain '+shlex.quote(value))
        for value in ['https://node.example','node.example:443','node..example','-bad.example','127.0.0.1','a.example\nInjected']:
            self.assertNotEqual(self.shell('argo_validate_domain '+shlex.quote(value),ok=False).returncode,0)

    def test_argo_install_preserves_main_config_and_keeps_token_out_of_units(self):
        self.configure('1');original=(self.config/'config.json').read_bytes()
        token=secrets.token_urlsafe(48)
        mocks='''need_root(){ :; }
ss(){ :; }
systemctl(){ if [[ $1 == list-unit-files ]]; then return 0; fi; }
download_cloudflared(){ printf '#!/bin/sh\nexit 0\n' > "$1"; chmod 700 "$1"; }
argo_wait(){ :; }
argo_install named'''
        result=self.shell(mocks,input='yes\n8080\n香港\nnode.example\n'+token+'\n')
        self.assertEqual(original,(self.config/'config.json').read_bytes())
        self.assertEqual((self.base/'argo.token').read_text(),token)
        self.assertEqual((self.base/'argo.token').stat().st_mode&0o777,0o600)
        for unit in (self.root/'systemd').iterdir():self.assertNotIn(token,unit.read_text())
        self.assertNotIn(token,result.stdout+result.stderr)
        self.assertNotIn(token,(self.base/'argo-state.json').read_text())
        self.assertIn('--argo-run',(self.root/'systemd'/'skybyte-argo-tunnel.service').read_text())

    def test_argo_quick_install_and_existing_files_refusal(self):
        self.configure('1')
        code='''need_root(){ :; }; ss(){ :; }
systemctl(){ :; }
download_cloudflared(){ printf '#!/bin/sh\nexit 0\n' > "$1"; chmod 700 "$1"; }
argo_wait(){ :; }
argo_install quick'''
        self.shell(code,input='yes\n\n\n')
        self.assertEqual(json.loads((self.base/'argo-state.json').read_text())['mode'],'quick')
        self.assertFalse((self.base/'argo.token').exists())
        before=(self.base/'argo-state.json').read_bytes()
        self.assertNotEqual(self.shell(code,input='yes\n',ok=False).returncode,0)
        self.assertEqual(before,(self.base/'argo-state.json').read_bytes())

    def test_argo_worker_publishes_on_registration_and_clears_on_stop(self):
        for mode in ['quick','named']:
            self.prepare_argo(mode,False)
            token=(self.base/'argo.token').read_text() if mode=='named' else ''
            args_file=self.root/'cloud-args.json'
            cloud='''#!/usr/bin/env python3
import json,pathlib,sys,time
pathlib.Path(%r).write_text(json.dumps(sys.argv))
print('https://fresh-route.trycloudflare.com',flush=True)
print('Registered tunnel connection',flush=True)
time.sleep(60)
''' % str(args_file)
            (self.base/'cloudflared').write_text(cloud);(self.base/'cloudflared').chmod(0o700)
            (self.root/'manager-command').write_text('#!/bin/bash\nexit 0\n')
            proc=subprocess.Popen([BASH,'-c',self.script('argo_run')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    state=json.loads((self.base/'argo-state.json').read_text())
                    if state['connected']:break
                    if proc.poll() is not None: self.fail(proc.communicate()[1])
                    time.sleep(.05)
                self.assertTrue(state['connected'])
                self.assertEqual(state['domain'],'fresh-route.trycloudflare.com' if mode=='quick' else 'node.example')
                args=json.loads(args_file.read_text())
                if mode=='named':
                    self.assertIn('--token-file',args);self.assertNotIn(token,args)
                else:self.assertIn('--url',args)
            finally:
                os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=10);proc.communicate(timeout=10)
            deadline=time.monotonic()+3
            while time.monotonic()<deadline and json.loads((self.base/'argo-state.json').read_text())['connected']:time.sleep(.05)
            state=json.loads((self.base/'argo-state.json').read_text())
            self.assertFalse(state['connected'])
            if mode=='quick':self.assertEqual(state['domain'],'')

    def test_argo_backup_restore_and_removal_keep_token_private(self):
        self.prepare_argo('named')
        self.shell('systemctl(){ :; }; argo_setup_units')
        token=(self.base/'argo.token').read_text()
        snapshot=Path(self.shell('backup').stdout.strip())
        self.assertEqual((snapshot/'argo.token').read_text(),token)
        self.assertEqual((snapshot/'argo.token').stat().st_mode&0o777,0o600)
        self.shell('systemctl(){ :; }; argo_remove_internal')
        self.assertFalse((self.base/'argo.token').exists())
        self.shell('systemctl(){ :; }; argo_restore_snapshot '+shlex.quote(str(snapshot)))
        self.assertEqual((self.base/'argo.token').read_text(),token)
        self.assertFalse(json.loads((self.base/'argo-state.json').read_text())['connected'])
        self.shell('systemctl(){ :; }; argo_remove_internal')
        self.assertTrue((self.config/'config.json').exists())
        self.assertTrue((snapshot/'argo.token').exists())

    def test_argo_guards_preserve_unowned_services(self):
        self.prepare_argo()
        unit=self.root/'systemd'/'skybyte-argo-node.service';unit.write_text('Description=another service\n')
        self.assertNotEqual(self.shell('argo_remove_internal',ok=False).returncode,0)
        self.assertTrue(unit.exists());self.assertTrue((self.base/'argo-server.json').exists())

    def test_uninstall_also_removes_owned_argo_with_backup(self):
        self.prepare_argo('named')
        self.shell('systemctl(){ :; }; setup_service; argo_setup_units')
        self.shell('need_root(){ :; }; systemctl(){ :; }; uninstall_manager',input='yes\n')
        self.assertFalse((self.base/'argo-state.json').exists());self.assertFalse((self.base/'argo.token').exists())
        self.assertFalse((self.root/'systemd'/'skybyte-argo-node.service').exists())
        snapshots=list(self.backups.iterdir());self.assertEqual(len(snapshots),1)
        self.assertTrue((snapshots[0]/'argo.token').exists())

    def user_setup(self, limit=2, mode='3', real=False):
        self.configure(mode)
        if real and SB: self.bin=Path(SB)
        self.shell('users_engine init '+str(limit))

    def add_user(self, name='Alice', quota='1', days='30'):
        uid=self.shell('users_engine add '+' '.join(shlex.quote(x) for x in [name,quota,days])).stdout.strip()
        if SB and self.bin.resolve()==Path(SB).resolve():
            # Live tests expose only loopback listeners on the development host.
            p=self.base/'users'/uid/'server.json';c=json.loads(p.read_text())
            for inbound in c['inbounds']:inbound['listen']='127.0.0.1'
            p.write_text(json.dumps(c))
        return uid

    def user_db(self):
        return json.loads((self.base/'users.json').read_text())

    def save_user_db(self, d):
        import fcntl
        with open(self.base/'users.lock','a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            tmp=self.base/'users-test.tmp';tmp.write_text(json.dumps(d));tmp.chmod(0o600)
            os.replace(tmp,self.base/'users.json')

    def test_users_limit_counts_disabled_accounts_and_frees_deleted_slots(self):
        self.user_setup(2);a=self.add_user();b=self.add_user('Bob')
        self.shell('users_engine disable '+a)
        self.assertNotEqual(self.shell('users_engine add Carol 1 30',ok=False).returncode,0)
        self.assertNotEqual(self.shell('users_engine limit 1',ok=False).returncode,0)
        self.shell('users_engine delete '+b);self.add_user('Carol')
        self.assertEqual(len([u for u in self.user_db()['users'] if not u.get('deleted')]),2)

    def test_users_independent_credentials_ports_and_private_controllers(self):
        self.user_setup();before=(self.config/'config.json').read_bytes()
        a=self.add_user('香港 & #1');b=self.add_user('Bob');db=self.user_db()
        ports=[u[k] for u in db['users'] for k in ['port','api_port']]
        self.assertEqual(len(ports),len(set(ports)))
        configs=[json.loads((self.base/'users'/uid/'server.json').read_text()) for uid in [a,b]]
        self.assertNotEqual(configs[0]['inbounds'][0]['users'][0]['uuid'],configs[1]['inbounds'][0]['users'][0]['uuid'])
        self.assertNotEqual(configs[0]['inbounds'][1]['users'][0]['password'],configs[1]['inbounds'][1]['users'][0]['password'])
        for u,c in zip(db['users'],configs):
            self.assertEqual(c['experimental']['clash_api']['external_controller'],'127.0.0.1:'+str(u['api_port']))
            self.assertTrue(c['experimental']['clash_api']['secret'])
            self.assertEqual(len(c['inbounds'][0]['users']),1)
            self.assertEqual((self.base/'users'/u['id']/'server.json').stat().st_mode & 0o777,0o600)
            self.assertEqual((self.base/'users'/u['id']/'private.key').stat().st_mode & 0o777,0o600)
        self.assertEqual((self.config/'config.json').read_bytes(),before)
        self.assertEqual((self.base/'users.json').stat().st_mode & 0o777,0o600)

    def test_users_validation_and_failed_config_are_atomic(self):
        self.user_setup();before=(self.base/'users.json').read_bytes()
        for command in ['users_engine add Alice -1 30','users_engine add Alice NaN 30','users_engine add Alice 1 0','users_engine add Alice 1 36501']:
            self.assertNotEqual(self.shell(command,ok=False).returncode,0)
        self.bin.write_text('#!/bin/sh\nexit 1\n')
        self.assertNotEqual(self.shell('users_engine add Alice 1 30',ok=False).returncode,0)
        self.assertEqual((self.base/'users.json').read_bytes(),before)
        self.assertEqual(list((self.base/'users').iterdir()),[])
        self.assertNotEqual(self.shell('users_engine init 3',ok=False).returncode,0)

    def test_users_expiry_and_quota_prevent_exports_and_allow_explicit_renewal(self):
        self.user_setup();a=self.add_user();d=self.user_db();d['users'][0]['expires_at']=1;self.save_user_db(d)
        self.assertIn('Expired',self.shell('users_engine list').stdout)
        self.assertNotEqual(self.shell('users_export '+a,ok=False).returncode,0)
        self.shell('users_engine set '+a+' 2 30')
        d=self.user_db();d['users'][0]['upload']=d['users'][0]['quota_bytes'];self.save_user_db(d)
        self.assertIn('Quota exceeded',self.shell('users_engine list').stdout)
        self.assertNotEqual(self.shell('users_export '+a,ok=False).returncode,0)
        self.shell('users_engine reset '+a);self.shell('users_export '+a)
        self.assertEqual(self.user_db()['users'][0]['upload'],0)

    def test_users_exports_use_only_that_users_credentials_and_port(self):
        self.user_setup();a=self.add_user();b=self.add_user('Bob');before=(self.config/'config.json').read_bytes()
        self.shell('users_export '+a)
        u=self.user_db()['users'][0];p=self.base/'users'/a
        out=json.loads((p/'outbounds.json').read_text())['outbounds']
        server=json.loads((p/'server.json').read_text())
        self.assertEqual(out[0]['uuid'],server['inbounds'][0]['users'][0]['uuid'])
        self.assertEqual(out[1]['password'],server['inbounds'][1]['users'][0]['password'])
        self.assertTrue(all(o['server_port']==u['port'] for o in out))
        bob=json.loads((self.base/'users'/b/'server.json').read_text())
        self.assertNotIn(bob['inbounds'][0]['users'][0]['uuid'],(p/'nodes.txt').read_text())
        self.assertNotIn(u['api_secret'],(p/'shadowrocket-native-nodes.txt').read_text())
        self.assertEqual((self.config/'config.json').read_bytes(),before)
        self.assertEqual(self.shell('users_export '+a+' >/dev/null; echo "$BASE"').stdout.strip(),str(self.base))

    def test_users_backup_restore_keeps_latest_usage_policy_and_private_keys(self):
        self.user_setup();a=self.add_user();backup=Path(self.shell('backup').stdout.strip())
        d=self.user_db();d['users'][0].update(upload=12345,enabled=False);self.save_user_db(d)
        b=self.add_user('Bob');self.shell('users_engine service off')
        self.shell('users_restore_snapshot '+shlex.quote(str(backup)))
        d=self.user_db();self.assertFalse(d['supervisor_enabled'])
        self.assertEqual(d['users'][0]['upload'],12345);self.assertFalse(d['users'][0]['enabled'])
        self.assertIn(b,[u['id'] for u in d['users']])
        self.assertEqual((backup/'users'/a/'private.key').stat().st_mode & 0o777,0o600)

    def test_users_units_and_uninstall_preserve_unknown_files(self):
        self.user_setup();a=self.add_user();self.shell('systemctl(){ :; }; users_setup_service')
        unit=self.root/'systemd'/'skybyte-users.service'
        self.assertIn('KillMode=mixed',unit.read_text())
        unit.write_text('Description=other\n')
        self.assertNotEqual(self.shell('users_remove',ok=False).returncode,0)
        self.assertTrue((self.base/'users.json').exists())
        self.shell('systemctl(){ :; }; rm "$SYSTEMD_DIR/skybyte-users.service"; users_setup_service')
        unknown=self.base/'users'/a/'my-note.txt';unknown.write_text('keep')
        self.shell('systemctl(){ :; }; users_remove')
        self.assertTrue(unknown.exists());self.assertFalse((self.base/'users.json').exists())
        self.assertFalse(unit.exists())

    def test_users_reject_symlinks_before_backup_or_removal(self):
        self.user_setup();a=self.add_user();p=self.base/'users'/a/'server.json'
        p.unlink();p.symlink_to(self.config/'config.json')
        before=(self.config/'config.json').read_bytes()
        self.assertNotEqual(self.shell('users_guard',ok=False).returncode,0)
        self.assertNotEqual(self.shell('backup',ok=False).returncode,0)
        self.assertNotEqual(self.shell('users_remove',ok=False).returncode,0)
        self.assertEqual((self.config/'config.json').read_bytes(),before)

    def test_users_menu_dispatch_and_translations(self):
        for language,label in [('zh_CN','用户数量'),('en_US','Account limits')]:
            r=self.shell('LANGUAGE_CHOICE='+language+'; sub_menu 2; echo "$MAIN_ACTION"',input='5\n')
            self.assertIn(label,r.stdout);self.assertTrue(r.stdout.rstrip().endswith('users'))

    @unittest.skipUnless(SB,'sing-box required for live per-user tests')
    def test_users_live_isolation_quota_stop_and_restart_accounting(self):
        self.user_setup(real=True);a=self.add_user('Alice','0.0001');b=self.add_user('Bob','1')
        self.shell('users_export '+a+' >/dev/null; users_export '+b+' >/dev/null')
        payload=b'X'*262144
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
            def log_message(self,*_):pass
        web=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=web.serve_forever,daemon=True).start()
        self.addCleanup(web.server_close);self.addCleanup(web.shutdown)
        url='http://127.0.0.1:'+str(web.server_port)
        worker=subprocess.Popen([BASH,'-c',self.script('users_engine watch')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        clients=[]
        def wait_ready(uid):
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if next(u for u in self.user_db()['users'] if u['id']==uid).get('running'):return
                time.sleep(.1)
            self.fail('User worker did not become ready')
        def request(uid,index=1):
            config=json.loads((self.base/'users'/uid/'sing-box-client.json').read_text());mixed=port()
            config['inbounds'][0]['listen_port']=mixed;config['route']['final']=config['outbounds'][index]['tag']
            f=self.root/('client-'+uid+'-'+str(mixed)+'.json');f.write_text(json.dumps(config))
            c=subprocess.Popen([SB,'run','-c',str(f)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);clients.append(c)
            deadline=time.monotonic()+3;result=None
            while time.monotonic()<deadline:
                result=subprocess.run(['curl','--silent','--max-time','1','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(mixed),url],capture_output=True)
                if result.returncode==0:break
                time.sleep(.1)
            return result
        try:
            wait_ready(a);wait_ready(b)
            self.assertEqual(request(b).stdout,payload)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and self.user_db()['users'][1]['download']<len(payload):time.sleep(.1)
            d=self.user_db();self.assertEqual(d['users'][0]['upload']+d['users'][0]['download'],0)
            self.assertGreaterEqual(d['users'][1]['download'],len(payload))
            self.assertGreater(d['users'][1]['upload'],0)
            self.shell('users_engine reset '+b)
            time.sleep(1.2)
            self.assertEqual(self.user_db()['users'][1]['download'],0)
            self.assertEqual(request(b).stdout,payload)
            self.assertEqual(request(a).stdout,payload)
            deadline=time.monotonic()+6
            while time.monotonic()<deadline and self.user_db()['users'][0]['running']:time.sleep(.1)
            self.assertFalse(self.user_db()['users'][0]['running'])
            self.assertNotEqual(request(a).returncode,0)
            self.assertEqual(request(b).stdout,payload)
            before=self.user_db()['users'][1]['download']
            worker.terminate();worker.communicate(timeout=15)
            self.assertFalse(self.user_db()['users'][1]['metering_blocked'])
            self.assertGreaterEqual(self.user_db()['users'][1]['download'],before)
            worker=subprocess.Popen([BASH,'-c',self.script('users_engine watch')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            wait_ready(b);self.assertEqual(request(b).stdout,payload)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and self.user_db()['users'][1]['download']<=before:time.sleep(.1)
            self.assertGreater(self.user_db()['users'][1]['download'],before)
            d=self.user_db();d['users'][1]['expires_at']=1;self.save_user_db(d)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and self.user_db()['users'][1]['running']:time.sleep(.1)
            self.assertFalse(self.user_db()['users'][1]['running'])
            self.assertNotEqual(request(b).returncode,0)
        finally:
            if worker.poll() is None:worker.terminate()
            try:worker.communicate(timeout=15)
            except subprocess.TimeoutExpired:worker.kill();worker.communicate(timeout=5)
            for c in clients:
                if c.poll() is None:c.terminate()
                try:c.wait(timeout=5)
                except subprocess.TimeoutExpired:c.kill();c.wait()

    @unittest.skipUnless(SB and ssl.HAS_TLSv1_3,'sing-box and Python TLS 1.3 required for Reality metering test')
    def test_users_reality_forwarding_is_metered_with_local_tls_decoy(self):
        import socketserver
        self.user_setup(mode='1',real=True)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version=ssl.TLSVersion.TLSv1_3
        context.set_ecdh_curve('X25519');context.set_alpn_protocols(['h2','http/1.1'])
        context.load_cert_chain(self.cert,self.key)
        class Decoy(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.settimeout(3)
                    with context.wrap_socket(self.request,server_side=True) as conn:conn.recv(1024)
                except (OSError,ssl.SSLError):pass
        class Server(socketserver.ThreadingTCPServer):daemon_threads=True
        tls=Server(('127.0.0.1',0),Decoy)
        threading.Thread(target=tls.serve_forever,daemon=True).start()
        self.addCleanup(tls.server_close);self.addCleanup(tls.shutdown)
        config=json.loads((self.config/'config.json').read_text())
        config['inbounds'][0]['tls']['server_name']='node.example'
        config['inbounds'][0]['tls']['reality']['handshake']={'server':'127.0.0.1','server_port':tls.server_address[1]}
        (self.config/'config.json').write_text(json.dumps(config))
        a=self.add_user('Reality');self.shell('users_export '+a+' >/dev/null')
        payload=b'REALITY METERED'*4096
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):self.send_response(200);self.end_headers();self.wfile.write(payload)
            def log_message(self,*_):pass
        web=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=web.serve_forever,daemon=True).start()
        self.addCleanup(web.server_close);self.addCleanup(web.shutdown)
        client=json.loads((self.base/'users'/a/'sing-box-client.json').read_text());mixed=port()
        client['inbounds'][0]['listen_port']=mixed
        f=self.root/'reality-client.json';f.write_text(json.dumps(client))
        worker=subprocess.Popen([BASH,'-c',self.script('users_engine watch')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        proxy=subprocess.Popen([SB,'run','-c',str(f)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+10;result=None
            while time.monotonic()<deadline:
                result=subprocess.run(['curl','--silent','--max-time','2','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(mixed),'http://127.0.0.1:'+str(web.server_port)],capture_output=True)
                if result.returncode==0:break
                time.sleep(.1)
            self.assertEqual(result.stdout,payload,result.stderr.decode())
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and self.user_db()['users'][0]['download']<len(payload):time.sleep(.1)
            self.assertGreaterEqual(self.user_db()['users'][0]['download'],len(payload))
        finally:
            proxy.terminate();proxy.wait(timeout=5)
            worker.terminate()
            try:worker.communicate(timeout=15)
            except subprocess.TimeoutExpired:worker.kill();worker.communicate(timeout=5)

    @unittest.skipUnless(SB,'sing-box required for fail-closed user tests')
    def test_users_metering_failure_and_corrupt_ledger_stop_child_cores(self):
        self.user_setup(mode='1',real=True);a=self.add_user()
        worker=None
        def start():
            proc=subprocess.Popen([BASH,'-c',self.script('users_engine watch')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                if self.user_db()['users'][0].get('running'):return proc
                time.sleep(.1)
            proc.terminate();proc.communicate(timeout=10);self.fail('Worker not ready')
        def listening():
            with socket.socket() as s:s.settimeout(.3);return s.connect_ex(('127.0.0.1',self.user_db()['users'][0]['port']))==0
        try:
            worker=start();self.assertTrue(listening())
            d=self.user_db();actual=d['users'][0]['api_secret'];d['users'][0]['api_secret']='wrong-token';self.save_user_db(d)
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and self.user_db()['users'][0]['running']:time.sleep(.1)
            self.assertTrue(self.user_db()['users'][0]['metering_blocked']);self.assertFalse(listening())
            worker.terminate();worker.communicate(timeout=10)
            d=self.user_db();d['users'][0]['api_secret']=actual;self.save_user_db(d)
            self.shell('users_engine enable '+a);worker=start();node_port=self.user_db()['users'][0]['port']
            # Simulate damaged local state: all child listeners must disappear.
            import fcntl
            with open(self.base/'users.lock','a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX)
                (self.base/'users.json').write_text('{broken')
            worker.communicate(timeout=10)
            with socket.socket() as s:
                s.settimeout(.3);self.assertNotEqual(s.connect_ex(('127.0.0.1',node_port)),0)
        finally:
            if worker is not None:
                if worker.poll() is None:worker.terminate()
                try:worker.communicate(timeout=10)
                except subprocess.TimeoutExpired:worker.kill();worker.communicate(timeout=5)

    def test_users_firewall_and_hopping_rules_use_only_user_node_ports(self):
        self.user_setup();meta=json.loads((self.base/'state.json').read_text())
        meta.update(hop=True,hop_start=20000,hop_end=30000)
        (self.base/'state.json').write_text(json.dumps(meta))
        a=self.add_user();u=self.user_db()['users'][0]
        self.assertFalse(20000<=u['port']<=30000)
        rules=self.shell('ufw(){ echo RULE "$*"; }; users_firewall_allow').stdout
        self.assertIn('RULE allow '+str(u['port'])+'/tcp',rules)
        self.assertIn('RULE allow '+str(u['port'])+'/udp',rules)
        self.assertNotIn(str(u['api_port']),rules)
        result=self.shell('nft(){ return 1; }; hop',input='1\n'+str(u['port'])+'\n'+str(u['port'])+'\nYES\n',ok=False)
        self.assertNotEqual(result.returncode,0);self.assertIn('overlaps',result.stderr)
        self.assertFalse((self.root/'systemd'/'singbox-v2-hop.service').exists())

    def test_users_full_uninstall_keeps_private_backup_and_unknown_files(self):
        self.user_setup();a=self.add_user();d=self.user_db();d['users'][0]['download']=1234;self.save_user_db(d)
        note=self.base/'users'/a/'keep.txt';note.write_text('keep')
        self.shell('systemctl(){ :; }; setup_service; users_setup_service')
        self.shell('need_root(){ :; }; systemctl(){ :; }; nft(){ return 1; }; uninstall_manager',input='yEs\n')
        self.assertTrue(note.exists());self.assertFalse((self.base/'users.json').exists())
        self.assertFalse((self.config/'config.json').exists())
        saved=next(self.backups.glob('*/users.json'))
        self.assertEqual(json.loads(saved.read_text())['users'][0]['download'],1234)
        self.assertEqual(saved.stat().st_mode & 0o777,0o600)
        self.assertTrue((saved.parent/'users'/a/'private.key').exists())

    def test_update_rejects_candidate_incompatible_with_user_configs(self):
        self.user_setup();self.add_user();before=self.bin.read_bytes()
        code="""download_binary(){ printf '%s\\n' '#!/usr/bin/env bash' '[[ $3 != */users/* ]]' > "$2"; chmod 755 "$2"; }
apply_update 9.9.9"""
        self.assertNotEqual(self.shell(code,ok=False).returncode,0)
        self.assertEqual(self.bin.read_bytes(),before)

    def test_users_controller_redirect_never_forwards_secret_or_resets_usage(self):
        self.user_setup();a=self.add_user();hits=[]
        class Sink(http.server.BaseHTTPRequestHandler):
            def do_GET(self):hits.append(self.headers.get('Authorization'));self.send_response(200);self.end_headers();self.wfile.write(b'{"uploadTotal":0,"downloadTotal":0}')
            def log_message(self,*_):pass
        sink=http.server.ThreadingHTTPServer(('127.0.0.1',0),Sink)
        class Redirect(http.server.BaseHTTPRequestHandler):
            def do_GET(self):self.send_response(302);self.send_header('Location','http://127.0.0.1:'+str(sink.server_port));self.end_headers()
            def log_message(self,*_):pass
        origin=http.server.ThreadingHTTPServer(('127.0.0.1',0),Redirect)
        for server in [sink,origin]:
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        d=self.user_db();d['users'][0].update(api_port=origin.server_port,running=True,generation='test',upload=1234)
        self.save_user_db(d)
        self.assertNotEqual(self.shell('users_engine reset '+a,ok=False).returncode,0)
        self.assertEqual(hits,[]);self.assertEqual(self.user_db()['users'][0]['upload'],1234)

    def test_startup_info_uses_local_system_and_actual_service_state(self):
        code="""uname(){ case "$1" in -r) echo test-kernel;; -m) echo x86_64;; esac; }
systemd-detect-virt(){ echo kvm; }
ip(){ case "$*" in *-4*) echo '2: eth0 inet 192.0.2.10/24 scope global eth0';; *-6*) echo '2: eth0 inet6 2001:db8::10/64 scope global';; esac; }
systemctl(){ [[ "$*" == 'is-active --quiet sing-box.service' ]]; }
nginx(){ :; }
curl(){ echo SHOULD_NOT_QUERY_NETWORK; return 1; }
startup_info"""
        for lang,os_label,running in [('en_US','OS','Running'),('zh_CN','操作系统','运行中')]:
            result=self.shell('LANGUAGE_CHOICE='+lang+'; '+code)
            self.assertIn(os_label+': Debian',result.stdout)
            for value in ['test-kernel','amd64','kvm','192.0.2.10/24','2001:db8::10/64','sing-box: '+running]:
                self.assertIn(value,result.stdout)
            self.assertNotIn('SHOULD_NOT_QUERY_NETWORK',result.stdout)

    def test_startup_info_handles_unavailable_optional_commands(self):
        result=self.shell('OS_RELEASE=/nonexistent; BIN=/nonexistent; systemctl(){ return 1; }; ip(){ return 1; }; systemd-detect-virt(){ return 1; }; startup_info')
        self.assertIn('OS: Unknown',result.stdout)
        self.assertIn('IPv4: Not detected',result.stdout)
        self.assertIn('sing-box: Not installed',result.stdout)

    def test_shadowrocket_native_links_roundtrip_credentials_and_security(self):
        import urllib.parse
        self.configure('3');self.shell('rename_node',input='香港 #1 & /\n')
        original=(self.base/'nodes.txt').read_text().splitlines()
        native=(self.base/'shadowrocket-native-nodes.txt').read_text().splitlines()
        u=urllib.parse.urlsplit(native[0]);q=dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual(base64.b64decode(u.netloc).decode(),'auto:'+self.uuid+'@127.0.0.1:443')
        self.assertEqual(q['remarks'],'香港 #1 & /-Reality')
        self.assertEqual(q['xtls'],'2');self.assertEqual(q['tls'],'1');self.assertEqual(q['allowInsecure'],'0')
        standard=dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(original[0]).query))
        for k in ['pbk','sid','fp']:self.assertEqual(q[k],standard[k])
        self.assertEqual(q['peer'],standard['sni'])
        self.assertEqual(native[1],original[1])
        self.assertEqual(base64.b64decode((self.base/'shadowrocket-native-subscription.txt').read_text()).decode(),'\n'.join(native)+'\n')
        for name in ['shadowrocket-native-nodes.txt','shadowrocket-native-subscription.txt']:
            self.assertEqual((self.base/name).stat().st_mode & 0o777,0o600)
        self.assertEqual((self.base/'shadowrocket-nodes.txt').read_text(),(self.base/'nodes.txt').read_text())

    def test_shadowrocket_native_argo_preserves_ws_and_verified_tls(self):
        import urllib.parse
        self.configure('2');self.shell('argo_write_config "$BASE" named node.example 8080 SKYBYTE')
        state=json.loads((self.base/'argo-state.json').read_text());state['connected']=True
        (self.base/'argo-state.json').write_text(json.dumps(state));self.shell('exports')
        u=urllib.parse.urlsplit((self.base/'shadowrocket-native-nodes.txt').read_text().splitlines()[-1])
        q=dict(urllib.parse.parse_qsl(u.query))
        self.assertEqual(q['obfs'],'websocket');self.assertEqual(q['obfsParam'],'node.example')
        self.assertEqual(q['peer'],'node.example');self.assertEqual(q['allowInsecure'],'0')
        self.assertNotIn('xtls',q);self.assertNotIn('pbk',q)
        origin=json.loads((self.base/'argo-server.json').read_text())['inbounds'][0]
        self.assertEqual(q['path'],origin['transport']['path'])
        self.assertEqual(base64.b64decode(u.netloc).decode(),'auto:'+origin['users'][0]['uuid']+'@node.example:443')

    def test_shadowrocket_qr_uses_exact_links_via_stdin(self):
        self.exported('3')
        self.shell('rename_node',input='HK %20 #1 & /\n')
        expected=(self.base/'shadowrocket-native-nodes.txt').read_text().splitlines()
        capture=self.root/'qr-input.txt'
        result=self.shell('qrencode(){ [[ "$*" == "-t ANSIUTF8 -m 2" ]] || return 1; cat >> '+shlex.quote(str(capture))+'; echo >> '+shlex.quote(str(capture))+'; echo QR; }; shadowrocket_qr')
        self.assertEqual(capture.read_text().splitlines(),expected)
        self.assertEqual(result.stdout.count('\nQR\n'),len(expected))
        self.assertIn('certificate trust',result.stdout)
        self.assertIn('HK %20 #1 & /-Reality',result.stdout)
        self.assertNotIn(self.password,result.stdout)
        result=self.shell('sub_menu 2; echo "$MAIN_ACTION"',input='4\n')
        self.assertTrue(result.stdout.rstrip().endswith('qr'))

    def test_shadowrocket_qr_stops_when_encoder_fails(self):
        self.exported('2')
        result=self.shell('qrencode(){ return 1; }; shadowrocket_qr',ok=False)
        self.assertNotEqual(result.returncode,0)

    def test_grouped_menu_dispatches_without_renumbering_function_logic(self):
        for language,label in [('en_US','Nodes and subscriptions'),('zh_CN','节点与订阅')]:
            code='need_root(){ :; }; flock(){ :; }; exports(){ echo EXPORTED; }; LANGUAGE_CHOICE='+language+'; main'
            result=self.shell(code,input='2\n1\n0\n')
            self.assertIn(label,result.stdout);self.assertIn('EXPORTED',result.stdout)
            self.assertNotIn('printf:',result.stderr)
            self.assertNotIn('24.',result.stdout)
        result=self.shell('need_root(){ :; }; flock(){ :; }; exports(){ echo BAD; }; main',input='2\n0\n0\n')
        self.assertNotIn('BAD',result.stdout)

    def test_cloudflared_download_digest_is_required(self):
        asset='cloudflared-linux-amd64'
        payload=self.root/'cloud-payload';payload.write_text('#!/bin/sh\nexit 0\n')
        manifest=self.root/'cloud-release.json'
        metadata={'tag_name':'2026.10.0','draft':False,'prerelease':False,
                  'assets':[{'name':asset,'digest':'sha256:'+hashlib.sha256(payload.read_bytes()).hexdigest()}]}
        manifest.write_text(json.dumps(metadata))
        mocks='''uname(){ printf x86_64; }
sha256sum(){ shasum -a 256 "$@"; }
curl(){ local url= out=; while (($#)); do if [[ $1 == -o ]]; then out=$2; shift 2; else url=$1; shift; fi; done
if [[ $url == */latest ]]; then cp '''+shlex.quote(str(manifest))+''' "$out"; else cp '''+shlex.quote(str(payload))+''' "$out"; fi; }
'''
        target=self.root/'cloud-target'
        self.shell(mocks+'download_cloudflared '+shlex.quote(str(target)))
        original=target.read_bytes();metadata['assets'][0]['digest']='sha256:'+'0'*64;manifest.write_text(json.dumps(metadata))
        self.assertNotEqual(self.shell(mocks+'download_cloudflared '+shlex.quote(str(target)),ok=False).returncode,0)
        self.assertEqual(target.read_bytes(),original)

    def test_argo_rename_keeps_credentials_and_routes_consistent(self):
        self.prepare_argo('named')
        before=(self.base/'argo-server.json').read_bytes()
        self.shell('rename_node',input='香港新节点\n')
        self.assertEqual(before,(self.base/'argo-server.json').read_bytes())
        self.assertEqual(json.loads((self.base/'argo-state.json').read_text())['node_name'],'香港新节点')
        out=json.loads((self.base/'outbounds.json').read_text())['outbounds']
        self.assertEqual(out[-1]['tag'],'香港新节点-Argo')
        self.assertTrue(json.loads((self.base/'argo-state.json').read_text())['connected'])

    def test_update_rejects_candidate_that_cannot_read_argo_config(self):
        self.prepare_argo()
        original=self.bin.read_bytes()
        code='''download_binary(){ printf '#!/bin/sh\ncase "$*" in *argo-server.json*) exit 1;; *) exit 0;; esac\n' > "$2"; chmod 700 "$2"; }
apply_update 1.14.3'''
        self.assertNotEqual(self.shell(code,ok=False).returncode,0)
        self.assertEqual(self.bin.read_bytes(),original)

    def test_restore_snapshot_without_argo_removes_only_owned_addon(self):
        self.configure('1')
        snapshot=Path(self.shell('backup').stdout.strip())
        self.prepare_argo('named');self.shell('systemctl(){ :; }; argo_setup_units')
        self.shell('systemctl(){ :; }; argo_restore_snapshot '+shlex.quote(str(snapshot)))
        self.assertFalse((self.base/'argo-state.json').exists())
        self.assertTrue((self.config/'config.json').exists())

    @unittest.skipUnless(SB, 'Set SING_BOX_BIN for real Argo WebSocket forwarding')
    def test_argo_exported_ws_configs_forward_through_verified_tls(self):
        import select,socketserver,yaml
        self.prepare_argo('named')
        origin=json.loads((self.base/'argo-server.json').read_text());origin_port=port()
        origin['inbounds'][0]['listen_port']=origin_port
        origin_file=self.root/'ws-origin.json';origin_file.write_text(json.dumps(origin))
        self.shell('exports')
        class HTTP(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'SKYBYTE Argo verified')
            def log_message(self,*_):pass
        target=http.server.ThreadingHTTPServer(('127.0.0.1',0),HTTP)
        threading.Thread(target=target.serve_forever,daemon=True).start()
        self.addCleanup(target.server_close);self.addCleanup(target.shutdown)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(self.cert,self.key)
        class Forward(socketserver.BaseRequestHandler):
            def handle(self):
                with socket.create_connection(('127.0.0.1',origin_port)) as upstream:
                    pair=[self.request,upstream]
                    try:
                        while True:
                            ready,_,_=select.select(pair,[],[],8)
                            if not ready:return
                            for src in ready:
                                data=src.recv(65536)
                                if not data:return
                                (upstream if src is self.request else self.request).sendall(data)
                    except (OSError,ssl.SSLError):pass
        class Edge(socketserver.ThreadingTCPServer):
            allow_reuse_address=True;daemon_threads=True
            def get_request(self):
                request,address=super().get_request()
                return context.wrap_socket(request,server_side=True),address
        edge=Edge(('127.0.0.1',0),Forward)
        threading.Thread(target=edge.serve_forever,daemon=True).start()
        self.addCleanup(edge.server_close);self.addCleanup(edge.shutdown)
        with contextlib.ExitStack() as stack:
            def run_engine(args,name):
                log=stack.enter_context(open(self.root/(name+'.log'),'w+'))
                proc=subprocess.Popen(args,stdout=log,stderr=log)
                def stop():
                    proc.terminate()
                    try:proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait()
                stack.callback(stop)
                return log
            run_engine([SB,'run','-c',str(origin_file)],'origin')
            sb=json.loads((self.base/'sing-box-client.json').read_text())
            node=sb['outbounds'][-2]
            sb['route']['final']=node['tag'];node['server']='127.0.0.1';node['server_port']=edge.server_address[1]
            node['tls']['certificate']=self.cert.read_text().splitlines()
            sb['inbounds'][0]['listen_port']=client_port=port()
            config=self.root/'ws-client.json';config.write_text(json.dumps(sb))
            log=run_engine([SB,'run','-c',str(config)],'client')
            def request(proxy_port):
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    result=subprocess.run(['curl','--silent','--show-error','--max-time','2','--noproxy','',
                                          '--proxy','socks5h://127.0.0.1:'+str(proxy_port),'http://127.0.0.1:'+str(target.server_port)],capture_output=True)
                    if result.returncode==0:return result
                    time.sleep(.1)
                return result
            result=request(client_port);log.flush();log.seek(0)
            self.assertEqual(result.stdout,b'SKYBYTE Argo verified',log.read())
            if MIHOMO:
                clash=yaml.safe_load((self.base/'clash-verge.yaml').read_text());proxy=clash['proxies'][-1]
                proxy.update(server='127.0.0.1',port=edge.server_address[1])
                clash['rules']=['MATCH,'+proxy['name']]
                clash['tls']={'custom-certifactes':[self.cert.read_text()]}
                clash['mixed-port']=client_port=port();clash['external-controller']=''
                config=self.root/'ws-client.yaml';config.write_text(quoted_yaml_dump(clash))
                log=run_engine([MIHOMO,'-d',str(self.root/'mihomo-data'),'-f',str(config)],'mihomo-ws')
                result=request(client_port);log.flush();log.seek(0)
                self.assertEqual(result.stdout,b'SKYBYTE Argo verified',log.read())

    @unittest.skipUnless(SB, 'Set SING_BOX_BIN to run real HY2 connectivity tests')
    def test_hy2_handshake_with_trust_and_reject_untrusted(self):
        cfg = self.configure('2')
        udp, mixed = port(socket.SOCK_DGRAM), port()
        cfg['inbounds'][0]['listen'] = '127.0.0.1'
        cfg['inbounds'][0]['listen_port'] = udp
        server_file = self.root/'server.json'
        server_file.write_text(json.dumps(cfg))
        self.exported('2')
        client=json.loads((self.base/'sing-box-client.json').read_text())
        client['inbounds'][0]['listen_port']=mixed
        client['outbounds'][0]['server_port']=udp
        client_file = self.root/'client.json'
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'SKYBYTE HY2 verified')
            def log_message(self, *_):
                pass
        webserver = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=webserver.serve_forever, daemon=True); thread.start()
        self.addCleanup(webserver.server_close)
        self.addCleanup(webserver.shutdown)
        url = 'http://127.0.0.1:'+str(webserver.server_port)
        with contextlib.ExitStack() as stack:
            def start(file):
                log = stack.enter_context(open(self.root/(file.stem+'.log'), 'w+'))
                proc = subprocess.Popen([SB,'run','-c',str(file)], stdout=log, stderr=log)
                def stop():
                    proc.terminate()
                    try: proc.wait(timeout=5)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait()
                stack.callback(stop)
                return proc, log
            server, _ = start(server_file)
            client_file.write_text(json.dumps(client))
            proc, log = start(client_file)
            try:
                deadline = time.monotonic()+10
                while time.monotonic()<deadline:
                    result = subprocess.run(['curl','--silent','--show-error','--max-time','2',
                                '--noproxy','', '--proxy','socks5h://127.0.0.1:'+str(mixed), url], capture_output=True)
                    if result.returncode == 0: break
                    time.sleep(.2)
                self.assertEqual(result.stdout, b'SKYBYTE HY2 verified', result.stderr.decode())
                self.assertIsNone(server.poll())
            finally:
                proc.terminate(); proc.wait(timeout=5)
            client['outbounds'][0]['tls'].pop('certificate')
            client['inbounds'][0]['listen_port']=mixed=port()
            client_file.write_text(json.dumps(client))
            proc, log = start(client_file)
            deadline = time.monotonic()+12
            rejection_log = ''
            while time.monotonic()<deadline:
                result = subprocess.run(['curl','--silent','--show-error','--max-time','3','--noproxy','',
                                         '--proxy','socks5h://127.0.0.1:'+str(mixed),url],capture_output=True)
                self.assertNotEqual(result.returncode,0, 'Untrusted TLS unexpectedly connected')
                log.seek(0); rejection_log = log.read()
                if 'certificate' in rejection_log: break
                time.sleep(.2)
            self.assertIn('certificate',rejection_log)
            if MIHOMO:
                import yaml
                config=yaml.safe_load((self.base/'clash-verge.yaml').read_text())
                config['proxies'][0]['port']=udp
                proxy_port=port()
                config.update({'mixed-port':proxy_port,'mode':'rule',
                               'external-controller':'','ipv6':False})
                config_file=self.root/'mihomo.yaml'
                config_file.write_text(quoted_yaml_dump(config))
                mh_log=stack.enter_context(open(self.root/'mihomo.log','w+'))
                mh=subprocess.Popen([MIHOMO,'-d',str(self.root/'mihomo-data'),'-f',str(config_file)],
                                    stdout=mh_log,stderr=mh_log)
                def stop_mh():
                    mh.terminate()
                    try: mh.wait(timeout=5)
                    except subprocess.TimeoutExpired: mh.kill(); mh.wait()
                stack.callback(stop_mh)
                deadline=time.monotonic()+10
                while time.monotonic()<deadline:
                    result=subprocess.run(['curl','--silent','--show-error','--max-time','2',
                                           '--noproxy','', '--proxy','socks5h://127.0.0.1:'+str(proxy_port),url],
                                          capture_output=True)
                    if result.returncode==0: break
                    time.sleep(.2)
                mh_log.flush(); mh_log.seek(0)
                self.assertEqual(result.stdout,b'SKYBYTE HY2 verified',mh_log.read())


if __name__ == '__main__':
    unittest.main(verbosity=2)
