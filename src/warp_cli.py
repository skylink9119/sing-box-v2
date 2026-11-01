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
