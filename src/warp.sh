warp_engine(){
 python3 - "$BASE" "$CONF" "$BIN" "$@" <<'PY_WARP'
# @include warp.py
PY_WARP
}
warp_guard(){
 local file unit=$SYSTEMD_DIR/skybyte-warp-gateway.service
 for file in warp-state.json warp-gateway.json warp-client.json warp-rules.json warp-rules.previous.json; do [[ ! -L $BASE/$file ]] || return 1; done
 if [[ -e $unit || -L $unit ]]; then
  if [[ -L $unit ]] || ! grep -Fxq 'Description=SKYBYTE managed WARP gateway' "$unit" || ! grep -Fxq "ExecStart=$BIN run -c $BASE/warp-gateway.json" "$unit"; then err "$(L 'WARP 网关归属异常' 'WARP gateway ownership mismatch')"; return 1; fi
 fi
 if [[ -f $BASE/warp-gateway.json && ! -f $unit ]]; then err "$(L '已有非托管网关配置，拒绝覆盖' 'Unmanaged gateway config exists; refusing overwrite')"; return 1; fi
 if [[ -f $BASE/warp-client.json ]]; then python3 - "$BASE/warp-client.json" <<'PY_WARP_OWNER'
import json,sys
s=json.load(open(sys.argv[1]));assert s['owner']=='SKYBYTE WARP client v1' and type(s['port']) is int and 1024<=s['port']<=65535
PY_WARP_OWNER
 fi
 warp_engine guard
}
warp_verify(){
 local port=$1 trace
 valid_port "$port" && ((10#$port>=1024)) || return 1
 trace=$(curl -q -fsSL --noproxy '' --proxy "socks5h://127.0.0.1:$port" --proto '=https' --proto-redir '=https' --max-time 12 --max-filesize 65536 https://www.cloudflare.com/cdn-cgi/trace) || { err "$(L 'WARP 代理连接失败' 'WARP proxy connection failed')"; return 1; }
 local egress
 egress=$(printf '%s\n' "$trace" | python3 -c 'import ipaddress,re,sys; d=dict(line.split("=",1) for line in sys.stdin.read().splitlines() if "=" in line); assert d.get("warp") in ("on","plus") and ipaddress.ip_address(d.get("ip","")).is_global and re.fullmatch("[A-Z]{2}",d.get("loc","")); print(d["ip"]+" ("+d["loc"]+")")' 2>/dev/null) || { err "$(L '代理未通过 WARP 出口验证，拒绝应用' 'Proxy did not verify as WARP; refusing apply')"; return 1; }
 ok "$(L 'WARP 出口验证通过：' 'WARP egress verified: ')$egress"
}
warp_wait_ready(){
 local port=$1 attempt
 say '等待 WARP 本机代理就绪……' 'Waiting for the WARP local proxy…'
 for ((attempt=0;attempt<3;attempt++)); do
  if warp_loopback "$port" && warp_verify "$port"; then return 0; fi
  [[ $attempt == 2 ]] || sleep 2
 done
 err "$(L 'WARP 尚未就绪，节点分流保持原样；可稍后使用现有本机代理选项重试' 'WARP is not ready; node routing is unchanged. Retry using the existing local proxy option later')"
 return 1
}
warp_loopback(){
 local port=$1 listeners address
 valid_port "$port" && ((10#$port>=1024)) || return 1
 require_cmd ss || return 1
 listeners=$(ss -H -ltn "( sport = :$port )") || return 1
 [[ -n $listeners ]] || { err "$(L '本地代理未监听' 'Local proxy is not listening')"; return 1; }
 while read -r address; do
  case $address in "127.0.0.1:$port"|"[::1]:$port"|"::1:$port") ;; *) err "$(L 'WARP 代理必须只监听回环地址' 'WARP proxy must listen only on loopback')"; return 1;; esac
 done < <(printf '%s\n' "$listeners" | awk '{print $4}')
}
warp_resume(){
 local admin=$1 argo=$2 users=$3
 if [[ $admin == true ]]; then systemctl restart sing-box.service && service_healthy || return 1; fi
 if [[ $argo == true ]]; then systemctl restart skybyte-argo-node.service && systemctl is-active --quiet skybyte-argo-node.service || return 1; fi
 if [[ $users == true ]]; then systemctl start skybyte-users.service && systemctl is-active --quiet skybyte-users.service || return 1; fi
}
warp_switch(){
 local mode=$1 port=$2 udp=$3 domains=$4 snap admin=false argo=false users=false
 check_owned && warp_guard && users_guard && argo_guard || return 1
 if [[ $mode != direct ]]; then warp_loopback "$port" && warp_verify "$port" || return 1; fi
 snap=$(backup) || return 1
 if systemctl is-active --quiet sing-box.service; then admin=true; fi
 if [[ -f $BASE/argo-state.json ]] && systemctl is-active --quiet skybyte-argo-node.service; then argo=true; fi
 if [[ -f $BASE/users.json ]] && systemctl is-active --quiet skybyte-users.service; then users=true; users_stop || return 1; fi
 if ! warp_engine switch "$mode" "$port" "$udp" "$domains"; then warp_resume "$admin" "$argo" "$users" || :; return 1; fi
 if ! warp_resume "$admin" "$argo" "$users"; then
  [[ $users != true ]] || users_stop || :
  warp_engine restore "$snap" || return 1
  warp_resume "$admin" "$argo" "$users" || :
  err "$(L 'WARP 分流重启失败，已回滚路由' 'WARP restart failed; routing rolled back')"; return 1
 fi
 ok "$(L '已应用出站模式：' 'Outbound mode applied: ')$mode"
 say "备份：$snap" "Backup: $snap"
}
warp_proxy_capability(){
 python3 - "$1" <<'PY_SOCKS_CAP'
import socket,struct,sys
port=int(sys.argv[1]);assert 1024<=port<=65535
with socket.create_connection(('127.0.0.1',port),timeout=3) as s:
 def read_exact(n):
  data=b''
  while len(data)<n:
   part=s.recv(n-len(data))
   if not part:raise ConnectionError('SOCKS reply ended early')
   data+=part
  return data
 s.sendall(b'\x05\x01\x00');hello=read_exact(2)
 if hello!=b'\x05\x00':raise ValueError('SOCKS5 no-auth handshake failed')
 s.sendall(b'\x05\x03\x00\x01'+socket.inet_aton('127.0.0.1')+struct.pack('!H',0))
 try:reply=read_exact(4)
 except (TimeoutError,ConnectionError):reply=b''
 print('true' if reply[:2]==b'\x05\x00' else 'false')
PY_SOCKS_CAP
}
warp_install_client(){
 need_root; check_owned && warp_guard || return 1
 local os_id code port tmp registration
 if command -v warp-cli >/dev/null; then err "$(L '已有 WARP 客户端，请用现有本机代理选项，避免覆盖其设置' 'WARP client exists; use the existing local proxy option to preserve its settings')"; return 1; fi
 if [[ -e ${WARP_DATA_DIR:-/var/lib/cloudflare-warp} || -L ${WARP_DATA_DIR:-/var/lib/cloudflare-warp} ]]; then err "$(L '发现已有 WARP 数据，请先手动核对注册与模式，避免启动已有全局连接' 'Existing WARP data found; inspect registration and mode before starting a potentially global connection')"; return 1; fi
 # shellcheck source=/dev/null
 . "$OS_RELEASE"
 os_id=${ID:-};code=${VERSION_CODENAME:-}
 case "$os_id:$code" in ubuntu:jammy|ubuntu:noble|ubuntu:resolute|debian:bookworm|debian:trixie) ;; *) err "$(L '自动安装 WARP 仅支持当前官方 Ubuntu/Debian 版本' 'Automatic WARP install requires a currently supported Ubuntu/Debian release')"; return 1;; esac
 for tmp in "$WARP_REPO_FILE" "$WARP_KEY_FILE"; do
  [[ ! -e $tmp && ! -L $tmp ]] || { err "$(L 'WARP 软件源文件已存在，拒绝覆盖' 'WARP repository file exists; refusing overwrite')"; return 1; }
 done
 say 'WARP 连接 Cloudflare；请阅读条款 https://www.cloudflare.com/application/terms/ 。不会切换系统默认路由。' 'WARP connects to Cloudflare. Terms: https://www.cloudflare.com/application/terms/ . System default routes are not switched.'
 confirm "$(L '安装官方客户端并注册、接受 WARP 服务条款？' 'Install/register the official client and accept WARP terms?')" || return 0
 prompt_read "$(L '本机代理端口 [40000]：' 'Local proxy port [40000]: ')" port || return 0; port=${port:-40000}
 valid_port "$port" && ((10#$port>=1024)) || return 1; port=$((10#$port))
 haproxy_engine check_port "$port" || return 1
 if ss -H -ltn "( sport = :$port )" | grep -q .; then err "$(L '端口已被占用' 'Port already occupied')"; return 1; fi
 apt_install curl ca-certificates gnupg || return 1
 tmp=$(mktemp -d "$BASE/warp-install.XXXXXX") || return 1
 if ! curl -q -fsSL --proto '=https' --max-time 30 https://pkg.cloudflareclient.com/pubkey.gpg -o "$tmp/key" ||
    ! gpg --batch --yes --dearmor --output "$tmp/keyring" "$tmp/key"; then rm -rf "$tmp"; return 1; fi
 command install -m 644 "$tmp/keyring" "$WARP_KEY_FILE" || { rm -rf "$tmp"; return 1; }
 printf 'deb [signed-by=%s] https://pkg.cloudflareclient.com/ %s main\n' "$WARP_KEY_FILE" "$code" > "$WARP_REPO_FILE"
 chmod 644 "$WARP_REPO_FILE"; rm -rf "$tmp"
 apt_install cloudflare-warp || return 1
 systemctl enable --now warp-svc.service || return 1
 if warp-cli --accept-tos registration show >/dev/null 2>&1; then err "$(L '发现已有 WARP 注册信息，保留不修改；请手动配置本机代理' 'Existing WARP registration found; retained. Configure a local proxy manually.')"; return 1; fi
 warp-cli --accept-tos registration new >/dev/null && warp-cli --accept-tos mode proxy && warp-cli --accept-tos proxy port "$port" && warp-cli --accept-tos connect || return 1
 registration=$(warp-cli --accept-tos registration show | sha256sum | awk '{print $1}') || return 1
 python3 - "$BASE/warp-client.json" "$port" "$registration" <<'PY_CLIENT_OWNER'
import json,os,sys,tempfile
fd,tmp=tempfile.mkstemp(dir=os.path.dirname(sys.argv[1]))
with os.fdopen(fd,'w') as f:json.dump({'owner':'SKYBYTE WARP client v1','port':int(sys.argv[2]),'registration_hash':sys.argv[3]},f)
os.replace(tmp,sys.argv[1])
PY_CLIENT_OWNER
 warp_wait_ready "$port" || return 1
 local udp domains
 udp=$(warp_proxy_capability "$port") || return 1; domains=$(warp_engine defaults) || return 1
 warp_switch restricted "$port" "$udp" "$domains"
}
warp_import_gateway(){
 check_owned && warp_guard || return 1
 local profile port saved active=false udp=true domains native=${1:-auto} routing=${2:-restricted}
 [[ $native == auto || $native == 4 || $native == 6 ]] && [[ $routing == global || $routing == restricted ]] || return 1
 prompt_read "$(L '已有 WARP WireGuard 配置路径（私密文件）：' 'Existing WARP WireGuard profile path (private): ')" profile || return 0
 [[ -f $profile && ! -L $profile ]] || return 1
 prompt_read "$(L '共享本机代理端口 [40000]：' 'Shared local proxy port [40000]: ')" port || return 0; port=${port:-40000}
 valid_port "$port" && ((10#$port>=1024)) || return 1; port=$((10#$port))
 haproxy_engine check_port "$port" || return 1
 confirm "$(L '导入私密配置并建立共享 WARP 网关？已有网关会短暂重启。' 'Import private profile and create shared WARP gateway? Existing gateway briefly restarts.')" || return 0
 saved=$(mktemp -d "$BASE/warp-import.XXXXXX") || return 1
 if [[ -f $BASE/warp-gateway.json ]]; then cp "$BASE/warp-gateway.json" "$saved/gateway.json" || return 1; fi
 if [[ -f $SYSTEMD_DIR/skybyte-warp-gateway.service ]]; then cp "$SYSTEMD_DIR/skybyte-warp-gateway.service" "$saved/unit" || return 1; fi
 if systemctl is-active --quiet skybyte-warp-gateway.service; then active=true; fi
 if ss -H -ltn "( sport = :$port )" | grep -q .; then
  if [[ $active != true ]] || [[ $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["inbounds"][0]["listen_port"])' "$BASE/warp-gateway.json") != "$port" ]]; then rm -rf "$saved";err "$(L '代理端口已被占用' 'Proxy port occupied')";return 1;fi
 fi
 if ! warp_engine gateway "$profile" "$port" "$native"; then rm -rf "$saved"; return 1; fi
 if [[ $active == true ]]; then if ! systemctl stop skybyte-warp-gateway.service; then cp "$saved/gateway.json" "$BASE/warp-gateway.json";rm -rf "$saved";return 1;fi;fi
 cat >"$SYSTEMD_DIR/skybyte-warp-gateway.service" <<UNIT
[Unit]
Description=SKYBYTE managed WARP gateway
After=network-online.target
Wants=network-online.target
[Service]
ExecStart=$BIN run -c $BASE/warp-gateway.json
Restart=on-failure
RestartSec=5
LimitNOFILE=1048576
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
 if ! systemctl daemon-reload || ! systemctl enable --now skybyte-warp-gateway.service || ! { sleep 2; warp_loopback "$port" && warp_verify "$port"; }; then
  systemctl stop skybyte-warp-gateway.service || :
  if [[ -f $saved/gateway.json ]]; then cp "$saved/gateway.json" "$BASE/warp-gateway.json"; else rm -f "$BASE/warp-gateway.json"; fi
  if [[ -f $saved/unit ]]; then cp "$saved/unit" "$SYSTEMD_DIR/skybyte-warp-gateway.service"; else systemctl disable skybyte-warp-gateway.service || :; rm -f "$SYSTEMD_DIR/skybyte-warp-gateway.service"; fi
  systemctl daemon-reload || :; [[ $active != true ]] || systemctl start skybyte-warp-gateway.service || :
  rm -rf "$saved"; err "$(L '网关验证失败，已恢复此前网关' 'Gateway verification failed; previous gateway restored')"; return 1
 fi
 rm -rf "$saved"; domains=$(warp_engine defaults) || return 1
 warp_switch "$routing" "$port" "$udp" "$domains"
}
warp_dualstack(){
 local port trace family ips ip
 port=$(warp_engine port) && warp_verify "$port" || return 1
 say '测试 WARP 的 IPv4/IPv6 TCP 出口，不代表系统全局双栈或平台解锁。' 'Tests WARP IPv4/IPv6 TCP egress, not system-wide dual-stack or service unlocking.'
 for family in A AAAA; do
  ips=$(curl -q -fsSL --noproxy '*' --max-time 12 --proto '=https' "https://cloudflare-dns.com/dns-query?name=www.cloudflare.com&type=$family" -H 'accept: application/dns-json' | python3 -c 'import ipaddress,json,sys; kind=1 if sys.argv[1]=="A" else 28; print("\n".join(str(ipaddress.ip_address(a["data"])) for a in json.load(sys.stdin).get("Answer",[]) if a.get("type")==kind and ipaddress.ip_address(a["data"]).is_global))' "$family") || { warn "$(L 'DNS 查询失败，能力未知' 'DNS query failed; capability unknown')"; continue; }
  ip=${ips%%$'\n'*}; [[ -n $ip ]] || { warn "$family: $(L '无目标地址' 'No target address')"; continue; }
  if [[ $family == AAAA ]]; then ip="[$ip]"; fi
  trace=$(curl -q -fsSL --noproxy '' --proxy "socks5h://127.0.0.1:$port" --proto '=https' --max-time 12 --max-filesize 65536 --connect-to "www.cloudflare.com:443:$ip:443" https://www.cloudflare.com/cdn-cgi/trace) || { warn "$family: $(L '连接失败，能力未验证' 'Connection failed; capability unverified')"; continue; }
  if printf '%s\n' "$trace" | python3 -c 'import ipaddress,sys; d=dict(line.strip().split("=",1) for line in sys.stdin if "=" in line); family=4 if sys.argv[1]=="A" else 6; sys.exit(0 if d.get("warp") in ("on","plus") and ipaddress.ip_address(d["ip"]).version==family else 1)' "$family"; then ok "$family: $(L 'WARP 出口通过' 'WARP egress passed')"; else warn "$family: $(L '未验证为 WARP 出口' 'Not verified as WARP egress')"; fi
 done
}
warp_remove(){
 warp_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-warp-gateway.service ]]; then systemctl disable --now skybyte-warp-gateway.service || return 1; rm -f "$SYSTEMD_DIR/skybyte-warp-gateway.service"; fi
 if [[ -f $BASE/warp-client.json ]] && command -v warp-cli >/dev/null; then
  local current expected
  current=$(warp-cli --accept-tos registration show | sha256sum | awk '{print $1}') || current=''
  expected=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["owner"]=="SKYBYTE WARP client v1"; print(d["registration_hash"])' "$BASE/warp-client.json") || return 1
  if [[ -n $current && $current == "$expected" ]]; then warp-cli --accept-tos disconnect || return 1; else warn "$(L 'WARP 注册已改变，保留客户端连接' 'WARP registration changed; client connection retained')"; fi
 fi
 rm -f "$BASE/warp-state.json" "$BASE/warp-gateway.json" "$BASE/warp-client.json"
}
warp_restore_snapshot(){
 local path=$1 active=false
 warp_guard || return 1
 if [[ -f $SYSTEMD_DIR/skybyte-warp-gateway.service ]] && systemctl is-active --quiet skybyte-warp-gateway.service; then active=true; systemctl stop skybyte-warp-gateway.service || return 1; fi
 warp_engine restore "$path" || return 1
 if [[ -f $path/warp-gateway.json ]]; then
  [[ -f $path/warp-gateway.unit && ! -L $path/warp-gateway.json && ! -L $path/warp-gateway.unit ]] || return 1
  grep -Fxq 'Description=SKYBYTE managed WARP gateway' "$path/warp-gateway.unit" && grep -Fxq "ExecStart=$BIN run -c $BASE/warp-gateway.json" "$path/warp-gateway.unit" || return 1
  "$BIN" check -c "$path/warp-gateway.json" || return 1
  cp "$path/warp-gateway.json" "$BASE/warp-gateway.json" && cp "$path/warp-gateway.unit" "$SYSTEMD_DIR/skybyte-warp-gateway.service" || return 1
  systemctl daemon-reload || return 1
  if [[ $active == true || ( -f $path/warp-gateway-active && $(cat "$path/warp-gateway-active") == true ) ]]; then systemctl enable --now skybyte-warp-gateway.service || return 1; fi
 elif [[ -f $SYSTEMD_DIR/skybyte-warp-gateway.service ]]; then
  systemctl disable --now skybyte-warp-gateway.service || return 1
  rm -f "$SYSTEMD_DIR/skybyte-warp-gateway.service" "$BASE/warp-gateway.json";systemctl daemon-reload || return 1
 fi
}
warp_reconcile(){
 [[ -f $BASE/warp-state.json ]] || return 0
 warp_engine reconcile
}

warp_profile_domains(){
 local choice domains
 prompt_options '选择分流平台
1. Netflix + Disney+ + ChatGPT + Gemini（默认）
2. 仅 Netflix
3. 仅 Disney+
4. 仅 ChatGPT
5. 仅 Gemini
6. 全部流媒体与 AI
7. 自定义域名后缀
0. 返回' 'Choose routing platforms
1. Netflix + Disney+ + ChatGPT + Gemini (default)
2. Netflix only
3. Disney+ only
4. ChatGPT only
5. Gemini only
6. All media and AI
7. Custom domain suffixes
0. Back' >&2
 prompt_read "$(L '选择 [1]：' 'Choose [1]: ')" choice || return 1
 case ${choice:-1} in
  1) warp_engine profile all;; 2) warp_engine profile netflix;; 3) warp_engine profile disney;; 4) warp_engine profile chatgpt;; 5) warp_engine profile gemini;; 6) warp_engine defaults;;
  7) prompt_read "$(L '域名后缀（空格分隔）：' 'Domain suffixes (space-separated): ')" domains || return 1; [[ -n $domains ]] || return 1; printf '%s\n' "$domains";;
  *) return 1;;
 esac
}
warp_menu(){
 check_owned && warp_guard || return 1
 local choice port udp domains mode
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 printf '\n%s%s%s\n' "$CYAN" "$(L '========== WARP 管理 ==========' '========== WARP Manager ==========')" "$RESET"
 warp_engine status "${LANGUAGE_CHOICE:-zh_CN}" || return 1
 prompt_options '
【代理设置】
1. 安装官方 WARP 本机代理
2. 使用已有本机代理
3. 导入 WireGuard 配置

【分流设置】
4. 选择分流平台
5. 切换出站模式 / 自定义分流
6. 管理分流规则

【连接检测】
7. 检测 IPv4 / IPv6 双栈出口
8. 对比直连 / WARP 平台响应

0. 返回
--------------------------------------' '
[Proxy setup]
1. Install official WARP local proxy
2. Use an existing local proxy
3. Import a WireGuard profile

[Routing]
4. Choose routing platforms
5. Outbound mode / custom routing
6. Manage routing rules

[Connection tests]
7. Test IPv4 / IPv6 egress
8. Compare direct / WARP platform responses

0. Back
--------------------------------------'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 case $choice in
  1) warp_install_client;; 3) warp_import_gateway;; 7) warp_dualstack;; 8) media_check --interactive;; 6) run_submenu warp_rules_menu;;
  4)
   domains=$(warp_profile_domains) || return 0
   prompt_read "$(L '本机 WARP SOCKS5 端口 [40000]：' 'Local WARP SOCKS5 port [40000]: ')" port || return 0; port=${port:-40000}
   valid_port "$port" && warp_loopback "$port" && warp_verify "$port" || return 1
   udp=$(warp_proxy_capability "$port") || return 1
   confirm "$(L '应用所选平台 WARP 分流并重启原先运行的节点？' 'Apply WARP for the selected platforms and restart previously running nodes?')" && warp_switch restricted "$port" "$udp" "$domains";;
  2)
   prompt_read "$(L '已有本机 WARP SOCKS5 端口 [40000]：' 'Existing local WARP SOCKS5 port [40000]: ')" port || return 0; port=${port:-40000}
   valid_port "$port" && warp_loopback "$port" && warp_verify "$port" || return 1
   udp=$(warp_proxy_capability "$port") || return 1; domains=$(warp_engine defaults) || return 1
   confirm "$(L '仅流媒体和 AI 域名使用此 WARP 出站？' 'Route only media/AI domains through this WARP proxy?')" && warp_switch restricted "$port" "$udp" "$domains";;
  5)
   port=$(warp_engine port) || return 1
   udp=$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1]))["udp"]).lower())' "$BASE/warp-state.json") || return 1
   prompt_options '选择出站模式
1. 全局直连
2. 全局 WARP
3. 仅指定域名使用 WARP' 'Choose outbound mode
1. Direct
2. Global WARP
3. Selected domains only'
   prompt_read '> ' mode || return 0
   case $mode in 1) mode=direct;; 2) mode=global;; 3) mode=restricted;; *) return 1;; esac
   domains=$(warp_engine defaults) || return 1
   if [[ $mode == restricted ]]; then
    prompt_read "$(L '域名后缀列表（空格分隔；回车默认流媒体＋AI）：' 'Domain suffixes (space-separated; Enter for media + AI): ')" choice || return 0
    domains=${choice:-$domains}
   fi
   if [[ $udp != true && $mode != direct ]]; then warn "$(L '此代理未支持 UDP：对应 UDP 流量会拒绝，允许应用回退 TCP。HY2 入站传输不受影响。' 'Proxy lacks UDP support: matching UDP is rejected for TCP fallback. HY2 inbound transport is unaffected.')"; fi
   confirm "$(L '应用出站模式并短暂重启运行中的节点？' 'Apply routing and briefly restart active nodes?')" && warp_switch "$mode" "$port" "$udp" "$domains";;
  0) return 0;; *) return 1;;
 esac
}

warp_rules_menu(){
 warp_guard || return 1
 local choice domains port udp
 # --menu renders only; a numeric argument executes one selected operation.
 if [[ $# == 0 || $1 == --menu ]]; then
 warp_engine catalog_status || return 1
 prompt_options '分流规则管理
1. 验证当前 WARP 出口
2. 手动更新规则列表
3. 应用当前列表到指定域名分流
0. 返回' 'Routing rule catalog
1. Verify current WARP egress
2. Update the catalog manually
3. Apply the catalog to selected domains
0. Back'
 [[ ${1:-} != --menu ]] || return 0
 prompt_read '> ' choice || return 0
 else
  choice=$1
 fi
 case $choice in
  1) port=$(warp_engine port) && warp_loopback "$port" && warp_verify "$port";;
  2) confirm "$(L '从 SKYBYTE 正式 Release 下载并验证规则列表？已有自定义分流不会改变。' 'Download/digest-verify the catalog from a SKYBYTE release? Custom routing remains unchanged.')" && warp_rules_update;;
  3) domains=$(warp_engine defaults) && port=$(warp_engine port) || return 1
   udp=$(python3 -c 'import json,sys;print(str(json.load(open(sys.argv[1]))["udp"]).lower())' "$BASE/warp-state.json") || return 1
   confirm "$(L '替换受限域名列表并重启原先运行的节点？' 'Replace restricted suffixes and restart previously active nodes?')" && warp_switch restricted "$port" "$udp" "$domains";;
  0) return 0;;*) return 1;;
 esac
}
warp_rules_update(){
 local tmp digest version
 tmp=$(mktemp -d "$BASE/rules-update.XXXXXX") || return 1
 if ! curl -q -fsSL --proto '=https' --max-time 25 --max-filesize 1048576 https://api.github.com/repos/skylink9119/sing-box-v2/releases/latest -o "$tmp/release.json";then rm -rf "$tmp";return 1;fi
 version=$(python3 - "$tmp/release.json" <<'PY_RULE_RELEASE'
import json,re,sys
r=json.load(open(sys.argv[1]));assert not r.get('draft') and not r.get('prerelease');v=r['tag_name'];assert re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+',v);print(v)
PY_RULE_RELEASE
 ) || { rm -rf "$tmp";return 1; }
 digest=$(python3 - "$tmp/release.json" <<'PY_RULE_DIGEST'
import json,re,sys
r=json.load(open(sys.argv[1]));a=next(a for a in r['assets'] if a['name']=='warp-rules.json');d=a.get('digest','');assert re.fullmatch('sha256:[a-fA-F0-9]{64}',d);print(d[7:])
PY_RULE_DIGEST
 ) || { rm -rf "$tmp";err "$(L '发布尚无可验证规则资产，保留原列表' 'Release has no verifiable catalog asset; current catalog retained')";return 1; }
 if ! curl -q -fsSL --proto '=https' --max-time 25 --max-filesize 65536 "https://github.com/skylink9119/sing-box-v2/releases/download/$version/warp-rules.json" -o "$tmp/rules.json" || ! printf '%s  %s\n' "$digest" "$tmp/rules.json" | sha256sum -c - >/dev/null;then rm -rf "$tmp";return 1;fi
 warp_engine catalog_update "$tmp/rules.json";local rc=$?;rm -rf "$tmp";return "$rc"
}
