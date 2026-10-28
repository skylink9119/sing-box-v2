import concurrent.futures,contextlib,copy,decimal,fcntl,json,os,pathlib,secrets,shutil,signal,socket,subprocess,sys,tempfile,time,unicodedata,urllib.request,urllib.error,uuid
base,conf,meta,binary,lang,action,*args=sys.argv[1:]
base=pathlib.Path(base);db=base/'users.json';root=base/'users';english=lang=='en_US'
def tr(zh,en):return en if english else zh
def error(zh,en):raise ValueError(tr(zh,en))
def require(condition):
 if not condition:error('用户数据或参数无效','Invalid user data or arguments')
def atomic(path,data):
 path=pathlib.Path(path)
 if path.is_symlink():error('拒绝修改符号链接','Refusing symlink')
 fd,tmp=tempfile.mkstemp(dir=path.parent)
 try:
  with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
  os.chmod(tmp,0o600);os.replace(tmp,path)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)
@contextlib.contextmanager
def lock():
 if (base/'users.lock').is_symlink():error('锁文件异常','Invalid lock file')
 with open(base/'users.lock','a') as f:fcntl.flock(f,fcntl.LOCK_EX);yield

def read():
 if db.is_symlink() or root.is_symlink():error('用户目录或文件异常','Invalid user directory/file')
 d=json.loads(db.read_text());require(d['owner']=='SKYBYTE user quotas v1' and d['schema']==1)
 require(type(d['limit'])==int and 1<=d['limit']<=100 and isinstance(d['users'],list))
 identifiers=set();ports=set()
 for u in d['users']:
  require(u['id'] not in identifiers);identifiers.add(u['id']);p=userdir(u['id'])
  for field in ['upload','download','quota_bytes','expires_at']:
   require(type(u[field])==int and u[field]>=0)
  for field in ['port','api_port']:
   require(type(u[field])==int and 1024<=u[field]<=65535 and u[field] not in ports);ports.add(u[field])
  for filename in GENERATED:
   if (p/filename).is_symlink():error('用户文件是符号链接','User file is a symlink')
 return d

def userdir(uid):
 require(len(uid)==16 and all(c in '0123456789abcdef' for c in uid))
 p=root/uid
 if p.is_symlink():error('用户目录异常','Invalid user directory')
 return p

def name(value):
 value=value.strip()
 if not value or len(value)>64 or any(unicodedata.category(c).startswith('C') for c in value):error('名称须为1至64字符，不能含控制字符','Name requires 1-64 characters without control characters')
 return value

def quota(value):
 q=decimal.Decimal(value)
 if not q.is_finite() or not decimal.Decimal('0.000001')<=q<=1000000:error('流量额度非法','Invalid quota')
 return int(q*1024**3)

def days(value):
 if not value.isdecimal() or not 1<=int(value)<=36500:error('有效天数须为1至36500','Validity must be 1-36500 days')
 return int(value)*86400

def eligible(u,now=None):return not u.get('deleted') and u['enabled'] and not u.get('metering_blocked') and u['expires_at']>(time.time() if now is None else now) and u['upload']+u['download']<u['quota_bytes']

def status(u):
 if u.get('deleted'):return tr('已删除','Deleted')
 if not u['enabled']:return tr('已禁用','Disabled')
 if u.get('metering_blocked'):return tr('计量异常，已停用','Metering failed; stopped')
 if u['expires_at']<=time.time():return tr('已到期','Expired')
 if u['upload']+u['download']>=u['quota_bytes']:return tr('流量用尽','Quota exceeded')
 return tr('可用','Eligible')

REASONS={
 'api_auth':('控制接口认证失败，请检查本地 API 配置','Controller authentication failed; check local API config'),
 'api_unreachable':('控制接口超时或未监听，请检查进程与端口冲突','Controller timed out or unavailable; check process and port conflicts'),
 'api_response':('控制接口返回无效数据','Invalid controller response'),
 'counter':('流量计数异常，已停止账户','Invalid traffic counters; account stopped'),
 'core_exit':('节点进程退出，请在本机检查 core.log','Core exited; inspect core.log locally'),
 'final_sample':('停止前采样失败','Final sample failed')}
def failure_reason(exc):
 if isinstance(exc,urllib.error.HTTPError):return 'api_auth' if exc.code in (401,403) else 'api_response'
 if isinstance(exc,(urllib.error.URLError,TimeoutError,OSError)):return 'api_unreachable'
 return 'api_response'
def block(u,reason,code=None):
 u['metering_blocked']=True;u['failure_reason']=reason;u['failure_at']=int(time.time())
 if code is not None:u['exit_code']=code

def expiry(u):return time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(u['expires_at']))

def available_port(used,api=False,listeners=None):
 for _ in range(300):
  n=20000+secrets.randbelow(40000)
  if n in used:continue
  with contextlib.ExitStack() as stack:
   try:
    bindings=[('127.0.0.1',socket.SOCK_STREAM)] if api else listeners or [('0.0.0.0',socket.SOCK_STREAM),('0.0.0.0',socket.SOCK_DGRAM)]
    for address,kind in dict.fromkeys(bindings):
     family=socket.AF_INET6 if ':' in address else socket.AF_INET
     s=stack.enter_context(socket.socket(family,kind))
     if family==socket.AF_INET6:s.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0)
     s.bind((address,n))
   except OSError:continue
  used.add(n);return n
 error('找不到可用端口','No free port available')

def config_check(path,exe=None):
 r=subprocess.run([exe or binary,'check','-c',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30)
 if r.returncode:error('sing-box 配置检查失败（需支持 Clash API）','sing-box config check failed (Clash API required)')

GENERATED={'server.json','state.json','certificate.crt','private.key','nodes.txt','subscription-base64.txt','v2rayn-nodes.txt','v2rayn-subscription.txt','shadowrocket-nodes.txt','shadowrocket-subscription.txt','shadowrocket-native-nodes.txt','shadowrocket-native-subscription.txt','sing-box-client.json','clash-verge.yaml','outbounds.json','mihomo-proxies.yaml','subscription-notes.txt','hy2-client-ca.pem','hy2-client-ca.cer','hy2-client-ca.mobileconfig','export.lock','core.log'}
def cleanup():
 for u in read()['users']:
  p=userdir(u['id'])
  if not p.exists():continue
  for f in GENERATED:
   target=p/f
   if target.is_symlink():error('用户文件归属异常','User file ownership mismatch')
   if target.is_file():target.unlink()
  if not list(p.iterdir()):p.rmdir()
 if root.exists() and not list(root.iterdir()):root.rmdir()
 db.unlink()

class NoControllerRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

_api_local=__import__('threading').local()
def api(u):
 if not hasattr(_api_local,'opener'):_api_local.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoControllerRedirect())
 request=urllib.request.Request('http://127.0.0.1:'+str(u['api_port'])+'/connections',headers={'Authorization':'Bearer '+u['api_secret']})
 # Ignore proxy environment; credentials go only to the loopback controller.
 with _api_local.opener.open(request,timeout=.8) as response:
  payload=response.read(2*1024*1024+1)
  require(len(payload)<=2*1024*1024)
  d=json.loads(payload)
 up,down=d['uploadTotal'],d['downloadTotal']
 require(type(up)==int and type(down)==int and up>=0 and down>=0)
 return up,down

def account_sample(u,generation,up,down):
 if u.get('generation')!=generation:
  u['observed_up']=u['observed_down']=0;u['generation']=generation
 # Totals cannot go backwards during the same supervised process.
 require(up>=u.get('observed_up',0) and down>=u.get('observed_down',0))
 u['upload']+=up-u.get('observed_up',0);u['download']+=down-u.get('observed_down',0)
 u['observed_up']=up;u['observed_down']=down;u['sampled_at']=time.time();u['observed_monotonic']=time.monotonic()

def watch():
 stopping=False;children={}
 if (base/'users-worker.lock').is_symlink():error('工作锁异常','Invalid worker lock')
 worker=open(base/'users-worker.lock','a');fcntl.flock(worker,fcntl.LOCK_EX|fcntl.LOCK_NB)
 def shutdown(*_):
  nonlocal stopping
  stopping=True
 signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
 def stop(uid,record=None):
  child=children.pop(uid,None)
  if not child:return
  if record is not None and not record.get('metering_blocked') and child['proc'].poll() is None:
   try:account_sample(record,child['generation'],*api(record))
   except Exception:block(record,'final_sample')
  proc=child['proc'];proc.terminate()
  try:proc.wait(timeout=3)
  except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
  child['log'].close()
 try:
  with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
   while not stopping:
    with lock():d=read()
    records={u['id']:u for u in d['users']}
    samples={};sample_started=time.monotonic()
    futures={uid:pool.submit(api,records[uid]) for uid in children if uid in records and children[uid]['proc'].poll() is None}
    for uid,f in futures.items():
     try:samples[uid]=f.result(timeout=2)
     except Exception as exc:samples[uid]=failure_reason(exc)
    with lock():
     d=read();before=copy.deepcopy(d);records={u['id']:u for u in d['users']}
     for uid,child in list(children.items()):
      u=records.get(uid)
      if child['log'].tell()>1048576:child['log'].seek(0);child['log'].truncate(0)
      if u is None:stop(uid);continue
      value=samples.get(uid)
      if child['proc'].poll() is not None:
       block(u,'core_exit',child['proc'].returncode);stop(uid);u['running']=False
      elif isinstance(value,tuple):
       try:
        # An explicit live reset may have sampled newer totals while this poll was in flight.
        if u.get('generation')!=child['generation'] or u.get('observed_monotonic',0)<=sample_started:account_sample(u,child['generation'],*value)
        child['ready']=True
       except Exception:block(u,'counter')
      elif child['ready'] or time.monotonic()-child['start']>5:block(u,value if isinstance(value,str) else 'api_unreachable')
      if not eligible(u) or not d.get('supervisor_enabled',True):stop(uid,u);u['running']=False
     for u in d['users']:
      uid=u['id']
      if uid in children: u['running']=children[uid]['ready'];continue
      if not eligible(u) or not d.get('supervisor_enabled',True):u['running']=False;continue
      p=userdir(uid);logpath=p/'core.log'
      if logpath.is_symlink() or (p/'server.json').is_symlink():error('用户配置异常','Invalid user configuration')
      # Prevent unbounded private core logs; do not forward them to journal.
      log=open(logpath,'w');os.chmod(logpath,0o600)
      proc=subprocess.Popen([binary,'run','-c',str(p/'server.json')],stdout=log,stderr=log)
      children[uid]={'proc':proc,'log':log,'start':time.monotonic(),'ready':False,'generation':secrets.token_hex(16)}
      u['running']=False;u['pid']=proc.pid
     if d!=before:atomic(db,d)
    for _ in range(10):
     if stopping:break
     time.sleep(.1)
 finally:
  try:
   with lock():
    d=read()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as final_pool:
     list(final_pool.map(lambda u: stop(u['id'],u),d['users']))
    for u in d['users']:u['running']=False
    atomic(db,d)
  finally:
   # Corrupt/missing ledgers must never leave unmetered child cores running.
   with concurrent.futures.ThreadPoolExecutor(max_workers=16) as cleanup_pool:
    list(cleanup_pool.map(stop,list(children)))
   worker.close()

if action=='watch':watch();sys.exit(0)
if action=='summary':
 # The supervisor atomically replaces the ledger. This menu-only snapshot can
 # read either complete generation without waiting on quota work or core stops.
 d=read()
 count=sum(not u.get('deleted') for u in d['users'])
 running=sum(bool(u.get('running')) and eligible(u) for u in d['users'])
 print(tr('账户：','Accounts: ')+f"{count}/{d['limit']}"+tr('；就绪：','; ready: ')+str(running))
 sys.exit(0)
with lock():
 if action=='init':
  limit=int(args[0]);require(1<=limit<=100)
  if db.exists() or root.exists():error('已有用户文件，拒绝覆盖','User files already exist; refusing overwrite')
  root.mkdir(mode=0o700);atomic(db,{'owner':'SKYBYTE user quotas v1','schema':1,'limit':limit,'supervisor_enabled':True,'users':[]});sys.exit(0)
 d=read()
 if action=='guard':
  pass
 elif action=='add':
  n,q,valid=name(args[0]),quota(args[1]),days(args[2])
  if len([u for u in d['users'] if not u.get('deleted')])>=d['limit']:error('用户数量已达上限','User limit reached')
  if any(u['name']==n and not u.get('deleted') for u in d['users']):error('用户名已存在','User name already exists')
  template=json.load(open(conf));metadata=json.load(open(meta));supported={'vless','hysteria2'}
  require(not template.get('services') and not template.get('endpoints') and len(template['inbounds'])<=2 and len({i['type'] for i in template['inbounds']})==len(template['inbounds']))
  warp_path=base/'warp-state.json';warp=None;warp_before=None
  if warp_path.exists():
   if warp_path.is_symlink():error('WARP 数据异常','Invalid WARP state')
   warp=json.loads(warp_path.read_text());warp_before=copy.deepcopy(warp);require(warp.get('owner')=='SKYBYTE WARP routing v1' and warp.get('schema')==1)
   require({k:template.get(k) for k in ('route','outbounds')}==warp['configs'][conf]['applied'])
  if not template['inbounds'] or any(i['type'] not in supported for i in template['inbounds']) or (warp is None and any(o['type']!='direct' for o in template['outbounds'])):error('用户功能只支持托管的 Reality/HY2 配置','User quotas support managed Reality/HY2 configs only')
  uid=secrets.token_hex(8);p=userdir(uid);p.mkdir(mode=0o700)
  try:
   used={u[k] for u in d['users'] for k in ['port','api_port']}
   # Reserve configured ports even while their services are stopped.
   for path in (pathlib.Path(conf),base/'argo-server.json',base/'warp-gateway.json'):
    if path.exists() or path.is_symlink():
     require(not path.is_symlink() and not path.parent.is_symlink() and path.stat().st_size<=4*1024**2)
     cfg=json.loads(path.read_text())
     for i in cfg.get('inbounds',[]):
      require(type(i['listen_port']) is int and 1<=i['listen_port']<=65535);used.add(i['listen_port'])
     controller=cfg.get('experimental',{}).get('clash_api',{}).get('external_controller')
     if controller:used.add(int(controller.rsplit(':',1)[1]))
   for path in (base/'subscriptions.json',base/'warp-client.json'):
    if path.exists() or path.is_symlink():
     require(not path.is_symlink() and path.stat().st_size<=131072)
     number=json.loads(path.read_text())['port'];require(type(number) is int and 1<=number<=65535);used.add(number)
   relay_file=base/'haproxy/state.json'
   if relay_file.exists() or relay_file.is_symlink():
    require(not relay_file.is_symlink() and not relay_file.parent.is_symlink() and relay_file.stat().st_size<=131072)
    relay=json.loads(relay_file.read_text());require(relay.get('owner')=='SKYBYTE HAProxy TCP v1' and relay.get('schema')==1)
    require(isinstance(relay.get('rules'),list) and len(relay['rules'])<=16)
    for rule in relay['rules']:
     require(type(rule.get('port'))==int and 1<=rule['port']<=65535);used.add(rule['port'])
   if metadata.get('hop'):used.update(range(int(metadata['hop_start']),int(metadata['hop_end'])+1))
   listeners=[(i['listen'],socket.SOCK_STREAM if i['type']=='vless' else socket.SOCK_DGRAM) for i in template['inbounds']]
   port=available_port(used,listeners=listeners);controller=available_port(used,True)
   identity=str(uuid.uuid4());password=secrets.token_urlsafe(32);token=secrets.token_urlsafe(32)
   template['log']={'level':'warn','timestamp':True}
   template.pop('experimental',None)
   template['experimental']={'clash_api':{'external_controller':'127.0.0.1:'+str(controller),'secret':token}}
   for inbound in template['inbounds']:
    inbound['listen_port']=port
    if inbound['type']=='vless':
     if not inbound.get('tls',{}).get('reality',{}).get('enabled'):error('只支持 Reality VLESS','Only Reality VLESS is supported')
     inbound['users']=[{'name':uid,'uuid':identity,'flow':'xtls-rprx-vision'}]
    else:
     inbound['users']=[{'name':uid,'password':password}]
     for field,filename in [('certificate_path','certificate.crt'),('key_path','private.key')]:
      shutil.copyfile(inbound['tls'][field],p/filename);os.chmod(p/filename,0o600);inbound['tls'][field]=str(p/filename)
     metadata['cert_path']=str(p/'certificate.crt')
   metadata.pop('export_ports',None)
   metadata.update(node_name=n,uuid=identity,hy2_password=password,hop=False,managed_certificates=[str(p/'certificate.crt'),str(p/'private.key')] if (p/'certificate.crt').exists() else [])
   atomic(p/'server.json',template);atomic(p/'state.json',metadata);config_check(p/'server.json')
   u={'id':uid,'name':n,'quota_bytes':q,'upload':0,'download':0,'expires_at':int(time.time())+valid,'enabled':True,'port':port,'api_port':controller,'api_secret':token,'running':False,'metering_blocked':False}
   if warp is not None:
    warp['configs'][str(p/'server.json')]=copy.deepcopy(warp['configs'][conf]);atomic(warp_path,warp)
   d['users'].append(u);atomic(db,d);print(uid)
  except Exception:
   if warp_before is not None:atomic(warp_path,warp_before)
   for child in p.iterdir():child.unlink()
   p.rmdir();raise
 elif action=='service':
  require(args[0] in ('on','off'));d['supervisor_enabled']=args[0]=='on';atomic(db,d)
 elif action=='ledger':
  atomic(pathlib.Path(args[0])/'users.json',d)
 elif action=='limit':
  n=int(args[0]);require(1<=n<=100 and n>=len([u for u in d['users'] if not u.get('deleted')]));d['limit']=n;atomic(db,d)
 elif action in ('enable','disable','delete','reset','set','quota','validity','export'):
  u=next((u for u in d['users'] if u['id']==args[0] and not u.get('deleted')),None)
  if u is None:error('用户不存在','User not found')
  if action=='export':
   if not eligible(u):error('用户不可用，拒绝导出','User unavailable; refusing export')
   p=userdir(u['id']);m=json.loads((p/'state.json').read_text());m['node_name']=u['name'];atomic(p/'state.json',m);print(p)
  else:
   if action=='enable':
    p=userdir(u['id']);config_check(p/'server.json')
    controller=json.loads((p/'server.json').read_text()).get('experimental',{}).get('clash_api',{})
    require(controller.get('external_controller')=='127.0.0.1:'+str(u['api_port']) and controller.get('secret')==u['api_secret'])
    u['enabled']=True;u['metering_blocked']=False
    for k in ('failure_reason','failure_at','exit_code'):u.pop(k,None)
   elif action=='disable':u['enabled']=False
   elif action=='delete':u['deleted']=True;u['enabled']=False
   elif action=='reset':
    if u.get('running'):account_sample(u,u['generation'],*api(u))
    u['upload']=u['download']=0
   elif action=='set':u['quota_bytes']=quota(args[1]);u['expires_at']=int(time.time())+days(args[2])
   elif action=='quota':u['quota_bytes']=quota(args[1])
   elif action=='validity':u['expires_at']=int(time.time())+days(args[1])
   atomic(db,d)
   if action in ('set','quota','validity'):print(tr('修改后到期时间：','Resulting expiry: ')+expiry(u))
 elif action=='list':
  color=sys.stdout.isatty() and not os.environ.get('NO_COLOR')
  if color:print('\033[1;33m',end='')
  print(tr('账户上限：','Account limit: ')+str(d['limit']))
  print(tr('ID | 名称 | 上传/下载 GiB | 已用/额度 GiB | 到期 | 状态 | 端口','ID | Name | Upload/download GiB | Used/quota GiB | Expiry | Status | Port'))
  for u in d['users']:
   if u.get('deleted'):continue
   expires=expiry(u)
   print('{} | {} | {:.3f}/{:.3f} GiB | {:.3f}/{:.3f} GiB | {} | {} | {}:{}'.format(u['id'],u['name'],u['upload']/1024**3,u['download']/1024**3,(u['upload']+u['download'])/1024**3,u['quota_bytes']/1024**3,expires,status(u),tr('端口','Port'),u['port']))
   if u.get('failure_reason'):print('  '+tr(*REASONS.get(u['failure_reason'],('原因未知，请诊断','Unknown reason; run diagnostics'))))
   if eligible(u) and not u.get('running'):print('  '+tr('计量服务尚未就绪；请检查用户服务状态','Metering service not ready; inspect user service status'))
  if color:print('\033[0m',end='')
 elif action=='diagnose':
  for u in d['users']:
   if u.get('deleted') or (args and args[0] and args[0]!=u['id']):continue
   print(u['id']+' | '+u['name']+' | '+status(u))
   if u.get('failure_reason'):
    print(tr(*REASONS.get(u['failure_reason'],('原因未知','Unknown reason'))))
    print(tr('异常发生时间 UTC：','Failure time UTC: ')+time.strftime('%Y-%m-%d %H:%M UTC',time.gmtime(u.get('failure_at',0))))
    if 'exit_code' in u:print(tr('进程退出码：','Core exit code: ')+str(u['exit_code']))
   try:
    config_check(userdir(u['id'])/'server.json');print(tr('配置检查：通过','Config check: passed'))
   except Exception:print(tr('配置检查：失败','Config check: failed'))
   if u.get('running'):
    try:api(u);print(tr('控制接口：正常','Controller: healthy'))
    except Exception as exc:print(tr(*REASONS[failure_reason(exc)]))
   print(tr('本地日志：','Local log: ')+str(userdir(u['id'])/'core.log'))
 elif action=='export_all':
  print('\n'.join(u['id'] for u in d['users'] if eligible(u)))
 elif action=='certificates':
  template=json.load(open(conf));tls=next((i['tls'] for i in template['inbounds'] if i['type']=='hysteria2'),None)
  if tls is None:error('未安装 HY2','HY2 not installed')
  files=[(tls[k],n) for k,n in [('certificate_path','certificate.crt'),('key_path','private.key')]]
  payloads=[(pathlib.Path(src).read_bytes(),n) for src,n in files]
  for u in d['users']:
   if u.get('deleted'):continue
   p=userdir(u['id']);cfg=json.loads((p/'server.json').read_text())
   inbound=next((i for i in cfg['inbounds'] if i['type']=='hysteria2'),None)
   if inbound is None:continue
   require(inbound['tls']['certificate_path']==str(p/'certificate.crt') and inbound['tls']['key_path']==str(p/'private.key') and inbound['tls']['server_name']==tls['server_name'])
   for data,n in payloads:
    fd,tmp=tempfile.mkstemp(dir=p)
    try:
     with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
     os.chmod(tmp,0o600);os.replace(tmp,p/n)
    finally:
     if os.path.exists(tmp):os.unlink(tmp)
 elif action=='firewall_rules':
  rules=set()
  for u in d['users']:
   if u.get('deleted') or (args and args[0] and args[0]!=u['id']):continue
   c=json.loads((userdir(u['id'])/'server.json').read_text())
   for i in c['inbounds']:
    require(i['type'] in ('vless','hysteria2') and type(i['listen_port'])==int and 1024<=i['listen_port']<=65535)
    rules.add(str(i['listen_port'])+('/tcp' if i['type']=='vless' else '/udp'))
  print('\n'.join(sorted(rules)))
 elif action=='hop_check':
  start,end=map(int,args);require(1024<=start<=end<=65535)
  for u in d['users']:
   if u.get('deleted'):continue
   for i in json.loads((userdir(u['id'])/'server.json').read_text())['inbounds']:
    if i['type']=='hysteria2' and start<=i['listen_port']<=end:error('跳跃范围覆盖用户 HY2 端口，请使用其他范围','Hopping range overlaps a user HY2 port; choose another range')
 elif action=='validate':
  for u in d['users']:
   if not u.get('deleted'):config_check(userdir(u['id'])/'server.json',args[0])
 elif action=='backup':
  target=pathlib.Path(args[0]);atomic(target/'users.json',d)
  destination=target/'users';destination.mkdir(mode=0o700)
  for u in d['users']:
   src=userdir(u['id']);dest=destination/u['id']
   if not src.exists():continue
   dest.mkdir(mode=0o700)
   for filename in GENERATED:
    f=src/filename
    if f.is_symlink():error('用户文件是符号链接','User file is a symlink')
    if f.is_file():shutil.copyfile(f,dest/filename);os.chmod(dest/filename,0o600)
 elif action=='restore':
  source=pathlib.Path(args[0]);new=json.loads((source/'users.json').read_text())
  require(new['owner']==d['owner'] and new['schema']==1)
  require(type(new['limit'])==int and 1<=new['limit']<=100 and isinstance(new['users'],list))
  ids=set();ports=set()
  for u in new['users']:
   require(u['id'] not in ids);ids.add(u['id']);userdir(u['id'])
   for k in ['upload','download','quota_bytes','expires_at']:require(type(u[k])==int and u[k]>=0)
   for k in ['port','api_port']:
    require(type(u[k])==int and 1024<=u[k]<=65535 and u[k] not in ports);ports.add(u[k])
  latest={u['id']:u for u in d['users']}
  planned=[latest.get(u['id'],u) for u in new['users']]+[u for u in d['users'] if u['id'] not in {v['id'] for v in new['users']}]
  merged_ports=[u[k] for u in planned for k in ('port','api_port')]
  require(len(merged_ports)==len(set(merged_ports)))
  if len([u for u in planned if not u.get('deleted')])>100:error('恢复后用户数超过100，拒绝恢复','Restore would exceed 100 accounts; refusing')
  root.mkdir(exist_ok=True,mode=0o700)
  for u in new['users']:
   p=userdir(u['id']);src=source/'users'/u['id']
   if src.is_symlink() or not src.is_dir():error('备份用户目录异常','Invalid backed-up user directory')
   p.mkdir(exist_ok=True,mode=0o700)
   for f in src.iterdir():
    if f.is_symlink() or f.name not in GENERATED or not f.is_file():error('备份用户文件异常','Invalid backed-up user file')
    if (p/f.name).is_symlink():error('目标用户文件异常','Invalid target user file')
    shutil.copyfile(f,p/f.name);os.chmod(p/f.name,0o600)
   if u['id'] in latest:u.update(latest.pop(u['id']))
   u['running']=False
  new['supervisor_enabled']=d.get('supervisor_enabled',True)
  new['users'].extend(latest.values());new['limit']=max(new['limit'],d['limit'],len([u for u in new['users'] if not u.get('deleted')]))
  atomic(db,new)
 elif action=='cleanup':cleanup()
 else:error('未知操作','Unknown operation')
