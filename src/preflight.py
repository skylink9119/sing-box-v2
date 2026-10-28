"""Bounded installation diagnostics: no package, firewall or configuration changes."""
import argparse
import errno
import fcntl
import json
import os
from pathlib import Path
import platform
import queue
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import threading
import urllib.error
import urllib.request


class Report:
    def __init__(self, english=False):
        self.english = english
        self.items = []

    def tr(self, zh, en):
        return en if self.english else zh

    def add(self, status, zh, en, detail_zh, detail_en=None):
        self.items.append((status, self.tr(zh, en),
                           self.tr(detail_zh, detail_en if detail_en is not None else detail_zh)))

    def render(self):
        def clean(value):
            return json.dumps(str(value), ensure_ascii=False)[1:-1]
        print(self.tr('\n========== 节点安装前检测 ==========', '\n========== NODE INSTALLATION CHECK =========='))
        for status, label, detail in self.items:
            title = {'pass': self.tr('通过', 'PASS'), 'warn': self.tr('提醒', 'WARN'), 'fail': self.tr('失败', 'FAIL')}[status]
            print('[' + title + '] ' + clean(label) + ': ' + clean(detail))
        failed = any(item[0] == 'fail' for item in self.items)
        warnings = sum(item[0] == 'warn' for item in self.items)
        summary = self.tr('检测未通过：请先处理失败项，停止本次安装。', 'FAILED: resolve failed checks before installing.') if failed else self.tr(
            '本阶段检测通过；请核对提醒项。', 'This stage passed; review any warnings.')
        color = ('\033[1;31m' if failed else '\033[1;32m') if sys.stdout.isatty() and not os.environ.get('NO_COLOR') else ''
        print(color + '===== ' + summary + ' =====' + ('\033[0m' if color else ''))
        print(self.tr('提醒数量：', 'Warnings: ') + str(warnings))
        print(self.tr('仅检测本 VPS；端口可绑定不代表公网可达。云安全组、NAT 映射和客户端连接须另行核对。',
                      'Checks this VPS only. A bindable port is not proof of public reachability; inspect provider rules, NAT mappings and client access.'))
        return int(failed)


def package_locks(paths):
    """APT/dpkg use POSIX record locks; an existing unlocked file is normal."""
    busy, unknown = [], []
    for path in map(Path, paths):
        fd = None
        try:
            if path.is_symlink():
                unknown.append(str(path))
                continue
            fd = os.open(path, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                unknown.append(str(path))
                continue
            fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.lockf(fd, fcntl.LOCK_UN)
        except FileNotFoundError:
            pass
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN) and fd is not None:
                busy.append(str(path))
            else:
                unknown.append(str(path))
        finally:
            if fd is not None:
                os.close(fd)
    return busy, unknown


def environment(report, project, os_release='/etc/os-release', paths=(), reality=False):
    report.add('pass' if os.geteuid() == 0 else 'fail', '运行权限', 'Privileges',
               'root' if os.geteuid() == 0 else '请以 root 账户运行',
               'root' if os.geteuid() == 0 else 'Run as root')
    distro = ''
    try:
        for line in Path(os_release).read_text().splitlines():
            if line.startswith('ID='):
                distro = line.split('=', 1)[1].strip().strip('"\'')
    except OSError:
        pass
    supported = platform.system() == 'Linux' and distro in ('ubuntu', 'debian')
    report.add('pass' if supported else 'fail', '系统支持', 'Operating system',
               'Linux / ' + distro if supported else '需要 Ubuntu/Debian Linux；检测到：' + (distro or platform.system()),
               'Linux / ' + distro if supported else 'Ubuntu/Debian Linux required; detected: ' + (distro or platform.system()))
    architectures = {'x86_64', 'aarch64', 'arm64'}
    if project == 'sing-box':
        architectures |= {'i386', 'i486', 'i586', 'i686', 'armv7l'}
    machine = platform.machine()
    report.add('pass' if machine in architectures else 'fail', '核心架构', 'Core architecture', machine)
    systemd = Path('/run/systemd/system').is_dir()
    report.add('pass' if systemd else 'fail', 'systemd', 'systemd',
               '可用' if systemd else '未发现正在运行的 systemd；无法安装托管服务',
               'Available' if systemd else 'Running systemd not found; managed services cannot be installed')
    if reality:
        report.add('pass' if ssl.HAS_TLSv1_3 else 'fail', 'Python TLS 1.3', 'Python TLS 1.3',
                   '支持握手目标检测' if ssl.HAS_TLSv1_3 else 'Python/OpenSSL 不支持 TLS 1.3，请先升级系统依赖',
                   'Target checks supported' if ssl.HAS_TLSv1_3 else 'Upgrade system Python/OpenSSL for TLS 1.3 target checks')
    busy, unknown = package_locks(['/var/lib/dpkg/lock-frontend', '/var/lib/dpkg/lock',
                                   '/var/lib/apt/lists/lock', '/var/cache/apt/archives/lock'])
    if busy:
        report.add('fail', 'APT/DPKG 锁', 'APT/DPKG locks',
                   '其他软件安装任务正在占用：' + ', '.join(busy) + '；等待任务完成后重试，请勿删除锁文件。',
                   'Another package task holds: ' + ', '.join(busy) + '; wait for it to finish. Do not delete lock files.')
    elif unknown:
        report.add('warn', 'APT/DPKG 锁', 'APT/DPKG locks',
                   '无法确认锁状态，请检查权限或异常路径：' + ', '.join(unknown),
                   'Cannot inspect locks; check permissions or unsafe paths: ' + ', '.join(unknown))
    else:
        report.add('pass', 'APT/DPKG 锁', 'APT/DPKG locks', '当前未被占用', 'Currently available')
    missing = [tool for tool in ('apt-get', 'curl', 'openssl', 'ss', 'ip', 'flock') if not shutil.which(tool)]
    report.add('fail' if 'apt-get' in missing else 'warn' if missing else 'pass', '依赖命令', 'Dependency commands',
               '缺少或不在 PATH：' + ', '.join(missing) + '；请核对 root PATH，安装流程会补齐可安装的依赖。' if missing else '所需命令可用',
               'Missing or outside PATH: ' + ', '.join(missing) + '; inspect root PATH; installation will add available dependencies.' if missing else 'Required commands available')
    seen = set()
    for destination in map(Path, paths):
        current = destination
        while not current.exists() and current != current.parent:
            current = current.parent
        if any(p.is_symlink() for p in (destination, *destination.parents)):
            report.add('fail', '安装路径', 'Installation path', '路径包含符号链接：' + str(destination),
                       'Path contains a symlink: ' + str(destination))
            continue
        try:
            device = current.stat().st_dev
            if device in seen:
                continue
            seen.add(device)
            info = os.statvfs(current)
            free = info.f_bavail * info.f_frsize // (1024 * 1024)
            blocked = bool(info.f_flag & getattr(os, 'ST_RDONLY', 1)) or info.f_favail == 0 or info.f_bavail == 0
            report.add('fail' if blocked else 'warn' if free < 256 else 'pass', '安装存储空间', 'Installation storage',
                       str(current) + '：可用 ' + str(free) + ' MiB' + ('；空间/inode 已耗尽或文件系统只读' if blocked else '；低于 256 MiB，建议先清理' if free < 256 else ''),
                       str(current) + ': ' + str(free) + ' MiB free' + ('; storage/inodes exhausted or filesystem read-only' if blocked else '; below 256 MiB, free space before installing' if free < 256 else ''))
        except OSError:
            report.add('fail', '安装存储空间', 'Installation storage', '无法检查：' + str(destination), 'Cannot inspect: ' + str(destination))


def ports(report, listen, tcp=None, udp=None):
    if tcp is None and udp is None:
        raise ValueError('Port required')
    family = socket.AF_INET6 if ':' in listen else socket.AF_INET
    for protocol, number, kind in (('TCP', tcp, socket.SOCK_STREAM), ('UDP', udp, socket.SOCK_DGRAM)):
        if number is None:
            continue
        if not 1 <= number <= 65535:
            raise ValueError('Invalid port')
        label = protocol + ' ' + str(number)
        try:
            with socket.socket(family, kind) as sock:
                if kind == socket.SOCK_STREAM:
                    # Match server binds: TCP TIME_WAIT is reusable, active listeners are not.
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if family == socket.AF_INET6:
                    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                sock.bind((listen, number))
            report.add('pass', label, label, '本机可绑定（' + listen + '）', 'Locally bindable (' + listen + ')')
        except OSError as error:
            occupied = error.errno == errno.EADDRINUSE
            report.add('fail', label, label,
                       '已被占用，请选择其他空闲端口；TCP 与 UDP 分别检查。' if occupied else '无法绑定该地址族/端口，请检查 IPv4/IPv6 与系统权限。',
                       'Occupied; choose another free port. TCP and UDP are checked separately.' if occupied else 'Cannot bind; check IPv4/IPv6 support and privileges.')
    active = []
    for executable, arguments, token in [('ufw', ['status'], 'Status: active'), ('firewall-cmd', ['--state'], 'running')]:
        if not shutil.which(executable):
            continue
        try:
            result = subprocess.run([executable, *arguments], capture_output=True, text=True, timeout=3,
                                    env={**os.environ, 'LC_ALL': 'C'})
            if result.returncode == 0 and token in result.stdout:
                active.append(executable)
        except (OSError, subprocess.SubprocessError):
            pass
    report.add('warn', '防火墙与公网端口', 'Firewall and public ports',
               ('已启用 ' + ', '.join(active) + '；' if active else '未确认已启用 UFW/firewalld，请安装/启用合适的防火墙；') + '先放行 SSH 和实际 TCP/UDP 端口，并核对云安全组；不自动修改规则。',
               ('Active: ' + ', '.join(active) + '. ' if active else 'Active UFW/firewalld not confirmed; install/enable a suitable firewall. ') + 'Allow SSH and actual TCP/UDP ports, and inspect provider rules; rules are not changed.')


def download(report, offline=False, timeout=10, existing_core=False):
    if offline or existing_core:
        report.add('warn', 'GitHub HTTPS', 'GitHub HTTPS',
                   '本机已有核心，本次沿用，跳过不必要的下载联网检测' if existing_core else '离线安装包模式，跳过联网检测',
                   'Existing local core will be reused; unnecessary download/network check skipped' if existing_core else 'Offline asset mode; network check skipped')
        return
    try:
        results = queue.Queue()
        opener = urllib.request.urlopen
        def request_head():
            try:
                request = urllib.request.Request('https://github.com/', method='HEAD', headers={'User-Agent': 'SKYBYTE-Installation-Check'})
                with opener(request, timeout=min(8, timeout), context=ssl.create_default_context()) as response:
                    if not 200 <= response.status < 400:
                        raise urllib.error.HTTPError(request.full_url, response.status, '', {}, None)
                results.put(None)
            except Exception as error:
                results.put(error)
        # Socket timeouts alone do not bound libc DNS resolution.
        threading.Thread(target=request_head, daemon=True).start()
        try:
            error = results.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError('HTTPS deadline') from None
        if error is not None:
            raise error
        report.add('pass', 'GitHub HTTPS', 'GitHub HTTPS', '首页 HTTPS 与证书验证通过；正式下载仍需校验 API/CDN 与文件摘要',
                   'Homepage HTTPS and certificate verified; downloads still require API/CDN access and digest checks')
    except (OSError, urllib.error.URLError, ValueError) as error:
        reason = getattr(error, 'reason', error)
        if isinstance(reason, ssl.SSLCertVerificationError):
            zh, en = '证书验证失败，请检查 VPS 时间、CA 证书与 HTTPS 拦截', 'Certificate verification failed; check VPS clock, CA roots and HTTPS interception'
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            zh, en = '连接超时，请检查 VPS 出站网络或使用离线安装包', 'Connection timed out; inspect egress connectivity or use offline assets'
        elif isinstance(reason, socket.gaierror):
            zh, en = 'DNS 解析失败，请先修复 VPS DNS', 'DNS lookup failed; repair VPS DNS first'
        elif isinstance(error, urllib.error.HTTPError):
            zh, en = 'HTTP ' + str(error.code) + '，请检查访问限制或限流', 'HTTP ' + str(error.code) + '; check access restrictions or rate limits'
        else:
            zh, en = 'HTTPS 连接失败，请检查出站网络、DNS 与系统时间', 'HTTPS connection failed; inspect egress, DNS and system clock'
        status = 'warn' if isinstance(error, urllib.error.HTTPError) and error.code in (403, 405, 429) else 'fail'
        if status == 'warn':
            zh += '；首页响应不等于发布附件可用性，将由正式下载与摘要校验确认。'
            en += '; homepage status does not establish release-asset availability; verified download will decide.'
        report.add(status, 'GitHub HTTPS', 'GitHub HTTPS', zh, en)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', choices=('sing-box', 'xray'), required=True)
    parser.add_argument('--phase', choices=('environment', 'ports', 'download'), required=True)
    parser.add_argument('--language', default='zh')
    parser.add_argument('--os-release', default='/etc/os-release')
    parser.add_argument('--paths', nargs='*', default=[])
    parser.add_argument('--reality', action='store_true')
    parser.add_argument('--listen', choices=('0.0.0.0', '::', '127.0.0.1', '::1'), default='0.0.0.0')
    parser.add_argument('--tcp-port', type=int)
    parser.add_argument('--udp-port', type=int)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--existing-core', action='store_true')
    options = parser.parse_args(argv)
    report = Report(options.language in ('en', 'en_US'))
    try:
        if options.phase == 'environment':
            environment(report, options.project, options.os_release, options.paths, options.reality)
        elif options.phase == 'ports':
            ports(report, options.listen, options.tcp_port, options.udp_port)
        else:
            print(report.tr('正在检查 GitHub HTTPS（网络等待上限 10 秒）……',
                            'Checking GitHub HTTPS (10-second network wait limit)…'), flush=True)
            download(report, options.offline, existing_core=options.existing_core)
    except (OSError, ValueError, TypeError):
        report.add('fail', '检测参数', 'Check parameters', '参数无效或无法读取本机环境', 'Invalid parameters or unreadable local environment')
    return report.render()


if __name__ == '__main__':
    sys.exit(main())
