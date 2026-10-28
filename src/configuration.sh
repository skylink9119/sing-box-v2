configuration_guard(){
 check_owned || return 1
 local path unit=$SYSTEMD_DIR/sing-box.service
 for path in "$BASE" "$CONF" "$META" "$BIN" "$(dirname "$CONF")";do [[ ! -L $path ]] || return 1;done
 if [[ -e $unit || -L $unit ]];then
  [[ ! -L $unit ]] && grep -Fxq 'Description=sing-box (managed by singbox-v2)' "$unit" && grep -Fxq "ExecStart=$BIN run -c $CONF" "$unit" || return 1
 fi
}
configuration_engine(){
 python3 - "$BASE" "$CONF" "$BIN" "$@" <<'PY_CONFIG'
# @include configuration.py
PY_CONFIG
}
configuration_apply(){
 configuration_guard && users_guard && warp_guard && argo_guard && hop_guard || return 1
 if [[ $1 == add && ${2:-} == vless ]];then
  local bind_family current_mode
  current_mode=$(protocol_mode) || return 1
  [[ $current_mode == 2 || $current_mode == 0 ]] || { err "$(L 'Reality 协议已经安装，请使用编辑或握手网站检测功能。' 'Reality is already installed; use node editing or target checks.')";return 1; }
  bind_family=$(state listen);bind_family=${bind_family:-0.0.0.0}
  reality_install_check "$4" "$3" "$bind_family" || return 1
 fi
 local stage snap admin=false users=false argo=false hop_active=false first_admin=false
 if python3 - "$CONF" "$META" <<'PY_INITIAL_ADMIN'
import json,sys
c=json.load(open(sys.argv[1]));s=json.load(open(sys.argv[2]));sys.exit(0 if not c.get('inbounds') and s.get('deployment')=='argo-only' else 1)
PY_INITIAL_ADMIN
 then first_admin=true;admin=true;fi
 stage=$(mktemp -d "$BASE/edit.XXXXXX") || return 1
 if ! configuration_engine "$stage" "$@";then rm -rf "$stage";return 1;fi
 if ! haproxy_engine check_configs "$stage";then rm -rf "$stage";return 1;fi
 snap=$(backup) || { rm -rf "$stage";return 1; }
 if systemctl is-active --quiet sing-box.service;then admin=true;fi
 if [[ -f $BASE/users.json ]] && systemctl is-active --quiet skybyte-users.service;then users=true;users_stop || { rm -rf "$stage";return 1; };fi
 if [[ -f $BASE/argo-state.json ]] && systemctl is-active --quiet skybyte-argo-node.service;then argo=true;fi
 if [[ $1 != reality && $(state hop) == True ]];then hop_active=true;hop_disable || { warp_resume "$admin" "$argo" "$users" || :;rm -rf "$stage";return 1; };fi
 if ! configuration_commit "$stage" "$1" || ! configuration_resume "$first_admin" "$admin" "$argo" "$users" || { [[ $1 == reality ]] && ! configuration_export_all; };then
  [[ $users != true ]] || users_stop || :
  [[ $first_admin != true ]] || systemctl disable --now sing-box.service || :
  configuration_rollback "$stage" || :
  if [[ $hop_active == true ]];then systemctl start singbox-v2-hop.service || :;fi
  [[ $first_admin != true ]] || admin=false
  warp_resume "$admin" "$argo" "$users" || :
  rm -rf "$stage";err "$(L '配置修改失败，已尝试恢复原配置' 'Configuration edit failed; original config restoration attempted')";return 1
 fi
 rm -rf "$stage"
 if [[ $1 != reality ]] && command -v ufw >/dev/null && LC_ALL=C ufw status | grep -q '^Status: active';then
  firewall_allow_protocols || return 1
 fi
 if [[ $1 != reality ]];then configuration_export_all || return 1;fi
 ok "$(L "配置已更新；备份：$snap" "Configuration updated; backup: $snap")"
 if [[ $hop_active == true ]];then warn "$(L '跳跃已关闭，请按新监听端口重新开启；旧 UFW 规则保留。' 'Hopping disabled; re-enable for the new listener. Old UFW rules remain.')";fi
}
configuration_export_all(){
 exports >/dev/null || return 1
 if [[ -f $BASE/users.json ]];then users_engine export_all | while IFS= read -r id;do users_export "$id" >/dev/null || return 1;done || return 1;fi
}
configuration_commit(){
 python3 - "$1" "${2:-}" <<'PY_CONFIG_COMMIT'
import json,os,pathlib,shutil,sys,tempfile
stage=pathlib.Path(sys.argv[1]);plan=json.loads((stage/'plan.json').read_text());rollback=[]
targets=[value for _,value in plan]
if sys.argv[2]=='reality':
 # Include exports in the same rollback journal before any live files change.
 names=('nodes.txt','subscription-base64.txt','v2rayn-nodes.txt','v2rayn-subscription.txt','shadowrocket-nodes.txt','shadowrocket-subscription.txt','shadowrocket-native-nodes.txt','shadowrocket-native-subscription.txt','outbounds.json','sing-box-client.json','clash-verge.yaml','mihomo-proxies.yaml','subscription-notes.txt','hy2-client-ca.pem','hy2-client-ca.cer','hy2-client-ca.mobileconfig')
 for _,value in plan:
  p=pathlib.Path(value)
  if p.name=='state.json':targets.extend(str(p.parent/name) for name in names)
for n,value in enumerate(dict.fromkeys(targets)):
 p=pathlib.Path(value)
 if p.is_symlink() or p.parent.is_symlink():raise ValueError('Target symlink')
 old=stage/('old-'+str(n));exists=p.exists()
 if exists:shutil.copyfile(p,old)
 rollback.append([str(old),str(p),exists])
(stage/'rollback.json').write_text(json.dumps(rollback))
for source,value in plan:
 p=pathlib.Path(value);fd,tmp=tempfile.mkstemp(dir=p.parent)
 with os.fdopen(fd,'wb') as f:f.write(pathlib.Path(source).read_bytes());f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)
PY_CONFIG_COMMIT
}
configuration_rollback(){
 [[ -f $1/rollback.json ]] || return 0
 python3 - "$1" <<'PY_CONFIG_ROLLBACK'
import json,pathlib,shutil,sys
for source,value,exists in json.loads((pathlib.Path(sys.argv[1])/'rollback.json').read_text()):
 p=pathlib.Path(value)
 if p.is_symlink():raise ValueError('Rollback target symlink')
 if exists:shutil.copyfile(source,p);p.chmod(0o600)
 elif p.exists():p.unlink()
PY_CONFIG_ROLLBACK
}
configuration_resume(){
 local first_admin=$1 admin=$2 argo=$3 users=$4
 if [[ $first_admin == true ]];then
  setup_service && systemctl enable --now sing-box.service || return 1
  admin=true
 fi
 warp_resume "$admin" "$argo" "$users"
}
node_settings(){
 check_owned || return 1
 local choice vp hp value protocol cert key domain up down ignore obfs bootstrap=false public='' listen='' family
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 prompt_options '1 修改主节点端口  2 服务器地址 / DDNS  3 Reality 握手域名  4 添加协议  5 移除协议  6 HY2 参数  7 使用已有 TLS 证书  0 返回' '1 Admin ports  2 Server address / DDNS  3 Reality handshake  4 Add protocol  5 Remove protocol  6 HY2 options  7 Existing TLS certificate  0 Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 case $choice in
  1) prompt_read 'Reality TCP [443]: ' vp || return 0;prompt_read 'HY2 UDP [443]: ' hp || return 0
   confirm "$(L '修改管理员端口，保留用户端口及凭据？' 'Change admin ports, retaining user ports and credentials?')" && configuration_apply ports "${vp:-443}" "${hp:-443}";;
  2) prompt_read "$(L '公网 IP 或 DDNS 域名：' 'Public IP or DDNS domain: ')" value || return 0
   confirm "$(L '更新所有节点的服务器地址？' 'Update server address for all nodes?')" && configuration_apply address "$value";;
  3) reality_replace;;
  4|5)
   prompt_options '1 Reality + Vision  2 Hysteria2' '1 Reality + Vision  2 Hysteria2';prompt_read '> ' protocol || return 0
   case $protocol in 1) protocol=vless;;2) protocol=hysteria2;;*) return 1;;esac
   if [[ $choice == 5 ]];then confirm "$(L '移除所选协议，保留另一协议与用户额度？' 'Remove selected protocol, retaining the other and account quotas?')" && configuration_apply remove "$protocol";return;fi
   if [[ $(python3 - "$CONF" "$META" <<'PY_INITIAL_NODE'
import json,sys
c=json.load(open(sys.argv[1]));s=json.load(open(sys.argv[2]));print('yes' if not c.get('inbounds') and s.get('deployment')=='argo-only' else 'no')
PY_INITIAL_NODE
   ) == yes ]];then
    bootstrap=true
    prompt_read "$(L '客户端使用的公网 IP / 域名：' 'Public IP/hostname used by clients: ')" public || return 0
    public=$(rescue_engine address "$public") || { err "$(L '公网地址无效' 'Invalid public address')";return 1; }
    family=$(rescue_engine family) || return 1
    case $family in 4)listen=0.0.0.0;;6)listen=::;;*)listen=::;;esac
    prompt_options '本机监听地址族：1 自动  2 IPv4  3 IPv6' 'Local bind family: 1 Auto  2 IPv4  3 IPv6'
    prompt_read '> ' family || return 0
    case ${family:-1} in 1);;2)listen=0.0.0.0;;3)listen=::;;*)return 1;;esac
   fi
   prompt_read "$(L '管理员监听端口 [443]：' 'Admin listener port [443]: ')" value || return 0;value=${value:-443}
   if [[ $protocol == vless ]];then prompt_read 'Reality SNI [addons.mozilla.org]: ' domain || return 0
    if [[ $bootstrap == true ]];then confirm "$(L '添加直连 Reality 节点并保留独立 Argo 隧道？' 'Add a direct Reality node and retain the separate Argo tunnel?')" && configuration_apply add vless "$value" "${domain:-addons.mozilla.org}" "$public" "$listen"
    else confirm "$(L '追加 Reality，保留现有凭据？' 'Add Reality, retaining existing credentials?')" && configuration_apply add vless "$value" "${domain:-addons.mozilla.org}";fi
   else
    prompt_options '1 自动自签名（无域名）  2 已有证书 / 托管 ACME' '1 Automatic self-signed (no domain)  2 Existing certificate / managed ACME'
    prompt_read '> ' protocol || return 0
    if [[ $protocol == 1 ]];then
     if [[ $bootstrap == true ]];then domain=$public;else domain=$(state ip) || return 1;fi
     if [[ $bootstrap == true ]];then confirm "$(L '生成自签名证书并添加 HY2；保留独立 Argo 隧道？客户端仍需信任公开证书。' 'Generate self-signed TLS and add HY2 while retaining the separate Argo tunnel? Clients must trust the public certificate.')" && configuration_apply add hysteria2 "$value" "$domain" selfsigned "$public" "$listen"
     else confirm "$(L '自动生成自签名证书并追加 HY2？客户端仍需信任公开证书。' 'Generate self-signed TLS and add HY2? Clients still need public-certificate trust.')" && configuration_apply add hysteria2 "$value" "$domain" selfsigned;fi
     return
    fi
    [[ $protocol == 2 ]] || return 1
    prompt_read "$(L '证书名称（域名或 IP）：' 'Certificate identity (domain or IP): ')" domain || return 0
    prompt_read 'TLS fullchain: ' cert || return 0;prompt_read 'TLS private key: ' key || return 0
    validate_certificate "$cert" "$key" "$domain" || return 1
    if [[ $bootstrap == true ]];then confirm "$(L '添加 HY2 并保留独立 Argo 隧道？' 'Add HY2 and retain the separate Argo tunnel?')" && configuration_apply add hysteria2 "$value" "$domain" "$cert" "$key" "$public" "$listen"
    else confirm "$(L '追加 HY2，沿用证书并保留用户用量？' 'Add HY2 with this certificate, retaining account usage?')" && configuration_apply add hysteria2 "$value" "$domain" "$cert" "$key";fi
   fi;;
  6) prompt_read "$(L '上行 Mbps [0=自动]：' 'Upload Mbps [0=auto]: ')" up || return 0;prompt_read "$(L '下行 Mbps [0=自动]：' 'Download Mbps [0=auto]: ')" down || return 0
   prompt_options '1 按带宽设置  2 忽略客户端带宽（须上下行均为0）' '1 Use bandwidth settings  2 Ignore client bandwidth (both must be 0)';prompt_read '> ' ignore || return 0
   case ${ignore:-1} in 1) ignore=false;;2) ignore=true;;*) return 1;;esac
   prompt_options '1 无混淆  2 Salamander' '1 No obfuscation  2 Salamander';prompt_read '> ' obfs || return 0
   case ${obfs:-1} in 1) obfs=none;;2) obfs=salamander;;*) return 1;;esac
   warn "$(L '混淆改动需重新导入客户端；此处不是每人跨协议硬限速。' 'Obfuscation changes require re-import; these are not cross-protocol per-account hard rate caps.')"
   confirm "$(L '应用 HY2 参数？' 'Apply HY2 options?')" && configuration_apply hy2 "${up:-0}" "${down:-0}" "$ignore" "$obfs";;
  7) prompt_read "$(L '证书名称：' 'Certificate identity: ')" domain || return 0;prompt_read 'TLS fullchain: ' cert || return 0;prompt_read 'TLS private key: ' key || return 0
   validate_certificate "$cert" "$key" "$domain" || return 1
   confirm "$(L '替换 HY2 使用的证书路径并同步用户节点？' 'Change HY2 certificate paths and sync account nodes?')" && configuration_apply tls "$domain" "$cert" "$key";;
  0) return 0;;*) return 1;;
 esac
}
firewall_allow_protocols(){
 local rule rules
 if [[ -f $CONF && -f $META ]];then
  rules=$(python3 - "$CONF" <<'PY_ALLOW'
import json,sys
for i in json.load(open(sys.argv[1]))['inbounds']:
 assert i['type'] in ('vless','hysteria2') and type(i['listen_port']) is int and 1<=i['listen_port']<=65535
 print(str(i['listen_port'])+('/tcp' if i['type']=='vless' else '/udp'))
PY_ALLOW
  ) || return 1
  while IFS= read -r rule;do [[ -z $rule ]] || ufw allow "$rule" || return 1;done <<<"$rules"
 fi
 if [[ -f $BASE/subscriptions.json ]];then
  online_guard || return 1
  rule=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["port"])' "$BASE/subscriptions.json") || return 1;ufw allow "$rule/tcp" || return 1
 fi
 if [[ -f $BASE/acme-state.json ]];then
  acme_guard || return 1
  if [[ $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["method"])' "$BASE/acme-state.json") == http ]];then ufw allow 80/tcp || return 1;fi
 fi
 users_firewall_allow
}
