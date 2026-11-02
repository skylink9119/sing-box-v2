"""Shared managed listener registry; included at build time, no VPS imports."""
def integrated_xhttp_ports(base):
    from pathlib import Path
    import json
    root=Path(base)/'xhttp';state=root/'state.json';marker=root/'.owner'
    if not root.exists() and not root.is_symlink():return set()
    if any(p.is_symlink() for p in (root,state,marker)):raise ValueError('Unsafe XHTTP state')
    if not marker.is_file() or marker.read_text()!='SKYBYTE-SB-XHTTP/1\n':raise ValueError('Unknown XHTTP owner')
    if not state.exists():return set()
    if state.stat().st_size>4*1024*1024:raise ValueError('XHTTP state too large')
    data=json.loads(state.read_text())
    if data.get('schema')!=1 or not isinstance(data.get('nodes'),dict):raise ValueError('Invalid XHTTP state')
    ports=set()
    for kind,node in data['nodes'].items():
        p=node['port']
        if kind not in ('xhttp-reality','xhttp-tls') or type(p)!=int or not 1<=p<=65535:raise ValueError('Invalid XHTTP port')
        ports.add(p)
    return ports
