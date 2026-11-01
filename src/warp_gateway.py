def gateway(profile,port,target,binary,family='auto'):
    if family not in ('auto','4','6'):raise ValueError('Invalid native gateway family')
    p=configparser.ConfigParser(interpolation=None,strict=True)
    try:
        with open(profile) as f:p.read_file(f)
    except configparser.Error:raise ValueError('Invalid WireGuard profile') from None
    if set(p.sections())!={'Interface','Peer'}:raise ValueError('Expected one Interface and Peer')
    if set(p['Interface'])-{'privatekey','address','dns','mtu','listenport'} or set(p['Peer'])-{'publickey','allowedips','endpoint','persistentkeepalive','reserved'}:raise ValueError('Unsupported profile directives; scripts are never executed')
    a=p['Interface'];b=p['Peer']
    for key in (a['privatekey'],b['publickey']):
        if len(base64.b64decode(key,validate=True))!=32:raise ValueError('Invalid WireGuard key')
    addresses=[str(ipaddress.ip_interface(x.strip())) for x in a['address'].split(',')]
    allowed=[str(ipaddress.ip_network(x.strip(),strict=False)) for x in b['allowedips'].split(',')]
    if {ipaddress.ip_interface(x).version for x in addresses}!={4,6} or set(allowed)!={'0.0.0.0/0','::/0'}:raise ValueError('A dual-stack WARP profile is required')
    endpoint=b['endpoint'].strip();match=re.fullmatch(r'(?:\[([^]]+)\]|([^:\s]+)):(\d+)',endpoint)
    if not match:raise ValueError('Invalid peer Endpoint')
    address=relay_address(match[1] or match[2]);peer_port=int(match[3])
    try:
        native=ipaddress.ip_address(address)
        if family!='auto' and native.version!=int(family):raise ValueError('WireGuard Endpoint does not match native connectivity; supply a reachable peer IP')
    except ValueError:
        # Distinguish a hostname from a numeric endpoint in the wrong family.
        if re.fullmatch('[0-9a-fA-F:.]+',address):raise
    if not 1<=peer_port<=65535:raise ValueError('Invalid peer port')
    reserved=[int(x.strip()) for x in b.get('reserved','0,0,0').split(',')]
    if len(reserved)!=3 or any(not 0<=x<=255 for x in reserved):raise ValueError('Invalid reserved bytes')
    mtu=int(a.get('mtu','1280'));listen=int(a.get('listenport','0'))
    if not 1280<=mtu<=9000 or not 0<=listen<=65535:raise ValueError('Invalid MTU/listen port')
    cfg={'log':{'level':'warn'},'inbounds':[{'type':'socks','tag':'warp-local','listen':'127.0.0.1','listen_port':port}],
         'outbounds':[{'type':'direct','tag':'direct'}],
         'endpoints':[{'type':'wireguard','tag':'warp-wg','system':False,'address':addresses,'private_key':a['privatekey'],'listen_port':listen,'mtu':mtu,
                       'peers':[{'address':address,'port':peer_port,'public_key':b['publickey'],'allowed_ips':allowed,'reserved':reserved,'persistent_keepalive_interval':int(b.get('persistentkeepalive','25'))}]}],
         'dns':{'servers':[{'type':'https','tag':'warp-dns','server':'1.1.1.1','path':'/dns-query','detour':'warp-wg'},{'type':'local','tag':'bootstrap'}]},
         'route':{'final':'warp-wg','default_domain_resolver':'warp-dns'}}
    try:ipaddress.ip_address(address)
    except ValueError:cfg['endpoints'][0]['domain_resolver']={'server':'bootstrap',**({'strategy':'ipv'+family+'_only'} if family!='auto' else {})}
    fd,tmp=tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(cfg,f)
        r=subprocess.run([binary,'check','-c',tmp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        if r.returncode:raise ValueError('Gateway config failed validation')
        atomic(target,cfg)
    finally:os.unlink(tmp)
