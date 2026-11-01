def relay_address(value):
    if not isinstance(value,str) or len(value)>253:raise ValueError('Invalid relay address')
    try:return str(ipaddress.ip_address(value))
    except ValueError:
        if not re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}',value):raise ValueError('Invalid relay hostname')
        return value.lower()

def relay_certificate(value,check_expiry=False):
    if not isinstance(value,str) or len(value)>65536 or 'PRIVATE KEY' in value:raise ValueError('Supply only a public relay certificate')
    blocks=re.findall(r'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----',value,re.S)
    if not blocks or ''.join(value.split())!=''.join(''.join(blocks).split()):raise ValueError('Invalid public certificate PEM')
    fingerprints=[]
    for block in blocks:
        der=ssl.PEM_cert_to_DER_cert(block);fingerprints.append(hashlib.sha256(der).hexdigest())
    # Import only unexpired trust material. The live TLS probe verifies the peer/name.
    if check_expiry:
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'public.pem';path.write_text(value)
            result=subprocess.run([os.environ.get('OPENSSL_BIN','openssl'),'x509','-in',str(path),'-noout','-checkend','0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            if result.returncode:raise ValueError('Relay certificate expired or invalid')
    return blocks,fingerprints

def relay_normalize(outbound):
    if not isinstance(outbound,dict):raise ValueError('Expected one relay outbound')
    d=copy.deepcopy(outbound);kind=d.get('type')
    common={'type','tag','server','server_port','tls','network'}
    allowed=common|({'uuid','flow','packet_encoding'} if kind=='vless' else {'password','obfs','up_mbps','down_mbps','server_ports','hop_interval'} if kind=='hysteria2' else set())
    if kind not in ('vless','hysteria2') or set(d)-allowed:raise ValueError('Unsupported relay protocol or fields')
    d['server']=relay_address(d['server']);port=d['server_port']
    if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid relay port')
    if 'network' in d and d['network'] not in ('tcp','udp'):raise ValueError('Invalid relay network')
    d['tag']='skybyte-relay';tls=d.get('tls')
    if not isinstance(tls,dict) or set(tls)-{'enabled','server_name','insecure','utls','reality','certificate','certificate_path','alpn'} or tls.get('enabled') is not True or tls.get('insecure',False) is not False:raise ValueError('Relay TLS verification must be enabled')
    tls['server_name']=relay_address(tls.get('server_name',d['server']));tls['insecure']=False
    if 'alpn' in tls and (not isinstance(tls['alpn'],list) or not tls['alpn'] or any(x not in ('h2','http/1.1','h3') for x in tls['alpn'])):raise ValueError('Unsupported relay ALPN')
    if 'certificate_path' in tls:raise ValueError('Embed public trust certificate; external certificate paths are not imported')
    if kind=='vless':
        try:d['uuid']=str(uuid.UUID(d['uuid']))
        except (ValueError,TypeError,AttributeError):raise ValueError('Invalid relay UUID') from None
        if d.get('flow')!='xtls-rprx-vision' or d.get('packet_encoding','xudp')!='xudp':raise ValueError('Relay supports Reality + Vision with XUDP')
        r=tls.get('reality',{})
        if not isinstance(r,dict) or set(r)-{'enabled','public_key','short_id'} or r.get('enabled') is not True:raise ValueError('Reality verification is required')
        key=r.get('public_key','');sid=r.get('short_id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}',key) or len(base64.urlsafe_b64decode(key+'='))!=32 or not re.fullmatch(r'(?:[0-9a-fA-F]{2}){0,8}',sid):raise ValueError('Invalid Reality public key/short ID')
        u=tls.setdefault('utls',{'enabled':True,'fingerprint':'chrome'})
        if not isinstance(u,dict) or set(u)-{'enabled','fingerprint'} or u.get('enabled') is not True or u.get('fingerprint') not in ('chrome','firefox','edge','safari','ios','android','random','randomized'):raise ValueError('Invalid Reality fingerprint')
        if 'certificate' in tls:raise ValueError('Reality uses its public key, not a custom CA')
    else:
        if 'utls' in tls or 'reality' in tls:raise ValueError('Invalid HY2 TLS fields')
        password=d.get('password')
        if not isinstance(password,str) or not password or len(password)>1024 or any(ord(c)<32 for c in password):raise ValueError('Invalid HY2 password')
        if 'certificate' in tls:
            cert=tls['certificate']
            if not isinstance(cert,list) or not cert or any(not isinstance(x,str) for x in cert):raise ValueError('Invalid embedded public certificate')
            tls['certificate']=relay_certificate('\n'.join(cert))[0]
        for field in ('up_mbps','down_mbps'):
            if field in d and (type(d[field]) is not int or not 1<=d[field]<=100000):raise ValueError('Invalid HY2 relay bandwidth')
        if 'obfs' in d:
            ob=d['obfs']
            if not isinstance(ob,dict) or set(ob)!={'type','password'} or ob['type']!='salamander' or not isinstance(ob['password'],str) or not 1<=len(ob['password'])<=1024 or any(ord(c)<32 for c in ob['password']):raise ValueError('Invalid HY2 relay obfuscation')
        if 'server_ports' in d:
            ranges=d['server_ports']
            if not isinstance(ranges,list) or not 1<=len(ranges)<=20:raise ValueError('Invalid HY2 hopping ranges')
            total=0
            for item in ranges:
                if not isinstance(item,str) or not re.fullmatch(r'[0-9]{1,5}(?::[0-9]{1,5})?',item):raise ValueError('Invalid HY2 hopping range')
                parts=list(map(int,item.split(':')));start,end=parts[0],parts[-1]
                if not 1<=start<=end<=65535:raise ValueError('Invalid HY2 hopping range')
                total+=end-start+1
            if total>20001:raise ValueError('HY2 hopping range is too large')
        if 'hop_interval' in d and (not isinstance(d['hop_interval'],str) or not re.fullmatch(r'(?:[1-9][0-9]?|[1-5][0-9]{2}|600)s',d['hop_interval'])):raise ValueError('Invalid HY2 hopping interval')
    return d

def relay_import(source,trust=''):
    p=Path(source)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>131072:raise ValueError('Invalid relay source file')
    text=p.read_text().strip();pin=''
    if text.startswith('{'):
        d=json.loads(text)
        if 'outbounds' in d:
            choices=[o for o in d['outbounds'] if o.get('type')!='direct']
            if len(choices)!=1:raise ValueError('Supply exactly one landing node')
            d=choices[0]
    else:
        if len(text)>8192 or any(ord(c)<32 for c in text) or re.search(r'%(?![0-9a-fA-F]{2})',text):raise ValueError('Invalid node link')
        u=urllib.parse.urlsplit(text);pairs=urllib.parse.parse_qsl(u.query,keep_blank_values=True)
        if len(dict(pairs))!=len(pairs):raise ValueError('Duplicate node link parameters')
        q=dict(pairs)
        if any(q.get(x,'0').lower() not in ('0','false') for x in ('insecure','allowInsecure','skip-cert-verify')):raise ValueError('Unsafe relay TLS link rejected')
        if u.scheme=='vless' and '@' not in u.netloc:
            authority=base64.b64decode(u.netloc+'='*(-len(u.netloc)%4),altchars=b'-_',validate=True).decode()
            if not authority.startswith('auto:'):raise ValueError('Unsupported native VLESS authority')
            u=urllib.parse.urlsplit('vless://'+authority[5:])
            if q.get('xtls')!='2' or q.get('tls') not in ('1','2'):raise ValueError('Only Reality/Vision native links are supported')
            q.update(security='reality',flow='xtls-rprx-vision',sni=q.get('peer',''))
        if u.path not in ('','/') or u.port is None or not u.hostname or '@' not in u.netloc:raise ValueError('Node credentials, address and port are required')
        tls={'enabled':True,'insecure':False,'server_name':q.get('sni') or q.get('peer') or u.hostname}
        d={'type':u.scheme,'server':u.hostname,'server_port':u.port,'tls':tls}
        if u.scheme=='vless':
            if q.get('security')!='reality' or q.get('type','tcp')!='tcp' or q.get('encryption','none')!='none':raise ValueError('Only VLESS Reality/Vision TCP links are supported')
            d.update(uuid=urllib.parse.unquote(u.username or ''),flow=q.get('flow',''))
            tls.update(reality={'enabled':True,'public_key':q.get('pbk',''),'short_id':q.get('sid','')},utls={'enabled':True,'fingerprint':q.get('fp','chrome')})
            allowed={'encryption','flow','security','sni','fp','pbk','sid','type','remarks','peer','tls','xtls','insecure','allowInsecure','skip-cert-verify'}
        elif u.scheme in ('hysteria2','hy2'):
            d['type']='hysteria2';d['password']=urllib.parse.unquote(u.netloc.rsplit('@',1)[0]);pin=q.get('pinSHA256','').replace(':','').lower()
            if 'obfs' in q:d['obfs']={'type':q['obfs'],'password':q.get('obfs-password','')}
            if 'mport' in q:d.update(server_ports=q['mport'].replace('-',':').split(','),hop_interval='30s')
            allowed={'sni','peer','insecure','allowInsecure','skip-cert-verify','pinSHA256','obfs','obfs-password','mport'}
        else:raise ValueError('Landing node must use Reality/Vision or HY2')
        if set(q)-allowed:raise ValueError('Unsupported node link parameters; use a single sing-box outbound JSON')
    if trust:
        if d.get('type')!='hysteria2':raise ValueError('Public trust certificate is only used for HY2')
        p=Path(trust)
        if p.is_symlink() or not p.is_file() or p.stat().st_size>65536:raise ValueError('Invalid public certificate file')
        blocks,fingerprints=relay_certificate(p.read_text(),True)
        if pin and (not re.fullmatch('[0-9a-f]{64}',pin) or pin not in fingerprints):raise ValueError('Relay certificate fingerprint mismatch')
        d['tls']['certificate']=blocks
    elif pin:raise ValueError('Pinned HY2 link requires the matching public certificate file')
    result=relay_normalize(d)
    if result['tls'].get('certificate'):relay_certificate('\n'.join(result['tls']['certificate']),True)
    return result

def relay_profile(path):
    p=Path(path)
    if p.is_symlink() or not p.is_file() or p.stat().st_size>131072:raise ValueError('Invalid private relay profile')
    d=json.loads(p.read_text())
    if d.get('owner')!=RELAY_OWNER or d.get('schema')!=1:raise ValueError('Relay profile ownership mismatch')
    return relay_normalize(d['outbound'])

def relay_probe(outbound,binary):
    outbound=relay_normalize(outbound)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    with tempfile.TemporaryDirectory() as root:
        p=Path(root)/'probe.json'
        cfg={'log':{'disabled':True},'inbounds':[{'type':'socks','listen':'127.0.0.1','listen_port':port}], 'outbounds':[outbound], 'route':{'final':'skybyte-relay'}}
        p.write_text(json.dumps(cfg));p.chmod(0o600)
        result=subprocess.run([binary,'check','-c',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
        if result.returncode:raise ValueError('Relay configuration failed validation')
        proc=subprocess.Popen([binary,'run','-c',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            deadline=time.monotonic()+5
            while True:
                if proc.poll() is not None:raise ValueError('Relay test core failed to start')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):break
                except OSError:
                    if time.monotonic()>deadline:raise ValueError('Relay test listener unavailable') from None
                    time.sleep(.1)
            result=subprocess.run(['curl','-q','-fsS','--noproxy','','--proxy','socks5h://127.0.0.1:'+str(port),'--proto','=https','--max-time','15','--max-filesize','65536','https://www.cloudflare.com/cdn-cgi/trace'],capture_output=True,timeout=20,text=True)
            if result.returncode:raise ValueError('Landing TLS/authentication/HTTPS connection test failed')
            fields=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
            try:ip=str(ipaddress.ip_address(fields['ip']))
            except (ValueError,KeyError):raise ValueError('Landing egress address was not verified') from None
            return ip
        finally:
            if proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=5)
