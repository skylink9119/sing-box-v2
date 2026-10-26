"""Read-only REALITY target diagnostics; standard library, no core required."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import queue
import re
import socket
import ssl
import sys
import threading
import time


def hostname(value):
    if not isinstance(value, str):
        raise ValueError('Invalid hostname')
    if '%' in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid hostname')
    value = value.strip().rstrip('.')
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    value = value.encode('idna').decode('ascii').lower()
    if len(value) > 253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', part)
                                   for part in value.split('.')):
        raise ValueError('Invalid hostname')
    return value


def target_parts(value, sni=''):
    if not isinstance(value, str):
        raise ValueError('Invalid target')
    value = value.strip()
    number = '443'
    if value.startswith('['):
        match = re.fullmatch(r'\[([^\]]+)\](?::([0-9]+))?', value)
        if not match:
            raise ValueError('Invalid target')
        host, number = match[1], match[2] or '443'
        if ipaddress.ip_address(host).version != 6:
            raise ValueError('Invalid IPv6 target')
    elif value.count(':') == 1:
        host, number = value.rsplit(':', 1)
    else:
        host = value
    host = hostname(host)
    if not re.fullmatch(r'[0-9]{1,5}', number) or not 1 <= int(number) <= 65535:
        raise ValueError('Invalid port')
    return host, int(number), hostname(sni or host)


def target_label(host, number):
    return ('[' + host + ']' if ':' in host else host) + ':' + str(number)


def resolve(host, number, timeout):
    # A daemon resolver bounds DNS even if libc's resolver does not return.
    results = queue.Queue()
    def lookup():
        try:
            results.put(socket.getaddrinfo(host, number, type=socket.SOCK_STREAM))
        except OSError as error:
            results.put(error)
    threading.Thread(target=lookup, daemon=True).start()
    try:
        value = results.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError('DNS deadline') from None
    if isinstance(value, OSError):
        raise value
    return value


def probe(target, sni='', ca_file=None, timeout=12):
    host, number, sni = target_parts(target, sni)
    checks = {key: {'status': 'skip', 'detail': 'not_checked'}
              for key in ('dns', 'tcp', 'tls', 'certificate', 'h2')}
    result = {'target': target_label(host, number), 'sni': sni, 'checks': checks, 'ok': False}
    started = time.monotonic()
    def remaining():
        value = timeout - (time.monotonic() - started)
        if value <= 0:
            raise TimeoutError('Reality target deadline')
        return value
    stage = 'dns'
    connection = None
    try:
        addresses = resolve(host, number, remaining())
        if not addresses:
            raise socket.gaierror()
        resolved = list(dict.fromkeys(str(ipaddress.ip_address(item[4][0])) for item in addresses))
        checks['dns'] = {'status': 'pass', 'detail': ', '.join(resolved[:4])}
        stage = 'tcp'
        last = None
        for family, kind, protocol, _, endpoint in addresses:
            wait = min(4, remaining())
            connection = socket.socket(family, kind, protocol)
            try:
                connection.settimeout(wait)
                connection.connect(endpoint)
                break
            except OSError as error:
                last = error
                connection.close()
                connection = None
        if connection is None:
            raise last or OSError('No usable address')
        peer = str(ipaddress.ip_address(connection.getpeername()[0]))
        checks['tcp'] = {'status': 'pass', 'detail': target_label(peer, number)}
        stage = 'tls'
        context = ssl.create_default_context(cafile=ca_file)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.set_alpn_protocols(['h2'])
        connection.settimeout(remaining())
        with context.wrap_socket(connection, server_hostname=sni) as secure:
            checks['tls'] = {'status': 'pass', 'detail': secure.version()}
            # create_default_context verifies CA trust, validity and name.
            checks['certificate'] = {'status': 'pass', 'detail': 'verified'}
            stage = 'h2'
            protocol = secure.selected_alpn_protocol()
            checks['h2'] = {'status': 'pass' if protocol == 'h2' else 'fail',
                            'detail': 'h2' if protocol == 'h2' else 'no_h2'}
            result['ok'] = protocol == 'h2'
    except ssl.SSLCertVerificationError as error:
        reason = {9: 'not_yet_valid', 10: 'expired', 62: 'name_mismatch', 64: 'name_mismatch'}.get(
            error.verify_code, 'untrusted')
        checks['certificate'] = {'status': 'fail', 'detail': reason}
    except socket.gaierror:
        checks[stage] = {'status': 'fail', 'detail': 'dns_failed'}
    except (TimeoutError, socket.timeout):
        checks[stage] = {'status': 'fail', 'detail': 'timeout'}
    except ssl.SSLError:
        checks[stage] = {'status': 'fail', 'detail': 'tls_failed'}
    except OSError:
        checks[stage] = {'status': 'fail', 'detail': 'connect_failed' if stage == 'tcp' else 'system_failed'}
    finally:
        if connection is not None:
            connection.close()
    result['elapsed_ms'] = round((time.monotonic() - started) * 1000)
    return result


def configured_targets(path, project):
    path = Path(path)
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Invalid configuration file')
    config = json.loads(path.read_text())
    targets = []
    for node in config.get('inbounds', []):
        if project == 'sing-box':
            tls = node.get('tls', {})
            reality = tls.get('reality', {})
            if not tls.get('enabled') or not reality.get('enabled'):
                continue
            handshake = reality['handshake']
            host = hostname(handshake['server'])
            target = target_label(host, handshake.get('server_port', 443))
            names = [tls['server_name']]
        else:
            stream = node.get('streamSettings', {})
            if stream.get('security') != 'reality':
                continue
            reality = stream['realitySettings']
            target = reality.get('target') or reality.get('dest')
            names = reality['serverNames']
        if not isinstance(names, list) or not names:
            raise ValueError('Missing SNI')
        for sni in names:
            # No-SNI REALITY is not configured by either manager.
            if not sni:
                raise ValueError('Empty SNI cannot be checked by this diagnostic')
            host, number, sni = target_parts(target, sni)
            item = (target_label(host, number), sni)
            if item not in targets:
                targets.append(item)
            if len(targets) > 64:
                raise ValueError('Too many targets')
    return targets


def render(result, language):
    english = language in ('en', 'en_US')
    def text(zh, en):
        return en if english else zh
    labels = {'dns': ('DNS 解析', 'DNS resolution'), 'tcp': ('TCP 连接', 'TCP connection'),
              'tls': ('TLS 1.3', 'TLS 1.3'), 'certificate': ('证书校验', 'Certificate'),
              'h2': ('HTTP/2 (ALPN)', 'HTTP/2 (ALPN)')}
    details = {
        'not_checked': ('未完成检测', 'Not checked'),
        'verified': ('信任链、有效期与握手域名匹配', 'Trusted chain, valid dates and matching SNI'),
        'no_h2': ('未协商到 h2', 'h2 was not negotiated'),
        'name_mismatch': ('证书与握手域名不匹配', 'Certificate does not match SNI'),
        'expired': ('证书已过期，请同时检查系统时间', 'Certificate expired; also check the system clock'),
        'not_yet_valid': ('证书尚未生效，请同时检查系统时间', 'Certificate not yet valid; also check the system clock'),
        'untrusted': ('证书链不受信任或验证失败', 'Untrusted certificate chain or verification failed'),
        'dns_failed': ('目标 DNS 解析失败', 'Target DNS lookup failed'),
        'timeout': ('检测超时', 'Timed out'),
        'tls_failed': ('TLS 握手失败，未完成 TLS 1.3 验证', 'TLS handshake failed; TLS 1.3 was not verified'),
        'connect_failed': ('无法连接目标端口', 'Cannot connect to target port'),
        'system_failed': ('本机网络或 CA 证书读取失败', 'Local network or CA store error'),
    }
    print('\n' + text('Reality 握手网站检测', 'Reality handshake target check'))
    print(text('握手目标：', 'Target: ') + result['target'])
    print(text('握手域名：', 'SNI: ') + result['sni'])
    for key, item in result['checks'].items():
        status = {'pass': text('通过', 'PASS'), 'fail': text('失败', 'FAIL'), 'skip': text('未检查', 'SKIP')}[item['status']]
        detail = text(*details[item['detail']]) if item['detail'] in details else item['detail']
        print('  [' + status + '] ' + text(*labels[key]) + ': ' + detail)
    summary = (text('检测通过：TLS 1.3、HTTP/2 与证书正常', 'PASSED: TLS 1.3, HTTP/2 and certificate verified')
               if result['ok'] else text('检测未通过：请根据上方原因检查目标', 'FAILED: inspect the reasons above'))
    color = ('\033[1;32m' if result['ok'] else '\033[1;31m') if sys.stdout.isatty() and not os.environ.get('NO_COLOR') else ''
    print(color + '===== ' + summary + ' =====' + ('\033[0m' if color else ''))
    print(text('检测耗时：', 'Check duration: ') + str(result['elapsed_ms']) + ' ms')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target')
    parser.add_argument('--sni', default='')
    parser.add_argument('--config')
    parser.add_argument('--list', action='store_true', help='List configured target/SNI pairs without probing')
    parser.add_argument('--normalize', action='store_true', help='Print validated host, port and SNI without probing')
    parser.add_argument('--project', choices=('sing-box', 'xray'), required=True)
    parser.add_argument('--language', choices=('zh', 'en', 'zh_CN', 'en_US'), default='zh')
    args = parser.parse_args(argv)
    english = args.language in ('en', 'en_US')
    try:
        if args.target is not None:
            host, number, sni = target_parts(args.target, args.sni)
            targets = [(target_label(host, number), sni)]
        elif args.config:
            targets = configured_targets(args.config, args.project)
        else:
            raise ValueError('Target or configuration required')
    except (ValueError, OSError, KeyError, TypeError, AttributeError, UnicodeError):
        print('Invalid target/SNI or unreadable REALITY configuration; use a hostname or host:port.' if english else
              '目标 / 握手域名无效，或无法读取 Reality 配置；请输入域名或 域名:端口。', file=sys.stderr)
        return 2
    if not targets:
        if args.list:
            return 0
        print('No configured Reality targets; choose custom target check.' if english else
              '未找到已配置的 Reality 握手目标，可选择“检测自定义网站”。')
        return 0
    if args.normalize:
        if args.target is None:
            return 2
        print('\t'.join((host, str(number), sni)))
        return 0
    if args.list:
        for target, sni in targets:
            print(target + '\t' + sni)
        return 0
    failed = False
    for target, sni in targets:
        result = probe(target, sni)
        render(result, args.language)
        failed |= not result['ok']
    print('\nOnly checks this VPS → target. It does not verify client → VPS or CDN connectivity.' if english else
          '\n仅检测本 VPS → 握手目标，不代表客户端 → VPS 或 CDN 已连通。')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
