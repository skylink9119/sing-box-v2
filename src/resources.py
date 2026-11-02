"""Read-only managed-core memory snapshots and conservative account planning."""
from pathlib import Path
import re
import subprocess
import sys

KIB = 1024
MIB_KIB = 1024


def processes(text, base, binary):
    """Select exact managed executable/config prefixes; never expose argv."""
    prefix = str(binary) + ' run -c '
    users = str(base / 'users') + '/'
    result = []
    for line in text.splitlines():
        fields = line.split(None, 2)
        if (len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit()
                or not fields[2].startswith(prefix)):
            continue
        config = fields[2][len(prefix):]
        result.append({'pid': int(fields[0]), 'rss': int(fields[1]),
                       'account': config if config.startswith(users) else None})
    return result


def read_number(path):
    try:
        value = path.read_text().strip()
        return int(value) if value.isdigit() else None
    except OSError:
        return None


def memory_snapshot(proc=Path('/proc'), cgroup=Path('/sys/fs/cgroup')):
    """Use MemAvailable and any visible cgroup ceiling, in KiB."""
    try:
        fields = dict(re.findall(r'^(MemTotal|MemAvailable):\s+(\d+)\s+kB$',
                                 (proc / 'meminfo').read_text(), re.M))
    except OSError:
        fields = {}
    total = int(fields['MemTotal']) if 'MemTotal' in fields else None
    available = int(fields['MemAvailable']) if 'MemAvailable' in fields else None
    # Walk the task's v2 hierarchy, including parent slices. The root also covers
    # containers that expose their cgroup as the namespace root.
    paths = [cgroup]
    try:
        for line in (proc / 'self/cgroup').read_text().splitlines():
            if not line.startswith('0::'):
                continue
            relative = Path(line[3:].lstrip('/'))
            if '..' not in relative.parts:
                path = cgroup / relative
                while path != cgroup:
                    paths.append(path)
                    path = path.parent
    except OSError:
        pass
    legacy = [cgroup / 'memory']
    try:
        for line in (proc / 'self/cgroup').read_text().splitlines():
            fields = line.split(':', 2)
            if len(fields) != 3 or 'memory' not in fields[1].split(','):
                continue
            relative = Path(fields[2].lstrip('/'))
            if '..' in relative.parts:
                continue
            path = cgroup / 'memory' / relative
            while path != cgroup / 'memory':
                legacy.append(path)
                path = path.parent
    except OSError:
        pass
    limits = [(path, 'memory.max', 'memory.current') for path in paths]
    limits += [(path, 'memory.limit_in_bytes', 'memory.usage_in_bytes') for path in legacy]
    limited = False
    for path, limit_file, usage_file in limits:
        limit = read_number(path / limit_file)
        if limit is None or (limit_file == 'memory.limit_in_bytes' and limit >= 1 << 60):
            continue
        limited = True
        used = read_number(path / usage_file)
        limit_kib = limit // KIB
        total = min(total, limit_kib) if total is not None else limit_kib
        remaining = max(0, limit - used) // KIB if used is not None else None
        available = min(available, remaining) if available is not None and remaining is not None else None
    if total is not None and available is not None:
        available = min(total, max(0, available))
    return total, available, limited


def pss_snapshot(records, proc=Path('/proc')):
    values = []
    for record in records:
        try:
            text = (proc / str(record['pid']) / 'smaps_rollup').read_text()
        except OSError:
            return None
        match = re.search(r'^Pss:\s+(\d+)\s+kB$', text, re.M)
        if match is None:
            return None
        values.append(int(match[1]))
    return sum(values) if values else None


def capacity(records, total, available):
    """Heuristic only: reserve 25%/256 MiB and budget twice maximum user RSS."""
    users = [row for row in records if row['account']]
    if not users or total is None or available is None or total <= 0:
        return None
    largest = max(row['rss'] for row in users)
    if largest <= 0:
        return None
    reserve = max(256 * MIB_KIB, (total + 3) // 4)
    budget = largest * 2
    additional = max(0, available - reserve) // budget
    # Account management supports at most 100 accounts. This is not a new limit.
    running = len({row['account'] for row in users})
    return reserve, budget, min(max(0, 100 - running), additional)


def render(records, total, available, limited, pss, en):
    def label(zh, english):
        return english if en else zh
    users = [row for row in records if row['account']]
    lines = [label('sing-box 进程数 / RSS：', 'sing-box processes / RSS: ') +
             f"{len(records)} / {sum(row['rss'] for row in records)/MIB_KIB:.1f} MiB",
             label('受限用户进程数 / RSS：', 'Quota user processes / RSS: ') +
             f"{len(users)} / {sum(row['rss'] for row in users)/MIB_KIB:.1f} MiB",
             label('运行受限账号数：', 'Running quota accounts: ') +
             str(len({row['account'] for row in users}))]
    if pss is not None:
        lines.append(label('核心合计 PSS（按比例计入共享页）：', 'Core PSS (shared pages apportioned): ') + f'{pss/MIB_KIB:.1f} MiB')
    else:
        lines.append(label('PSS：不可用；RSS 合计可能重复计算共享内存。', 'PSS unavailable; summed RSS may count shared pages repeatedly.'))
    if total is not None and available is not None:
        lines.append(label('可用 / 有效总内存：', 'Available / effective total RAM: ') + f'{available/MIB_KIB:.1f} / {total/MIB_KIB:.1f} MiB')
    else:
        lines.append(label('可用内存：未知，不估算新增账号容量。', 'Available RAM unknown; no additional-account estimate.'))
    if limited:
        lines.append(label('已按可见 cgroup 内存限制收紧可用预算。', 'Budget constrained by visible cgroup memory limits.'))
    estimate = capacity(records, total, available)
    if estimate is None:
        lines.append(label('容量估算：数据不足，请先运行一个受限账号后观察。', 'Capacity estimate: insufficient data; observe a running quota account first.') if not users else label('容量估算：内存或进程样本不完整，暂不估算。', 'Capacity estimate: incomplete memory/process samples; no estimate.'))
    else:
        reserve, budget, additional = estimate
        lines += [label('保留余量（总内存 25%，至少 256 MiB）：', 'Reserved headroom (25%, at least 256 MiB): ') + f'{reserve/MIB_KIB:.1f} MiB',
                  label('每新增账号参考预算（当前最大账号 RSS × 2）：', 'Budget per new account (largest current user RSS × 2): ') + f'{budget/MIB_KIB:.1f} MiB',
                  label('可增加的运行账号参考数（仅内存）：', 'Additional running-account estimate (memory only): ') + str(additional)]
        if not additional:
            lines.append(label('余量不足，建议先减少运行账号或升级内存。', 'Insufficient headroom; reduce running accounts or add RAM first.'))
    lines.append(label('这是当前快照与经验估算；连接数、HY2 缓冲和流量负载会增加占用，不能保证承载人数。', 'Snapshot and heuristic only: connections, HY2 buffers and traffic add memory; account capacity is not guaranteed.'))
    return '\n'.join(lines)


def main():
    base, binary, language = sys.argv[1:]
    result = subprocess.run(['ps', '-eo', 'pid=,rss=,args='], capture_output=True,
                            text=True, check=True, timeout=5)
    records = processes(result.stdout, Path(base), Path(binary))
    total, available, limited = memory_snapshot()
    print(render(records, total, available, limited, pss_snapshot(records), language == 'en_US'))
    try:
        load = Path('/proc/loadavg').read_text().split()[:3]
        print(('Load (1/5/15 min): ' if language == 'en_US' else '负载（1/5/15 分钟）：') + ' '.join(load))
    except OSError:
        pass


if __name__ == '__main__':
    main()
