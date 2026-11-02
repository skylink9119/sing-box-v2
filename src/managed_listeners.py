"""Public managed listener inventory for firewall setup and auditing."""
from src.managed_ports import integrated_xhttp_ports

def managed_public_ports(base, conf):
    """Enumerate configured public node/services, including stopped reservations."""
    from pathlib import Path
    import json,re
    base=Path(base);result=set()
    if base.is_symlink():raise ValueError('Unsafe managed base')
    def read(path):
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file() or path.stat().st_size>4*1024**2:
            raise ValueError('Unsafe managed listener state')
        return json.loads(path.read_text())
    def add(protocol,number):
        if protocol not in ('tcp','udp') or type(number)!=int or not 1<=number<=65535:raise ValueError('Invalid managed listener')
        result.add((protocol,number))
    def inbounds(path):
        for node in read(path).get('inbounds',[]):
            if node.get('type') not in ('vless','hysteria2'):raise ValueError('Unknown managed inbound')
            add('udp' if node['type']=='hysteria2' else 'tcp',node['listen_port'])
    if (base/'state.json').is_file() and (Path(conf).exists() or Path(conf).is_symlink()):inbounds(Path(conf))
    ledger=base/'users.json'
    if ledger.exists() or ledger.is_symlink():
        data=read(ledger)
        if data.get('owner')!='SKYBYTE user quotas v1' or data.get('schema')!=1:raise ValueError('Invalid user owner')
        for user in data['users']:
            if user.get('deleted'):continue
            if not re.fullmatch('[0-9a-f]{16}',user['id']):raise ValueError('Invalid user ID')
            inbounds(base/'users'/user['id']/'server.json')
    subscription=base/'subscriptions.json'
    if subscription.exists() or subscription.is_symlink():
        data=read(subscription)
        if data.get('owner')!='SKYBYTE HTTPS subscriptions v1' or data.get('schema')!=1:raise ValueError('Invalid subscription owner')
        add('tcp',data['port'])
    relay=base/'haproxy/state.json'
    if relay.exists() or relay.is_symlink():
        data=read(relay)
        if data.get('owner')!='SKYBYTE HAProxy TCP v1' or data.get('schema')!=1:raise ValueError('Invalid HAProxy owner')
        for rule in data['rules']:add('tcp',rule['port'])
    acme=base/'acme-state.json'
    if acme.exists() or acme.is_symlink():
        data=read(acme)
        if data.get('owner')!='SKYBYTE ACME v1' or data.get('schema')!=1:raise ValueError('Invalid ACME owner')
        if data['method']=='http':add('tcp',80)
    for number in integrated_xhttp_ports(base):add('tcp',number)
    return sorted(result)
