"""Read-only diagnostics for managed sing-box and integrated XHTTP listeners."""
import ipaddress
import json
from pathlib import Path
import shlex
import socket
import subprocess
import sys


def read_json(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Invalid managed configuration')
    return json.loads(path.read_text())


def node_list(base, config):
    nodes = []
    if (base / 'state.json').exists():
        state = read_json(base / 'state.json')
        for item in read_json(config).get('inbounds', []):
            if item.get('type') not in ('vless', 'hysteria2'):
                continue
            transport = 'udp' if item['type'] == 'hysteria2' else 'tcp'
            nodes.append((item['type'], transport, item.get('listen', '0.0.0.0'),
                          item['listen_port'], 'sing-box.service', state.get('ip', '')))
    root = base / 'xhttp'
    if (root / 'state.json').exists():
        marker = root / '.owner'
        if root.is_symlink() or marker.is_symlink() or marker.read_text() != 'SKYBYTE-SB-XHTTP/1\n':
            raise ValueError('Unknown XHTTP deployment')
        state = read_json(root / 'state.json')
        if state.get('schema') != 1:
            raise ValueError('Unsupported XHTTP state')
        for kind, node in state['nodes'].items():
            if kind not in ('xhttp-reality', 'xhttp-tls'):
                raise ValueError('Unsupported XHTTP node')
            nodes.append((kind, 'tcp', node['listen'], node['port'],
                          'skybyte-sb-xhttp.service', node['address']))
    return nodes


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=5,
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None, ''


def listener_status(address, port, transport):
    ip = ipaddress.ip_address(address)
    family = '-6' if ip.version == 6 else '-4'
    option = '-lnt' if transport == 'tcp' else '-lnu'
    code, output = command(['ss', '-H', family, option, '( sport = :' + str(port) + ' )'])
    if code != 0:
        return None
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 5:
            return None
        host, _, number = fields[3].rpartition(':')
        host = host.strip('[]')
        if number == str(port) and (host == '*' or ipaddress.ip_address(host) == ip):
            return True
    return False


def local_tcp(address, port):
    ip = ipaddress.ip_address(address)
    if ip.is_unspecified:
        address = '::1' if ip.version == 6 else '127.0.0.1'
    family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect((address, port))
        return True
    except OSError:
        return False


def main(argv):
    base, config, language = argv
    english = language == 'en_US'
    def text(zh, en):
        return en if english else zh
    try:
        nodes = node_list(Path(base), Path(config))
        for _, _, address, port, _, _ in nodes:
            ipaddress.ip_address(address)
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError('Invalid port')
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print(text('无法读取托管节点配置。', 'Cannot read managed node configuration.'), file=sys.stderr)
        return 1
    if not nodes:
        print(text('尚未安装直连节点。', 'No direct nodes installed.'))
        return 0
    failed = False
    for name, transport, address, port, unit, public in nodes:
        print('\n=== ' + name + ' / ' + transport.upper() + ' ' + str(port) + ' ===')
        code, _ = command(['systemctl', 'is-active', '--quiet', unit])
        failed |= code != 0
        service = text('运行中', 'active') if code == 0 else text('未运行或无法查询', 'inactive or unavailable')
        print(text('服务：', 'Service: ') + unit + ' — ' + service)
        listening = listener_status(address, port, transport)
        status = text('未能查询', 'unknown')
        if listening is not None:
            status = text('存在监听', 'listening') if listening else text('未发现监听', 'not listening')
        print(text('监听：', 'Listener: ') + address + ':' + str(port) + ' — ' + status)
        if listening is not True:
            failed = True
        if transport == 'tcp':
            connected = local_tcp(address, port)
            failed |= not connected
            print(text('本机 TCP 连接：', 'Local TCP connection: ') + ('PASS' if connected else 'FAIL'))
            if public and not any(ord(c) < 32 or ord(c) == 127 for c in str(public)):
                print(text('在另一台已安装脚本的机器检测公网入站：', 'Test external ingress from another machine with this script: '))
                print('bash singbox-v2.sh --check-port ' + shlex.quote(str(public)) + ' ' + str(port))
        else:
            print(text('UDP 公网状态：待验证；请用 HY2 客户端连接并访问网站，检查 QUIC/TLS 与传输。',
                       'UDP public ingress: unverified; connect with a HY2 client and test QUIC/TLS and traffic.'))
    print(text('\n请核对系统防火墙、云安全组和 NAT 映射。以上监听与本机 TCP 结果仅反映本机状态。',
               '\nReview host/provider firewall rules and NAT mappings. Listener and local TCP results describe this host.'))
    print(text('更改端口后，请重新导入客户端节点。', 'Re-import client nodes after changing ports.'))
    return int(failed)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
