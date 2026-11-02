# lib/detect.sh — build-time module; assembled by scripts/build.py.
startup_probe(){
 # coreutils timeout is standard on supported Ubuntu/Debian systems. If absent,
 # omit optional information rather than launch an unbounded startup query.
 command -v timeout >/dev/null || return 124
 timeout --kill-after=1s 2s "$@" 2>/dev/null
}
startup_service_info(){
 local label=$1 installed=$2 unit=$3 value snapshot=${4:-} state
 if (( $# < 4 )); then snapshot=$(startup_probe systemctl show --no-pager --property=Id,LoadState,ActiveState "$unit") || snapshot=''; fi
 state=$(awk -v unit="$unit" 'BEGIN {RS="";FS="\n"} {id="";active="";for(i=1;i<=NF;i++){if($i=="Id="unit)id=unit;if($i~/^ActiveState=/)active=substr($i,13)}if(id==unit){print active;exit}}' <<< "$snapshot")
 case $state in
 active|reloading) value=$(L '运行中' 'Running');;
 failed) value=$(L '运行失败' 'Failed');;
 activating) value=$(L '启动中' 'Starting');;
 deactivating) value=$(L '停止中' 'Stopping');;
 inactive) if [[ $installed == true ]]; then value=$(L '已安装，未运行' 'Installed, inactive'); else value=$(L '未安装' 'Not installed'); fi;;
 *) if [[ $installed == true ]]; then value=$(L '已安装，状态未知' 'Installed, status unknown'); else value=$(L '未安装' 'Not installed'); fi;;
 esac
 printf '  %s: %s\n' "$label" "$value"
}
startup_info(){
 local os kernel arch virtual ipv4 ipv6 addresses services sb=false argo=false nginx=false users=false hp=false cert_info core_output core_version sb_label=sing-box
 # shellcheck disable=SC1090
 os=$( ( . "$OS_RELEASE"; printf '%s' "${PRETTY_NAME:-${ID:-}}" ) 2>/dev/null) || os=''
 os=${os:-$(L '未知' 'Unknown')}
 kernel=$(uname -r 2>/dev/null) || kernel=$(L '未知' 'Unknown')
 arch=$(uname -m 2>/dev/null) || arch=$(L '未知' 'Unknown')
 case $arch in x86_64) arch=amd64;; aarch64) arch=arm64;; esac
 virtual=$(L '未知' 'Unknown')
 if command -v systemd-detect-virt >/dev/null; then virtual=$(startup_probe systemd-detect-virt) || virtual=${virtual:-$(L '未知' 'Unknown')}; fi
 ipv4=''; ipv6=''
 if command -v ip >/dev/null; then
  addresses=$(startup_probe ip -o addr show scope global) || addresses=''
  ipv4=$(awk '$3=="inet" {print $4}' <<< "$addresses" | paste -sd ', ' -)
  ipv6=$(awk '$3=="inet6" {print $4}' <<< "$addresses" | paste -sd ', ' -)
 fi
 if [[ -x $BIN ]];then
  sb=true
  core_version=$(L '版本未知' 'Version unknown')
  core_output=$(startup_probe "$BIN" version) || core_output=''
  if [[ $core_output =~ ^sing-box[[:space:]]version[[:space:]]([0-9]+[.][0-9]+[.][0-9]+([-+][[:alnum:].-]+)?)($|[[:space:]]) ]];then
   core_version=${BASH_REMATCH[1]}
  fi
  sb_label="sing-box($core_version)"
 fi
 if [[ -x $BASE/cloudflared ]] || command -v cloudflared >/dev/null; then argo=true; fi
 if command -v nginx >/dev/null; then nginx=true; fi
 services=$(startup_probe systemctl show --no-pager --property=Id,LoadState,ActiveState sing-box.service skybyte-argo-tunnel.service nginx.service skybyte-haproxy.service skybyte-users.service skybyte-sb-xhttp.service) || services=''
 printf '%s\n----------------------------------------------\n' "$YELLOW"
 say "脚本版本：SKYBYTE Manager v$MANAGER_VERSION" "Script version: SKYBYTE Manager v$MANAGER_VERSION"
 say '功能更新：跳跃保留、用户故障隔离、证书与恢复修复；菜单提速' 'Features: hopping preservation, account isolation, certificate/restore fixes; faster menus'
 say '系统信息：' 'System information:'
 printf '  %s: %s\n' "$(L '操作系统' 'OS')" "$os" "$(L '内核' 'Kernel')" "$kernel" "$(L '处理器架构' 'Architecture')" "$arch" "$(L '虚拟化' 'Virtualization')" "$virtual"
 printf '  IPv4: %s\n  IPv6: %s\n' "${ipv4:-$(L '未检测到' 'Not detected')}" "${ipv6:-$(L '未检测到' 'Not detected')}"
 startup_service_info "$sb_label" "$sb" sing-box.service "$services"
 local xhttp_installed=false xhttp_label=Xray xhttp_version
 if [[ -x $BASE/xhttp-core/xray ]];then
  xhttp_installed=true
  xhttp_version=$(startup_probe "$BASE/xhttp-core/xray" version | awk 'NR==1{print $2}') || xhttp_version=''
  [[ -z $xhttp_version ]] || xhttp_label="Xray($xhttp_version)"
 fi
 startup_service_info "$xhttp_label / XHTTP" "$xhttp_installed" skybyte-sb-xhttp.service "$services"
 startup_service_info Argo "$argo" skybyte-argo-tunnel.service "$services"
 startup_service_info Nginx "$nginx" nginx.service "$services"
 [[ ! -d $BASE/haproxy ]] || hp=true
 startup_service_info 'HAProxy TCP' "$hp" skybyte-haproxy.service "$services"
 [[ ! -f $BASE/users.json ]] || users=true
 startup_service_info "$(L '用户配额服务' 'User quota supervisor')" "$users" skybyte-users.service "$services"
 say 'IP 为本机网卡地址，可能与公网出口不同。' 'IPs are local interface addresses; they may differ from public egress.'
 printf '%s\n' "$RESET"
 if [[ -f $CONF ]] && command -v openssl >/dev/null; then cert_info=$(certificate_info) || cert_info=$(L '证书检查失败' 'Certificate check failed'); [[ -z $cert_info ]] || warn "$cert_info"; fi
}

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
