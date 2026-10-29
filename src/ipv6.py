"""Native IPv6 backup checks. No downloads, routing changes, or credential output."""
import ipaddress
import json
import pathlib
import socket
import subprocess
import time


def public_ipv6(value):
    if isinstance(value, str) and "%" in value:
        raise ValueError("Scoped IPv6 is not a public entry address")
    try:
        address = ipaddress.IPv6Address(value)
    except (ValueError, TypeError):
        raise ValueError('请输入公网 IPv6，不含方括号、端口或网卡后缀 / Enter a public IPv6 without brackets, port or scope') from None
    if not address.is_global or address.is_multicast or address.ipv4_mapped or address.is_reserved:
        raise ValueError('需要原生公网 IPv6，不能使用回环、内网或映射地址 / Native public IPv6 required')
    return str(address)


def ipv6_candidates():
    result = subprocess.run(['ip', '-j', '-6', 'addr', 'show', 'scope', 'global'],
                            capture_output=True, text=True, check=True, timeout=4)
    candidates = []
    for interface in json.loads(result.stdout):
        if 'UP' not in interface.get('flags', []):
            continue
        for item in interface.get('addr_info', []):
            if item.get('family') != 'inet6' or item.get('scope') != 'global':
                continue
            flags = set(item.get('flags', []))
            if flags & {'tentative', 'dadfailed', 'deprecated', 'temporary'} or any(item.get(k) for k in ('tentative', 'dadfailed', 'deprecated', 'temporary')) or item.get('preferred_life_time') == 0:
                continue
            try:
                value = public_ipv6(item['local'])
            except ValueError:
                continue
            if value not in candidates:
                candidates.append(value)
    return candidates


def ipv6_local(value):
    value = public_ipv6(value)
    if value not in ipv6_candidates():
        raise ValueError('IPv6 未配置在本机可用网卡，或地址尚未就绪 / IPv6 is not assigned and ready on this VPS')
    result = subprocess.run(['ip', '-6', 'route', 'get', '2606:4700:4700::1111', 'from', value],
                            capture_output=True, text=True, check=True, timeout=3)
    if not result.stdout.strip() or any(word in result.stdout.split() for word in ('unreachable', 'prohibit', 'blackhole')):
        raise ValueError('没有可用的 IPv6 路由 / No usable IPv6 route')
    with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
        probe.bind((value, 0))
    return value


def ipv6_firewall():
    """UFW must manage IPv6 when active; never silently edit/reload SSH policy."""
    import os
    import shutil
    if not shutil.which('ufw'):
        print('提示：未安装 UFW，请安装防火墙并放行 SSH 和节点端口 / Install a firewall; allow SSH and node ports')
        return
    result = subprocess.run(['ufw', 'status'], capture_output=True, text=True, timeout=5,
                            env={**os.environ, 'LC_ALL': 'C'})
    if result.returncode:
        raise ValueError('无法读取 UFW 状态 / Cannot inspect UFW')
    if 'Status: active' not in result.stdout:
        print('提示：UFW 未启用，请配置防火墙 / UFW is inactive; configure your firewall')
        return
    import re
    if not re.search(r'^IPV6\s*=\s*["\x27]?yes["\x27]?\s*(?:#.*)?$', pathlib.Path('/etc/default/ufw').read_text(), re.M | re.I):
        raise ValueError('UFW 已启用但未管理 IPv6；请先设置 IPV6=yes 并核对 SSH 的 IPv6 放行规则 / Active UFW does not manage IPv6; enable IPV6=yes and verify IPv6 SSH rules first')


def ipv6_bind_check(listeners):
    for item in listeners:
        if item['listen'] not in ('0.0.0.0', '::') or item.get('ipv6_only'):
            raise ValueError('仅支持公网通配监听，拒绝更改回环或 IPv6-only 节点 / Public wildcard listeners required; loopback/IPv6-only nodes are preserved')
        if item['listen'] == '::':
            continue
        transport = socket.SOCK_DGRAM if item['protocol'] == 'udp' else socket.SOCK_STREAM
        with socket.socket(socket.AF_INET6, transport) as probe:
            # The current IPv4 listener remains running during preflight.
            probe.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            probe.bind(('::', item['port']))


def ipv6_listeners(project, root, conf=None, users=True):
    root = pathlib.Path(root)
    state = json.loads((root / 'state.json').read_text())
    if project == 'xray':
        return [{'listen': n['listen'], 'port': n['port'], 'protocol': 'tcp'}
                for n in state['nodes'].values() if not n.get('cdn')]
    configs = [pathlib.Path(conf)]
    ledger = root / 'users.json'
    if users and ledger.exists():
        for user in json.loads(ledger.read_text())['users']:
            if not user.get('deleted'):
                identity = user['id']
                import re
                if not re.fullmatch('[0-9a-f]{16}', identity):
                    raise ValueError('Invalid managed user ID')
                configs.append(root / 'users' / identity / 'server.json')
    listeners = []
    for filename in configs:
        for inbound in json.loads(filename.read_text())['inbounds']:
            if inbound['type'] in ('vless', 'hysteria2'):
                listeners.append({'listen': inbound['listen'], 'port': inbound['listen_port'],
                                  'protocol': 'udp' if inbound['type'] == 'hysteria2' else 'tcp',
                                  'ipv6_only': inbound.get('ipv6_only', False)})
    return listeners


def ipv6_ready(listeners):
    """Local TCP dual-stack and UDP6 listener checks; not a public ingress test."""
    deadline = time.monotonic() + 5
    while True:
        try:
            for item in listeners:
                if item['protocol'] == 'tcp':
                    for host in ('127.0.0.1', '::1'):
                        with socket.create_connection((host, item['port']), timeout=.3):
                            pass
                else:
                    result = subprocess.run(['ss', '-H', '-lnu6'], capture_output=True, text=True, check=True, timeout=2)
                    endpoints = [line.split()[3] for line in result.stdout.splitlines() if len(line.split()) > 4]
                    if not any(endpoint.rsplit(':', 1)[-1] == str(item['port']) and endpoint.rsplit(':', 1)[0] in ('*', '[::]', '::') for endpoint in endpoints):
                        raise ValueError('IPv6 UDP listener missing')
            return
        except (OSError, ValueError, subprocess.SubprocessError):
            if time.monotonic() >= deadline:
                raise ValueError('双栈监听检查失败；恢复原配置 / Dual-stack listener check failed; restoring the previous configuration') from None
            time.sleep(.2)


def ipv6_cli(project, root, conf, action, value=''):
    if action == 'detect':
        values = ipv6_candidates()
        if not values:
            raise ValueError('VPS 未发现可用的原生公网 IPv6；请先向服务商开通 / No native public IPv6; provision it with your VPS provider first')
        print('\n'.join(values))
    elif action == 'check':
        ipv6_local(value)
        listeners = ipv6_listeners(project, root, conf)
        if not listeners:
            raise ValueError('没有可用的直连节点；Argo/CDN 节点保持不变 / No direct nodes; Argo/CDN nodes are preserved')
        ipv6_bind_check(listeners)
        ipv6_firewall()
    elif action == 'ready':
        ipv6_ready(ipv6_listeners(project, root, conf, users=False))
    elif action == 'status':
        state = json.loads((pathlib.Path(root) / 'state.json').read_text())
        states = list(state['nodes'].values()) if project == 'xray' else [state]
        for node in states:
            backup = node.get('ipv6_backup')
            print(node.get('name', node.get('node_name', 'SKYBYTE')) + ': ' +
                  ('IPv6 备用已配置 / IPv6 backup configured: ' + backup['address'] if backup else '未配置 IPv6 备用 / IPv6 backup not configured'))
        print('客户端网络也必须支持 IPv6；本机检查不等于公网可达。请放行云防火墙的实际 IPv6 TCP/UDP 端口。\nClient IPv6 is required; local checks do not prove public reachability. Allow the actual IPv6 TCP/UDP ports in your provider firewall.')
    else:
        raise ValueError('Invalid IPv6 action')
