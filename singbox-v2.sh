#!/usr/bin/env bash
# SKYBYTE Manager V2.1 community manager; review before running, Debian/Ubuntu only
set -Eeuo pipefail
umask 077
SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
BASE=/etc/singbox-v2
CONF=/etc/sing-box/config.json
SYSTEMD_DIR=/etc/systemd/system
OS_RELEASE=/etc/os-release
MANAGER_BIN=/usr/local/sbin/singbox-v2
MANAGER_LIB=/usr/local/lib/singbox-v2/singbox-v2.sh
SYSCTL_FILE=/etc/sysctl.d/90-singbox-v2-bbr.conf
META=$BASE/state.json
REPORT=$BASE/reports
BACKUP=$BASE/backups
BIN=/usr/local/bin/sing-box
LOCK=/run/singbox-v2.lock

# Language preference is independent of sing-box configuration.
LANG_FILE="$BASE/language.conf"
LANGUAGE_CHOICE=""
load_language() {
  if [[ -f "$LANG_FILE" ]]; then
    local value
    value=$(cat "$LANG_FILE")
    case "$value" in zh_CN|en_US) LANGUAGE_CHOICE=$value;; esac
  fi
}
select_language() {
  local choice
  while :; do
    printf '%s\n========== Language / 语言 ==========\n 1. 简体中文\n 2. English\n=======================================\n%s' "$GREEN" "$RESET"
    read -r -p '请选择语言 / Select language [1/2]: ' choice || return 1
    case "$choice" in 1) LANGUAGE_CHOICE=zh_CN;; 2) LANGUAGE_CHOICE=en_US;; *) continue;; esac
    printf '%s\n' "$LANGUAGE_CHOICE" > "$LANG_FILE"
    chmod 600 "$LANG_FILE"
    break
  done
}
say(){ printf '%s\n' "$(L "$1" "$2")"; }
L() { if [[ "$LANGUAGE_CHOICE" == en_US ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
 GREEN=$'\033[1;32m'; RED=$'\033[1;31m'; YELLOW=$'\033[1;33m'; CYAN=$'\033[1;36m'; RESET=$'\033[0m'
else GREEN=''; RED=''; YELLOW=''; CYAN=''; RESET=''; fi
YOUTUBE='https://www.youtube.com/@SKYBYTE9119'
ok(){ printf '%s✔ %s%s\n' "$GREEN" "$*" "$RESET"; }
warn(){ printf '%s⚠ %s%s\n' "$YELLOW" "$*" "$RESET"; }
err(){ printf '%s✖ %s%s\n' "$RED" "$*" "$RESET" >&2; }
need_root(){ [[ $EUID == 0 ]] || { err "$(L '需要 root 权限' 'Root privileges required')"; exit 1; }; }
confirm(){ local answer; read -r -p "$1 $(L '[输入 YES 确认]' '[Type YES to confirm]'): " answer || return 1; [[ $answer =~ ^[[:space:]]*[Yy][Ee][Ss][[:space:]]*$ ]]; }
notice(){ if [[ "$LANGUAGE_CHOICE" == en_US ]]; then cat <<'EOF_EN'
[LEGAL & PRIVACY NOTICE] Use only for lawful networking education and server administration. You must comply with applicable law and service terms. Updating software or changing firewall/network settings may interrupt service or cause data loss; make backups first. Provided as-is to the extent permitted by law. Third-party components retain their licenses.
Installation and updates can contact github.com, api.github.com and GitHub release CDNs; these services can see your source IP. Installation queries api.ipify.org for your public IPv4. The optional IP report queries ipinfo.io, which may retain your IP and request metadata; reports are stored locally in /etc/singbox-v2/reports and deleted after 30 days. No developer telemetry and no intentional upload of node credentials. Auto-update is opt-in. HY2 requires TLS. A no-domain self-signed certificate mode is available, but clients must securely trust the certificate.
Optional Argo connects to Cloudflare, which terminates outer TLS and can inspect WebSocket payloads. Tunnel tokens are stored locally and included in private backups.
EOF_EN
else cat <<'EOF'
【法律与隐私披露】此工具仅供合法网络技术学习和服务器管理；使用者应遵守适用法律和服务条款。更改防火墙、网络参数及更新软件可能导致中断或损失，请提前备份。软件按现状提供，不排除依法不得排除的责任。第三方软件遵循其许可证。
安装/更新可能连接：github.com、api.github.com、GitHub 发布文件 CDN，访问服务会暴露请求来源 IP。安装时 api.ipify.org 用于识别出口 IP。可选 IP 检测使用 ipinfo.io，报告保存在本地 /etc/singbox-v2/reports，默认保留 30 天；第三方可能记录来源 IP、查询目标和请求时间。无开发者遥测或上传节点密钥；请勿公开包含凭据的配置和导出文件。自动更新默认关闭。HY2 必须有 TLS 证书，无域名用户可生成自签名证书，客户端必须正确配置信任，不能默认跳过证书验证。
可选 Argo 连接 Cloudflare，外层 TLS 在其边缘终止，可检查 WebSocket 载荷。隧道 Token 保存在本地并包含在私密备份中。
EOF
fi
}
require_cmd(){ command -v "$1" >/dev/null || { err "$(L "缺少命令 $1" "Missing command: $1")"; return 1; }; }
valid_port(){ [[ $1 =~ ^[0-9]{1,5}$ ]] && (( 1 <= 10#$1 && 10#$1 <= 65535 )); }
state(){ python3 - "$META" "$1" <<'PY'
import json,sys
with open(sys.argv[1]) as f: d=json.load(f)
print(d.get(sys.argv[2],''))
PY
}
protocol_mode(){
 python3 - "$CONF" <<'PY'
import json,sys
p={i['type'] for i in json.load(open(sys.argv[1]))['inbounds']}
if {'vless','hysteria2'} <= p: print('3')
elif 'vless' in p: print('1')
elif 'hysteria2' in p: print('2')
else: raise ValueError('No supported installed protocols')
PY
}
check_owned(){ [[ -f $META && -f $CONF ]] || { err "$(L '未发现由本脚本部署的节点' 'No deployment managed by this script was found')"; return 1; }; }
backup(){
 check_owned || return 1
 local path file
 path="$BACKUP/$(date +%Y%m%d-%H%M%S)-$RANDOM"
 mkdir -m 700 "$path" || return 1; cp -a "$(dirname "$CONF")" "$path/config" || return 1
 cp "$META" "$path/state.json" || return 1
 cp "$BIN" "$path/sing-box.bin" || return 1
 if [[ -f "$BASE/hop.nft" ]]; then cp "$BASE/hop.nft" "$path/hop.nft" || return 1; fi
 for file in argo-state.json argo-server.json argo-empty.yml argo.token; do
  if [[ -f $BASE/$file ]]; then cp "$BASE/$file" "$path/$file" || return 1; fi
 done
 if [[ -f $BASE/argo-state.json && -f $BASE/cloudflared ]]; then cp "$BASE/cloudflared" "$path/cloudflared.bin" || return 1; fi
 python3 - "$path" "$CONF" <<'PY' || return 1
import json,sys,shutil,pathlib
root=pathlib.Path(sys.argv[1]); cfg=json.load(open(sys.argv[2])); meta=json.load(open(root/'state.json'))
for i in cfg['inbounds']:
 if i['type']=='hysteria2':
  for field,name in [('certificate_path','hy2-backup.crt'),('key_path','hy2-backup.key')]:
   shutil.copyfile(i['tls'][field],root/'config'/name)
   i['tls'][field]=str(pathlib.Path(sys.argv[2]).parent/name)
  meta['cert_path']=i['tls']['certificate_path']
  meta['managed_certificates']=[i['tls']['certificate_path'],i['tls']['key_path']]
(root/'config'/'config.json').write_text(json.dumps(cfg,indent=2))
(root/'state.json').write_text(json.dumps(meta,indent=2))
PY
 chmod -R go-rwx "$path" || return 1; printf '%s\n' "$path"
}
validate_certificate(){
 local cert=$1 key=$2 name=$3 certpub keypub
 LC_ALL=C openssl x509 -in "$cert" -noout -checkend 0 >/dev/null || { err "$(L '证书无效或已过期' 'Certificate invalid or expired')"; return 1; }
 if [[ $name =~ ^[0-9.]+$ ]]; then
  LC_ALL=C openssl x509 -in "$cert" -noout -checkip "$name" | grep -q "does match" || { err "$(L '证书 IP 不匹配' 'Certificate IP does not match')"; return 1; }
 else
  LC_ALL=C openssl x509 -in "$cert" -noout -checkhost "$name" | grep -q "does match" || { err "$(L '证书域名不匹配' 'Certificate hostname does not match')"; return 1; }
 fi
 certpub=$(openssl x509 -in "$cert" -pubkey -noout) || return 1
 keypub=$(openssl pkey -in "$key" -pubout -passin pass: 2>/dev/null) || return 1
 [[ $certpub == "$keypub" ]] || { err "$(L '证书和私钥不匹配' 'Certificate and private key do not match')"; return 1; }
}
# Download only a verified release binary; never execute a package installer on updates.
download_binary(){
 local version=$1 target=$2 arch tmp asset sum
 [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
 case "$(uname -m)" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) err "$(L '不支持此架构' 'Unsupported architecture')"; return 1;; esac
 tmp=$(mktemp -d) || return 1
 asset="sing-box-$version-linux-$arch.tar.gz"
 if ! curl -fsSL --retry 2 --max-time 180 "https://github.com/SagerNet/sing-box/releases/download/v$version/$asset" -o "$tmp/$asset" ||
    ! curl -fsSL --retry 2 --max-time 30 "https://api.github.com/repos/SagerNet/sing-box/releases/tags/v$version" -o "$tmp/release.json"; then rm -rf "$tmp"; return 1; fi
 sum=$(python3 - "$tmp/release.json" "$asset" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); assert not r['draft'] and not r['prerelease']
a=next(a for a in r['assets'] if a['name']==sys.argv[2])
digest=a.get('digest') or ''; assert digest.startswith('sha256:')
print(digest.split(':',1)[1])
PY
 ) || { rm -rf "$tmp"; return 1; }
 if [[ ! $sum =~ ^[a-fA-F0-9]{64}$ ]] || ! printf '%s  %s\n' "$sum" "$tmp/$asset" | sha256sum -c - >/dev/null; then rm -rf "$tmp"; return 1; fi
 tar -xzf "$tmp/$asset" -C "$tmp" || { rm -rf "$tmp"; return 1; }
 command install -m 755 "$tmp/sing-box-$version-linux-$arch/sing-box" "$target"
 local rc=$?; rm -rf "$tmp"; return "$rc"
}
setup_service(){ cat >"$SYSTEMD_DIR/sing-box.service" <<EOF
[Unit]
Description=sing-box (managed by singbox-v2)
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=$BIN run -c $CONF
Restart=on-failure
RestartSec=3
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
EOF
 systemctl daemon-reload; }
# Installation requires a clean deployment; configuration generation is separately testable.
choose_node_name(){
 local value
 read -r -p "$(L '节点名称前缀 [SKYBYTE]（回车默认）：' 'Node name prefix [SKYBYTE] (Enter for default): ')" value || return 1
 python3 - "$value" <<'PY'
import sys,unicodedata
name=sys.argv[1].strip() or 'SKYBYTE'
if len(name)>64 or any(unicodedata.category(c).startswith('C') for c in name):
 print('节点名称最多 64 个字符且不能包含控制字符 / Maximum 64 characters; no control characters',file=sys.stderr)
 sys.exit(1)
print(name)
PY
}
rename_node(){
 check_owned || return 1
 local name
 name=$(choose_node_name) || { err "$(L '节点名称无效' 'Invalid node name')"; return 1; }
 python3 - "$META" "$name" <<'PY'
import json,sys,os,tempfile
p,name=sys.argv[1:];state=json.load(open(p));state['node_name']=name
with tempfile.NamedTemporaryFile(mode='w',dir=os.path.dirname(p),delete=False) as f:
 json.dump(state,f,ensure_ascii=False,indent=2);temp=f.name
os.chmod(temp,0o600);os.replace(temp,p)
PY
 if [[ -f $BASE/argo-state.json ]]; then
  python3 - "$BASE" "$name" <<'PY'
import fcntl,json,pathlib,sys,os,tempfile
base=pathlib.Path(sys.argv[1]);p=base/'argo-state.json'
with open(base/'argo-state.lock','a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX);s=json.loads(p.read_text());s['node_name']=sys.argv[2]
 with tempfile.NamedTemporaryFile(mode='w',dir=base,delete=False) as f:json.dump(s,f,ensure_ascii=False,indent=2);tmp=f.name
 os.chmod(tmp,0o600);os.replace(tmp,p)
PY
 fi
 exports
}
write_config(){
 python3 - "$@" <<'PY'
import json,sys
conf,meta,domain,cert,key,sni,uuid,priv,pub,sid,password,ip,mode,cert_mode=sys.argv[1:15]
node_name=sys.argv[15] if len(sys.argv)>15 else 'SKYBYTE'
d={'log':{'level':'info','timestamp':True},'inbounds':[{'type':'vless','tag':'reality','listen':'0.0.0.0','listen_port':443,'users':[{'name':'user1','uuid':uuid,'flow':'xtls-rprx-vision'}],'tls':{'enabled':True,'server_name':sni,'reality':{'enabled':True,'handshake':{'server':sni,'server_port':443},'private_key':priv,'short_id':[sid]}}},{'type':'hysteria2','tag':'hy2','listen':'0.0.0.0','listen_port':443,'users':[{'name':'user1','password':password}],'tls':{'enabled':True,'server_name':domain,'certificate_path':cert,'key_path':key}}],'outbounds':[{'type':'direct','tag':'direct'}],'route':{'final':'direct'}}
if mode=='1': d['inbounds']=d['inbounds'][:1]
elif mode=='2': d['inbounds']=d['inbounds'][1:]
with open(conf,'w') as f:json.dump(d,f,indent=2)
with open(meta,'w') as f:json.dump({'node_name':node_name,'mode':mode,'cert_mode':cert_mode,'cert_path':cert,'managed_certificates':[cert,key] if cert_mode=='1' else [],'ip':ip,'domain':domain,'sni':sni,'uuid':uuid,'public_key':pub,'sid':sid,'hy2_password':password,'hop':False,'hop_start':20000,'hop_end':30000},f,indent=2)
PY
}
install_protocol(){
 need_root
 [[ -r $OS_RELEASE ]] || return 1
 # shellcheck source=/dev/null
 . "$OS_RELEASE"
 case ${ID:-} in ubuntu|debian) ;; *) err "$(L '仅支持 Ubuntu/Debian' 'Ubuntu/Debian required')"; return 1;; esac
 local mode="${1:-}" cert_mode="" 
 if [[ -z "$mode" ]]; then printf '\033[1;32m%s\033[0m\n' "$(L '1 Reality 单协议 | 2 HY2 单协议 | 3 双协议 | 0 返回' '1 Reality only | 2 HY2 only | 3 Dual | 0 Back')"
 read -r -p '> ' mode || return; fi
 [[ "$mode" == 0 ]] && return 0
 [[ "$mode" =~ ^[123]$ ]] || { err "Invalid selection"; return 1; }
 notice; confirm "$(L '同意声明并安装所选协议？' 'Accept notice and install selected protocol(s)?')" || return 0
 if [[ -e $CONF || -e $META || -e $BIN ]] || command -v sing-box >/dev/null; then err "$(L '发现已有配置，拒绝覆盖' 'Existing configuration or binary found; refusing to overwrite')"; return 1; fi
 if systemctl list-unit-files sing-box.service --no-legend 2>/dev/null | grep -q sing-box; then err "$(L '已有 sing-box 服务，拒绝覆盖' 'Existing sing-box service found; refusing to overwrite')"; return 1; fi
 require_cmd ss || { apt-get update && apt-get install -y iproute2 || return 1; }
 if [[ $mode != 2 ]] && ss -H -ltn '( sport = :443 )' | grep -q .; then err "$(L 'TCP 443 已被占用' 'TCP 443 is occupied')"; return 1; fi
 if [[ $mode != 1 ]] && ss -H -lun '( sport = :443 )' | grep -q .; then err "$(L 'UDP 443 已被占用' 'UDP 443 is occupied')"; return 1; fi
 local domain="" cert="" key="" sni="" node_name
 node_name=$(choose_node_name) || { err "$(L '节点名称无效' 'Invalid node name')"; return 1; }
 if [[ $mode != 1 ]]; then
  say 'HY2证书: 1 无域名(自动自签名)  2 已有证书' 'HY2 certificate: 1 No domain (self-signed)  2 Existing certificate'
  read -r -p '> ' cert_mode
  case "$cert_mode" in
   1) say '需要客户端安全地导入证书并启用验证。' 'Client must securely import and verify the certificate.';;
   2) read -r -p "$(L '证书域名：' 'Certificate domain: ')" domain
      [[ $domain =~ ^[a-zA-Z0-9.-]+$ && $domain == *.* ]] || { err "$(L '域名无效' 'Invalid domain')"; return 1; }
      read -r -p "$(L 'TLS 完整证书路径：' 'TLS fullchain path: ')" cert
      read -r -p "$(L 'TLS 私钥路径：' 'TLS key path: ')" key
      [[ -f $cert && -f $key ]] || { err "$(L '证书或私钥不存在' 'Certificate/key missing')"; return 1; };;
   *) err "$(L '无效证书选项' 'Invalid certificate option')"; return 1;;
  esac
 fi
 if [[ $mode != 2 ]]; then
  read -r -p "$(L 'Reality 握手域名 [addons.mozilla.org]：' 'Reality handshake [addons.mozilla.org]: ')" sni
  sni=${sni:-addons.mozilla.org}
  [[ $sni =~ ^[a-zA-Z0-9.-]+$ ]] || { err "$(L '无效 SNI' 'Invalid SNI')"; return 1; }
 fi
 say '安装依赖...' 'Installing dependencies...'; apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y curl openssl ca-certificates python3 iproute2 util-linux nftables || return 1
 require_cmd getent; getent ahostsv4 github.com >/dev/null || { err "$(L 'GitHub DNS 解析失败，请先修复 DNS' 'GitHub DNS lookup failed; fix DNS first')"; return 1; }
 mkdir -p "$(dirname "$BIN")"
 if [[ $cert_mode == 2 ]]; then validate_certificate "$cert" "$key" "$domain" || return 1; fi
 download_binary "$(latest)" "$BIN" || { err "$(L '官方安装失败' 'Release installation failed')"; return 1; }
 chmod 755 "$BIN"
 local uuid pair priv="" pub="" sid="" passwd ip
 uuid=$(cat /proc/sys/kernel/random/uuid)
 if [[ $mode != 2 ]]; then pair=$("$BIN" generate reality-keypair)
 priv=$(sed -n 's/^PrivateKey: *//p' <<<"$pair"); pub=$(sed -n 's/^PublicKey: *//p' <<<"$pair")
 [[ -n $priv && -n $pub ]] || { err "$(L 'Reality 密钥生成失败' 'Reality key generation failed')"; return 1; }; fi
 sid=$(openssl rand -hex 4); passwd=$(openssl rand -hex 16)
 ip=$(curl -4fsS --max-time 15 https://api.ipify.org) || { err "$(L '公网 IPv4 查询失败' 'Public IPv4 lookup failed')"; return 1; }
 python3 - "$ip" <<'PY' || return 1
import ipaddress,sys
assert ipaddress.ip_address(sys.argv[1]).is_global
PY
 mkdir -p "$(dirname "$CONF")"
 if [[ $cert_mode == 1 ]]; then
  [[ ! -e $(dirname "$CONF")/hy2-selfsigned.crt && ! -e $(dirname "$CONF")/hy2-selfsigned.key ]] || { err "TLS files already exist"; return 1; }
  domain="$ip"; cert="$(dirname "$CONF")/hy2-selfsigned.crt"; key="$(dirname "$CONF")/hy2-selfsigned.key"
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 365 -subj "/CN=$ip" -addext "subjectAltName=IP:$ip" -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign" -keyout "$key" -out "$cert" >/dev/null 2>&1 || return 1
  chmod 600 "$key"; chmod 644 "$cert"
 fi
 if [[ $mode != 1 ]]; then validate_certificate "$cert" "$key" "$domain" || return 1; fi
 write_config "$CONF" "$META" "$domain" "$cert" "$key" "$sni" "$uuid" "$priv" "$pub" "$sid" "$passwd" "$ip" "$mode" "$cert_mode" "$node_name"
 chmod 600 "$CONF" "$META"
 "$BIN" check -c "$CONF" || { err "$(L '配置检查失败' 'Configuration check failed')"; return 1; }
 # Binary installation does not create a package unit; create our managed service.
 setup_service
 if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active'; then if [[ $mode != 2 ]]; then ufw allow 443/tcp; fi; if [[ $mode != 1 ]]; then ufw allow 443/udp; fi; fi
 systemctl daemon-reload; systemctl enable --now sing-box; systemctl restart sing-box
 sleep 2; systemctl is-active --quiet sing-box || { err "$(L '服务启动失败，请查看 journalctl -u sing-box' 'Service failed; inspect journalctl -u sing-box')"; return 1; }
 if [[ $cert_mode == 1 ]]; then echo "$(L '自签名证书：' 'Self-signed certificate: ')$cert"; openssl x509 -in "$cert" -noout -fingerprint -sha256; say '务必将证书安全导入客户端并验证，链接本身不足以建立信任。' 'Securely import and verify certificate on client; URL alone cannot establish trust.'; fi
 ok "$(L '部署完成；请检查云防火墙' 'Installed; check provider firewall')"; exports
}
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
section(tr('小火箭 / Shadowrocket 订阅','Shadowrocket subscription'), ['shadowrocket-nodes.txt','shadowrocket-subscription.txt'])
info(tr('以下为本地 Base64 订阅内容；不是在线订阅 URL。单节点可从 shadowrocket-nodes.txt 复制。','Local Base64 subscription content below; this is not a hosted subscription URL. Copy individual URIs from shadowrocket-nodes.txt.'))
sensitive(subscription_text)
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
hop(){ check_owned || return; [[ "$(protocol_mode)" != 1 ]] || { err "$(L '未安装 HY2' 'HY2 not installed')"; return 1; }; require_cmd nft || return 1; say '端口跳跃仅支持 IPv4，规则通过专属 systemd 服务持久化。请同步修改云防火墙。' 'Port hopping is IPv4 only and uses a dedicated systemd service. Also configure your provider firewall.'; say '1 开启  2 关闭' '1 Enable  2 Disable'; read -r -p '> ' choice
 if [[ $choice == 2 ]]; then confirm "$(L '关闭端口跳跃？' 'Disable HY2 port hopping?')" && { systemctl disable --now singbox-v2-hop.service 2>/dev/null || :; hop_disable; }; return; fi
 [[ $choice == 1 ]] || return 0
 read -r -p "$(L '起始端口 [20000]: ' 'Start port [20000]: ')" start; start=${start:-20000}; read -r -p "$(L '结束端口 [30000]: ' 'End port [30000]: ')" end; end=${end:-30000}
 if ! valid_port "$start" || ! valid_port "$end" || ! (( 10#$start<=10#$end && 10#$start>=1024 && 10#$end-10#$start<=10000 )); then err "$(L '端口范围非法（最多10001个）' 'Invalid range (maximum 10001 ports)')"; return 1; fi
 start=$((10#$start)); end=$((10#$end))
 confirm "$(L "启用 UDP $start-$end 转发到 443？" "Forward UDP $start-$end to 443?")" || return 0
 nft list table ip singbox_v2_hop >/dev/null 2>&1 && { err "$(L '已存在端口跳跃规则，请先关闭' 'Hopping table exists; disable it first')"; return 1; }
 cat >"$SYSTEMD_DIR/singbox-v2-hop.service" <<EOF
[Unit]
Description=singbox V2 HY2 IPv4 port hopping
After=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $BASE/hop.nft
ExecStop=/usr/sbin/nft delete table ip singbox_v2_hop
[Install]
WantedBy=multi-user.target
EOF
 cat >"$BASE/hop.nft" <<EOF
add table ip singbox_v2_hop
add chain ip singbox_v2_hop prerouting { type nat hook prerouting priority dstnat; policy accept; }
add rule ip singbox_v2_hop prerouting udp dport $start-$end redirect to :443
EOF
 systemctl daemon-reload; systemctl enable --now singbox-v2-hop.service || { err "$(L '开启失败' 'Enable failed')"; return 1; }
 if command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active'; then ufw allow "$start:$end/udp"; warn "$(L '关闭跳跃后请按需要手动删除 UFW 范围规则' 'After disabling hopping, remove UFW range rules manually if needed')"; fi
 python3 - "$META" "$start" "$end" <<'PY'
import json,sys
p=sys.argv[1];d=json.load(open(p));d.update(hop=True,hop_start=int(sys.argv[2]),hop_end=int(sys.argv[3]))
with open(p,'w') as f:json.dump(d,f,indent=2)
PY
 say '已启用。请在客户端配置 server_ports 和 hop_interval=30s' 'Enabled. Configure server_ports and hop_interval=30s on clients'; }
latest(){ curl -4fsSL --max-time 25 https://api.github.com/repos/SagerNet/sing-box/releases/latest | python3 -c 'import json,sys; d=json.load(sys.stdin); assert not d.get("prerelease") and not d.get("draft"); print(d["tag_name"].lstrip("v"))'; }
update(){
 check_owned || return 1
 local new current
 current=$("$BIN" version | awk 'NR==1{print $3}'); new=$(latest) || return 1
 printf '%s -> %s\n' "$current" "$new"
 [[ $current != "$new" ]] || return 0
 confirm "$(L '更新会短暂中断连接，继续？' 'Update briefly interrupts connections. Continue?')" || return 0
 apply_update "$new"
}
managed_restart(){
 local argo_active=false tunnel_active=false
 if [[ -f $SYSTEMD_DIR/skybyte-argo-node.service ]] && systemctl is-active --quiet skybyte-argo-node.service; then argo_active=true; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-tunnel.service ]] && systemctl is-active --quiet skybyte-argo-tunnel.service; then tunnel_active=true; fi
 systemctl restart sing-box && service_healthy || return 1
 if [[ $argo_active == true ]]; then
  systemctl restart skybyte-argo-node.service && systemctl is-active --quiet skybyte-argo-node.service || return 1
  if [[ $tunnel_active == true ]]; then systemctl restart skybyte-argo-tunnel.service || return 1; fi
 fi
}
apply_update(){
 local new=$1 snap candidate
 candidate=$(mktemp "$BASE/sing-box.candidate.XXXXXX") || return 1
 snap=$(backup) || { rm -f "$candidate"; return 1; }
 download_binary "$new" "$candidate" || { rm -f "$candidate"; return 1; }
 "$candidate" check -c "$CONF" || { rm -f "$candidate"; return 1; }
 if [[ -f $BASE/argo-server.json ]]; then "$candidate" check -c "$BASE/argo-server.json" || { rm -f "$candidate"; return 1; }; fi
 command install -m 755 "$candidate" "$BIN" || return 1; rm -f "$candidate"
 if ! managed_restart; then
  command install -m 755 "$snap/sing-box.bin" "$BIN"; systemctl restart sing-box || :; argo_restore_snapshot "$snap" || :
  err "$(L '更新失败，已恢复原二进制' 'Update failed; original binary restored')"; return 1
 fi
 ok "$(L '更新完成，请检查客户端连接' 'Updated; verify client connectivity')"
}
service_healthy(){ sleep 2; systemctl is-active --quiet sing-box; }
update_auto(){
 check_owned || return 1
 local current new
 current=$("$BIN" version | awk 'NR==1{print $3}'); new=$(latest) || return 1
 [[ $current == "$new" ]] || apply_update "$new"
}
configure_auto(){ need_root; say '1 启用每周自动更新  2 关闭' '1 Enable weekly automatic updates  2 Disable'; read -r -p '> ' x
 if [[ $x == 1 ]]; then
 check_owned || return 1
 warn "$(L '自动更新会短暂中断服务；请保留备份' 'Automatic updates briefly interrupt service; retain backups')"
 cat >"$SYSTEMD_DIR/singbox-v2-update.service" <<EOF
[Unit]
Description=sing-box v2 weekly update
After=network-online.target
[Service]
Type=oneshot
ExecStart=/bin/bash $MANAGER_BIN --auto-update
EOF
 cat >"$SYSTEMD_DIR/singbox-v2-update.timer" <<'EOF'
[Unit]
Description=sing-box v2 weekly update timer
[Timer]
OnCalendar=Sun *-*-* 04:00:00
RandomizedDelaySec=15min
Persistent=true
[Install]
WantedBy=timers.target
EOF
 command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN"; systemctl daemon-reload; systemctl enable --now singbox-v2-update.timer
 elif [[ $x == 2 ]]; then systemctl disable --now singbox-v2-update.timer 2>/dev/null || :; fi; }
ipcheck(){ notice; confirm "$(L '访问 ipinfo.io 检查 IP 并保存本地报告？' 'Query ipinfo.io and save the IP report locally?')" || return 0; local stamp path; stamp=$(date +%Y%m%d-%H%M%S); path="$REPORT/ip-$stamp.json"; curl -4fsSL --max-time 20 https://ipinfo.io/json >"$path" || { rm -f "$path"; err "$(L 'IP 检测失败' 'IP lookup failed')"; return 1; }; chmod 600 "$path"; python3 -m json.tool "$path"; find "$REPORT" -type f -mtime +30 -delete; say "报告：${path}；不是风险或解锁报告" "Report: $path; not a reputation/unblocking test"; }
netcheck(){ local stamp path; stamp=$(date +%Y%m%d-%H%M%S); path="$REPORT/net-$stamp.txt"; { echo "date=$(date -Is)"; echo 'route:'; ip route get 1.1.1.1; echo 'DNS:'; getent ahostsv4 github.com | sed -n '1,3p'; echo 'HTTP:'; curl -4 -o /dev/null -sS --max-time 15 -w 'github_https_code=%{http_code} connect=%{time_connect}s total=%{time_total}s\n' https://github.com || :; echo 'TCP listeners:'; ss -lnt '( sport = :443 )'; echo 'UDP listeners:'; ss -lnu '( sport = :443 )'; } | tee "$path"; chmod 600 "$path"; find "$REPORT" -type f -mtime +30 -delete; say '仅为基础连通性，不测三网回程、UDP 丢包或吞吐量' 'Basic connectivity only; no route-back, UDP loss or throughput testing'; }
protocol_port(){
 python3 - "$CONF" "$1" <<'PY'
import json,sys
port=next(i['listen_port'] for i in json.load(open(sys.argv[1]))['inbounds'] if i['type']==sys.argv[2])
assert isinstance(port,int) and 1<=port<=65535
print(port)
PY
}
hy2_diagnostics(){
 check_owned || return 1
 local port details cert key name listener
 port=$(protocol_port hysteria2) || { err "$(L '未找到 HY2 入站' 'No HY2 inbound found')"; return 1; }
 say '---------------- HY2 连接诊断 ----------------' '---------------- HY2 connection checks ----------------'
 if "$BIN" check -c "$CONF"; then ok "$(L '服务端配置检查通过' 'Server configuration check passed')"; else err "$(L '服务端配置无效' 'Server configuration invalid')"; fi
 if systemctl is-active --quiet sing-box; then ok "$(L 'sing-box 服务正在运行' 'sing-box service is active')"; else err "$(L 'sing-box 服务未运行；请查看服务与日志 → 日志（3 → 2） 日志' 'sing-box is not active; inspect Services and logs > Logs (3 > 2) logs')"; fi
 listener=$(ss -H -lun "( sport = :$port )") || return 1
 if [[ -n $listener ]]; then ok "$(L "本机 UDP $port 有监听" "Local UDP $port has a listener")"; else err "$(L "本机 UDP $port 未监听" "No local UDP $port listener")"; fi
 details=$(python3 - "$CONF" <<'PY'
import json,sys
c=next(i for i in json.load(open(sys.argv[1]))['inbounds'] if i['type']=='hysteria2')['tls']
for field in ['certificate_path','key_path','server_name']:print(c[field])
PY
 ) || return 1
 { read -r cert; read -r key; read -r name; } <<<"$details"
 if validate_certificate "$cert" "$key" "$name"; then ok "$(L '证书有效期、名称与私钥匹配检查通过' 'Certificate expiry, name and key matching checks passed')"; else err "$(L '证书检查失败，请检查文件或证书身份' 'Certificate checks failed; inspect files and certificate identity')"; fi
 openssl x509 -in "$cert" -noout -dates -fingerprint -sha256 || return 1
 firewall_audit
 warn "$(L '本机检查不能证明手机到 VPS 的 UDP 可达，也不能证明小火箭已信任证书。' 'Local checks do not prove phone-to-VPS UDP reachability or Shadowrocket certificate trust.')"
 say 'certificate/x509 错误：检查客户端证书信任、SNI 和指纹。' 'certificate/x509 errors: check client certificate trust, SNI and fingerprint.'
 say 'timeout/no recent network activity：检查本机与云防火墙 UDP，换 Wi-Fi/移动网络测试。' 'timeout/no recent network activity: inspect local/provider UDP rules and try another Wi-Fi/mobile network.'
 say 'authentication failed：重新导出、导入节点，核对密码；不要公开节点链接。' 'authentication failed: re-export/import the node and verify password; do not publish the URI.'
 say '请用小火箭实际连接或 URL 测试；普通 ICMP 延迟不能验证 HY2。' 'Use an actual Shadowrocket connection or URL test; ICMP latency does not validate HY2.'
 printf '%s\n' "$(L '只读抓包命令（连接节点时执行；不显示数据包内容）：' 'Read-only packet check while connecting (does not display packet contents):')"
 printf '  sudo timeout 15 tcpdump -nn -i any "udp port %s"\n' "$port"
 say '---------------- 诊断结束 ----------------' '---------------- End of checks ----------------'
}
firewall_audit(){
 if command -v ufw >/dev/null; then
  local rules hy2_port; rules=$(LC_ALL=C ufw status); printf '%s\n' "$rules"
  if [[ -f $META && $(protocol_mode) != 1 && $rules == *'Status: active'* ]]; then
   hy2_port=$(protocol_port hysteria2) || return 1
   grep -Eq "${hy2_port}/udp[[:space:]]+ALLOW" <<<"$rules" || warn "$(L "未检测到 UDP $hy2_port 放行，请检查规则" "UDP $hy2_port allow rule not detected; inspect rules")"
   if [[ $(state hop) == True ]]; then
    grep -F "$(state hop_start):$(state hop_end)/udp" <<<"$rules" | grep -q ALLOW || warn "$(L '未检测到跳跃 UDP 范围放行' 'Hopping UDP range allow rule not detected')"
   fi
  fi
 else warn "$(L '未安装 UFW；请检查 nftables 和云防火墙' 'UFW unavailable; inspect nftables and provider firewall')"; fi
 warn "$(L '云防火墙须在服务商控制台检查' 'Check provider firewall in the hosting console')"
}
status(){ systemctl --no-pager status sing-box 2>&1 | head -25 || :; echo 'TCP:'; ss -ltn '( sport = :443 )'; echo 'UDP:'; ss -lun '( sport = :443 )'; echo 'UFW:'; firewall_audit; echo 'Hop:'; nft list table ip singbox_v2_hop 2>/dev/null || :; }
restore(){
 check_owned || return 1
 local path snap
 find "$BACKUP" -mindepth 1 -maxdepth 1 -type d | sort -r
 read -r -p "$(L '完整备份路径：' 'Full backup directory path: ')" path || return
 path=$(realpath "$path") || return 1
 [[ $path == "$(realpath "$BACKUP")/"* && -f $path/config/config.json && -f $path/sing-box.bin && -f $path/state.json ]] || { err "$(L '备份路径错误' 'Invalid backup path')"; return 1; }
 confirm "$(L '恢复配置并重启？' 'Restore configuration and restart?')" || return 0
 argo_guard || return 1
 snap=$(backup) || return 1
 cp -a "$path/config/." "$(dirname "$CONF")" || return 1; cp "$path/state.json" "$META" || return 1
 command install -m 755 "$path/sing-box.bin" "$BIN" || return 1
 if ! "$BIN" check -c "$CONF" || ! systemctl restart sing-box || ! service_healthy || ! argo_restore_snapshot "$path"; then
  cp -a "$snap/config/." "$(dirname "$CONF")"; cp "$snap/state.json" "$META"
  command install -m 755 "$snap/sing-box.bin" "$BIN"; systemctl restart sing-box || :; argo_restore_snapshot "$snap" || :
  err "$(L '恢复失败，已回滚' 'Restore failed; rolled back')"; return 1
 fi
 # Hopping is host state: avoid restoring metadata claiming rules that are absent.
 systemctl disable --now singbox-v2-hop.service 2>/dev/null || :
 hop_disable
 ok "$(L '配置已恢复；需要跳跃时请重新开启' 'Configuration restored; re-enable hopping if needed')"
}
# Optional fresh-server preparation. No SSH, firewall, kernel or reboot changes.
initialize_server(){
 need_root
 if [[ ! -r $OS_RELEASE ]]; then err "$(L '无法识别操作系统' 'Cannot detect operating system')"; return 1; fi
 # shellcheck source=/dev/null
 . "$OS_RELEASE"
 case "${ID:-}" in
  ubuntu|debian) ;;
  *) err "$(L "只支持 Ubuntu/Debian，当前：${ID:-unknown}" "Ubuntu/Debian only; detected ${ID:-unknown}")"; return 1;;
 esac
 command -v apt-get >/dev/null || { err "$(L '缺少 apt-get' 'apt-get not found')"; return 1; }
 say "系统：${PRETTY_NAME:-$ID}" "System: ${PRETTY_NAME:-$ID}"
 say '本功能将更新 apt 索引、升级已安装软件、安装诊断工具。' 'This updates apt indexes, upgrades installed packages, and installs diagnostic tools.'
 say '不会自动启用 UFW、变更 SSH、修改 BBR 或重启系统。' 'Does not enable UFW, change SSH/BBR, or reboot.'
 warn "$(L '升级可能更改内核、SSH 等软件包；建议先做 VPS 快照并保留控制台。' 'Updates may change kernel/SSH; create a snapshot and retain console access.')"
 confirm "$(L '确认执行新服务器初始化？' 'Initialize this server (including system upgrade)?')" || { say '已取消' Cancelled; return 0; }
 local -a packages=(curl wget nano vim unzip zip tar openssl ca-certificates ufw iproute2 iputils-ping dnsutils traceroute mtr-tiny net-tools netcat-openbsd jq git socat lsof htop python3 bc util-linux nftables)
 # Installing chrony can remove timesyncd; keep an existing active time-sync service.
 if ! systemctl is-active --quiet chrony && ! systemctl is-active --quiet systemd-timesyncd && ! systemctl is-active --quiet ntp && ! systemctl is-active --quiet ntpsec; then packages+=(chrony); fi
 say '更新软件索引...' 'Updating package indexes...'
 apt-get update || { err "$(L '软件索引更新失败' 'Package index update failed')"; return 1; }
 say '升级已安装软件（不会自动执行 full-upgrade）...' 'Upgrading packages (not full-upgrade)...'
 DEBIAN_FRONTEND=noninteractive apt-get upgrade -y || { err "$(L '系统升级失败；请检查 apt/dpkg 状态' 'Upgrade failed; check apt/dpkg status')"; return 1; }
 say '安装基础工具...' 'Installing essential tools...'
 DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}" || { err "$(L '工具安装失败' 'Tool installation failed')"; return 1; }
 say '检测时间同步服务...' 'Checking time synchronization...'
 if command -v timedatectl >/dev/null 2>&1; then timedatectl status --no-pager 2>/dev/null || :; fi
 # Do not forcibly disable an existing time-sync daemon.
 if systemctl is-active --quiet chrony 2>/dev/null; then
  say 'chrony 已运行。' 'chrony is running.'
 elif systemctl is-active --quiet systemd-timesyncd 2>/dev/null || systemctl is-active --quiet ntp 2>/dev/null || systemctl is-active --quiet ntpsec 2>/dev/null; then
  say '其他时间同步服务正在运行，不会强制切换到 chrony。' 'Another time synchronization service is running; not switching.'
 else
  say '尝试启用 chrony 时间同步...' 'Trying to enable chrony...'
  systemctl enable --now chrony 2>/dev/null || warn "$(L 'chrony 未启动，请人工检查' 'chrony did not start; check manually')"
 fi
 say '========== 只读检查 ==========' '========== Read-only checks =========='
 echo 'DNS github.com:'
 getent ahostsv4 github.com | sed -n '1,3p' || say 'DNS 解析失败' 'DNS resolution failed'
 say 'GitHub HTTPS:' 'GitHub HTTPS:'
 curl -4sS -I -L --connect-timeout 8 --max-time 18 -o /dev/null -w 'HTTP %{http_code}\n' https://github.com || warn "$(L 'HTTPS 无法连接' 'HTTPS connection failed')"
 say 'SSH 监听端口（仅查看）：' 'SSH listening ports (read-only):'
 ss -ltnp | grep -E 'sshd|:22[[:space:]]' || say '未识别 sshd 监听，请自行核实实际 SSH 端口' 'Could not identify sshd; verify actual SSH port'
 say 'UFW 状态（没有自动开启）：' 'UFW status (not enabled automatically):'
 ufw status verbose || :
 say '系统内核：' Kernel:
 uname -r
 say '如内核或关键服务已升级，请在维护窗口确认后自行决定是否重启。' 'If kernel or essential services were upgraded, plan a manual reboot if necessary.'
 say '新服务器初始化结束。' 'Server initialization complete.'
}

# UFW safety: never assume SSH port 22, and never bypass cloud firewall checks.
detect_ssh_ports(){
 local ports connection_port
 connection_port=$(awk '{print $4}' <<<"${SSH_CONNECTION:-}")
 ports=$(ss -H -lntp | awk '/sshd/ {n=split($4,a,":"); print a[n]}' | sort -nu)
 if [[ -z $ports ]] && command -v sshd >/dev/null; then ports=$(sshd -T 2>/dev/null | awk '$1=="port"{print $2}' | sort -nu); fi
 if valid_port "$connection_port"; then ports=$(printf '%s\n%s\n' "$ports" "$connection_port" | sed '/^$/d' | sort -nu); fi
 SSH_PORTS=$ports
 printf '%s\n' "$(L '识别到 SSH 端口（请确认）：' 'Detected SSH ports (verify): ')$ports"
}
firewall(){
 need_root
 say '1 安装 UFW  2 开启  3 关闭  4 查看状态  5 放行端口  6 删除规则  0 返回' '1 Install UFW  2 Enable  3 Disable  4 Status  5 Allow port  6 Delete rule  0 Back'
 local choice port proto
 read -r -p '> ' choice || return
 case "$choice" in
 1) confirm "$(L '安装 UFW？' 'Install UFW?')" && apt-get update && apt-get install -y ufw ;;
 2)
   require_cmd ufw || return
   say '当前 SSH 监听信息（必须人工核实）：' 'SSH listener information (VERIFY manually):'
   detect_ssh_ports
   read -r -p "$(L '输入当前 SSH TCP 端口（请核实云控制台/sshd 设置）：' 'Enter verified SSH TCP port: ')" port
   port=${port:-${SSH_PORTS:-}}
   valid_port "$port" || { err "$(L 'SSH 端口无效' 'Invalid SSH port')"; return 1; }
   warn "$(L '如果 SSH 端口判断错误，开启 UFW 可能导致远程连接断开！请保留 VPS 控制台访问。' 'Wrong SSH port may lock you out. Keep VPS console access.')"
   say '将放行 SSH 端口与当前部署节点的 443 端口。' 'Will allow SSH and relevant deployed 443 ports.'
   confirm "$(L '确认开启 UFW 防火墙？' 'Enable UFW now?')" || return 0
   ufw allow "$port/tcp" || return 0
   local detected
   while read -r detected; do [[ -z $detected ]] || ufw allow "$detected/tcp" || return 1; done <<<"$SSH_PORTS"
   if [[ -f $META ]]; then
    case "$(protocol_mode)" in 1) ufw allow 443/tcp;; 2) ufw allow 443/udp;; 3) ufw allow 443/tcp; ufw allow 443/udp;; esac
   fi
   if [[ -f $META && $(state hop) == True ]]; then ufw allow "$(state hop_start):$(state hop_end)/udp" || return 1; fi
   ufw default deny incoming; ufw default allow outgoing; ufw --force enable
   warn "$(L '如有 HY2 跳跃或云防火墙，需另外确认规则。' 'Check HY2 hopping and provider firewall rules separately.')" ;;
 3) require_cmd ufw && confirm "$(L '关闭 UFW 会降低保护，确定？' 'Disable UFW and reduce protection?')" && ufw --force disable ;;
 4) require_cmd ufw && ufw status verbose ;;
 5) require_cmd ufw || return
    read -r -p "$(L '端口：' 'Port: ')" port; valid_port "$port" || return 1
    read -r -p "$(L '协议 (tcp/udp)：' 'Protocol (tcp/udp): ')" proto; [[ $proto == tcp || $proto == udp ]] || return 1
    confirm "$(L "放行 $port/${proto}？" "Allow $port/$proto?")" && ufw allow "$port/$proto" ;;
 6) require_cmd ufw || return; ufw status numbered
    read -r -p "$(L '规则编号：' 'Rule number: ')" port; [[ $port =~ ^[0-9]+$ ]] || return 1
    confirm "$(L '删除指定规则？确认不会影响 SSH！' 'Delete rule? Ensure SSH stays reachable!')" && ufw --force delete "$port" ;;
 0) return;; *) err "$(L '无效选择' 'Invalid choice')";;
 esac
 return 0
}
service_manager(){
 say '1 状态  2 启动  3 重启  4 停止  5 开机自启  6 配置检查  0 返回' '1 Status  2 Start  3 Restart  4 Stop  5 Enable at boot  6 Config check  0 Back'
 local x; read -r -p '> ' x || return
 case "$x" in
 1) status;; 2) check_owned && confirm "$(L '启动 sing-box？' 'Start sing-box?')" && systemctl start sing-box;;
 3) check_owned && confirm "$(L '重启 sing-box？' 'Restart sing-box?')" && "$BIN" check -c "$CONF" && systemctl restart sing-box;;
 4) check_owned && warn "$(L '直连节点将断开连接；Argo 请单独管理' 'Direct nodes will disconnect; manage Argo separately')" && confirm "$(L '停止 sing-box？' 'Stop sing-box?')" && systemctl stop sing-box;;
 5) check_owned && confirm "$(L '设置开机自启？' 'Enable sing-box at boot?')" && systemctl enable sing-box;;
 6) check_owned && "$BIN" check -c "$CONF";; 0) return;; *) err "$(L '无效选择' 'Invalid choice')";; esac
 return 0
}
traffic(){
 say 'vnStat 统计 VPS 网卡流量，不能区分 Reality/HY2；历史数据从安装后开始。' 'vnStat tracks VPS interface traffic, NOT Reality/HY2 separately. History starts when installed.'
 say '1 安装 vnStat  2 今日  3 本月  4 实时网速  5 历史汇总  0 返回' '1 Install vnStat  2 Today  3 Monthly  4 Live  5 History  0 Back'
 local x; read -r -p '> ' x || return
 case "$x" in
 1) confirm "$(L '安装 vnStat？' 'Install vnStat?')" && apt-get update && apt-get install -y vnstat && systemctl enable --now vnstat;;
 2) require_cmd vnstat && vnstat -d;; 3) require_cmd vnstat && vnstat -m;;
 4) require_cmd vnstat && vnstat -l;; 5) require_cmd vnstat && vnstat;; 0) return;; *) err "$(L '无效选择' 'Invalid choice')";; esac
 return 0
}
shadowrocket_qr(){
 check_owned || return 1
 if ! command -v qrencode >/dev/null; then
  say '安装二维码工具 qrencode...' 'Installing qrencode...'
  apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y qrencode || return 1
 fi
 exports >/dev/null || return 1
 warn "$(L '二维码包含节点凭据，请勿公开。HY2 自签名节点仍需配置信任证书。' 'QR codes contain node credentials; keep them private. Self-signed HY2 still requires certificate trust.')"
 local link name count=0
 while IFS= read -r link; do
  [[ -n $link ]] || continue
  name=$(printf '%s' "$link" | python3 -c 'import sys,urllib.parse; u=urllib.parse.urlsplit(sys.stdin.read()); print(urllib.parse.unquote(u.fragment) if u.fragment else dict(urllib.parse.parse_qsl(u.query)).get("remarks","Shadowrocket"))') || return 1
  printf '%s\n' '----------------------------------------------'
  printf '%s%s%s\n' "$YELLOW" "$name" "$RESET"
  # Feed credentials via stdin; keep the QR high-contrast for phone cameras.
  printf '%s' "$link" | qrencode -t ANSIUTF8 -m 2 || return 1
  count=$((count+1))
 done < "$BASE/shadowrocket-native-nodes.txt"
 printf '%s\n' '----------------------------------------------'
 (( count > 0 )) || { err "$(L '没有可生成二维码的节点' 'No nodes available for QR codes')"; return 1; }
}

subscription(){
 check_owned || return
 warn "$(L '仅生成本地订阅文件；不会开启公开的 HTTP/HTTPS 订阅服务。' 'Local subscription files only; no public HTTP/HTTPS service will be started.')"
 exports || return 1
 say '已生成各客户端格式；请核实自签名信任。本地订阅文件不等于在线订阅网址。' 'Client formats exported; verify self-signed trust. Local subscription files are not hosted URLs.'
}

# Argo is an add-on to an existing managed deployment; its loopback origin is separate.
argo_state(){
 python3 - "$BASE/argo-state.json" "$1" <<'PY'
import json,sys
print(json.load(open(sys.argv[1])).get(sys.argv[2],''))
PY
}
argo_guard(){
 local unit marker expected
 for unit in skybyte-argo-node.service skybyte-argo-tunnel.service; do
  marker="Description=SKYBYTE managed $unit"
  if [[ $unit == skybyte-argo-node.service ]]; then expected="ExecStart=$BIN run -c $BASE/argo-server.json"; else expected="ExecStart=/bin/bash $MANAGER_BIN --argo-run"; fi
  if [[ -e $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]]; then
   if [[ ! -f $SYSTEMD_DIR/$unit || -L $SYSTEMD_DIR/$unit ]] || ! grep -Fxq "$marker" "$SYSTEMD_DIR/$unit" || ! grep -Fxq "$expected" "$SYSTEMD_DIR/$unit"; then err "$(L 'Argo 服务归属异常，拒绝修改' 'Argo unit ownership mismatch; refusing changes')"; return 1; fi
  fi
 done
 for unit in argo-state.json argo-server.json argo-empty.yml argo.token cloudflared; do
  [[ ! -L $BASE/$unit ]] || { err "$(L 'Argo 文件是符号链接，拒绝修改' 'Argo file is a symlink; refusing changes')"; return 1; }
 done
}
download_cloudflared(){
 local target=$1 tmp arch tag asset digest
 case "$(uname -m)" in x86_64) arch=amd64;; aarch64|arm64) arch=arm64;; *) return 1;; esac
 tmp=$(mktemp -d) || return 1
 curl -fsSL --retry 2 --max-time 30 https://api.github.com/repos/cloudflare/cloudflared/releases/latest -o "$tmp/release.json" || { rm -rf "$tmp"; return 1; }
 tag=$(python3 -c 'import json,sys; r=json.load(open(sys.argv[1])); assert not r["prerelease"] and not r["draft"]; print(r["tag_name"])' "$tmp/release.json") || { rm -rf "$tmp"; return 1; }
 [[ $tag =~ ^[0-9]{4}\.[0-9]+\.[0-9]+$ ]] || { rm -rf "$tmp"; return 1; }
 asset="cloudflared-linux-$arch"
 digest=$(python3 - "$tmp/release.json" "$asset" <<'PY'
import json,sys
asset=next(a for a in json.load(open(sys.argv[1]))['assets'] if a['name']==sys.argv[2])
digest=asset.get('digest') or ''; assert digest.startswith('sha256:')
print(digest.split(':',1)[1])
PY
 ) || { rm -rf "$tmp"; return 1; }
 if [[ ! $digest =~ ^[a-fA-F0-9]{64}$ ]] ||
    ! curl -fsSL --retry 2 --max-time 180 "https://github.com/cloudflare/cloudflared/releases/download/$tag/$asset" -o "$tmp/binary" ||
    ! printf '%s  %s\n' "$digest" "$tmp/binary" | sha256sum -c - >/dev/null; then rm -rf "$tmp"; return 1; fi
 command install -m 755 "$tmp/binary" "$target"
 local rc=$?; rm -rf "$tmp"; return "$rc"
}
argo_validate_domain(){
 python3 - "$1" <<'PY'
import re,sys
name=sys.argv[1]
assert len(name)<=253 and '.' in name and not re.fullmatch(r'[0-9.]+',name)
assert all(re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?',p) for p in name.split('.'))
PY
}
argo_write_config(){
 python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import json,pathlib,secrets,sys,uuid
root,mode,domain,port,name=sys.argv[1:];root=pathlib.Path(root)
assert mode in ('quick','named') and 1024<=int(port)<=65535
uid=str(uuid.uuid4());path='/'+secrets.token_hex(16)
config={'log':{'level':'warn'},'inbounds':[{'type':'vless','tag':'argo-ws','listen':'127.0.0.1','listen_port':int(port),'users':[{'uuid':uid}], 'transport':{'type':'ws','path':path}}], 'outbounds':[{'type':'direct','tag':'direct'}], 'route':{'final':'direct'}}
state={'mode':mode,'domain':domain,'port':int(port),'path':path,'node_name':name,'connected':False}
(root/'argo-server.json').write_text(json.dumps(config,indent=2))
(root/'argo-state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
(root/'argo-empty.yml').write_text('{}\n')
PY
}
argo_setup_units(){
 argo_guard || return 1
 if [[ -L $MANAGER_BIN ]]; then err "$(L '管理脚本不能是符号链接' 'Manager executable cannot be a symlink')"; return 1; fi
 if [[ -e $MANAGER_BIN ]] && ! grep -q '^# SKYBYTE Manager V2.1 community manager;' "$MANAGER_BIN"; then err "$(L '管理脚本路径被其他程序占用' 'Manager executable path is occupied')"; return 1; fi
 if [[ ! $SCRIPT_PATH -ef $MANAGER_BIN ]]; then command install -m 700 "$SCRIPT_PATH" "$MANAGER_BIN" || return 1; fi
 cat >"$SYSTEMD_DIR/skybyte-argo-node.service" <<EOF
[Unit]
Description=SKYBYTE managed skybyte-argo-node.service
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=$BIN run -c $BASE/argo-server.json
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
 cat >"$SYSTEMD_DIR/skybyte-argo-tunnel.service" <<EOF
[Unit]
Description=SKYBYTE managed skybyte-argo-tunnel.service
After=network-online.target skybyte-argo-node.service
Requires=skybyte-argo-node.service
[Service]
ExecStart=/bin/bash $MANAGER_BIN --argo-run
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=15
[Install]
WantedBy=multi-user.target
EOF
 systemctl daemon-reload
}
argo_wait(){
 local attempt
 for ((attempt=0; attempt<30; attempt++)); do
  [[ $(argo_state connected) == True ]] && return 0
  systemctl is-active --quiet skybyte-argo-tunnel.service || return 1
  sleep 1
 done
 return 1
}
argo_install(){
 need_root; check_owned || return 1; argo_guard || return 1
 local mode=$1 port name domain='' token='' stage snap file
 [[ $mode == quick || $mode == named ]] || return 1
 for file in argo-state.json argo-server.json argo.token argo-empty.yml cloudflared; do
  [[ ! -e $BASE/$file ]] || { err "$(L '已有 Argo 文件；请先用 Argo 管理入口卸载' 'Argo files exist; remove via Argo controls first')"; return 1; }
 done
 for file in skybyte-argo-node.service skybyte-argo-tunnel.service; do
  [[ ! -e $SYSTEMD_DIR/$file ]] || return 1
  if systemctl list-unit-files "$file" --no-legend 2>/dev/null | grep -q "$file"; then err "$(L '已有同名 Argo 服务，拒绝覆盖' 'An Argo service with this name exists; refusing overwrite')"; return 1; fi
 done
 warn "$(L '新增 VLESS+WS 隧道节点；Cloudflare 终止公网 TLS，可处理隧道流量。临时隧道仅供测试，重启会换地址。' 'Adds a VLESS+WS node. Cloudflare terminates public TLS and can process tunnel traffic. Quick tunnels are for testing; restarts change the hostname.')"
 confirm "$(L '安装所选 Argo 模式？' 'Install selected Argo mode?')" || return 0
 read -r -p "$(L '本机 WS 端口 [8080]：' 'Local WS port [8080]: ')" port || return 1
 port=${port:-8080}; valid_port "$port" && (( 10#$port>=1024 )) || return 1; port=$((10#$port))
 if ss -H -ltn "( sport = :$port )" | grep -q .; then err "$(L '端口已占用' 'Port is occupied')"; return 1; fi
 name=$(choose_node_name) || return 1
 if [[ $mode == named ]]; then
  read -r -p "$(L 'Cloudflare 固定公开域名：' 'Cloudflare published hostname: ')" domain || return 1
  argo_validate_domain "$domain" || { err "$(L '域名格式无效' 'Invalid hostname')"; return 1; }
  say "请在 Cloudflare 控制台将该域名的 HTTP 服务指向 http://127.0.0.1:${port}；需要支持 WebSocket，不能要求交互式 Access 登录。" "In Cloudflare, route this hostname to HTTP http://127.0.0.1:$port with WebSocket support; interactive Access login is incompatible."
  read -rs -p "$(L 'Tunnel Token（隐藏输入）：' 'Tunnel Token (hidden input): ')" token || return 1; printf '\n'
  if [[ ! $token =~ ^[a-zA-Z0-9+/=_-]+$ ]] || (( ${#token}<20 || ${#token}>4096 )); then err "$(L 'Token 格式无效' 'Invalid token format')"; return 1; fi
 fi
 snap=$(backup) || return 1
 stage=$(mktemp -d "$BASE/.argo-install.XXXXXX") || return 1
 if ! argo_write_config "$stage" "$mode" "$domain" "$port" "$name" || ! "$BIN" check -c "$stage/argo-server.json" || ! download_cloudflared "$stage/cloudflared"; then rm -rf "$stage"; return 1; fi
 if [[ $mode == named ]]; then printf '%s' "$token" >"$stage/argo.token"; token=''; fi
 chmod 600 "$stage"/argo-*; chmod 755 "$stage/cloudflared"
 for file in argo-state.json argo-server.json argo-empty.yml cloudflared argo.token; do
  if [[ -f $stage/$file ]]; then mv "$stage/$file" "$BASE/$file" || { rm -rf "$stage"; return 1; }; fi
 done
 rmdir "$stage"
 if ! argo_setup_units || ! systemctl enable --now skybyte-argo-node.service || ! systemctl enable --now skybyte-argo-tunnel.service; then
  err "$(L 'Argo 启动失败；保留配置供诊断，原节点配置未改变' 'Argo startup failed; config retained for diagnosis. Existing node config was not changed')"; return 1
 fi
 if ! argo_wait; then warn "$(L '隧道尚未注册连接；请使用 Argo 状态检查 Token、路由或出站网络。' 'Tunnel not registered yet; use Argo status to check token, route or outbound connectivity.')"; return 1; fi
 ok "$(L 'Argo 已启动；安装前备份：' 'Argo started; pre-install backup: ')$snap"
 exports
}
argo_run(){
 # Worker mode never takes the interactive manager lock. Only state/exports use their own locks.
 python3 - "$BASE" "$MANAGER_BIN" <<'PY'
import fcntl,json,os,pathlib,re,signal,subprocess,sys,tempfile
base=pathlib.Path(sys.argv[1]);runner=sys.argv[2];state_path=base/'argo-state.json'
def update(**fields):
 with open(base/'argo-state.lock','a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  if not state_path.exists():return
  state=json.loads(state_path.read_text());state.update(fields)
  with tempfile.NamedTemporaryFile(mode='w',dir=base,delete=False) as tmp:
   json.dump(state,tmp,ensure_ascii=False,indent=2);name=tmp.name
  os.chmod(name,0o600);os.replace(name,state_path)
def sync():
 try:subprocess.run(['/bin/bash',runner,'--argo-export'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20,check=False)
 except (OSError,subprocess.TimeoutExpired):pass
state=json.loads(state_path.read_text());mode=state['mode']
assert mode in ('quick','named')
common=[str(base/'cloudflared'),'tunnel','--config',str(base/'argo-empty.yml'),'--no-autoupdate','--grace-period','5s','--protocol','auto']
if mode=='quick':
 update(domain='',connected=False,last_error='');command=common+['--url',f"http://127.0.0.1:{state['port']}"]
else:
 assert (base/'argo.token').is_file();update(connected=False,last_error='')
 command=common+['run','--token-file',str(base/'argo.token')]
sync()
# Do not inherit incidental shell tokens/configuration from the interactive environment.
env={k:v for k,v in os.environ.items() if not k.startswith(('TUNNEL_','CF_'))}
proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env=env)
stopping=False;hostname=state.get('domain','') if mode=='named' else '';registered=False
pattern=re.compile(r'https://([a-z0-9]+(?:-[a-z0-9]+)*\.trycloudflare\.com)(?![a-z0-9.-])')
def stop(*_):
 global stopping
 stopping=True;proc.terminate()
 try:proc.wait(timeout=7)
 except subprocess.TimeoutExpired:proc.kill()
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
try:
 for line in proc.stdout:
  match=pattern.search(line)
  if mode=='quick' and match:hostname=match.group(1)
  lower=line.lower()
  if 'invalid tunnel token' in lower or 'unauthorized' in lower: update(last_error='token_or_account')
  elif 'timeout' in lower or 'failed to dial' in lower or 'network is unreachable' in lower: update(last_error='outbound_network')
  elif 'certificate' in lower and ('error' in lower or 'failed' in lower): update(last_error='tls')
  if 'Registered tunnel connection' in line:registered=True
  if registered and hostname:
   update(domain=hostname,connected=True,last_error='');sync();registered=False
 # Suppress raw cloudflared output: it can include operational/account information.
finally:
 if proc.poll() is None:stop()
 update(connected=False,**({'domain':''} if mode=='quick' else {}));sync()
rc=proc.wait();sys.exit(0 if stopping else rc if rc>0 else 1)
PY
}
argo_status(){
 [[ -f $BASE/argo-state.json ]] || { say '尚未配置 Argo 隧道。' 'Argo is not configured.'; return 0; }
 local mode domain port connected
 say "最近错误类别：$(argo_state last_error)" "Last error category: $(argo_state last_error)"
 mode=$(argo_state mode); domain=$(argo_state domain); port=$(argo_state port); connected=$(argo_state connected)
 say "模式：${mode}；公开域名：${domain:-尚未分配}；本机端口：${port}；已注册：$connected" "Mode: $mode; hostname: ${domain:-not assigned}; local port: $port; registered: $connected"
 if systemctl is-active --quiet skybyte-argo-node.service; then ok "$(L 'Argo WS 服务运行中' 'Argo WS origin active')"; else err "$(L 'Argo WS 服务未运行' 'Argo WS origin inactive')"; fi
 if systemctl is-active --quiet skybyte-argo-tunnel.service; then ok "$(L 'Argo 隧道服务运行中' 'Argo tunnel worker active')"; else err "$(L 'Argo 隧道服务未运行' 'Argo tunnel worker inactive')"; fi
 warn "$(L '服务运行不代表客户端可达；固定模式还需核对 Cloudflare 公开路由和客户端 SNI/WS 路径。' 'Active services do not prove client connectivity; verify published routes and client SNI/WS paths.')"
}
argo_clear_ready(){
 [[ -f $BASE/argo-state.json ]] || return 0
 python3 - "$BASE" <<'PY'
import fcntl,json,os,pathlib,tempfile,sys
base=pathlib.Path(sys.argv[1]);p=base/'argo-state.json'
with open(base/'argo-state.lock','a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX);s=json.loads(p.read_text());s['connected']=False
 if s['mode']=='quick':s['domain']=''
 with tempfile.NamedTemporaryFile(mode='w',dir=base,delete=False) as f:json.dump(s,f,indent=2);tmp=f.name
 os.chmod(tmp,0o600);os.replace(tmp,p)
PY
}
argo_stop(){
 argo_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-argo-tunnel.service ]]; then systemctl stop skybyte-argo-tunnel.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-node.service ]]; then systemctl stop skybyte-argo-node.service || return 1; fi
 argo_clear_ready
}
argo_start(){
 [[ -f $BASE/argo-state.json ]] || return 1
 argo_setup_units || return 1
 "$BIN" check -c "$BASE/argo-server.json" || return 1
 systemctl start skybyte-argo-node.service || return 1
 systemctl start skybyte-argo-tunnel.service || return 1
 argo_wait || { err "$(L '隧道连接未就绪，请检查状态' 'Tunnel connection not ready; inspect status')"; return 1; }
 exports
}
argo_remove_internal(){
 argo_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-argo-tunnel.service ]]; then systemctl disable --now skybyte-argo-tunnel.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-argo-node.service ]]; then systemctl disable --now skybyte-argo-node.service || return 1; fi
 for file in argo-state.json argo-server.json argo-empty.yml argo.token cloudflared; do rm -f -- "$BASE/$file"; done
 rm -f -- "$SYSTEMD_DIR/skybyte-argo-node.service" "$SYSTEMD_DIR/skybyte-argo-tunnel.service"
 systemctl daemon-reload
}
argo_remove(){
 [[ -f $BASE/argo-state.json ]] || return 0
 argo_guard || return 1
 confirm "$(L '备份后卸载本机 Argo 附加节点？Cloudflare 账户内的隧道和 DNS 不会删除。' 'Back up and remove the local Argo add-on? Cloudflare tunnel/DNS records will not be deleted.')" || return 0
 local snap; snap=$(backup) || return 1
 argo_remove_internal || return 1
 ok "$(L 'Argo 已卸载；备份：' 'Argo removed; backup: ')$snap"
 exports
}
argo_restore_snapshot(){
 local path=$1 file
 argo_guard || return 1
 if [[ ! -f $path/argo-state.json ]]; then
  [[ ! -f $BASE/argo-state.json ]] || argo_remove_internal || return 1
  return 0
 fi
 [[ -f $path/argo-server.json && -f $path/cloudflared.bin ]] || return 1
 "$BIN" check -c "$path/argo-server.json" || return 1
 argo_stop || return 1
 for file in argo-state.json argo-server.json argo-empty.yml argo.token; do
  if [[ -f $path/$file ]]; then cp "$path/$file" "$BASE/$file" || return 1; chmod 600 "$BASE/$file"; else rm -f -- "$BASE/$file"; fi
 done
 command install -m 755 "$path/cloudflared.bin" "$BASE/cloudflared" || return 1
 argo_clear_ready || return 1
 argo_setup_units || return 1
 systemctl enable --now skybyte-argo-node.service || return 1
 systemctl enable --now skybyte-argo-tunnel.service || return 1
}
argo_manager(){
 local choice
 say '1 临时隧道  2 固定隧道  3 状态  4 启动  5 停止  6 重启  7 刷新节点  8 卸载 Argo  0 返回' '1 Quick  2 Named  3 Status  4 Start  5 Stop  6 Restart  7 Refresh nodes  8 Remove Argo  0 Back'
 read -r -p '> ' choice || return 0
 case $choice in
  1) argo_install quick;; 2) argo_install named;; 3) argo_status;; 4) argo_start;;
  5) argo_stop && exports;; 6) argo_stop && argo_start;; 7) exports;; 8) argo_remove;; 0) return 0;; *) err "$(L '无效选项' 'Invalid choice')"; return 1;;
 esac
}

uninstall_manager(){
 need_root
 check_owned || return 1
 argo_guard || return 1
 local unit snap file description managed_certs
 unit="$SYSTEMD_DIR/sing-box.service"
 # Metadata alone is insufficient: refuse to remove another service or a replacement binary symlink.
 if [[ ! -f $unit || -L $unit || -L $BIN || -L $CONF || -L $META ]] ||
    ! grep -Fxq 'Description=sing-box (managed by singbox-v2)' "$unit" ||
    ! grep -Fxq "ExecStart=$BIN run -c $CONF" "$unit"; then
  err "$(L '服务不属于本工具或已被修改，拒绝卸载' 'Service is not owned by this manager or has changed; refusing uninstall')"; return 1
 fi
 for file in singbox-v2-update.service singbox-v2-update.timer singbox-v2-hop.service; do
  case $file in
   singbox-v2-update.service) description='Description=sing-box v2 weekly update';;
   singbox-v2-update.timer) description='Description=sing-box v2 weekly update timer';;
   singbox-v2-hop.service) description='Description=singbox V2 HY2 IPv4 port hopping';;
  esac
  if [[ -e $SYSTEMD_DIR/$file || -L $SYSTEMD_DIR/$file ]]; then
   if [[ -L $SYSTEMD_DIR/$file ]] || ! grep -Fxq "$description" "$SYSTEMD_DIR/$file"; then
    err "$(L "附属服务 $file 已修改，拒绝卸载" "Auxiliary unit $file has changed; refusing uninstall")"; return 1
   fi
  fi
 done
 warn "$(L '卸载将停止所有节点，删除本工具的服务、二进制、节点配置及订阅文件。' 'Uninstall stops all nodes and removes managed services, binary, node config and subscription exports.')"
 say '先自动备份并保留备份；外部证书、UFW 规则、BBR 设置和 vnStat 均保留。' 'A backup is created and retained; external certificates, UFW rules, BBR settings and vnStat are kept.'
 confirm "$(L '确认卸载 SKYBYTE Manager 与托管 sing-box？' 'Uninstall SKYBYTE Manager and managed sing-box?')" || return 0
 managed_certs=$(python3 - "$META" "$CONF" <<'PY'
import json,sys,pathlib
s=json.load(open(sys.argv[1])); root=pathlib.Path(sys.argv[2]).parent
paths=s.get('managed_certificates',[])
# Legacy generated self-signed certificates have a known managed pathname and mode.
if 'managed_certificates' not in s and s.get('cert_mode')=='1' and s.get('cert_path')==str(root/'hy2-selfsigned.crt'):
 paths=[str(root/'hy2-selfsigned.crt'),str(root/'hy2-selfsigned.key')]
allowed={'hy2-selfsigned.crt','hy2-selfsigned.key','hy2-backup.crt','hy2-backup.key'}
for value in paths:
 p=pathlib.Path(value)
 if p.parent==root and p.name in allowed: print(p)
PY
 ) || return 1
 snap=$(backup) || { err "$(L '备份失败，已取消卸载' 'Backup failed; uninstall cancelled')"; return 1; }
 if [[ -f $BASE/argo-state.json ]]; then argo_remove_internal || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-update.timer ]]; then systemctl disable --now singbox-v2-update.timer || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-update.service ]]; then systemctl stop singbox-v2-update.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-hop.service ]]; then systemctl disable --now singbox-v2-hop.service || return 1; fi
 if [[ -f $SYSTEMD_DIR/singbox-v2-hop.service ]] && command -v nft >/dev/null && nft list table ip singbox_v2_hop >/dev/null 2>&1; then nft delete table ip singbox_v2_hop || return 1; fi
 systemctl disable --now sing-box.service || return 1
 # Remove explicit managed files only; never recursively delete user configuration directories.
 rm -f -- "$unit" "$SYSTEMD_DIR/singbox-v2-update.service" "$SYSTEMD_DIR/singbox-v2-update.timer" "$SYSTEMD_DIR/singbox-v2-hop.service" "$BIN" "$CONF"
 while IFS= read -r file; do if [[ -n $file ]]; then rm -f -- "$file"; fi; done <<<"$managed_certs"
 for file in state.json language.conf hop.nft nodes.txt subscription-base64.txt v2rayn-nodes.txt v2rayn-subscription.txt shadowrocket-nodes.txt shadowrocket-subscription.txt shadowrocket-native-nodes.txt shadowrocket-native-subscription.txt sing-box-client.json clash-verge.yaml outbounds.json mihomo-proxies.yaml subscription-notes.txt hy2-client-ca.pem hy2-client-ca.cer hy2-client-ca.mobileconfig; do rm -f -- "$BASE/$file"; done
 # Remove executable copies only when they are identifiable manager scripts.
 for file in "$MANAGER_BIN" "$MANAGER_LIB"; do
  if [[ -f $file && ! -L $file ]] && grep -q '^# SKYBYTE Manager V2.1 community manager;' "$file"; then rm -f -- "$file"; fi
 done
 systemctl daemon-reload || return 1
 ok "$(L '卸载完成；备份保存在：' 'Uninstalled; backup retained at: ')$snap"
 warn "$(L 'UFW 放行规则、BBR 设置和备份中的私钥仍保留，请按需要人工管理。' 'UFW allow rules, BBR settings and backup private keys remain; manage them as needed.')"
}
action_failed(){ err "$(L '操作失败；请检查上面的输出' 'Operation failed; inspect the output above')"; }
sub_menu(){
 local group=$1 choice
 MAIN_ACTION=""
 printf '%s\n----------------------------------------------\n' "$GREEN"
 case $group in
  1)
   say ' 1. 安装 Reality + Vision' ' 1. Install Reality + Vision'
   say ' 2. 安装 Hysteria2' ' 2. Install Hysteria2'
   say ' 3. 安装双协议' ' 3. Install both protocols'
   say ' 4. Argo 临时 / 固定隧道管理' ' 4. Argo Quick / Named Tunnel controls'
   ;;
  2)
   say ' 1. 查看节点与各客户端格式' ' 1. View nodes and client formats'
   say ' 2. 导出本地订阅' ' 2. Export local subscriptions'
   say ' 3. 自定义节点名称' ' 3. Customize node names'
   say ' 4. 小火箭节点二维码' ' 4. Shadowrocket node QR codes'
   ;;
  3)
   say ' 1. sing-box 状态与启停' ' 1. sing-box status and controls'
   say ' 2. 查看 sing-box 日志' ' 2. View sing-box logs'
   say ' 3. Argo 隧道状态' ' 3. Argo tunnel status'
   ;;
  4)
   say ' 1. 新服务器初始化' ' 1. Initialize new server'
   say ' 2. UFW 防火墙管理' ' 2. UFW controls'
   say ' 3. 检查防火墙规则' ' 3. Audit firewall rules'
   say ' 4. 启用 BBR + FQ' ' 4. Enable BBR + FQ'
   say ' 5. HY2 端口跳跃' ' 5. HY2 port hopping'
   say ' 6. VPS 流量统计（vnStat）' ' 6. VPS traffic (vnStat)'
   say ' 7. IP 信息' ' 7. IP information'
   say ' 8. 基础网络诊断' ' 8. Basic network checks'
   say ' 9. HY2 / 小火箭连接诊断' ' 9. HY2 / Shadowrocket checks'
   ;;
  5)
   say ' 1. 手动更新 sing-box' ' 1. Update sing-box'
   say ' 2. 每周自动更新' ' 2. Weekly automatic updates'
   say ' 3. 备份配置' ' 3. Back up configuration'
   say ' 4. 恢复配置' ' 4. Restore configuration'
   ;;
  6)
   say ' 1. 切换语言' ' 1. Change language'
   say ' 2. 法律与隐私声明' ' 2. Legal and privacy notice'
   say ' 3. 卸载 SKYBYTE Manager / sing-box' ' 3. Uninstall SKYBYTE Manager / sing-box'
   ;;
 esac
 say ' 0. 返回主菜单' ' 0. Back to main menu'
 printf -- '----------------------------------------------%s\n' "$RESET"
 read -r -p "$(L '请选择：' 'Select: ')" choice || return 1
 case "$group:$choice" in
  1:1) MAIN_ACTION=install_reality;;
  1:2) MAIN_ACTION=install_hy2;;
  1:3) MAIN_ACTION=install_dual;;
  1:4) MAIN_ACTION=argo;;
  2:1) MAIN_ACTION=nodes;;
  2:2) MAIN_ACTION=subscription;;
  2:3) MAIN_ACTION=rename;;
  2:4) MAIN_ACTION=qr;;
  3:1) MAIN_ACTION=service;;
  3:2) MAIN_ACTION=logs;;
  3:3) MAIN_ACTION=argo_status;;
  4:1) MAIN_ACTION=initialize;;
  4:2) MAIN_ACTION=firewall;;
  4:3) MAIN_ACTION=audit;;
  4:4) MAIN_ACTION=bbr;;
  4:5) MAIN_ACTION=hop;;
  4:6) MAIN_ACTION=traffic;;
  4:7) MAIN_ACTION=ip;;
  4:8) MAIN_ACTION=network;;
  4:9) MAIN_ACTION=hy2_check;;
  5:1) MAIN_ACTION=update;;
  5:2) MAIN_ACTION=auto;;
  5:3) MAIN_ACTION=backup;;
  5:4) MAIN_ACTION=restore;;
  6:1) MAIN_ACTION=language;;
  6:2) MAIN_ACTION=notice;;
  6:3) MAIN_ACTION=uninstall;;
  *:0) return 0;; *) err "$(L '无效选项' 'Invalid choice')";;
 esac
}
dispatch_action(){
 case $1 in
 install_reality) install_protocol 1;; install_hy2) install_protocol 2;; install_dual) install_protocol 3;;
 argo) argo_manager;; nodes) exports;; subscription) subscription;; rename) rename_node;; qr) shadowrocket_qr;;
 service) service_manager;; logs) journalctl -u sing-box -n 80 --no-pager;; argo_status) argo_status;;
 initialize) initialize_server;; firewall) firewall;; audit) firewall_audit;; bbr) bbr;; hop) hop;; traffic) traffic;;
 ip) ipcheck;; network) netcheck;; hy2_check) hy2_diagnostics;;
 update) update;; auto) configure_auto;; backup) backup;; restore) restore;;
 language) select_language;; notice) notice;; uninstall) uninstall_manager;;
 esac
}
main(){
 need_root; require_cmd flock
 local group action_status
 while :; do
  printf '%s\n==============================================\n' "$CYAN"
  cat <<'LOGO'
   ███████╗██╗  ██╗██╗   ██╗██████╗ ██╗   ██╗████████╗███████╗
   ██╔════╝██║ ██╔╝╚██╗ ██╔╝██╔══██╗╚██╗ ██╔╝╚══██╔══╝██╔════╝
   ███████╗█████╔╝  ╚████╔╝ ██████╔╝ ╚████╔╝    ██║   █████╗
   ╚════██║██╔═██╗   ╚██╔╝  ██╔══██╗  ╚██╔╝     ██║   ██╔══╝
   ███████║██║  ██╗   ██║   ██████╔╝   ██║      ██║   ███████╗
   ╚══════╝╚═╝  ╚═╝   ╚═╝   ╚═════╝    ╚═╝      ╚═╝   ╚══════╝
                  SKYBYTE Manager V2.1
                Reality · Hysteria2 · VPS
LOGO
  printf '==============================================%s\n' "$RESET"
  printf '%s' "$GREEN"
  say ' 1. 协议安装与 Argo 隧道' ' 1. Protocol installation and Argo tunnels'
  say ' 2. 节点与订阅' ' 2. Nodes and subscriptions'
  say ' 3. 服务与日志' ' 3. Services and logs'
  say ' 4. 服务器与网络' ' 4. Server and network'
  say ' 5. 更新与备份' ' 5. Updates and backups'
  say ' 6. 设置与卸载' ' 6. Settings and uninstall'
  say ' 0. 退出' ' 0. Exit'
  printf '%s' "$RESET"
  printf '%sYouTube: %s%s\n' "$CYAN" "$YOUTUBE" "$RESET"
  read -r -p "$(L '请选择：' 'Select: ')" group || return 0
  [[ $group != 0 ]] || return 0
  case $group in 1|2|3|4|5|6) ;; *) err "$(L '无效选项' 'Invalid choice')"; continue;; esac
  sub_menu "$group" || return 0
  [[ -n $MAIN_ACTION ]] || continue
  set +e
  ( set -Eeuo pipefail; trap action_failed ERR; dispatch_action "$MAIN_ACTION" )
  action_status=$?
  set -e
  if [[ $MAIN_ACTION == uninstall && $action_status == 0 && ! -e $META ]]; then return 0; fi
  load_language
 done
}

bootstrap(){
 need_root
 require_cmd flock || return 1
 mkdir -p "$BASE" "$REPORT" "$BACKUP"; chmod 700 "$BASE" "$REPORT" "$BACKUP"
 exec 9>"$LOCK"; flock -n 9 || { err "$(L '其他管理任务正在运行' 'Another manager is running')"; return 1; }
 load_language
 if [[ -z $LANGUAGE_CHOICE ]]; then
  if [[ ${1:-} == --auto-update || ${1:-} == --notice ]]; then LANGUAGE_CHOICE=en_US; else select_language || return 1; fi
 fi
 export LANGUAGE_CHOICE
}
if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
 case ${1:-} in
  --argo-run) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; argo_run; exit $?;;
  --argo-export) need_root; load_language; LANGUAGE_CHOICE=${LANGUAGE_CHOICE:-en_US}; exports; exit $?;;
 esac
 bootstrap "${1:-}" || exit 1
 case "${1:-}" in --auto-update) update_auto;; --notice) notice;; *) main;; esac
fi
