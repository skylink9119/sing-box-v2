"""Private token subscriptions served over TLS. Never expose server configs or controller keys."""
import copy,hmac,http.server,json,os,pathlib,re,secrets,socket,socketserver,ssl,subprocess,sys,tempfile,threading,time,urllib.parse
OWNER='SKYBYTE HTTPS subscriptions v1'
FORMATS={'shadowrocket':'shadowrocket-native-subscription.txt','v2rayn':'v2rayn-subscription.txt','clash':'clash-verge.yaml','singbox':'sing-box-client.json'}

def atomic(p,d):
 if p.is_symlink():raise ValueError('Subscription state symlink')
 fd,tmp=tempfile.mkstemp(dir=p.parent)
 try:
  with os.fdopen(fd,'w') as f:json.dump(d,f,indent=2);f.flush();os.fsync(f.fileno())
  os.replace(tmp,p)
 finally:
  if os.path.exists(tmp):os.unlink(tmp)

def read(base):
 p=pathlib.Path(base)/'subscriptions.json'
 if p.is_symlink():raise ValueError('Subscription state symlink')
 d=json.loads(p.read_text())
 if d.get('owner')!=OWNER or d.get('schema')!=1 or type(d['port']) is not int or not 1024<=d['port']<=65535:raise ValueError('Invalid subscription settings')
 if len(d['host'])>253 or not re.fullmatch(r'(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}',d['host']):raise ValueError('Invalid subscription hostname')
 if not isinstance(d['tokens'],dict):raise ValueError('Invalid token ledger')
 for uid,token in d['tokens'].items():
  if not re.fullmatch('[0-9a-f]{16}',uid) or token is not None and not re.fullmatch('[A-Za-z0-9_-]{43}',token):raise ValueError('Invalid subscription token')
 return d

def user(base,uid):
 path=pathlib.Path(base)/'users.json'
 if path.is_symlink() or (path.parent/'users').is_symlink():raise ValueError('User ledger symlink')
 d=json.loads(path.read_text())
 if d.get('owner')!='SKYBYTE user quotas v1' or d.get('schema')!=1:raise ValueError('Invalid user ledger')
 u=next((u for u in d['users'] if u['id']==uid and not u.get('deleted')),None)
 if u is None:raise ValueError('Account not found')
 return d,u

def authorize(base,token):
 d=read(base);uid=next((uid for uid,value in d['tokens'].items() if value and hmac.compare_digest(value,token)),None)
 if uid is None:return None
 ledger,u=user(base,uid)
 if not ledger.get('supervisor_enabled',True) or not u['enabled'] or u.get('metering_blocked') or u['expires_at']<=time.time() or u['upload']+u['download']>=u['quota_bytes']:return None
 return uid,u

def links(d,uid):
 token=d['tokens'].get(uid)
 if not token:raise ValueError('Subscription revoked or not issued')
 return {kind:'https://'+d['host']+(':'+str(d['port']) if d['port']!=443 else '')+'/s/'+token+'/'+kind for kind in FORMATS}

def handler(base,manager,exporter=None):
 base=pathlib.Path(base)
 def export(uid):
  r=subprocess.run(['/bin/bash',str(manager),'--subscription-export',uid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
  if r.returncode:raise ValueError('Export generation failed')
 export=exporter or export
 class Handler(http.server.BaseHTTPRequestHandler):
  protocol_version='HTTP/1.1';server_version='SKYBYTE';sys_version=''
  def log_message(self,*_):pass
  def setup(self):
   self.request.settimeout(10)
   if isinstance(self.request,ssl.SSLSocket):self.request.do_handshake()
   super().setup()
  def reply(self,code,payload=b'',headers=None):
   self.send_response(code);self.send_header('Content-Length',str(len(payload)));self.send_header('Cache-Control','no-store');self.send_header('Connection','close')
   for key,value in (headers or {}).items():self.send_header(key,value)
   self.end_headers();self.close_connection=True
   if self.command!='HEAD' and payload:self.wfile.write(payload)
  def do_GET(self):self.deliver()
  def do_HEAD(self):self.deliver()
  def deliver(self):
   try:
    path=urllib.parse.urlsplit(self.path)
    match=re.fullmatch(r'/s/([A-Za-z0-9_-]{43})/(shadowrocket|v2rayn|clash|singbox)',path.path)
    if not match or path.query or path.fragment:return self.reply(404)
    token,kind=match.groups();auth=authorize(base,token)
    if not auth:return self.reply(404)
    uid,_=auth
    if not self.server.allow(self.client_address[0],uid):return self.reply(429)
    if self.command!='HEAD':export(uid)
    auth=authorize(base,token)
    if not auth or auth[0]!=uid:return self.reply(404)
    _,u=auth;p=base/'users'/uid/FORMATS[kind]
    if p.is_symlink() or p.parent.is_symlink() or not p.is_file():return self.reply(503)
    if p.stat().st_size>8*1024*1024:return self.reply(503)
    payload=p.read_bytes()
    headers={'Content-Type':'application/json' if kind=='singbox' else 'text/yaml; charset=utf-8' if kind=='clash' else 'text/plain; charset=utf-8',
             'subscription-userinfo':'upload='+str(u['upload'])+'; download='+str(u['download'])+'; total='+str(u['quota_bytes'])+'; expire='+str(u['expires_at']),
             'X-Content-Type-Options':'nosniff','Content-Disposition':'attachment; filename="'+FORMATS[kind]+'"'}
    self.reply(200,payload,headers)
   except (ValueError,KeyError,OSError,subprocess.SubprocessError):self.reply(503)
 return Handler

class Server(socketserver.ThreadingMixIn,http.server.HTTPServer):
 daemon_threads=True;allow_reuse_address=True
 def __init__(self,*args,**kwargs):
  self.slots=threading.BoundedSemaphore(16);self.rate_lock=threading.Lock();self.rates={};super().__init__(*args,**kwargs)
 def process_request(self,request,address):
  if not self.slots.acquire(blocking=False):self.shutdown_request(request);return
  try:super().process_request(request,address)
  except BaseException:self.slots.release();raise
 def process_request_thread(self,request,address):
  try:super().process_request_thread(request,address)
  finally:self.slots.release()
 def handle_error(self,*_):pass
 def allow(self,ip,identity=None):
  # Only authenticated account identities enter this table in the HTTP handler.
  ip="account:"+identity if identity is not None else ip
  with self.rate_lock:
   now=time.monotonic()
   self.rates={k:v for k,v in self.rates.items() if now-v[0]<60}
   if ip not in self.rates and len(self.rates)>=1024:return False
   start,count=self.rates.get(ip,(now,0));self.rates[ip]=(start,count+1);return count<60
 def get_request(self):
  request,address=self.socket.accept();request.settimeout(10)
  try:return (self.context.wrap_socket(request,server_side=True,do_handshake_on_connect=False),address) if hasattr(self,'context') else (request,address)
  except BaseException:request.close();raise

class DualServer(Server):
 address_family=socket.AF_INET6
 def server_bind(self):self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,0);super().server_bind()

def serve(base,manager):
 d=read(base);context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2;context.load_cert_chain(d['cert'],d['key'])
 try:server=DualServer(('::',d['port']),handler(base,manager))
 except OSError:server=Server(('0.0.0.0',d['port']),handler(base,manager))
 server.context=context
 with server:server.serve_forever(poll_interval=.5)

if __name__=='__main__':
 base,manager,action,*args=sys.argv[1:];base=pathlib.Path(base);p=base/'subscriptions.json'
 if action=='serve':serve(base,manager)
 elif action=='guard':
  if p.exists():read(base)
 elif action=='init':
  if p.exists() or p.is_symlink():raise ValueError('Subscription settings already exist')
  host,port,cert,key=args;d={'owner':OWNER,'schema':1,'host':host,'port':int(port),'cert':cert,'key':key,'tokens':{}};atomic(p,d)
  try:read(base)
  except BaseException:p.unlink();raise
 elif action in ('issue','revoke','links'):
  d=read(base);uid=args[0];user(base,uid)
  if action=='issue':d['tokens'][uid]=secrets.token_urlsafe(32);atomic(p,d)
  elif action=='revoke':d['tokens'][uid]=None;atomic(p,d)
  if action!='revoke':
   for kind,url in links(d,uid).items():print(kind+'\n'+url+'\n'+'-'*64)
 else:raise ValueError('Unknown subscription operation')
