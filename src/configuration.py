"""Stage administrator/user inbound edits; preserve route ownership, credentials and usage."""
import copy,ipaddress,json,os,pathlib,re,secrets,shutil,socket,subprocess,sys,tempfile,uuid
base,conf,binary,stage,action,*args=sys.argv[1:];base=pathlib.Path(base);conf=pathlib.Path(conf);stage=pathlib.Path(stage)
def load(p):
 if p.is_symlink() or p.parent.is_symlink():raise ValueError('Refusing config symlink')
 return json.loads(p.read_text())
def address(s):
 try:ipaddress.ip_address(s);return s
 except ValueError:
  if len(s)>253 or not re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}',s):raise ValueError('Invalid address/domain')
  return s.lower()
def port(s):
 if not s.isdecimal() or len(s)>5 or not (int(s)==443 or 1024<=int(s)<=65535):raise ValueError('Port requires 443 or 1024-65535')
 return int(s)
def write(p,d):
 p.parent.mkdir(parents=True,exist_ok=True,mode=0o700);p.write_text(json.dumps(d,indent=2));p.chmod(0o600)
generated=[];generated_cert=None
main=load(conf);meta=load(base/'state.json');original=copy.deepcopy(main);old_meta=copy.deepcopy(meta);paths=[(conf,main,base/'state.json',meta)]
if (base/'users.json').exists():
 ledger=load(base/'users.json')
 if ledger['owner']!='SKYBYTE user quotas v1':raise ValueError('Invalid user owner')
 for u in ledger['users']:
  if u.get('deleted'):continue
  if not re.fullmatch('[0-9a-f]{16}',u['id']):raise ValueError('Invalid user ID')
  p=base/'users'/u['id'];paths.append((p/'server.json',load(p/'server.json'),p/'state.json',load(p/'state.json')))

def check_admin_port(value,protocol,adding=False):
 for _,cfg,_,_ in paths[1:]:
  if any(i['listen_port']==value and (adding or i['type']==protocol) for i in cfg['inbounds']):raise ValueError('Port overlaps an account')
  if protocol=='vless' and int(cfg.get('experimental',{}).get('clash_api',{}).get('external_controller','127.0.0.1:0').rsplit(':',1)[1])==value:raise ValueError('Port overlaps an account controller')
 if protocol=='vless':
  for p in (base/'argo-server.json',base/'warp-gateway.json'):
   if p.exists() or p.is_symlink():
    if any(i.get('type')!='hysteria2' and i.get('listen_port')==value for i in load(p).get('inbounds',[])):raise ValueError('Port reserved by a managed TCP service')
  for p in (base/'subscriptions.json',base/'warp-client.json'):
   if p.exists() or p.is_symlink():
    if load(p)['port']==value:raise ValueError('Port reserved by a managed TCP service')

# Handshake-only edits retain the unrelated HY2 listener and hopping rules.
if action!='reality':meta['hop']=False
if action=='ports':
 vp,hp=map(port,args)
 for inbound in main['inbounds']:
  value=vp if inbound['type']=='vless' else hp
  if value==inbound['listen_port']:continue
  check_admin_port(value,inbound['type'])
  if inbound['type']=='hysteria2' and old_meta.get('hop') and old_meta['hop_start']<=value<=old_meta['hop_end']:raise ValueError('HY2 listener overlaps hopping range')
  family=socket.SOCK_STREAM if inbound['type']=='vless' else socket.SOCK_DGRAM
  with socket.socket(socket.AF_INET6 if ':' in inbound['listen'] else socket.AF_INET,family) as s:
   if family==socket.SOCK_STREAM:s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
   if s.family==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
   s.bind((inbound['listen'],value))
  inbound['listen_port']=value
elif action=='address':
 value=address(args[0])
 for _,_,_,s in paths:s['ip']=value
elif action=='nat_exports':
 value=address(args[0]);ports=[]
 try:public_ip=ipaddress.ip_address(value)
 except ValueError:public_ip=None
 if public_ip is not None and not public_ip.is_global:raise ValueError('Supply a public NAT address')
 for item in args[1:]:
  if not item.isdecimal() or len(item)>5 or not 0<=int(item)<=65535:raise ValueError('Invalid public mapped port')
  ports.append(int(item))
 if len(ports)!=2:raise ValueError('Two mapped ports required')
 meta['ip']=value;meta['export_ports']=dict(zip(('vless','hysteria2'),ports))
elif action in ('sni','reality'):
 value=address(args[0])
 host=address(args[1]) if action=='reality' else value
 number=int(args[2]) if action=='reality' else None
 if number is not None and not 1<=number<=65535:raise ValueError('Invalid handshake target port')
 if not any(i['type']=='vless' for i in main['inbounds']):raise ValueError('Reality is not installed')
 for _,cfg,_,s in paths:
  for i in cfg['inbounds']:
   if i['type']=='vless':
    i['tls']['server_name']=value;i['tls']['reality']['handshake']['server']=host;s['sni']=value
    if number is not None:i['tls']['reality']['handshake']['server_port']=number
elif action=='tls':
 domain,cert,key=args;domain=address(domain)
 if 'hysteria2' not in {i['type'] for i in main['inbounds']}:raise ValueError('HY2 is not installed')
 for _,cfg,_,s in paths:
  for i in cfg['inbounds']:
   if i['type']=='hysteria2':i['tls'].update(server_name=domain,certificate_path=cert,key_path=key);s.update(domain=domain,cert_path=cert,cert_mode='2')
 # Managed user certificates will be copied from the selected chain on commit.
elif action in ('add','remove'):
 protocol=args[0]
 if protocol not in ('vless','hysteria2'):raise ValueError('Unsupported protocol')
 existing={i['type'] for i in main['inbounds']}
 bootstrap=action=='add' and not existing and meta.get('deployment')=='argo-only'
 if action=='remove':
  if protocol not in existing or len(existing)<2:raise ValueError('Cannot remove the final protocol')
  for _,cfg,_,_ in paths:cfg['inbounds']=[i for i in cfg['inbounds'] if i['type']!=protocol]
 else:
  if protocol in existing or (not existing and not bootstrap):raise ValueError('No managed base protocol to extend')
  value=port(args[1])
  check_admin_port(value,protocol,True)
  listen=main['inbounds'][0]['listen'] if existing else meta.get('listen','0.0.0.0')
  if bootstrap:
   required=5 if protocol=='vless' else 6 if len(args)>3 and args[3]=='selfsigned' else 7
   if len(args)<required:raise ValueError('Initial direct node needs an advertised address and bind family')
   public=args[-2];listen=args[-1]
   if listen not in ('::','0.0.0.0'):raise ValueError('Invalid listener family')
   meta.update(ip=address(public),listen=listen,uuid=str(uuid.uuid4()),hy2_password=secrets.token_urlsafe(32))
   meta.pop('deployment',None)
  family=socket.AF_INET6 if ':' in listen else socket.AF_INET
  sock=socket.socket(family,socket.SOCK_STREAM if protocol=='vless' else socket.SOCK_DGRAM)
  try:
   if protocol=='vless':sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
   if family==socket.AF_INET6:sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
   sock.bind(('::' if family==socket.AF_INET6 else '0.0.0.0',value))
  finally:sock.close()
  if protocol=='vless':
   sni=address(args[2]);pairs=subprocess.check_output([binary,'generate','reality-keypair'],text=True);keys=dict(line.split(': ',1) for line in pairs.strip().splitlines())
   meta.update(public_key=keys['PublicKey'],sid=secrets.token_hex(4),sni=sni)
   template={'type':'vless','tag':'reality','listen':listen,'listen_port':value,'users':[{'name':'user1','uuid':meta['uuid'],'flow':'xtls-rprx-vision'}],'tls':{'enabled':True,'server_name':sni,'reality':{'enabled':True,'handshake':{'server':sni,'server_port':443},'private_key':keys['PrivateKey'],'short_id':[meta['sid']]}}}
  else:
   domain=address(args[2]);cert_mode='2'
   if args[3]=='selfsigned':
    dest_cert=conf.parent/'hy2-added.crt';dest_key=conf.parent/'hy2-added.key'
    if any(p.exists() or p.is_symlink() for p in (dest_cert,dest_key)):raise ValueError('Generated certificate paths already exist; use existing-certificate mode')
    cert=str(stage/'hy2-added.crt');key=str(stage/'hy2-added.key');exe=os.environ.get('OPENSSL_BIN','openssl')
    try:ipaddress.ip_address(domain);san='IP:'+domain
    except ValueError:san='DNS:'+domain
    # OpenSSL 1.1.1 can duplicate system CA extensions when using -addext.
    with tempfile.NamedTemporaryFile(mode='w',dir=stage) as request:
     request.write('[req]\ndistinguished_name=dn\nx509_extensions=ids\n[dn]\n[ids]\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n');request.flush()
     result=subprocess.run([exe,'req','-config',request.name,'-x509','-newkey','rsa:3072','-sha256','-nodes','-days','365','-subj','/CN='+domain,'-addext','subjectAltName='+san,'-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign','-keyout',key,'-out',cert],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if result.returncode:raise ValueError('Self-signed certificate generation failed')
    pathlib.Path(cert).chmod(0o600);pathlib.Path(key).chmod(0o600)
    generated=[[cert,str(dest_cert)],[key,str(dest_key)]];generated_cert=(str(dest_cert),str(dest_key));cert_mode='1'
    meta['managed_certificates']=list(dict.fromkeys(meta.get('managed_certificates',[])+list(generated_cert)))
   else:cert,key=args[3:5]
   meta.update(domain=domain,cert_path=generated_cert[0] if generated_cert else cert,cert_mode=cert_mode)
   template={'type':'hysteria2','tag':'hy2','listen':listen,'listen_port':value,'users':[{'name':'user1','password':meta['hy2_password']}],'tls':{'enabled':True,'server_name':domain,'certificate_path':cert,'key_path':key}}
  main['inbounds'].append(template)
  for p,cfg,_,s in paths[1:]:
   user_listen=cfg['inbounds'][0]['listen']
   with socket.socket(socket.AF_INET6 if ':' in user_listen else socket.AF_INET,socket.SOCK_STREAM if protocol=='vless' else socket.SOCK_DGRAM) as sock:
    if protocol=='vless':sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    if sock.family==socket.AF_INET6:sock.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
    sock.bind((user_listen,cfg['inbounds'][0]['listen_port']))
   inbound=copy.deepcopy(template);inbound['listen_port']=cfg['inbounds'][0]['listen_port'];inbound['listen']=cfg['inbounds'][0]['listen']
   inbound['users']=[{'name':p.parent.name,**({'uuid':s['uuid'],'flow':'xtls-rprx-vision'} if protocol=='vless' else {'password':s['hy2_password']})}]
   if protocol=='vless':s.update(public_key=meta['public_key'],sid=meta['sid'],sni=meta['sni'])
   else:s.update(domain=domain,cert_path=cert,cert_mode=meta['cert_mode'])
   cfg['inbounds'].append(inbound)
elif action=='hy2':
 up,down=int(args[0]),int(args[1]);ignore=args[2]=='true';obfs=args[3]
 if not 0<=up<=100000 or not 0<=down<=100000 or args[2] not in ('true','false') or obfs not in ('none','salamander'):raise ValueError('Invalid HY2 settings')
 if ignore and (up or down):raise ValueError('Bandwidth conflicts with ignore_client_bandwidth')
 if not any(i['type']=='hysteria2' for i in main['inbounds']):raise ValueError('HY2 is not installed')
 for _,cfg,_,s in paths:
  for i in cfg['inbounds']:
   if i['type']!='hysteria2':continue
   i['ignore_client_bandwidth']=ignore
   for field,v in [('up_mbps',up),('down_mbps',down)]:
    i.pop(field,None)
    if v:i[field]=v
   if obfs=='none':i.pop('obfs',None)
   else:i.setdefault('obfs',{'type':'salamander','password':secrets.token_urlsafe(24)})
else:raise ValueError('Unknown config edit')

def tls_check(i):
 t=i['tls'];exe=os.environ.get('OPENSSL_BIN','openssl');cert=t['certificate_path'];key=t['key_path'];name=t['server_name']
 identity='-checkip' if ':' in name or re.fullmatch(r'[0-9.]+',name) else '-checkhost'
 if subprocess.run([exe,'x509','-in',cert,'-noout','-checkend','0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:raise ValueError('Certificate invalid or expired')
 # Older OpenSSL releases may exit zero even when checkhost/checkip does not match.
 result=subprocess.run([exe,'x509','-in',cert,'-noout',identity,name],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,env={**os.environ,'LC_ALL':'C'})
 if result.returncode or b'does match' not in result.stdout:raise ValueError('Certificate identity mismatched')
 certpub=subprocess.check_output([exe,'x509','-in',cert,'-pubkey','-noout'],stderr=subprocess.DEVNULL)
 keypub=subprocess.check_output([exe,'pkey','-in',key,'-pubout','-passin','pass:'],stderr=subprocess.DEVNULL)
 if certpub!=keypub:raise ValueError('Certificate/key mismatch')

planned=list(generated)
for n,(p,cfg,mp,s) in enumerate(paths):
 types={i['type'] for i in cfg['inbounds']};s['mode']='0' if not types else '3' if len(types)==2 else '1' if 'vless' in types else '2'
 if not cfg['inbounds'] and not (p==conf and s.get('deployment')=='argo-only'):raise ValueError('Account would have no protocol')
 # Persist own private certificate copies for quota-managed accounts.
 for i in cfg['inbounds']:
  if i['type']=='hysteria2':tls_check(i)
  if i['type']=='hysteria2' and p!=conf:
   for field,filename in [('certificate_path','certificate.crt'),('key_path','private.key')]:
    src=pathlib.Path(i['tls'][field]);dest=p.parent/filename
    staged=stage/(str(n)+'-'+filename);shutil.copyfile(src,staged);staged.chmod(0o600);planned.append([str(staged),str(dest)])
    i['tls'][field]=str(staged)
   s.update(cert_path=str(p.parent/'certificate.crt'),managed_certificates=[str(p.parent/'certificate.crt'),str(p.parent/'private.key')])
 candidate=stage/(str(n)+'-config.json');write(candidate,cfg)
 result=subprocess.run([binary,'check','-c',str(candidate)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
 if result.returncode:raise ValueError('Candidate configuration failed validation')
 if p==conf and generated_cert:
  for i in cfg['inbounds']:
   if i['type']=='hysteria2':i['tls'].update(certificate_path=generated_cert[0],key_path=generated_cert[1])
 if p!=conf:
  for i in cfg['inbounds']:
   if i['type']=='hysteria2':i['tls'].update(certificate_path=str(p.parent/'certificate.crt'),key_path=str(p.parent/'private.key'))
 write(candidate,cfg);planned.append([str(candidate),str(p)])
 sm=stage/(str(n)+'-state.json');write(sm,s);planned.append([str(sm),str(mp)])
write(stage/'plan.json',planned)
