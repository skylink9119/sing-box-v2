"""Read client parameters locally; never export server private keys or passwords."""
import json
from pathlib import Path
import sys


def load(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('Unsafe configuration path')
    return json.loads(path.read_text())


def render(meta, config, base, english=False):
    def tr(zh, en):
        return en if english else zh

    lines = [tr('========== 保密提醒 ==========', '========== KEEP PRIVATE =========='),
             tr('本脚本的节点配置、凭据、订阅和备份等重要数据保存在当前 VPS，请妥善保管。',
                'Node configuration, credentials, subscriptions and backups are stored on this VPS. Protect them.'),
             tr('请在可信终端查看；不要公开节点参数、完整链接、二维码或截图。',
                'Use a trusted terminal. Do not publish node parameters, full links, QR codes or screenshots.'),
             tr('请务必安装并启用防火墙：主菜单 d → 2；先放行 SSH 和实际节点端口。',
                'Install and enable a firewall: main menu d → 2. Allow SSH and actual node ports first.')]
    if not Path(meta).exists() and not Path(config).exists():
        return '\n'.join(lines + [tr('尚未安装节点。', 'No nodes installed.')])
    state, main = load(meta), load(config)
    configurations = [(main, state, 'Reality / VLESS')]
    argo = Path(base) / 'argo-server.json'
    if argo.exists() or argo.is_symlink():
        argo_state = Path(base) / 'argo-state.json'
        configurations.append((load(argo), load(argo_state) if argo_state.exists() else {}, 'Argo / VLESS + WS'))
    found = False
    na = tr('不适用（此节点不使用 Reality）', 'Not applicable (this node does not use Reality)')
    missing = tr('未保存', 'Not saved')

    def field(label, value):
        # Escape terminal control characters from manually edited metadata.
        value = json.dumps(str(value), ensure_ascii=False)[1:-1]
        label = json.dumps(str(label), ensure_ascii=False)[1:-1]
        lines.append(label + ': ' + value)

    for cfg, metadata, kind in configurations:
        for inbound in cfg.get('inbounds', []):
            if inbound.get('type') != 'vless':
                continue
            found = True
            tls = inbound.get('tls', {})
            reality = tls.get('reality', {})
            enabled = reality.get('enabled', False)
            lines += ['-' * 60, kind]
            field(tr('节点名称', 'Node name'), metadata.get('node_name') or 'SKYBYTE')
            field(tr('连接地址', 'Server address'), metadata.get('ip') or metadata.get('domain') or missing)
            field(tr('端口', 'Port'), metadata.get('export_ports', {}).get('vless') or
                  (443 if kind.startswith('Argo') else inbound.get('listen_port', missing)))
            for user in inbound.get('users', []):
                field('UUID' + (' (' + str(user.get('name', '')) + ')' if len(inbound['users']) > 1 else ''), user.get('uuid', missing))
            field(tr('公钥', 'Public key'), (metadata.get('public_key') or missing) if enabled else na)
            ids = reality.get('short_id', [])
            if isinstance(ids, str):
                ids = [ids]
            field('Short ID', ', '.join(x or tr('（空）', '(empty)') for x in ids) if enabled else na)
            field(tr('握手网站（SNI）', 'Handshake SNI'), tls.get('server_name') or metadata.get('domain') or missing)
            handshake = reality.get('handshake', {})
            host = handshake.get('server', '')
            if ':' in host:
                host = '[' + host + ']'
            field(tr('Reality 握手目标', 'Reality target'),
                  host + ':' + str(handshake.get('server_port', 443)) if enabled else na)
    if not found:
        lines.append(tr('未安装 VLESS/Reality 节点；Hysteria2 不使用 UUID、Reality 公钥或 Short ID。',
                        'No VLESS/Reality node installed. Hysteria2 does not use UUIDs, Reality public keys or short IDs.'))
    return '\n'.join(lines)


if __name__ == '__main__':
    try:
        print(render(*sys.argv[1:4], english=sys.argv[4] == 'en_US'))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print('Cannot read node parameters; inspect local managed configuration. / 无法读取节点参数，请检查本机托管配置。', file=sys.stderr)
        sys.exit(1)
