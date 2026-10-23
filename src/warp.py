"""Owned WARP/landing routing transactions; client-facing node credentials stay intact."""
import base64
import configparser
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import hashlib
import socket
import ssl
import time
import urllib.parse
import uuid

OWNER='SKYBYTE WARP routing v1'
MEDIA=['netflix.com','netflix.net','nflxext.com','nflximg.com','nflximg.net','nflxso.net','nflxvideo.net',
       'disneyplus.com','disney-plus.net','dssott.com','bamgrid.com','youtube.com','youtu.be','googlevideo.com','ytimg.com','youtubei.googleapis.com',
       'primevideo.com','amazonvideo.com','aiv-cdn.net','aiv-delivery.net','tiktok.com','tiktokv.com','tiktokcdn.com','tiktokcdn-us.com','byteoversea.com','ibytedtos.com']
AI=['openai.com','chatgpt.com','oaistatic.com','oaiusercontent.com','anthropic.com','claude.ai','claude.com',
    'gemini.google.com','aistudio.google.com','generativelanguage.googleapis.com']
PROFILES={'netflix':MEDIA[:7],'disney':MEDIA[7:11],'chatgpt':AI[:4],'gemini':AI[7:]}
RULE_VERSION='2026.10.23'
FIELDS=('route','outbounds')
RELAY_OWNER='SKYBYTE relay profile v1'

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

def atomic(path,data):
    path=Path(path)
    if path.is_symlink():raise ValueError('Refusing WARP symlink')
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def read_state(base):
    p=base/'warp-state.json'
    if p.is_symlink():raise ValueError('WARP state is a symlink')
    if not p.exists():return None
    d=json.loads(p.read_text())
    if d.get('owner')!=OWNER or d.get('schema')!=1 or d['mode'] not in ('direct','restricted','global'):raise ValueError('WARP state ownership/schema mismatch')
    provider=d.get('provider','warp')
    if provider not in ('warp','relay'):raise ValueError('Invalid outbound provider')
    if type(d['port']) is not int or not (1 if provider=='relay' else 1024)<=d['port']<=65535 or type(d['udp']) is not bool:raise ValueError('Invalid outbound settings')
    if 'relay' in d:relay_normalize(d['relay'])
    if provider=='relay' and 'relay' not in d:raise ValueError('Missing landing profile')
    return d

def status_text(state,language='en_US'):
    zh=language=='zh_CN'
    if not state:return '当前状态：未配置 WARP' if zh else 'Status: WARP not configured'
    if state.get('provider','warp')!='warp':return '当前状态：WARP 未启用（当前使用落地中转）' if zh else 'Status: WARP inactive (relay selected)'
    modes={'direct':('已关闭 WARP 分流，当前直连','Direct; WARP routing disabled'),
           'restricted':('仅指定域名使用 WARP','Selected domains use WARP'),
           'global':('全部节点流量使用 WARP','All node traffic uses WARP')}
    mode=modes[state['mode']][0 if zh else 1]
    proxy=('本机代理：' if zh else 'Local proxy: ')+'127.0.0.1:'+str(state['port'])
    udp=('支持' if state['udp'] else '不支持') if zh else ('supported' if state['udp'] else 'unsupported')
    return ('当前模式：' if zh else 'Routing: ')+mode+'\n'+proxy+' | UDP: '+udp

def view(cfg):return {k:copy.deepcopy(cfg.get(k)) for k in FIELDS}

def put(cfg,routing):
    for k,v in routing.items():
        if v is None:cfg.pop(k,None)
        else:cfg[k]=copy.deepcopy(v)
    return cfg

def render(baseline,mode,port,udp,domains,relay=None):
    result=copy.deepcopy(baseline)
    if mode=='direct':return result
    tag='skybyte-relay' if relay else 'skybyte-warp'
    result['outbounds'].append(relay_normalize(relay) if relay else {'type':'socks','tag':tag,'server':'127.0.0.1','server_port':port,'version':'5',**({} if udp else {'network':'tcp'})})
    route=result['route'];prefix=[]
    if mode=='restricted':
        prefix=[{'action':'sniff','timeout':'500ms'}]
        if not udp:prefix.append({'domain_suffix':domains,'network':'udp','action':'reject'})
        prefix.append({'domain_suffix':domains,'action':'route','outbound':tag})
    else:
        route['final']=tag
        if not udp:prefix=[{'network':'udp','action':'reject'}]
    route['rules']=prefix+route.get('rules',[])
    return result

def config_paths(base,conf):
    paths=[conf]
    if (base/'argo-state.json').exists():paths.append(base/'argo-server.json')
    if (base/'users.json').exists():
        users=json.loads((base/'users.json').read_text())
        if users.get('owner')!='SKYBYTE user quotas v1':raise ValueError('Invalid user owner')
        for u in users['users']:
            if not re.fullmatch('[0-9a-f]{16}',u['id']):raise ValueError('Invalid account ID')
            if not u.get('deleted'):paths.append(base/'users'/u['id']/'server.json')
    for p in paths:
        if p.is_symlink() or p.parent.is_symlink():raise ValueError('Config symlink')
    return paths

def domains_parse(text):
    domains=sorted(set(text.replace(',', ' ').split()))
    if not domains or len(domains)>200 or any(len(x)>253 or not re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}',x) for x in domains):raise ValueError('Invalid domain suffix list')
    return sorted(set(d.lower() for d in domains))

def catalog(base):
    path=base/'warp-rules.json'
    if path.is_symlink():raise ValueError('Rule catalog symlink')
    d=json.loads(path.read_text()) if path.exists() else {'owner':'SKYBYTE WARP rules v1','schema':1,'version':RULE_VERSION,'media':MEDIA,'ai':AI}
    validate_catalog(d)
    return d

def validate_catalog(d):
    if d.get('owner')!='SKYBYTE WARP rules v1' or d.get('schema')!=1 or not re.fullmatch(r'[0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\.[0-9]+)?',d.get('version','')):raise ValueError('Invalid rule catalog')
    if not isinstance(d['media'],list) or not isinstance(d['ai'],list) or any(not isinstance(x,str) for x in d['media']+d['ai']):raise ValueError('Invalid catalog suffixes')
    domains_parse(' '.join(d['media']+d['ai']))


def switch(base,conf,binary,mode,port,udp,domains,relay=None):
    if mode not in ('direct','restricted','global') or not (1 if relay else 1024)<=port<=65535:raise ValueError('Invalid outbound mode/port')
    if relay:
        relay=relay_normalize(relay)
        names={'127.0.0.1','::1','localhost'}
        for p in (base/'state.json',):
            if p.exists():names.add(json.loads(p.read_text()).get('ip','').lower())
        for p in config_paths(base,conf):
            cfg=json.loads(p.read_text())
            if relay['server'].lower() in names and any(i.get('listen_port')==relay['server_port'] for i in cfg.get('inbounds',[])):raise ValueError('Landing points back to a managed listener')
    prior=read_state(base)
    state=copy.deepcopy(prior) if prior else {'owner':OWNER,'schema':1,'configs':{}}
    originals={};planned={}
    for path in config_paths(base,conf):
        cfg=json.loads(path.read_text());originals[path]=cfg
        old=state['configs'].get(str(path))
        if old:
            if view(cfg)!=old['applied']:raise ValueError('Routing changed outside manager; refusing overwrite: '+str(path))
            baseline=old['baseline']
        else:
            if cfg.get('endpoints') or any(o['type']!='direct' for o in cfg['outbounds']) or cfg['route'].get('final')!='direct':raise ValueError('Unmanaged routing; refusing overwrite')
            baseline=view(cfg)
        if relay and mode!='direct' and baseline.get('route',{}).get('rules'):raise ValueError('Custom baseline routing requires manual review before relay')
        routing=render(baseline,mode,port,udp,domains,relay)
        candidate=put(copy.deepcopy(cfg),routing)
        fd,tmp=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump(candidate,f)
            r=subprocess.run([binary,'check','-c',tmp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            if r.returncode:raise ValueError('WARP candidate config failed validation')
        finally:os.unlink(tmp)
        planned[path]=candidate;state['configs'][str(path)]={'baseline':baseline,'applied':routing}
    state.update(mode=mode,port=port,udp=udp,domains=domains,provider='relay' if relay else 'warp')
    if relay:state['relay']=relay
    try:
        for p,cfg in planned.items():atomic(p,cfg)
        atomic(base/'warp-state.json',state)
    except BaseException:
        for p,cfg in originals.items():atomic(p,cfg)
        if prior:atomic(base/'warp-state.json',prior)
        elif (base/'warp-state.json').exists():(base/'warp-state.json').unlink()
        raise

def restore_routing(base,conf,snapshot,binary):
    saved=snapshot/'warp-state.json'
    new=json.loads(saved.read_text()) if saved.exists() else None
    if saved.is_symlink():raise ValueError('Backup state symlink')
    prior=read_state(base)
    originals={}
    if new and (new.get('owner')!=OWNER or new.get('schema')!=1):raise ValueError('Invalid WARP backup')
    if new and 'relay' in new:relay_normalize(new['relay'])
    if new and new.get('provider')=='relay' and 'relay' not in new:raise ValueError('Relay backup has no landing profile')
    planned={}
    for path in config_paths(base,conf):
        if path==conf:source=snapshot/'config'/'config.json'
        elif path==base/'argo-server.json':source=snapshot/'argo-server.json'
        else:source=snapshot/'users'/path.parent.name/'server.json'
        current=json.loads(path.read_text());originals[path]=copy.deepcopy(current)
        if source.exists():
            if source.is_symlink():raise ValueError('Backup symlink')
            routing=view(json.loads(source.read_text()))
        else:
            old=prior['configs'].get(str(path)) if prior else None
            if old:
                if view(current)!=old['applied']:raise ValueError('New account routing changed; refusing overwrite')
                baseline=old['baseline']
            else:
                if any(o['type']!='direct' for o in current['outbounds']):raise ValueError('Unmanaged new account routing')
                baseline=view(current)
            routing=render(baseline,new['mode'],new['port'],new['udp'],new['domains'],new.get('relay') if new.get('provider')=='relay' else None) if new else baseline
            if new:new['configs'][str(path)]={'baseline':baseline,'applied':routing}
        planned[path]=put(current,routing)
    for path,cfg in planned.items():
        fd,tmp=tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd,'w') as f:json.dump(cfg,f)
            r=subprocess.run([binary,'check','-c',tmp],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
            if r.returncode:raise ValueError('Restored WARP config failed validation')
        finally:os.unlink(tmp)
    try:
        for path,cfg in planned.items():
            if cfg!=originals[path]:atomic(path,cfg)
        if new:atomic(base/'warp-state.json',new)
        elif (base/'warp-state.json').exists():(base/'warp-state.json').unlink()
    except BaseException:
        for path,cfg in originals.items():atomic(path,cfg)
        if prior:atomic(base/'warp-state.json',prior)
        raise

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

if __name__=='__main__':
    import sys
    base,conf,binary,action,*args=sys.argv[1:];base=Path(base);conf=Path(conf)
    if action=='switch':switch(base,conf,binary,args[0],int(args[1]),args[2]=='true',domains_parse(args[3]))
    elif action=='reconcile':
        s=read_state(base)
        if s:switch(base,conf,binary,s['mode'],s['port'],s['udp'],s['domains'],s.get('relay') if s.get('provider')=='relay' else None)
    elif action.startswith('relay_'):
        try:
            if action=='relay_prepare':atomic(args[1],{'owner':RELAY_OWNER,'schema':1,'outbound':relay_import(args[0],args[2])})
            elif action=='relay_export':
                s=read_state(base)
                if not s or 'relay' not in s:raise ValueError('No landing node configured')
                atomic(args[0],{'owner':RELAY_OWNER,'schema':1,'outbound':s['relay']})
            elif action=='relay_probe':print(relay_probe(relay_profile(args[0]),binary))
            elif action=='relay_switch':
                r=relay_profile(args[1]);switch(base,conf,binary,args[0],r['server_port'],r.get('network')!='tcp',domains_parse(args[2]),r)
            elif action=='relay_status':
                s=read_state(base)
                zh=bool(args and args[0]=='zh_CN')
                if not s or 'relay' not in s:print('尚未配置落地节点' if zh else 'Relay: not configured')
                else:
                    r=relay_normalize(s['relay']);mode=s['mode'] if s.get('provider')=='relay' else 'inactive'
                    print(('中转：' if zh else 'Relay: ')+r['type']+' | '+r['server']+':'+str(r['server_port'])+(' | TLS 验证：开启 | ' if zh else ' | TLS verification: on | ')+({'global':'全局中转','restricted':'指定域名中转','direct':'已恢复直连','inactive':'中转未启用'}[mode] if zh else mode))
                    for cert in r['tls'].get('certificate',[]):print(('公开证书 SHA256：' if zh else 'Public certificate SHA256: ')+hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert)).hexdigest())
            elif action=='relay_forget':
                s=read_state(base)
                if s and 'relay' in s:
                    if s.get('provider')=='relay' and s['mode']!='direct':raise ValueError('Disable relay routing before removing its profile')
                    s.pop('relay')
                    if s.get('provider')=='relay':s['provider']='warp';s['port']=40000
                    atomic(base/'warp-state.json',s)
            else:raise ValueError('Unknown relay action')
        except (ValueError,KeyError,TypeError,OSError,subprocess.SubprocessError):
            raise SystemExit('Relay operation failed; check protocol fields, trusted certificate and landing connectivity. TLS verification remains required.') from None
    elif action=='restore':restore_routing(base,conf,Path(args[0]),binary)
    elif action=='gateway':gateway(args[0],int(args[1]),base/'warp-gateway.json',binary,args[2] if len(args)>2 else 'auto')
    elif action=='port':
        state=read_state(base)
        if not state or state.get('provider','warp')!='warp':raise ValueError('WARP routing is not configured; current provider is relay')
        print(state['port'])
    elif action=='status':
        state=read_state(base)
        print(status_text(state,args[0] if args else 'en_US'))
    elif action=='forget_argo':
        state=read_state(base)
        if state:
            state['configs'].pop(str(base/'argo-server.json'),None);atomic(base/'warp-state.json',state)
    elif action=='defaults':
        d=catalog(base);print(' '.join(d['media']+d['ai']))
    elif action=='profile':
        print(' '.join(PROFILES[args[0]] if args[0]!='all' else sum(PROFILES.values(),[])))
    elif action=='catalog_status':
        d=catalog(base);print('WARP rules: '+d['version']+' | suffixes: '+str(len(domains_parse(' '.join(d['media']+d['ai'])))))
    elif action=='catalog_update':
        p=Path(args[0])
        if p.is_symlink() or p.stat().st_size>65536:raise ValueError('Invalid catalog file')
        d=json.loads(p.read_text());validate_catalog(d)
        current=catalog(base)
        if tuple(map(int,d['version'].split('.'))) < tuple(map(int,current['version'].split('.'))):raise ValueError('Older catalog refused')
        atomic(base/'warp-rules.previous.json',current);atomic(base/'warp-rules.json',d)
        print('WARP rules: '+d['version'])
    elif action=='guard':read_state(base)
    else:raise ValueError('Unknown WARP action')
