"""Owned HAProxy TCP passthrough; never terminate TLS or import node credentials."""
import contextlib
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid


from src.managed_ports import integrated_xhttp_ports

OWNER = 'SKYBYTE HAProxy TCP v1'
UNIT = 'skybyte-haproxy.service'


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError('Port must be 1-65535 / 端口必须为 1-65535')
    return value


def host(value, listen=False):
    if not isinstance(value, str) or not value or len(value) > 253:
        raise ValueError('Invalid address / 地址无效')
    try:
        ip = ipaddress.ip_address(value)
        if ip.is_multicast or ip.is_link_local or (not listen and ip.is_unspecified):
            raise ValueError('Invalid peer address / 落地地址无效')
        return str(ip)
    except ValueError:
        if listen or not re.fullmatch(r'(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', value):
            raise ValueError('Use an IP or DNS hostname / 请填写 IP 或域名') from None
        if any(not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', label) for label in value.split('.')):
            raise ValueError('Invalid DNS hostname / 域名无效')
        # Numeric-looking invalid IPs must not become DNS names.
        if re.fullmatch(r'[0-9.]+', value):
            raise ValueError('Invalid IP address / IP 地址无效')
        return value.lower()


def normalize(state):
    if not isinstance(state, dict) or set(state) != {'owner', 'schema', 'rules'} or state['owner'] != OWNER or type(state['schema']) is not int or state['schema'] != 1:
        raise ValueError('HAProxy ownership mismatch / HAProxy 归属异常')
    if not isinstance(state['rules'], list) or not 1 <= len(state['rules']) <= 16:
        raise ValueError('Use 1-16 TCP rules / 支持 1-16 条 TCP 转发规则')
    result = {'owner': OWNER, 'schema': 1, 'rules': []}
    ids, ports = set(), set()
    for rule in state['rules']:
        if not isinstance(rule, dict) or set(rule) != {'id', 'name', 'listen', 'port', 'peer', 'peer_port'}:
            raise ValueError('Unknown rule fields / 存在未知规则字段')
        rid, name = rule['id'], rule['name']
        if not isinstance(rid, str) or not re.fullmatch(r'[a-f0-9]{12}', rid) or rid in ids:
            raise ValueError('Invalid rule ID / 规则 ID 无效')
        if not isinstance(name, str) or not name.strip() or len(name) > 64 or any(unicodedata.category(c).startswith('C') for c in name):
            raise ValueError('Name requires 1-64 characters without controls / 名称为 1-64 字且不能含控制字符')
        lp = port(rule['port'])
        if lp in ports:
            raise ValueError('Duplicate entry port / 中转端口重复')
        ids.add(rid); ports.add(lp)
        result['rules'].append(dict(id=rid, name=name.strip(), listen=host(rule['listen'], True), port=lp, peer=host(rule['peer']), peer_port=port(rule['peer_port'])))
    return result


def endpoint(address, number):
    return ('[' + address + ']' if ':' in address else address) + ':' + str(number)


def render(state):
    state = normalize(state)
    lines = ['# ' + OWNER, 'global', '    maxconn 1024', '    user haproxy', '    group haproxy',
             '    log stdout format raw local0', 'defaults', '    mode tcp', '    log global',
             '    option tcplog', '    timeout connect 5s', '    timeout client 1h',
             '    timeout server 1h', '    timeout check 3s']
    if any(not is_ip(r['peer']) for r in state['rules']):
        lines += ['resolvers skybyte_dns', '    parse-resolv-conf', '    timeout resolve 2s',
                  '    timeout retry 1s', '    hold valid 10s']
    for r in state['rules']:
        dns = '' if is_ip(r['peer']) else ' resolvers skybyte_dns init-addr last,libc,none'
        lines += ['listen skybyte_' + r['id'], '    bind ' + endpoint(r['listen'], r['port']) + (' v6only' if ':' in r['listen'] else ''),
                  '    server landing ' + endpoint(r['peer'], r['peer_port']) + ' check inter 5s fall 3 rise 2' + dns]
    return '\n'.join(lines) + '\n'


def is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def tcp_ports(cfg):
    result = set()
    for inbound in cfg.get('inbounds', []):
        if inbound.get('type') != 'hysteria2' and inbound.get('listen_port'):
            result.add(port(inbound['listen_port']))
    api = cfg.get('experimental', {}).get('clash_api', {}).get('external_controller', '')
    if api:
        match = re.search(r':([0-9]{1,5})$', api)
        if not match: raise ValueError('Invalid controller address')
        result.add(port(int(match[1])))
    return result


class Relay:
    def __init__(self, base, units, binary, conf):
        self.base, self.units, self.binary, self.conf = Path(base), Path(units), str(binary), Path(conf)
        self.root = self.base / 'haproxy'
        self.unit = self.units / UNIT
        self.backups = self.base / 'haproxy-backups'
        for value in (str(self.base), str(self.units), self.binary):
            if not value.startswith('/') or not re.fullmatch(r'[a-zA-Z0-9_./-]+', value):
                raise ValueError('Unsafe runtime path')

    def unit_text(self):
        cfg = str(self.root / 'haproxy.cfg')
        return ('[Unit]\nDescription=SKYBYTE managed HAProxy TCP passthrough\nAfter=network-online.target\nWants=network-online.target\n'
                '[Service]\nType=simple\nExecStart=' + self.binary + ' -W -db -f ' + cfg + '\n'
                'Restart=on-failure\nRestartSec=3\nUMask=0077\nNoNewPrivileges=yes\n'
                'CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID\n'
                'ProtectSystem=strict\nProtectHome=yes\nPrivateTmp=yes\nLimitNOFILE=8192\n'
                '[Install]\nWantedBy=multi-user.target\n')

    def read(self, path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 131072:
            raise ValueError('Unsafe HAProxy file / HAProxy 文件异常')
        return path.read_bytes()

    def guard(self):
        if self.base.is_symlink() or self.units.is_symlink() or self.root.is_symlink() or self.backups.is_symlink():
            raise ValueError('HAProxy path is a symlink / HAProxy 路径不能为软链接')
        overrides = self.units / (UNIT + '.d')
        if overrides.exists() or overrides.is_symlink():
            raise ValueError('Custom HAProxy service overrides / HAProxy 存在自定义服务覆盖')
        if not self.root.exists():
            if self.unit.exists() or self.unit.is_symlink():
                raise ValueError('Unmanaged HAProxy unit / 存在非托管 HAProxy 服务')
            return None
        if not self.root.is_dir() or {p.name for p in self.root.iterdir()} != {'state.json', 'haproxy.cfg'}:
            raise ValueError('Unknown HAProxy files; refusing overwrite / 存在未知 HAProxy 文件，拒绝覆盖')
        state = normalize(json.loads(self.read(self.root / 'state.json')))
        if self.read(self.root / 'haproxy.cfg').decode() != render(state) or self.read(self.unit).decode() != self.unit_text():
            raise ValueError('HAProxy config/unit changed; refusing overwrite / HAProxy 配置或服务已修改，拒绝覆盖')
        source = self.ctl('show', '--property=FragmentPath', '--property=DropInPaths', UNIT, check=False)
        if source.returncode == 0:
            properties = dict(line.split('=', 1) for line in source.stdout.splitlines() if '=' in line)
            if properties.get('DropInPaths') or properties.get('FragmentPath', str(self.unit)) != str(self.unit):
                raise ValueError('External HAProxy service override / HAProxy 服务被外部配置覆盖')
        return state

    def ctl(self, *args, check=True):
        return subprocess.run(['systemctl', *args], check=check, capture_output=True, text=True, timeout=30)

    def flags(self):
        return (self.ctl('is-active', '--quiet', UNIT, check=False).returncode == 0,
                self.ctl('is-enabled', '--quiet', UNIT, check=False).returncode == 0)

    def write(self, path, data, mode=0o600):
        if path.is_symlink():
            raise ValueError('Refusing symlink write')
        fd, tmp = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(data); f.flush(); os.fsync(f.fileno())
            os.chmod(tmp, mode); os.replace(tmp, path)
        finally:
            if os.path.exists(tmp): os.unlink(tmp)

    def reserved(self):
        paths = [self.conf, self.base / 'argo-server.json', self.base / 'warp-gateway.json']
        users = self.base / 'users'
        if users.exists() and not users.is_symlink():
            paths += list(users.glob('*/server.json'))
        ports = integrated_xhttp_ports(self.base)
        for path in paths:
            if path.exists():
                if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 4 * 1024**2:
                    raise ValueError('Unsafe managed node config')
                ports.update(tcp_ports(json.loads(path.read_text())))
        for path in (self.base / 'subscriptions.json', self.base / 'warp-client.json'):
            if path.exists(): ports.add(port(json.loads(self.read(path))['port']))
        return ports

    def preflight(self, state, old=None, active=False, probe=True):
        reserved = self.reserved()
        old_binds = {(r['listen'], r['port']) for r in (old or {'rules': []})['rules']} if active else set()
        local = {'127.0.0.1', '::1'}
        try:
            result = subprocess.run(['ip', '-j', 'addr'], check=True, capture_output=True, text=True, timeout=5)
            local.update(a['local'] for row in json.loads(result.stdout) for a in row.get('addr_info', []))
        except (OSError, ValueError, subprocess.SubprocessError):
            try: local.update(a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, type=socket.SOCK_STREAM))
            except socket.gaierror: pass
        local.update(r['listen'] for r in state['rules'] if r['listen'] not in ('0.0.0.0', '::'))
        entry_ports = {r['port'] for r in state['rules']}
        for r in state['rules']:
            if r['port'] in reserved:
                raise ValueError('Port reserved by a managed TCP node / 端口已被托管 TCP 节点预留')
            if (r['listen'], r['port']) not in old_binds:
                with socket.socket(socket.AF_INET6 if ':' in r['listen'] else socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    if ':' in r['listen']: sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    sock.bind((r['listen'], r['port']))
            addresses = {a[4][0] for a in socket.getaddrinfo(r['peer'], r['peer_port'], type=socket.SOCK_STREAM)}
            if r['peer_port'] in entry_ports and (addresses & local or any(ipaddress.ip_address(a).is_loopback or getattr(ipaddress.ip_address(a), 'ipv4_mapped', None) in {ipaddress.ip_address(x) for x in local if is_ip(x)} for a in addresses)):
                raise ValueError('TCP forwarding loop / TCP 转发回环')
            if probe:
                with socket.create_connection((r['peer'], r['peer_port']), timeout=5): pass

    def validate(self, state):
        with tempfile.TemporaryDirectory(prefix='haproxy-check-', dir=self.base) as tmp:
            cfg = Path(tmp) / 'haproxy.cfg'; cfg.write_text(render(state)); cfg.chmod(0o600)
            result = subprocess.run([self.binary, '-c', '-q', '-f', str(cfg)], capture_output=True, text=True, timeout=20)
            if result.returncode:
                raise ValueError('HAProxy validation failed / HAProxy 配置检查失败: ' + result.stderr[:2000])

    def snapshot(self, destination=None):
        state = self.guard()
        if state is None: raise ValueError('No HAProxy rules / 尚无 HAProxy 规则')
        if destination is None:
            self.backups.mkdir(mode=0o700, exist_ok=True)
            destination = self.backups / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        destination = Path(destination)
        if not (destination.parent == self.backups or destination.name == 'haproxy' and destination.parent.parent == self.base / 'backups'):
            raise ValueError('Backup must stay in managed directories')
        if destination.exists() or destination.is_symlink() or destination.parent.is_symlink():
            raise ValueError('Backup destination exists or is unsafe')
        destination.mkdir(mode=0o700)
        active, enabled = self.flags()
        for name in ('state.json', 'haproxy.cfg'):
            self.write(destination / name, self.read(self.root / name))
        self.write(destination / 'snapshot.json', json.dumps(dict(owner=OWNER, schema=1, active=active, enabled=enabled)).encode())
        return destination

    def health(self):
        for _ in range(5):
            time.sleep(.2)
            if self.ctl('is-active', '--quiet', UNIT, check=False).returncode:
                raise ValueError('HAProxy service did not stay active / HAProxy 服务启动失败')

    def apply(self, state, active=True, enabled=True, probe=True):
        state = normalize(state); old = self.guard()
        if old is None:
            source = self.ctl('show', '--property=FragmentPath', '--value', UNIT, check=False).stdout.strip()
            if source or any(self.flags()):
                raise ValueError('Existing external HAProxy relay unit / 已有外部 HAProxy 中转服务')
        old_active, old_enabled = self.flags() if old else (False, False)
        self.preflight(state, old, old_active, probe); self.validate(state)
        snapshot = self.snapshot() if old else None
        files = [self.root / 'state.json', self.root / 'haproxy.cfg', self.unit]
        previous = {p: self.read(p) for p in files} if old else {}
        try:
            self.root.mkdir(mode=0o700, exist_ok=True)
            self.write(files[0], json.dumps(state, indent=2).encode())
            self.write(files[1], render(state).encode())
            self.write(self.unit, self.unit_text().encode(), 0o644)
            self.ctl('daemon-reload')
            self.ctl('enable' if enabled else 'disable', UNIT)
            self.ctl('restart' if active else 'stop', UNIT)
            if active: self.health()
        except Exception as error:
            self.ctl('stop', UNIT, check=False)
            for path in files:
                if path in previous: self.write(path, previous[path], 0o644 if path == self.unit else 0o600)
                elif path.exists(): path.unlink()
            if not old and self.root.exists(): self.root.rmdir()
            self.ctl('daemon-reload')
            self.ctl('enable' if old_enabled else 'disable', UNIT, check=False)
            if old_active:
                self.ctl('restart', UNIT); self.health()
            raise ValueError('Apply failed; previous HAProxy state restored / 应用失败，已恢复原 HAProxy 状态') from error
        return snapshot

    def restore(self, value):
        path = Path(value)
        own = path.parent == self.backups
        full = path.name == 'haproxy' and path.parent.parent == self.base / 'backups'
        if full and (self.base / 'backups').is_symlink():
            raise ValueError('Full backup path is a symlink')
        if not (own or full) or path.is_symlink() or path.parent.is_symlink() or not path.is_dir() or {p.name for p in path.iterdir()} != {'state.json', 'haproxy.cfg', 'snapshot.json'}:
            raise ValueError('Not a managed HAProxy snapshot / 非托管 HAProxy 备份')
        state = normalize(json.loads(self.read(path / 'state.json')))
        if self.read(path / 'haproxy.cfg').decode() != render(state): raise ValueError('Backup config mismatch')
        flags = json.loads(self.read(path / 'snapshot.json'))
        if set(flags) != {'owner', 'schema', 'active', 'enabled'} or flags['owner'] != OWNER or type(flags['schema']) is not int or flags['schema'] != 1 or type(flags['active']) is not bool or type(flags['enabled']) is not bool:
            raise ValueError('Invalid snapshot metadata')
        return self.apply(state, flags['active'], flags['enabled'], probe=flags['active'])

    def purge(self):
        if self.guard() is None: return None
        snapshot = self.snapshot()
        self.ctl('disable', '--now', UNIT)
        self.unit.unlink()
        for name in ('state.json', 'haproxy.cfg'): (self.root / name).unlink()
        self.root.rmdir(); self.ctl('daemon-reload')
        return snapshot

    @contextlib.contextmanager
    def lock(self):
        path = self.base / 'haproxy.lock'
        fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    def run(self, action, args):
        state = self.guard()
        if action == 'guard': return
        if action == 'purge' and state is None: return
        if action == 'check_id':
            if not state or args[0] not in {r['id'] for r in state['rules']}:
                raise ValueError('Unknown rule ID / 无此规则 ID')
            return
        if action in ('check_port', 'check_configs'):
            reserved = {r['port'] for r in (state or {'rules':[]})['rules']} | integrated_xhttp_ports(self.base)
            if action == 'check_port': wanted = {port(int(args[0]))}
            else:
                directory = Path(args[0])
                if directory.is_symlink() or not directory.is_dir(): raise ValueError('Invalid candidate directory')
                paths = list(directory.glob('[0-9]*-config.json'))
                paths += [p for p in (directory / 'config/config.json', directory / 'argo-server.json', directory / 'warp-gateway.json') if p.exists()]
                paths += list((directory / 'users').glob('*/server.json'))
                wanted = set()
                for path in paths:
                    if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 4 * 1024**2: raise ValueError('Unsafe candidate config')
                    wanted.update(tcp_ports(json.loads(path.read_text())))
                subscription = directory / 'subscriptions.json'
                if subscription.exists() and not (self.base / 'subscriptions.json').exists():
                    wanted.add(port(json.loads(self.read(subscription))['port']))
            if wanted & reserved: raise ValueError('TCP port reserved by HAProxy / TCP 端口已被 HAProxy 预留')
            return
        if action == 'list':
            for r in (state or {'rules': []})['rules']:
                print(r['id'] + ' | ' + r['name'] + ' | ' + endpoint(r['listen'], r['port']) + ' → ' + endpoint(r['peer'], r['peer_port']))
            return
        if action == 'probe':
            if not state: raise ValueError('No HAProxy rules')
            for r in state['rules']:
                with socket.create_connection((r['peer'], r['peer_port']), timeout=5): pass
                print(r['name'] + ': TCP reachable / TCP 可达（尚未验证节点认证）')
            return
        with self.lock():
            state = self.guard()
            if action in ('add', 'edit'):
                if action == 'edit':
                    rid, *args = args
                    if not state or rid not in {r['id'] for r in state['rules']}: raise ValueError('Unknown rule ID')
                else: rid = uuid.uuid4().hex[:12]
                name, listen, lp, peer, pp = args
                state = state or dict(owner=OWNER, schema=1, rules=[])
                rule = dict(id=rid, name=name or 'SKYBYTE-TCP', listen=listen or '0.0.0.0', port=int(lp), peer=peer, peer_port=int(pp))
                if action == 'edit': state['rules'] = [rule if r['id'] == rid else r for r in state['rules']]
                else: state['rules'].append(rule)
                saved = self.apply(state)
            elif action == 'remove':
                if not state or args[0] not in {r['id'] for r in state['rules']}: raise ValueError('Unknown rule ID')
                state['rules'] = [r for r in state['rules'] if r['id'] != args[0]]
                saved = self.apply(state, probe=False) if state['rules'] else self.purge()
            elif action in ('start', 'restart'):
                if not state: raise ValueError('No HAProxy rules')
                saved = self.apply(state)
            elif action == 'stop':
                if state: self.ctl('disable', '--now', UNIT)
                saved = None
            elif action == 'backup': saved = self.snapshot(args[0] if args else None)
            elif action == 'restore': saved = self.restore(args[0])
            elif action == 'purge': saved = self.purge()
            else: raise ValueError('Unknown HAProxy action')
            if saved: print('Backup / 备份: ' + str(saved))


if __name__ == '__main__':
    try:
        base, units, binary, conf, action, *args = sys.argv[1:]
        Relay(base, units, binary, conf).run(action, args)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('HAProxy: ' + str(error), file=sys.stderr)
        sys.exit(1)
