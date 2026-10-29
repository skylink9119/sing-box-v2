"""Verified, on-demand upstream diagnostics. No node configuration is read."""
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import tempfile
import zipfile

TOOLS = {'unlock': ('oneclickvirt/UnlockTests', 'Apache-2.0'), 'ecs': ('oneclickvirt/ecs', 'GPL-3.0')}
MAX_DOWNLOAD = 128 * 1024 * 1024


def clean_env(home):
    env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'NO_COLOR', 'SSL_CERT_FILE', 'SSL_CERT_DIR') if k in os.environ}
    env.update(HOME=str(home), TMPDIR=str(home))
    return env


def fetch(url, limit):
    if not url.startswith('https://'):
        raise ValueError('Non-HTTPS diagnostic download refused')
    with tempfile.TemporaryDirectory(prefix='skybyte-diagnostic-download-') as home:
        target = Path(home) / 'download'
        args = ['curl', '-q', '-fsSL', '--proto', '=https', '--proto-redir', '=https',
                '--connect-timeout', '8', '--max-time', '60', '--max-filesize', str(limit),
                '--user-agent', 'SKYBYTE-Diagnostics', '-o', str(target), url]
        result = subprocess.run(args, env=clean_env(home), capture_output=True, timeout=65)
        if result.returncode:
            raise ValueError('Official diagnostic download failed / 官方检测工具下载失败，请检查 GitHub 连接')
        data = target.read_bytes()
    if len(data) > limit:
        raise ValueError('Diagnostic download too large')
    return data


def private_dir(path):
    path = Path(path)
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Unsafe diagnostic directory / 检测目录异常')
    if path.exists() and not path.is_dir():
        raise ValueError('Diagnostic directory is not a directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def asset_name(tool, system=None, machine=None):
    system = (system or platform.system()).lower()
    machine = machine or platform.machine()
    arch = {'x86_64': 'amd64', 'amd64': 'amd64', 'aarch64': 'arm64', 'arm64': 'arm64',
            'armv7l': 'arm', 'armv6l': 'arm', 'i386': '386', 'i686': '386'}.get(machine)
    if system not in ('linux', 'darwin') or arch is None:
        raise ValueError('Unsupported diagnostic architecture / 检测工具不支持此架构')
    return ('ut-' + system + '-' + arch) if tool == 'unlock' else ('goecs_' + system + '_' + arch + '.zip')


def ensure_tool(report_dir, tool):
    repo, _license = TOOLS[tool]
    folder = private_dir(Path(report_dir).parent / 'diagnostic-tools' / tool)
    metadata = json.loads(fetch('https://api.github.com/repos/' + repo + '/releases/latest', 2 * 1024 * 1024))
    tag = metadata.get('tag_name', '')
    if metadata.get('draft') or metadata.get('prerelease') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,100}', tag):
        raise ValueError('Invalid diagnostic release')
    name = asset_name(tool)
    assets = [x for x in metadata.get('assets', []) if x.get('name') == name]
    if len(assets) != 1:
        raise ValueError('Official diagnostic asset missing')
    asset = assets[0]
    url = 'https://github.com/' + repo + '/releases/download/' + tag + '/' + name
    digest = asset.get('digest', '')
    if asset.get('browser_download_url') != url or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest):
        raise ValueError('Official diagnostic SHA256/URL missing or invalid')
    # Cache the original release asset, not an unverified extracted executable.
    cached = folder / (digest[7:] + '.asset')
    if cached.is_symlink() or (cached.exists() and not cached.is_file()):
        raise ValueError('Unsafe diagnostic cache')
    if cached.exists():
        if cached.stat().st_size > MAX_DOWNLOAD: raise ValueError('Diagnostic cache too large')
        data = cached.read_bytes()
    else:
        print('Downloading verified ' + repo + ' ' + tag + ' …', flush=True)
        data = fetch(url, MAX_DOWNLOAD)
    if len(data) > MAX_DOWNLOAD or hashlib.sha256(data).hexdigest() != digest[7:]:
        raise ValueError('Diagnostic SHA256 mismatch; not executed / 检测工具校验失败，未执行')
    if not cached.exists():
        fd, temp = tempfile.mkstemp(dir=folder, prefix='.download-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.replace(temp, cached)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    # Retain only the current verified asset; diagnostics must not grow with every release.
    for previous in folder.glob('*.asset'):
        if previous != cached and re.fullmatch(r'[a-f0-9]{64}[.]asset', previous.name) and previous.is_file() and not previous.is_symlink():
            previous.unlink()
    if tool == 'ecs':
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = [x for x in archive.infolist() if Path(x.filename).name in ('goecs', 'ecs') and not x.is_dir()]
            if len(entries) != 1 or entries[0].file_size > MAX_DOWNLOAD:
                raise ValueError('Invalid official diagnostic archive')
            data = archive.read(entries[0])
    return data, {'repository': repo, 'release': tag, 'asset': name, 'sha256': digest[7:]}


def execute(args, home, timeout, stdout=None, stderr=None):
    process = subprocess.Popen(args, cwd=home, env=clean_env(home), stdout=stdout, stderr=stderr, start_new_session=True)
    try:
        process.communicate(timeout=timeout)
    except BaseException:
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.communicate()
        raise
    return process


def unlock_arguments(path, port=None, all_platforms=False, language='zh_CN'):
    if path not in ('4', '6', 'warp'):
        raise ValueError('Invalid diagnostic path')
    args = ['-json', '-region', '20' if all_platforms else '0,21', '-conc', '6', '-timeout', '2m',
            '-m', '6' if path == '6' else '4', '-L', 'en' if language in ('en', 'en_US') else 'zh']
    if path == 'warp':
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Invalid loopback proxy port')
        args += ['-socks-proxy', 'socks5://127.0.0.1:' + str(port)]
    return args


def ecs_arguments(mode, language='zh_CN'):
    if mode not in ('route', 'speed', 'full'):
        raise ValueError('Invalid benchmark mode')
    # Explicitly opt into each module; upstream default includes uploads/stress tests.
    return ['-menu=false', '-upload=false', '-log=false', '-l', 'zh', '-dns-mode', 'system',
            '-basic=' + str(mode == 'full').lower(), '-ut=' + str(mode == 'full').lower(),
            '-security=' + str(mode == 'full').lower(), '-backtrace=' + str(mode != 'speed').lower(),
            '-nt3=' + str(mode != 'speed').lower(), '-speed=' + str(mode != 'route').lower(),
            '-cpu=false', '-memory=false', '-disk=false', '-email=false', '-ping=false', '-web=false', '-tgdc=false']


def safe_text(value):
    # Provider strings must not inject terminal control sequences or extra rows.
    value = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(value))
    return ''.join(c for c in value if c.isprintable()).strip()[:250]


def save_report(directory, report):
    directory = private_dir(directory)
    fd, name = tempfile.mkstemp(prefix='diagnostic-', suffix='.json', dir=directory)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    return Path(name)


def run(paths, report_dir, port=None, language='zh_CN', all_platforms=False):
    if not paths or any(p not in ('4', '6', 'warp') for p in paths):
        raise ValueError('Invalid diagnostic paths')
    arguments = [unlock_arguments(p, port, all_platforms, language) for p in paths]
    report_dir = private_dir(report_dir)
    payload, source = ensure_tool(report_dir, 'unlock')
    report = {'engine': source, 'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'playback_verified': False, 'runs': []}
    failed = False
    with tempfile.TemporaryDirectory(prefix='.unlock-', dir=report_dir.parent) as home:
        binary = Path(home) / 'ut'; binary.write_bytes(payload); binary.chmod(0o700)
        for path, args in zip(paths, arguments):
            print('\n=== ' + ('SOCKS5 / WARP (address family selected by proxy)' if path == 'warp' else 'VPS direct IPv' + path) + ' ===', flush=True)
            # Output goes to a private file so unexpected upstream output cannot exhaust RAM.
            with tempfile.TemporaryFile() as output:
                try:
                    result = execute([str(binary), *args], home, 140, stdout=output, stderr=subprocess.DEVNULL)
                    output.seek(0); raw = output.read(4 * 1024 * 1024 + 1)
                    if len(raw) > 4 * 1024 * 1024: raise ValueError('Diagnostic result too large')
                    data = json.loads(raw)
                    if not isinstance(data, dict) or data.get('schema_version') != 'goecs.unlocktests/v1' or not isinstance(data.get('results'), list):
                        raise ValueError('Unsupported diagnostic JSON schema')
                    rows = []
                    for item in data['results']:
                        if not isinstance(item, dict): raise ValueError('Invalid provider result')
                        row = {key: safe_text(item.get(key, '')) for key in ('name', 'status', 'region', 'unlock_type', 'info', 'error', 'ip_version')}
                        rows.append(row)
                    error = safe_text(data.get('error', ''))
                    failed = failed or result.returncode != 0 or bool(error) or not rows
                except (subprocess.TimeoutExpired, ValueError) as exc:
                    rows = []; error = safe_text(type(exc).__name__ + ': diagnostic incomplete / 检测未完成'); failed = True
            report['runs'].append({'path': path, 'results': rows, 'error': error})
            print('平台 / Platform | 状态 / Status | 地区 / Region | 类型 / Type')
            for row in rows:
                print(' | '.join(row[k] or '-' for k in ('name', 'status', 'region', 'unlock_type')))
                if row['info'] or row['error']: print('  ' + ' / '.join(x for x in (row['info'], row['error']) if x))
            if error: print('检测未完成 / Incomplete: ' + error)
    output = save_report(report_dir, report)
    print('本机报告 / Local report: ' + str(output))
    print('Upstream assessment; account eligibility/playback are not guaranteed. DNS/proxy types do not certify residential IPs.' if language in ('en', 'en_US') else '结果为上游检测判定；不保证账号资格或实际播放。DNS/代理类型为辅助判断，不能当作住宅 IP 认证。')
    if failed: raise ValueError('Diagnostic incomplete; partial report retained / 检测未完成，已保留部分结果')
    return report['runs']


def benchmark(mode, report_dir, language='zh_CN'):
    args = ecs_arguments(mode, language)
    report_dir = private_dir(report_dir)
    payload, source = ensure_tool(report_dir, 'ecs')
    print('VPS direct network only / 仅测试 VPS 直连网络；代理和节点客户端线路不在本检测范围。', flush=True)
    print('Engine: ' + source['repository'] + ' ' + source['release'], flush=True)
    with tempfile.TemporaryDirectory(prefix='.ecs-', dir=report_dir.parent) as home:
        binary = Path(home) / 'goecs'; binary.write_bytes(payload); binary.chmod(0o700)
        result = execute([str(binary), *args], home, 1200)
    if result.returncode: raise ValueError('Benchmark incomplete / 综合检测未完成')


def diagnostic_main(argv):
    if len(argv) != 4:
        raise ValueError('Invalid diagnostic invocation')
    action, directory, language, port = argv
    if action in ('route', 'speed', 'full'):
        return benchmark(action, directory, language)
    mapping = {'4': ['4'], '6': ['6'], 'both': ['4', '6'], 'warp': ['warp'], 'compare': ['4', 'warp'], 'all': ['4']}
    if action not in mapping:
        raise ValueError('Unknown diagnostic operation')
    return run(mapping[action], directory, int(port) if port else None, language, action == 'all')
