installation_available(){
 if [[ -e $CONF || -L $CONF || -e $META || -L $META || -e $BIN || -L $BIN || -e $SYSTEMD_DIR/sing-box.service || -L $SYSTEMD_DIR/sing-box.service ]] || command -v sing-box >/dev/null; then err "$(L '发现已有配置或核心，拒绝覆盖；追加协议用 b → 9 → 4，已有节点增加 IPv6 备用用 d → 13 → 2。' 'Existing configuration or binary found; refusing to overwrite. Add a protocol through b → 9 → 4, or add IPv6 backups through d → 13 → 2.')"; return 1; fi
 if systemctl list-unit-files sing-box.service --no-legend 2>/dev/null | grep -q sing-box; then err "$(L '已有 sing-box 服务，拒绝覆盖' 'Existing sing-box service found; refusing to overwrite')"; return 1; fi
}
# modules/install.sh — build-time module; assembled by scripts/build.py.
choose_node_name(){
 local value
 prompt_read "$(L '节点名称前缀 [SKYBYTE]（回车默认）：' 'Node name prefix [SKYBYTE] (Enter for default): ')" value || return 1
 python3 - "$value" "${1:-}" <<'PY'
import sys,unicodedata
name=(sys.argv[1].strip() or 'SKYBYTE')+sys.argv[2]
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
 # Credentials stay off process arguments; stdin contains the embedded program.
 python3 - 3< <(printf '%s\0' "$@") <<'PY'
import json,os
with os.fdopen(3,'rb') as f:args=f.read().decode('utf-8').split('\0')
if args.pop()!='':raise ValueError('Invalid config input')
conf,meta,domain,cert,key,sni,uuid,priv,pub,sid,password,ip,mode,cert_mode=args[:14]
node_name=args[14] if len(args)>14 else 'SKYBYTE'
vp=int(args[15]) if len(args)>15 else 443;hp=int(args[16]) if len(args)>16 else 443
assert 1<=vp<=65535 and 1<=hp<=65535
listen=args[17] if len(args)>17 and args[17] else ('::' if ':' in ip else '0.0.0.0')
assert listen in ('::','0.0.0.0')
d={'log':{'level':'info','timestamp':True},'inbounds':[{'type':'vless','tag':'reality','listen':listen,'listen_port':443,'users':[{'name':'user1','uuid':uuid,'flow':'xtls-rprx-vision'}],'tls':{'enabled':True,'server_name':sni,'reality':{'enabled':True,'handshake':{'server':sni,'server_port':443},'private_key':priv,'short_id':[sid]}}},{'type':'hysteria2','tag':'hy2','listen':listen,'listen_port':443,'users':[{'name':'user1','password':password}],'tls':{'enabled':True,'server_name':domain,'certificate_path':cert,'key_path':key}}],'outbounds':[{'type':'direct','tag':'direct'}],'route':{'final':'direct'}}
if mode=='1': d['inbounds']=d['inbounds'][:1]
elif mode=='2': d['inbounds']=d['inbounds'][1:]
for i in d['inbounds']:i['listen_port']=vp if i['type']=='vless' else hp
with open(conf,'w') as f:json.dump(d,f,indent=2)
with open(meta,'w') as f:json.dump({'node_name':node_name,'mode':mode,'cert_mode':cert_mode,'cert_path':cert,'managed_certificates':[cert,key] if cert_mode=='1' else [],'ip':ip,'listen':listen,'domain':domain,'sni':sni,'uuid':uuid,'public_key':pub,'sid':sid,'hy2_password':password,'hop':False,'hop_start':20000,'hop_end':30000},f,indent=2)
PY
}
install_protocol() (
 local stage="" committed=false final_bin=$BIN final_conf=$CONF final_meta=$META final_base=$BASE
 trap installation_cleanup EXIT
 need_root
 local guided=false ipv6_install=false
 case ${2:-} in guided|guided-ipv6) guided=true;;esac
 case ${2:-} in ipv6|guided-ipv6) ipv6_install=true;;esac
 local mode="${1:-}" cert_mode="" vp=443 hp=443 supplied_ip='' listen_addr=''
 if [[ -z "$mode" ]]; then prompt_options '1. Reality 单协议
2. HY2 单协议
3. 双协议
0. 返回' '1. Reality only
2. HY2 only
3. Dual
0. Back'
 prompt_read '> ' mode || return; fi
 [[ "$mode" == 0 ]] && return 0
 [[ "$mode" =~ ^[123]$ ]] || { err "Invalid selection"; return 1; }
 if [[ $guided != true ]];then notice; confirm "$(L '同意声明并安装所选协议？' 'Accept notice and install selected protocol(s)?')" || return 0;fi
 installation_available || return 1
 install_environment_check "$mode" || return 1
 if [[ $ipv6_install == true ]];then
  local ipv6_status
  if [[ $guided == true ]];then supplied_ip=$(ipv6_install_auto_address) || return 1
  else supplied_ip=$(ipv6_install_address) || { ipv6_status=$?;[[ $ipv6_status == 2 ]] && return 0;return 1; };fi
  listen_addr=::
  warn "$(L '使用所选 IPv6 作为节点连接地址，监听支持双栈；客户端网络必须支持 IPv6。请放行云安全组和系统防火墙的 IPv6 TCP/UDP 端口。纯 IPv6 VPS 访问 IPv4 网站需要另行配置可用出站。' 'The selected IPv6 is the client address with a dual-stack listener. Client IPv6 and provider/host IPv6 TCP/UDP rules are required. IPv6-only VPSs need a separate working egress for IPv4-only sites.')"
  if [[ $guided != true && $mode != 2 ]];then prompt_read "$(L 'Reality TCP 端口 [443]：' 'Reality TCP port [443]: ')" vp || return 1;vp=${vp:-443};fi
  if [[ $guided != true && $mode != 1 ]];then prompt_read "$(L 'HY2 UDP 端口 [443]：' 'HY2 UDP port [443]: ')" hp || return 1;hp=${hp:-443};fi
 fi
 if [[ ${2:-} == custom ]];then
  if [[ $mode != 2 ]];then prompt_read "$(L '本机 Reality TCP 端口 [443]：' 'Local Reality TCP port [443]: ')" vp || return 1;vp=${vp:-443};fi
  if [[ $mode != 1 ]];then prompt_read "$(L '本机 HY2 UDP 端口 [443]：' 'Local HY2 UDP port [443]: ')" hp || return 1;hp=${hp:-443};fi
  prompt_read "$(L '客户端连接的公网 IP / 域名（回车自动查询）：' 'Public IP/hostname for clients (Enter detects): ')" supplied_ip || return 1
  [[ -z $supplied_ip ]] || supplied_ip=$(rescue_engine address "$supplied_ip") || return 1
  local native_family
  native_family=$(rescue_engine family) || return 1
  case $native_family in 4) listen_addr=0.0.0.0;; 6) listen_addr=::;; *) [[ $supplied_ip == *:* ]] && listen_addr=:: || listen_addr=0.0.0.0;; esac
  prompt_options '本机监听地址族：
1. 自动
2. IPv4
3. IPv6（NAT 请按 VPS 网卡选择）' 'Local bind family:
1. Auto
2. IPv4
3. IPv6 (for NAT, choose the VPS interface family)'
  prompt_read '> ' native_family || return 1
  case ${native_family:-1} in 1);; 2)listen_addr=0.0.0.0;; 3)listen_addr=::;; *)return 1;; esac
 fi
 valid_port "$vp" && valid_port "$hp" || return 1;vp=$((10#$vp));hp=$((10#$hp))
 if [[ $mode != 2 ]];then haproxy_engine check_port "$vp" || return 1;fi
 install_port_check "$mode" "$vp" "$hp" "${listen_addr:-0.0.0.0}" || return 1
 local domain="" cert="" key="" sni="" node_name node_suffix=''
 [[ $ipv6_install != true ]] || node_suffix=-IPv6
 if [[ $guided == true ]];then node_name=$WIZARD_NODE_NAME
 else node_name=$(choose_node_name "$node_suffix") || { err "$(L '节点名称无效' 'Invalid node name')"; return 1; };fi
 if [[ $mode != 1 ]]; then
  if [[ $guided == true ]];then cert_mode=1
  else
  prompt_options 'HY2证书:
1. 无域名(自动自签名)
2. 已有证书
3. 托管 ACME' 'HY2 certificate:
1. No domain (self-signed)
2. Existing certificate
3. Managed ACME'
  prompt_read '> ' cert_mode
  fi
  case "$cert_mode" in
   1) say '需要客户端安全地导入证书并启用验证。' 'Client must securely import and verify the certificate.';;
   2) prompt_read "$(L '证书域名：' 'Certificate domain: ')" domain
      [[ $domain =~ ^[a-zA-Z0-9.-]+$ && $domain == *.* ]] || { err "$(L '域名无效' 'Invalid domain')"; return 1; }
      prompt_read "$(L 'TLS 完整证书路径：' 'TLS fullchain path: ')" cert
      prompt_read "$(L 'TLS 私钥路径：' 'TLS key path: ')" key
      [[ -f $cert && -f $key ]] || { err "$(L '证书或私钥不存在' 'Certificate/key missing')"; return 1; };;
   3) acme_guard || return 1
      [[ -f $BASE/acme-state.json ]] || acme_issue || return 1
      domain=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["domain"])' "$BASE/acme-state.json") || return 1
      cert=$BASE/acme/config/live/skybyte/fullchain.pem;key=$BASE/acme/config/live/skybyte/privkey.pem;cert_mode=2;;
   *) err "$(L '无效证书选项' 'Invalid certificate option')"; return 1;;
  esac
 fi
 if [[ $mode != 2 ]]; then
  if [[ $guided == true ]];then sni=addons.mozilla.org
  else prompt_read "$(L 'Reality 握手域名 [addons.mozilla.org]：' 'Reality handshake [addons.mozilla.org]: ')" sni || return 1;fi
  sni=${sni:-addons.mozilla.org}
  [[ $sni =~ ^[a-zA-Z0-9.-]+$ && $sni == *.* && $sni =~ [a-zA-Z] ]] || { err "$(L '无效 SNI' 'Invalid SNI')"; return 1; }
 fi
 if [[ -z ${SKYBYTE_ASSET_DIR:-} ]];then
  say '安装依赖...' 'Installing dependencies...'
  apt_install curl openssl ca-certificates python3 iproute2 util-linux nftables procps || { err "$(L '依赖安装失败，尚未生成节点；请检查上方 APT 锁、软件源或网络错误。' 'Dependency installation failed before node generation; inspect the APT lock, repository or network error above.')";return 1; }
  require_cmd getent; getent ahosts github.com >/dev/null || { err "$(L 'GitHub DNS 解析失败，请先修复 DNS或使用离线包' 'GitHub DNS lookup failed; repair DNS or use offline assets')"; return 1; }
 else rescue_dependencies && require_cmd openssl || return 1;fi
 [[ $mode == 2 ]] || install_reality_target "$sni" || return 1
 install_download_check || return 1
 mkdir -p "$(dirname "$BIN")"
 if [[ $cert_mode == 2 ]]; then
  local absolute_paths
  absolute_paths=$(python3 - "$cert" "$key" <<'PY_CERT_ABSOLUTE'
import os,sys
# Keep live renewal symlinks: abspath normalizes the location without pinning an archive generation.
for path in sys.argv[1:]:print(os.path.abspath(path))
PY_CERT_ABSOLUTE
  ) || return 1
  { IFS= read -r cert;IFS= read -r key; } <<< "$absolute_paths"
  validate_certificate "$cert" "$key" "$domain" || return 1
 fi
 if [[ $cert_mode == 1 ]]; then
  [[ ! -e $(dirname "$final_conf")/hy2-selfsigned.crt && ! -e $(dirname "$final_conf")/hy2-selfsigned.key ]] || { err "TLS files already exist"; return 1; }
 fi
 stage=$(mktemp -d "$BASE/install.XXXXXX") || return 1
 local BIN=$stage/sing-box CONF=$stage/config/config.json META=$stage/state.json BASE=$stage
 mkdir -m 700 "$stage/config"
 download_install_core "$BIN" || { err "$(L '官方安装失败' 'Release installation failed')"; return 1; }
 chmod 755 "$BIN"
 local uuid pair priv="" pub="" sid="" passwd ip
 uuid=$(cat /proc/sys/kernel/random/uuid)
 if [[ $mode != 2 ]]; then pair=$("$BIN" generate reality-keypair)
 priv=$(sed -n 's/^PrivateKey: *//p' <<<"$pair"); pub=$(sed -n 's/^PublicKey: *//p' <<<"$pair")
 [[ -n $priv && -n $pub ]] || { err "$(L 'Reality 密钥生成失败' 'Reality key generation failed')"; return 1; }; fi
 sid=$(openssl rand -hex 4); passwd=$(openssl rand -hex 16)
 if [[ -n $supplied_ip ]];then ip=$supplied_ip;else
 ip=$(curl -q -4fsS --noproxy '*' --max-time 12 https://api.ipify.org) || ip=$(curl -q -6fsS --noproxy '*' --max-time 12 https://api64.ipify.org) || { err "$(L '公网 IP 查询失败，请从受限网络入口指定地址' 'Public IP lookup failed; specify an address via restricted-network setup')"; return 1; }
 python3 - "$ip" <<'PY' || return 1
import ipaddress,sys
assert ipaddress.ip_address(sys.argv[1]).is_global
PY
 fi
 mkdir -p "$(dirname "$CONF")"
 if [[ $cert_mode == 1 ]]; then
  [[ ! -e $(dirname "$CONF")/hy2-selfsigned.crt && ! -e $(dirname "$CONF")/hy2-selfsigned.key ]] || { err "TLS files already exist"; return 1; }
  domain="$ip"; cert="$(dirname "$CONF")/hy2-selfsigned.crt"; key="$(dirname "$CONF")/hy2-selfsigned.key"
  local san
  san=$(python3 - "$ip" <<'PY_INSTALL_SAN'
import ipaddress,sys
try:ipaddress.ip_address(sys.argv[1]);print('IP:'+sys.argv[1])
except ValueError:print('DNS:'+sys.argv[1])
PY_INSTALL_SAN
  ) || return 1
  # OpenSSL 1.1.1 appends -addext to system x509_extensions instead of replacing
  # duplicate OIDs. An explicit minimal request config avoids invalid HY2 certs.
  openssl req -config <(printf '[req]\ndistinguished_name=dn\nx509_extensions=ids\n[dn]\n[ids]\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n') -x509 -newkey rsa:3072 -sha256 -nodes -days 365 -subj "/CN=$ip" -addext "subjectAltName=$san" -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign" -keyout "$key" -out "$cert" >/dev/null 2>&1 || return 1
  chmod 600 "$key"; chmod 644 "$cert"
 fi
 if [[ $mode != 1 ]]; then validate_certificate "$cert" "$key" "$domain" || return 1; fi
 write_config "$CONF" "$META" "$domain" "$cert" "$key" "$sni" "$uuid" "$priv" "$pub" "$sid" "$passwd" "$ip" "$mode" "$cert_mode" "$node_name" "$vp" "$hp" "$listen_addr"
 chmod 600 "$CONF" "$META"
 "$BIN" check -c "$CONF" || { err "$(L '配置检查失败' 'Configuration check failed')"; return 1; }
 exports >/dev/null || return 1
 if [[ $ipv6_install == true ]];then
  ipv6_engine check-install "$supplied_ip" || return 1
  if command -v ufw >/dev/null;then
   local ipv6_ufw_status
   ipv6_ufw_status=$(LC_ALL=C ufw status) || { err "$(L '无法读取 UFW 状态，停止安装。' 'Cannot inspect UFW; installation stopped.')";return 1; }
   if [[ $ipv6_ufw_status == *'Status: active'* ]];then
    warn "$(L '即将先放行所选端口；后续安装失败时，已添加的放行规则会保留，请自行核对。' 'Allowing selected ports first; added rules remain if installation later fails. Review them if needed.')"
    if [[ $mode != 2 ]];then ufw allow "$vp/tcp" || return 1;fi
    if [[ $mode != 1 ]];then ufw allow "$hp/udp" || return 1;fi
   fi
  fi
 fi
 installation_commit "$stage" "$final_bin" "$final_conf" "$final_meta" "$final_base" || return 1
 BIN=$final_bin;CONF=$final_conf;META=$final_meta;BASE=$final_base
 cert=$(state cert_path)
 "$BIN" check -c "$CONF" || return 1
 setup_service || return 1
 if [[ $ipv6_install != true ]] && command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active'; then if [[ $mode != 2 ]]; then ufw allow "$vp/tcp"; fi; if [[ $mode != 1 ]]; then ufw allow "$hp/udp"; fi; fi
 systemctl daemon-reload && systemctl enable --now sing-box && systemctl restart sing-box || return 1
 sleep 2; systemctl is-active --quiet sing-box || { err "$(L '服务启动失败，请查看 journalctl -u sing-box' 'Service failed; inspect journalctl -u sing-box')"; return 1; }
 [[ $ipv6_install != true ]] || ipv6_engine ready || return 1
 if [[ $cert_mode == 1 ]]; then echo "$(L '自签名证书：' 'Self-signed certificate: ')$cert"; openssl x509 -in "$cert" -noout -fingerprint -sha256; say '务必将证书安全导入客户端并验证，链接本身不足以建立信任。' 'Securely import and verify certificate on client; URL alone cannot establish trust.'; fi
 exports || return 1
 if [[ $mode != 1 ]];then certificate_record "$(openssl x509 -in "$cert" -noout -fingerprint -sha256)" || return 1;fi
 committed=true
 ok "$(L '部署完成；请检查云防火墙' 'Installed; check provider firewall')"
 if [[ $guided == true ]];then
  deployment_apply_selected "$WIZARD_BBR" "$WIZARD_FIREWALL" "$WIZARD_QR" || warn "$(L '节点已安装，部分所选配置未完成，请查看上方结果。' 'Node installed; some selected setup is incomplete. Inspect the results above.')"
 else automatic_setup || warn "$(L '节点已保留，部分配套配置未完成，可通过 d → 14 重试。' 'Node retained; some optional setup is incomplete. Retry via d → 14.')"
 fi
)
