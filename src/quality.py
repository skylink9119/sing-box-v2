"""Local-only adapters for the xykt engines used by NodeQuality.

Shared process/download/text helpers are composed from media.py by build.py.
No node state, credentials, web server, or report-upload service is used.
"""
import time

QUALITY_TOOLS = {
    'hardware': ('HardwareQuality', 'hardware.sh', '06f99880d516bb744afa2948261b9697c79789e2',
                 '73e032ef5409e014cca411a71c677a76db19a94ef0a96a73827b41b2059cd86c'),
    'ip': ('IPQuality', 'ip.sh', 'f0df4dc1d7961a092609a17c5b66a7ce49b519cc',
           'b30df5a3c2204276c54e99dcc5080b46f8a627667730aee7de63b109b8ecaecf'),
    'network': ('NetQuality', 'net.sh', 'd5b99484d51286374d24b892c1b54235dc282148',
                '6c40fe1ae40d969255cb63075c94882733b82ba43831341eb1aadeea7b1fbfcd'),
}
QUALITY_LIMIT = 4 * 1024 * 1024
QUALITY_LABELS = {
    'hardware': '硬件质量 / Hardware', 'ip': 'IP 质量与解锁 / IP quality',
    'network': '网络质量与测速 / Network', 'route': '三网回程 / Return routes',
    'OS': '系统', 'Motherboard': '主板', 'CPU': 'CPU', 'GPU': 'GPU',
    'Memory': '内存', 'Disk': '磁盘', 'Benchmark': '性能评分',
    'Info': 'IP 信息', 'Type': 'IP 类型', 'Score': '风险评分',
    'Factor': '风险因素', 'Media': '流媒体与 AI', 'Mail': '邮件连通性',
    'BGP': 'BGP 信息', 'Local': '本机网络', 'Connectivity': '互联网络',
    'Delay': '三网延迟', 'Speedtest': '上下行测速', 'Transfer': '传输质量',
}


def quality_arguments(kind, output, family='4', language='zh_CN', quick=False):
    if kind not in ('hardware', 'ip', 'network', 'route') or family not in ('4', '6'):
        raise ValueError('Invalid quality test / 检测选项无效')
    # -p suppresses Check.Place report uploads AND hardware Geekbench uploads.
    # -y permits dependencies only after the manager's explicit confirmation.
    args = ['-p', '-y', '-l', 'en' if language in ('en', 'en_US') else 'cn',
            '-o', str(output)]
    # HardwareQuality has no -4/-6 switch; it inspects the local host.
    if kind != 'hardware':
        args += ['-' + family]
    if kind == 'hardware' and quick:
        args += ['-F']
    if kind == 'network':
        args += ['-S', '5']  # routes have their own run / report section
    if kind == 'route':
        args += ['-R', '-S', '123']  # route-only; no bandwidth benchmark
    return args


def quality_download(kind):
    repo, filename, commit, digest = QUALITY_TOOLS['network' if kind == 'route' else kind]
    data = fetch('https://raw.githubusercontent.com/xykt/' + repo + '/' + commit + '/' + filename,
                 2 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError('检测工具 SHA256 不匹配，未执行 / Diagnostic SHA256 mismatch')
    return data, {'repository': 'xykt/' + repo, 'commit': commit, 'sha256': digest, 'license': 'AGPL-3.0'}


def quality_execute(args, home, log, timeout):
    """Bounded logs, periodic progress, and process-group cleanup on cancellation."""
    process = subprocess.Popen(args, cwd=home, env=clean_env(home), stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    def drain():
        remaining = QUALITY_LIMIT
        with log.open('wb') as stream:
            while chunk := process.stdout.read(8192):
                if remaining:
                    stream.write(chunk[:remaining])
                    remaining = max(0, remaining - len(chunk))
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    started = time.monotonic()
    try:
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                return process.wait(timeout=min(15, remaining))
            except subprocess.TimeoutExpired:
                print('检测中 / Testing … ' + str(int(time.monotonic() - started)) + ' s', flush=True)
    finally:
        # Kill residual children even if their parent has already exited.
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.wait(timeout=2)
        except subprocess.TimeoutExpired: pass
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        process.wait()
        reader.join(timeout=3)
        process.stdout.close()


def quality_read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('工具未生成报告 / No report generated')
    with path.open('rb') as stream:
        data = stream.read(QUALITY_LIMIT + 1)
    if len(data) > QUALITY_LIMIT:
        raise ValueError('检测报告过大 / Report too large')
    return data.decode('utf-8', 'replace')


def quality_json(text):
    """Upstream appends JSON objects (one per address family), not a JSON array."""
    decoder = json.JSONDecoder()
    objects = []
    while text.strip():
        value, end = decoder.raw_decode(text.lstrip())
        if not isinstance(value, dict) or not isinstance(value.get('Head'), dict):
            raise ValueError('不支持的报告结构 / Unsupported report schema')
        objects.append(value)
        if len(objects) > 2:
            raise ValueError('Too many report objects')
        text = text.lstrip()[end:]
    if not objects:
        raise ValueError('空报告 / Empty report')
    return objects


def quality_rows(value, prefix='', depth=0):
    """Keep all source fields in JSON; cap terminal details without hiding truncation."""
    if depth > 12:
        yield (prefix, '[嵌套过深 / Too deeply nested]')
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from quality_rows(item, (prefix + ' / ' if prefix else '') + safe_text(key, 80), depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from quality_rows(item, prefix + ' [' + str(index + 1) + ']', depth + 1)
    else:
        result = '未知 / Unknown' if value is None or value == '' or value == 'null' else str(value)
        yield (prefix, safe_text(result, 1000))


def quality_table(rows, language='zh_CN', columns=None, *, headers=None, widths=None):
    columns = max(40, min(140, columns or shutil.get_terminal_size((100, 24)).columns))
    if widths is None:
        label_width = max(12, (columns - 7) // 3)
        widths = [label_width, columns - 7 - label_width]
    result = []
    def border(left, middle, right):
        return left + middle.join('─' * (w + 2) for w in widths) + right
    def cells(row):
        wrapped = [wrap_cell(x, w) for x, w in zip(row, widths)]
        for i in range(max(map(len, wrapped))):
            parts = [lines[i] if i < len(lines) else '' for lines in wrapped]
            result.append('│' + '│'.join(' ' + x + ' ' * (w - display_width(x) + 1)
                                        for x, w in zip(parts, widths)) + '│')
    result.append(border('┌', '┬', '┐'))
    cells(headers or (('Item', 'Result') if language in ('en', 'en_US') else ('项目', '检测结果')))
    result.append(border('├', '┼', '┤'))
    count = 0
    for row in rows:
        if count == 300:
            cells(('更多 / More', '其余字段见本地 JSON / See local JSON for remaining fields'))
            break
        cells(row)
        count += 1
    if not count:
        cells(('—', '无结果 / No results'))
    result.append(border('└', '┴', '┘'))
    return '\n'.join(result)


ROUTE_HOP = re.compile(r'^(\d+(?:-\s*\d+)?)\s+(\d+(?:\.\d+)?\s*ms|\*)\s*(.*)$')
ROUTE_GROUP = re.compile(r'^(.+?\s(?:电信|联通|移动))\s+(.*?->.*)$')


def quality_route(text, language, columns):
    columns = max(40, min(140, columns or shutil.get_terminal_size((100, 24)).columns))
    english = language in ('en', 'en_US')
    output = []
    hops = []

    def flush_hops():
        if not hops:
            return
        if columns >= 80:
            address_width = min(29, max(16, max(display_width(row[2]) for row in hops)))
            widths = [5, 10, address_width, 9]
            widths.append(columns - 16 - sum(widths))
            headers = ('Hop', 'Latency', 'Address', 'ASN', 'Network / location') if english else ('跳点', '延迟', '地址', 'ASN', '线路 / 位置')
            output.append(quality_table(hops, language, columns, headers=headers, widths=widths))
        else:
            headers = ('Hop', 'Route details') if english else ('跳点', '路由详情')
            rows = [(hop, '  '.join(value for value in (latency, addr, asn, detail) if value))
                    for hop, latency, addr, asn, detail in hops]
            output.append(quality_table(rows, language, columns, headers=headers, widths=[5, columns - 12]))
        hops.clear()

    started = False
    for raw in text.splitlines():
        line = safe_text(raw, 1000)
        if not line:
            continue
        if re.fullmatch(r'[=*]{5,}', line):
            if started and line.startswith('='):
                break  # upstream footer
            continue
        if line.startswith(('https://github.com/xykt/NetQuality', 'bash <(')):
            continue
        group = ROUTE_GROUP.fullmatch(line)
        if group:
            flush_hops()
            output.append('')
            output.extend(wrap_cell(group[1] + '  ·  ' + group[2], columns))
            started = True
            continue
        hop = ROUTE_HOP.fullmatch(line)
        if hop:
            number, latency, rest = hop.groups()
            addr, _, detail = rest.partition(' ')
            detail = detail.strip()
            asn = ''
            if re.match(r'^AS[0-9]+(?:\s|$)', detail):
                asn, _, detail = detail.partition(' ')
            hops.append((''.join(number.split()), latency, addr, asn, detail.strip()))
            started = True
            continue
        flush_hops()
        # Keep metadata, path summaries and unfamiliar lines readable at full width.
        for part in re.split(r'\s+(?=自治系统路径：)', line):
            output.extend(wrap_cell(part, columns))
    flush_hops()
    return '\n'.join(output)


def quality_render(run, language='zh_CN', columns=None):
    scope = '本机 / Local' if run['kind'] == 'hardware' else 'IPv' + run['family']
    output = ['\n=== ' + QUALITY_LABELS[run['kind']] + ' · ' + scope + ' ===']
    if run['kind'] == 'route':
        output.append(('Execution: ' if language in ('en', 'en_US') else '执行状态：') + run['status'])
    else:
        output.append(quality_table([('执行状态 / Execution', run['status'])], language, columns))
    if run.get('error'):
        output.append(quality_table([('说明 / Details', run['error'])], language, columns))
    for document in run.get('data', []):
        for chapter, value in document.items():
            if chapter == 'Head' or not value:
                continue
            output.append('\n' + safe_text(chapter if language in ('en', 'en_US') else QUALITY_LABELS.get(chapter, chapter)))
            if chapter == 'Media' and isinstance(value, dict):
                output.append(report_table([{'name': name, 'status': item.get('Status', 'Unknown'),
                                             'region': item.get('Region', ''), 'unlock_type': item.get('Type', '')}
                                            for name, item in value.items() if isinstance(item, dict)],
                                           language, columns, color=False))
            else:
                output.append(quality_table(quality_rows(value), language, columns))
    if run.get('route_text'):
        output.append(quality_route(run['route_text'], language, columns))
    return '\n'.join(output)


def quality_main(argv):
    action, directory, language, family = argv
    if action not in ('hardware', 'quick', 'ip', 'network', 'route', 'full') or family not in ('4', '6'):
        raise ValueError('Invalid quality test')
    directory = private_dir(directory)
    folder = Path(tempfile.mkdtemp(prefix='quality-', dir=directory))
    report = {'schema': 'skybyte.quality/v1', 'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'upload': False, 'runs': []}
    kinds = ['hardware', 'ip', 'network', 'route'] if action == 'full' else ['hardware' if action == 'quick' else action]
    failed = False
    for kind in kinds:
        run = {'kind': kind, 'family': family, 'status': '未完成 / Incomplete'}
        report['runs'].append(run)
        cancelled = False
        print('\n开始 / Starting: ' + QUALITY_LABELS[kind], flush=True)
        try:
            payload, run['engine'] = quality_download(kind)
            with tempfile.TemporaryDirectory(prefix='.quality-', dir=directory) as home:
                script = Path(home) / 'check.sh'
                script.write_bytes(payload)
                output = Path(home) / ('result.txt' if kind == 'route' else 'result.json')
                log = folder / (kind + '.log')
                try:
                    code = quality_execute(['bash', str(script), *quality_arguments(kind, output, family, language, action == 'quick')],
                                           home, log, 1800 if kind in ('hardware', 'network') else 900)
                finally:
                    # Preserve completed output even if a later stage times out.
                    if output.is_file() and not output.is_symlink():
                        try:
                            raw = quality_read(output)
                            if kind == 'route':
                                run['route_text'] = '\n'.join(safe_text(line, 1000) for line in raw.splitlines())
                            else:
                                run['data'] = quality_json(raw)
                        except (ValueError, OSError, RecursionError):
                            pass
                run['exit_code'] = code
                raw = quality_read(output)
                if kind == 'route':
                    if not raw.strip(): raise ValueError('Empty route report')
                    run['route_text'] = '\n'.join(safe_text(line, 1000) for line in raw.splitlines())
                else:
                    run['data'] = quality_json(raw)
                # These pinned IP/Net scripts end with an IPv6 && expression.
                # A successful IPv4-only report therefore exits 1. Accept only
                # with a parsed report, keeping the original exit code recorded.
                completed = code == 0 or (code == 1 and family == '4' and kind != 'hardware')
                run['status'] = '完成 / Completed' if completed else '部分结果 / Partial results'
                failed |= not completed
        except (ValueError, OSError, subprocess.SubprocessError, RecursionError) as error:
            run['status'] = '失败 / Failed'
            run['error'] = safe_text(error)
            failed = True
        except KeyboardInterrupt:
            run['status'] = '已取消 / Cancelled'
            cancelled = failed = True
        text = quality_render(run, language)
        print(text, flush=True)
        # Save after every stage, including errors/cancellation; never create HTML.
        (folder / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        (folder / 'report.txt').write_text('\n'.join(quality_render(item, language) for item in report['runs']) + '\n')
        for path in folder.iterdir(): path.chmod(0o600)
        if cancelled:
            break
    print('\n本地报告 / Local reports: ' + str(folder / 'report.txt') + '\n' + str(folder / 'report.json'))
    print('检测完成不等于所有项目通过；实际播放与客户端连通性需另行验证。 / Completion does not imply every probe passed.')
    if failed:
        raise ValueError('部分检测未完成，查看本地报告及 .log / Some tests failed; inspect reports and logs')
