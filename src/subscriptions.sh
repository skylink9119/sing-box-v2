exports() (
 check_owned || return
 if command -v flock >/dev/null; then exec 8>"$BASE/export.lock"; flock 8; fi
 python3 - "$META" "$BASE" "$CONF" "${LANGUAGE_CHOICE:-zh_CN}" <<'PY'
import base64,json,os,sys,urllib.parse,subprocess,plistlib,uuid,re
s=json.load(open(sys.argv[1]));base=sys.argv[2];ip=s['ip']
en=sys.argv[4]=='en_US'
def tr(zh,english): return english if en else zh
separator='-'*64
node_name=s.get('node_name') or 'SKYBYTE'
reality_name=node_name+'-Reality'; hy2_name=node_name+'-HY2'
config=json.load(open(sys.argv[3])); inbound={i['type']:i for i in config['inbounds'] if i['type'] in ('vless','hysteria2')}
if not inbound: raise ValueError('No supported installed protocols')
mode='3' if len(inbound)==2 else '1' if 'vless' in inbound else '2'
if 'vless' in inbound:
 i=inbound['vless'];s.update(uuid=i['users'][0]['uuid'],sni=i['tls']['server_name'],sid=i['tls']['reality']['short_id'][0])
if 'hysteria2' in inbound:
 i=inbound['hysteria2'];s.update(hy2_password=i['users'][0]['password'],domain=i['tls']['server_name'],cert_path=i['tls']['certificate_path'])
d=s.get('domain','');sni=s.get('sni','')
vp=inbound.get('vless',{}).get('listen_port',443); hp=inbound.get('hysteria2',{}).get('listen_port',443)
cert_pem=None; fingerprint=None
self_signed=s.get('cert_mode')=='1'
if mode!='1':
 identity=subprocess.check_output(['openssl','x509','-in',s['cert_path'],'-noout','-issuer','-subject','-nameopt','RFC2253'],text=True).splitlines()
 names=[line.split('=',1)[1].strip() for line in identity]
 self_signed=self_signed or names[0]==names[1]
if mode!='1' and self_signed:
 import hashlib,ssl
 cert_pem=open(s['cert_path']).read()
 fingerprint=hashlib.sha256(ssl.PEM_cert_to_DER_cert(cert_pem)).hexdigest()
v='vless://{}@{}:{}?{}#{}'.format(s.get('uuid',''),ip,vp,urllib.parse.urlencode({'encryption':'none','flow':'xtls-rprx-vision','security':'reality','sni':sni,'fp':'chrome','pbk':s.get('public_key',''),'sid':s.get('sid',''),'type':'tcp'}),urllib.parse.quote(reality_name,safe=''))
h='hysteria2://{}@{}:{}?{}#{}'.format(urllib.parse.quote(s.get('hy2_password',''),safe=''),ip,hp,urllib.parse.urlencode(dict({'sni':d,'insecure':'0'}, **({'pinSHA256':fingerprint} if fingerprint else {}))),urllib.parse.quote(hy2_name,safe=''))
links=[v] if mode=='1' else [h] if mode=='2' else [v,h]
link_names=[reality_name] if mode=='1' else [hy2_name] if mode=='2' else [reality_name,hy2_name]
argo=None;argo_note=None;argo_name=node_name+'-Argo'
argo_state=os.path.join(base,'argo-state.json');argo_conf=os.path.join(base,'argo-server.json')
if os.path.isfile(argo_state):
 a=json.load(open(argo_state))
 if a.get('connected') and a.get('domain'):
  host=a['domain'];assert len(host)<=253 and all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',p) for p in host.split('.'))
  origin=json.load(open(argo_conf))['inbounds'][0]
  assert origin['type']=='vless' and origin['listen']=='127.0.0.1' and origin['transport']['type']=='ws'
  uid=origin['users'][0]['uuid'];path=origin['transport']['path']
  argo_name=(a.get('node_name') or node_name)+'-Argo'
  argo={'domain':host,'uuid':uid,'path':path,'mode':a['mode']}
  query={'encryption':'none','security':'tls','type':'ws','sni':host,'host':host,'path':path,'alpn':'http/1.1'}
  links.append('vless://{}@{}:443?{}#{}'.format(uid,host,urllib.parse.urlencode(query),urllib.parse.quote(argo_name,safe='')))
  link_names.append(argo_name)
 else:argo_note=tr('Argo 未注册连接，暂不导出旧隧道节点。','Argo is not registered; stale tunnel nodes are not exported.')
def write(name,content):
 path=os.path.join(base,name)
 with open(path,'wb' if isinstance(content,bytes) else 'w') as f:f.write(content)
 os.chmod(path,0o600)
 return path
node_text='\n'.join(links)+'\n'
subscription_text=base64.b64encode(node_text.encode()).decode()+'\n'
write('nodes.txt',node_text); write('subscription-base64.txt',subscription_text)
write('v2rayn-nodes.txt',node_text); write('v2rayn-subscription.txt',subscription_text)
write('shadowrocket-nodes.txt',node_text); write('shadowrocket-subscription.txt',subscription_text)
# Shadowrocket's native VLESS dialect: base64(auto:UUID@host:port).
# Keep standard exports intact for existing consumers.
rocket_links=[]
for link,name in zip(links,link_names):
 u=urllib.parse.urlsplit(link)
 if u.scheme!='vless':
  rocket_links.append(link);continue
 q=dict(urllib.parse.parse_qsl(u.query));host=u.hostname
 address='['+host+']' if ':' in host else host
 authority=base64.b64encode(('auto:'+u.username+'@'+address+':'+str(u.port)).encode()).decode()
 options={'remarks':name,'tls':'1','allowInsecure':'0','peer':q['sni']}
 if q.get('security')=='reality':
  options.update(xtls='2',pbk=q['pbk'],sid=q['sid'],fp=q['fp'])
 elif q.get('type')=='ws':
  options.update(obfs='websocket',obfsParam=q['host'],path=q['path'],alpn=q.get('alpn','http/1.1'))
 rocket_links.append('vless://'+authority+'?'+urllib.parse.urlencode(options,quote_via=urllib.parse.quote))
rocket_text='\n'.join(rocket_links)+'\n'
write('shadowrocket-native-nodes.txt',rocket_text)
write('shadowrocket-native-subscription.txt',base64.b64encode(rocket_text.encode()).decode()+'\n')

out=[];proxy=[]
if mode!='2':
 out.append({'type':'vless','tag':reality_name,'server':ip,'server_port':vp,'uuid':s['uuid'],'flow':'xtls-rprx-vision','tls':{'enabled':True,'server_name':sni,'utls':{'enabled':True,'fingerprint':'chrome'},'reality':{'enabled':True,'public_key':s['public_key'],'short_id':s['sid']}}})
 proxy.append({'name':reality_name,'type':'vless','server':ip,'port':vp,'uuid':s['uuid'],'network':'tcp','tls':True,'servername':sni,'client-fingerprint':'chrome','flow':'xtls-rprx-vision','reality-opts':{'public-key':s['public_key'],'short-id':s['sid']}})
if mode!='1':
 tls={'enabled':True,'server_name':d}
 if self_signed:tls['certificate']=cert_pem.splitlines()
 ho={'type':'hysteria2','tag':hy2_name,'server':ip,'server_port':hp,'password':s['hy2_password'],'tls':tls}
 if s.get('hop'):ho.update({'server_ports':[f"{s['hop_start']}:{s['hop_end']}"],'hop_interval':'30s'})
 out.append(ho)
 mp={'name':hy2_name,'type':'hysteria2','server':ip,'port':hp,'password':s['hy2_password'],'sni':d,'skip-cert-verify':False}
 if s.get('hop'):mp['ports']=f"{s['hop_start']}-{s['hop_end']}";mp['hop-interval']=30
 if self_signed:mp['fingerprint']=fingerprint
 proxy.append(mp)
if argo:
 host=argo['domain'];path=argo['path'];uid=argo['uuid']
 out.append({'type':'vless','tag':argo_name,'server':host,'server_port':443,'uuid':uid,
             'tls':{'enabled':True,'server_name':host,'alpn':['http/1.1']},
             'transport':{'type':'ws','path':path,'headers':{'Host':host}}})
 proxy.append({'name':argo_name,'type':'vless','server':host,'port':443,'uuid':uid,'network':'ws',
               'tls':True,'servername':host,'skip-cert-verify':False,
               'ws-opts':{'path':path,'headers':{'Host':host}}})
write('outbounds.json',json.dumps({'outbounds':out},ensure_ascii=False,indent=2)+'\n')
client_config={'inbounds':[{'type':'mixed','tag':'mixed-in','listen':'127.0.0.1','listen_port':1080}],
               'outbounds':out+[{'type':'direct','tag':'direct'}], 'route':{'final':out[0]['tag']}}
client_json=json.dumps(client_config,ensure_ascii=False,indent=2)+'\n'
write('sing-box-client.json',client_json)
trust_files=[]
# Remove obsolete public trust exports, so a changed certificate cannot leave stale instructions.
for name in ['hy2-client-ca.pem','hy2-client-ca.cer','hy2-client-ca.mobileconfig']:
 path=os.path.join(base,name)
 if os.path.isfile(path): os.remove(path)
if cert_pem:
 write('hy2-client-ca.pem',cert_pem)
 der=ssl.PEM_cert_to_DER_cert(cert_pem)
 write('hy2-client-ca.cer',der)
 trust_files=['hy2-client-ca.pem','hy2-client-ca.cer']
 # iOS root profiles require a CA certificate; never label a leaf-only cert as a CA.
 text=subprocess.check_output(['openssl','x509','-in',s['cert_path'],'-noout','-text'],text=True)
 if 'CA:TRUE' in text:
  payload={'PayloadType':'com.apple.security.root','PayloadVersion':1,
           'PayloadIdentifier':'com.skybyte.hy2.ca.'+fingerprint,
           'PayloadUUID':str(uuid.uuid4()).upper(),'PayloadDisplayName':'SKYBYTE HY2 '+ip,
           'PayloadCertificateFileName':'hy2-client-ca.cer','PayloadContent':der}
  profile={'PayloadType':'Configuration','PayloadVersion':1,
           'PayloadIdentifier':'com.skybyte.hy2.trust.'+fingerprint,
           'PayloadUUID':str(uuid.uuid4()).upper(),'PayloadDisplayName':'SKYBYTE HY2 Trust '+ip,
           'PayloadDescription':tr('仅包含此 HY2 自签名公开证书；核对指纹后安装并手动开启信任。','Contains only the HY2 public certificate. Verify the fingerprint before installing and manually enabling trust.'),
           'PayloadContent':[payload]}
  write('hy2-client-ca.mobileconfig',plistlib.dumps(profile))
  trust_files.append('hy2-client-ca.mobileconfig')
def scalar(x):return json.dumps(x,ensure_ascii=False) if isinstance(x,str) else ('true' if x is True else 'false' if x is False else str(x))
def yaml_dump(v,level=0):
 lines=[]
 if isinstance(v,dict):
  for k,val in v.items():
   key=' '*level+str(k)+':'
   if isinstance(val,(list,dict)):lines.append(key);lines.extend(yaml_dump(val,level+2))
   else:lines.append(key+' '+scalar(val))
 elif isinstance(v,list):
  for val in v:
   if isinstance(val,(list,dict)):lines.append(' '*level+'-');lines.extend(yaml_dump(val,level+2))
   else:lines.append(' '*level+'- '+scalar(val))
 return lines
yaml_config={'proxies':proxy}
if cert_pem: yaml_config['tls']={'custom-certifactes':[cert_pem]}
write('mihomo-proxies.yaml','# SKYBYTE: merge proxies AND tls trust settings with your Mihomo config.\n'+'\n'.join(yaml_dump(yaml_config))+'\n')
clash_config=dict(yaml_config)
clash_config.update({'mixed-port':7890,'allow-lan':False,'mode':'rule',
                     'proxy-groups':[{'name':'SKYBYTE','type':'select','proxies':[p['name'] for p in proxy]}],
                     'rules':['MATCH,SKYBYTE']})
clash_yaml='\n'.join(yaml_dump(clash_config))+'\n'
write('clash-verge.yaml',clash_yaml)
notes=[]
if argo_note:notes.append(argo_note)
if argo:
 notes.append(tr('Argo 使用 VLESS+WS+TLS，不是 Reality/Vision 或 HY2。临时隧道重启后请重新导入新地址。','Argo uses VLESS+WS+TLS, not Reality/Vision or HY2. Re-import changed Quick Tunnel hostnames after restarting.'))
if mode!='1' and self_signed:
 notes += [tr('无域名模式仍使用 TLS 自签名证书；只导入链接不会自动建立信任。','No-domain mode still uses self-signed TLS; importing a URI does not establish trust.'),
           tr('SHA-256 指纹：','SHA-256 fingerprint: ')+fingerprint,
           tr('sing-box JSON 和 Mihomo YAML 已包含公开信任证书。','sing-box JSON and Mihomo YAML include the trusted public certificate.'),
           tr('小火箭：通过可信 SSH/SFTP 取回公开证书，核对指纹后建立证书信任。','Shadowrocket: retrieve the public certificate via trusted SSH/SFTP, verify its fingerprint and configure certificate trust.')]
 if 'hy2-client-ca.mobileconfig' in trust_files:
  notes += [tr('iPhone：安装 hy2-client-ca.mobileconfig，再在设置 → 通用 → 关于本机 → 证书信任设置中开启此证书的完全信任。','iPhone: install hy2-client-ca.mobileconfig, then enable full trust in Settings > General > About > Certificate Trust Settings.'),
            tr('这是系统信任配置；小火箭 HY2 是否使用系统信任须由连接日志验证。','This configures system trust; check connection logs to verify whether Shadowrocket HY2 uses it.')]
 else:
  notes.append(tr('当前证书不是 CA 证书，不能生成 iOS 根证书描述文件；使用客户端支持的自定义信任或受信任 CA 证书。','This certificate is not a CA; no iOS root profile is generated. Use supported client custom trust or a trusted CA certificate.'))
 notes += [tr('保留 TLS 验证；不要仅为连接而打开跳过验证。不要传输服务端私钥。','Keep TLS verification enabled. Do not enable skip verification just to connect. Never transfer the server private key.'),
           tr('仍失败时运行服务器与网络 → HY2 诊断（4 → 9）；服务运行、证书信任与 UDP 可达需要分别检查。','If connection fails, run Server and network > HY2 checks (4 > 9); service health, certificate trust and UDP reachability are separate checks.')]
if s.get('hop'):notes.append(tr('端口跳跃需客户端支持，并放行本机和云防火墙 UDP 范围；普通 URI 不包含跳跃范围。','Hopping requires client support and local/provider UDP range rules; basic URIs do not include the range.'))
write('subscription-notes.txt','\n'.join(notes or [tr('导入前核实客户端协议支持。','Check client protocol support before importing.')])+'\n')
color=sys.stdout.isatty() and not os.getenv('NO_COLOR')
def info(text):print(('\033[1;33m' if color else '')+text+('\033[0m' if color else ''))
def sensitive(text):print(('\033[1;31m' if color else '')+text.rstrip()+('\033[0m' if color else ''))
def section(title,names):
 print(separator)
 info(title)
 for name in names:info(tr('文件：','File: ')+os.path.join(base,name))
section('v2rayN', ['v2rayn-nodes.txt','v2rayn-subscription.txt'])
info(tr('从剪贴板导入以下节点；HY2 自签名需要证书信任。','Import these URIs from clipboard; self-signed HY2 needs certificate trust.'))
for link,name in zip(links,link_names):
 info(tr('节点：','Node: ')+('VLESS + WS + Argo' if argo and name==argo_name else 'VLESS + Reality + Vision' if link.startswith('vless:') else 'Hysteria2'))
 info(tr('节点名称：','Node name: ')+name)
 sensitive(link)
section('Clash Verge / Mihomo YAML', ['clash-verge.yaml'])
info(tr('完整客户端配置，可作为本地配置导入；经典 Clash 不支持这些协议。','Complete local client config; classic Clash does not support these protocols.'))
sensitive(clash_yaml)
section('sing-box JSON', ['sing-box-client.json','outbounds.json'])
info(tr('完整客户端配置，默认使用首个节点；outbounds.json 为合并用片段。','Complete client config using the first node by default; outbounds.json is a merge fragment.'))
sensitive(client_json)
section(tr('小火箭专用链接 / Shadowrocket','Shadowrocket native links'), ['shadowrocket-native-nodes.txt','shadowrocket-native-subscription.txt'])
for link,name in zip(rocket_links,link_names):
 info(tr('节点名称：','Node name: ')+name)
 sensitive(link)
 print(separator)
print(separator)
info(tr('兼容导出和证书说明：','Legacy exports and certificate notes:'))
for name in ['nodes.txt','subscription-base64.txt','mihomo-proxies.yaml','subscription-notes.txt']+trust_files:info('  '+os.path.join(base,name))

for note in notes:print(('\033[1;33m' if color else '')+tr('提示：','NOTICE: ')+note+('\033[0m' if color else ''))
if notes:print(separator)

PY
)

bbr(){ need_root; confirm "$(L '更改系统 TCP 拥塞控制为 BBR、默认队列为 FQ？' 'Change system TCP congestion control to BBR and default qdisc to FQ?')" || return 0; modprobe tcp_bbr 2>/dev/null || :; if ! sysctl -n net.ipv4.tcp_available_congestion_control | grep -qw bbr; then err "$(L '内核不支持 BBR' 'Kernel does not support BBR')"; return 1; fi
 printf 'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\n' >"$SYSCTL_FILE"
 sysctl -p "$SYSCTL_FILE"; sysctl net.ipv4.tcp_congestion_control net.core.default_qdisc; }
hop_disable(){ nft delete table ip singbox_v2_hop 2>/dev/null || :; if [[ -f $META ]]; then python3 - "$META" <<'PY'
import json,sys
p=sys.argv[1];d=json.load(open(p));d['hop']=False
with open(p,'w') as f:json.dump(d,f,indent=2)
PY
 fi; say '已关闭本工具管理的端口跳跃规则' 'Disabled managed port-hopping rules'; }
