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
