# Automatic post-install setup; one explicit confirmation, no hidden menu input.
deployment_firewall_gate(){
 python3 - <<'PY_DEPLOYMENT_GATE'
# @include deployment_checks.py
PY_DEPLOYMENT_GATE
}
deployment_firewall(){
 local status port listeners allowed saved_rules
 detect_ssh_ports || return 1
 [[ -n $SSH_PORTS ]] || { err "$(L '未确认 SSH 端口，未启用防火墙' 'SSH ports unknown; firewall was not enabled')";return 1; }
 while IFS= read -r port;do valid_port "$port" || return 1;done <<<"$SSH_PORTS"
 status=$(LC_ALL=C ufw status) || return 1
 saved_rules=$(LC_ALL=C ufw show added) || return 1
 python3 - "$saved_rules" <<'PY_SAVED_UFW' || return 1
import sys
for line in sys.argv[1].splitlines():
 line=line.strip()
 if line.startswith('ufw ') and not line.startswith('ufw allow '):
  raise SystemExit('Saved UFW deny/limit or custom rules need manual review / UFW 保存了拒绝、限制或自定义规则，请先用 d → 2 手工核对')
PY_SAVED_UFW
 case $status in
  'Status: active'*) ;;
  'Status: inactive'*)
   deployment_firewall_gate || return 1
   # Do not silently block an existing website or other public listener.
   listeners=$(ss -H -lntu) || return 1
   allowed=$(python3 - "$CONF" <<'PY_DEPLOYMENT_PORTS'
import json,sys
from pathlib import Path
for inbound in (json.load(open(sys.argv[1]))['inbounds'] if Path(sys.argv[1]).exists() else []):
 print(('tcp' if inbound['type']=='vless' else 'udp')+':'+str(inbound['listen_port']))
PY_DEPLOYMENT_PORTS
   ) || return 1
   local xhttp_ports xhttp_port
   xhttp_ports=$(xhttp_command ports) || return 1
   while IFS= read -r xhttp_port;do
    [[ -n $xhttp_port ]] || continue
    valid_port "$xhttp_port" || return 1
    allowed+=$'\n'"tcp:$xhttp_port"
   done <<< "$xhttp_ports"
   python3 - "$SSH_PORTS" "$allowed" 3< <(printf '%s\n' "$listeners") <<'PY_DEPLOYMENT_LISTENERS' || return 1
import os,sys
allowed={'tcp:'+port for port in sys.argv[1].split()}|set(sys.argv[2].split())
for line in os.fdopen(3):
 fields=line.split()
 if len(fields)<5:raise SystemExit('Cannot parse listeners / 无法识别监听信息')
 address,port=fields[4].rsplit(':',1)
 if address.startswith('127.') or address in ('[::1]','::1'):continue
 if fields[0]+':'+port not in allowed:raise SystemExit('Other public listeners detected; inspect d → 2 first / 存在其它公开监听服务，请先通过 d → 2 手工核对')
PY_DEPLOYMENT_LISTENERS
   ;;
  *) err "$(L 'UFW 状态未知，未启用' 'Unknown UFW state; not enabled')";return 1;;
 esac
 # Both IP families must be protected; do not silently enable IPv4-only UFW.
 grep -Eq '^IPV6=[Yy][Ee][Ss][[:space:]]*$' "${UFW_DEFAULTS:-/etc/default/ufw}" || { err "$(L 'UFW IPv6 配置未开启，请先人工核对' 'UFW IPv6 protection is not enabled; inspect manually')";return 1; }
 while IFS= read -r port;do ufw allow "$port/tcp" || return 1;done <<<"$SSH_PORTS"
 firewall_allow_protocols || return 1
 if [[ -f $META && $(state hop) == True ]];then ufw allow "$(state hop_start):$(state hop_end)/udp" || return 1;fi
 if [[ $status == 'Status: inactive'* ]];then
  deployment_firewall_gate || return 1
  ufw default deny incoming || return 1
  ufw default allow outgoing || return 1
  ufw --force enable || return 1
 fi
 status=$(LC_ALL=C ufw status) || return 1
 [[ $status == 'Status: active'* ]]
}
deployment_bbr() (
 local previous_cc previous_qdisc created=false
 if [[ -L $SYSCTL_FILE ]] || { [[ -e $SYSCTL_FILE ]] && ! cmp -s "$SYSCTL_FILE" <(printf 'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\n'); };then
  err "$(L 'BBR 配置路径已有其它内容，未覆盖' 'BBR configuration path is already used; retained')";return 1
 fi
 [[ -e $SYSCTL_FILE ]] || created=true
 previous_cc=$(sysctl -n net.ipv4.tcp_congestion_control) || return 1
 previous_qdisc=$(sysctl -n net.core.default_qdisc) || return 1
 if bbr_apply && [[ $(sysctl -n net.ipv4.tcp_congestion_control) == bbr && $(sysctl -n net.core.default_qdisc) == fq ]];then return 0;fi
 sysctl -w "net.ipv4.tcp_congestion_control=$previous_cc" "net.core.default_qdisc=$previous_qdisc" || err "$(L 'BBR 参数恢复未完成，请人工检查 sysctl' 'BBR parameter restore incomplete; inspect sysctl manually')"
 if [[ $created == true ]] && cmp -s "$SYSCTL_FILE" <(printf 'net.core.default_qdisc = fq\nnet.ipv4.tcp_congestion_control = bbr\n');then rm -f -- "$SYSCTL_FILE";fi
 return 1
)

deployment_hopping(){
 local target listeners address
 case $(protocol_mode) in 2|3) ;;*) return 2;;esac
 address=$(state ip) || return 1
 if [[ $address == *:* || ( $(state listen) == :: && ! $address =~ ^[0-9]+[.][0-9]+[.][0-9]+[.][0-9]+$ ) ]];then
  report_output say '[跳过] 当前 HY2 使用 IPv6 或域名地址族未确认；自动跳跃仅用于确认的 IPv4 入口' '[SKIP] HY2 uses IPv6 or an unconfirmed domain family; automatic hopping requires a confirmed IPv4 entry'
  return 2
 fi
 if [[ $(state hop) == True ]];then
  hop_guard && systemctl is-active --quiet singbox-v2-hop.service || return 1
  case $(state hop_backend) in
   nftables) nft list table ip singbox_v2_hop >/dev/null 2>&1 || return 1;;
   iptables) iptables -w 5 -t nat -S SKYBYTE_HY2_HOP >/dev/null 2>&1 || return 1;;
   *) return 1;;
  esac
  [[ $(state hop_target) == "$(protocol_port hysteria2)" ]] || return 1
  report_output say '[通过] 保留现有 HY2 跳跃范围' '[PASS] Existing HY2 hopping range retained'
  return 0
 fi
 target=$(protocol_port hysteria2) || return 1
 if (( target >= 20000 && target <= 30000 ));then
  err "$(L 'HY2 监听端口位于默认跳跃范围内，请用 d → 5 自选范围' 'HY2 listener overlaps the default hopping range; choose another through d → 5')";return 1
 fi
 listeners=$(ss -H -lun) || return 1
 python3 - 3< <(printf '%s\n' "$listeners") <<'PY_HOP_RANGE' || return 1
import os
for line in os.fdopen(3):
 fields=line.split()
 if len(fields)<5:raise SystemExit('Cannot inspect UDP listeners / 无法核对 UDP 监听')
 port=fields[4].rsplit(':',1)[1]
 if not port.isdigit() or 20000<=int(port)<=30000:raise SystemExit('UDP hopping range is occupied; choose another through d → 5 / 默认跳跃范围已占用，请用 d → 5 自选范围')
PY_HOP_RANGE
 hop 1 --automatic || return 1
 systemctl is-active --quiet singbox-v2-hop.service || return 1
 report_output say '[通过] HY2 已开启 20000–30000/UDP 跳跃；请放行云安全组同一范围' '[PASS] HY2 hopping enabled on UDP 20000–30000; allow the same provider range'
}
automatic_setup(){
 need_root
 check_owned || return 1
 say '自动配置：安装 UFW/二维码工具、启用 BBR + FQ、放行 SSH 与节点端口后启用 UFW；HY2 自动配置 IPv4 端口跳跃。' 'Automatic setup: install UFW/qrencode, enable BBR + FQ, allow SSH/node ports and enable UFW; configure IPv4 hopping for HY2.'
 say 'BBR 作用于 TCP，不直接改变 HY2 的 UDP 拥塞控制。云防火墙仍需在服务商处放行。' 'BBR affects TCP, not HY2 UDP congestion control. Provider firewall rules still need checking.'
 detect_ssh_ports || return 1
 confirm "$(L '按以上计划自动配置？' 'Apply this automatic setup plan?')" || return 0
 deployment_apply_selected 1 1 1
}
deployment_apply_selected(){
 [[ $# == 3 || $# == 4 ]] || return 1
 need_root
 local deployment_context=${4:-sing-box}
 if [[ $deployment_context == xhttp ]];then xhttp_command guard || return 1
 else check_owned || return 1;fi
 local selected_bbr=$1 selected_firewall=$2 selected_qr=$3
 [[ $selected_bbr =~ ^[01]$ && $selected_firewall =~ ^[01]$ && $selected_qr =~ ^[01]$ ]] || return 1
 local failed=0 firewall_ready=false hopping_status packages=()
 if [[ $selected_firewall == 1 ]];then command -v ufw >/dev/null || packages+=(ufw);fi
 if [[ $selected_qr == 1 ]];then command -v qrencode >/dev/null || packages+=(qrencode);fi
 if (( ${#packages[@]} ));then
  if ! apt_install --no-install-recommends "${packages[@]}";then
   err "$(L '[失败] 工具安装未完成，已安装的节点保留' '[FAIL] Tool installation incomplete; installed nodes retained')";failed=1
  fi
 fi
 if [[ $selected_qr == 1 ]];then
  if command -v qrencode >/dev/null;then report_output say '[通过] 二维码工具已安装；sing-box 用 b → 4，XHTTP 用 b → 11 → 5' '[PASS] qrencode installed; sing-box: b → 4, XHTTP: b → 11 → 5'
  else err "$(L '[失败] 二维码工具不可用' '[FAIL] qrencode unavailable')";failed=1;fi
 else report_output say '[跳过] 二维码工具' '[SKIP] QR tooling';fi
 if [[ $selected_bbr == 1 ]];then
  if deployment_bbr;then report_output say '[通过] 已开启 BBR + FQ' '[PASS] BBR + FQ enabled'
  else err "$(L '[未完成] BBR 未成功启用，请查看上方原因' '[INCOMPLETE] BBR not enabled; inspect the reason above')";failed=1;fi
 else report_output say '[跳过] BBR 设置' '[SKIP] BBR settings';fi
 if [[ $selected_firewall == 1 ]];then
  if command -v ufw >/dev/null && deployment_firewall;then
   firewall_ready=true
   report_output say '[通过] UFW 已启用，已放行 SSH 和实际节点端口' '[PASS] UFW enabled with SSH and actual node ports allowed'
  else err "$(L '[未完成] 防火墙设置未完成，请用 d → 2 核对' '[INCOMPLETE] Firewall setup incomplete; inspect d → 2')";failed=1;fi
 else report_output say '[跳过] UFW 安装与启用' '[SKIP] UFW installation and activation';fi
 if [[ $deployment_context == sing-box ]] && [[ $(protocol_mode) == 2 || $(protocol_mode) == 3 ]];then
  if [[ $selected_firewall == 0 || $firewall_ready == true ]];then
   if deployment_hopping;then :;else
    hopping_status=$?
    if [[ $hopping_status != 2 ]];then err "$(L '[未完成] HY2 跳跃未启用，请用 d → 5 核对' '[INCOMPLETE] HY2 hopping not enabled; inspect d → 5')";failed=1;fi
   fi
  else err "$(L '[未完成] 请先完成防火墙设置，再开启 HY2 跳跃' '[INCOMPLETE] Complete firewall setup before HY2 hopping')";failed=1;fi
 fi
 return "$failed"
}
