install_check_engine(){ python3 - "$@" <<'PY_INSTALL_CHECKS'
# @include preflight.py
PY_INSTALL_CHECKS
}
install_environment_check(){
 local options=(--project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --phase environment --os-release "$OS_RELEASE")
 [[ ${1:-1} == 2 ]] || options+=(--reality)
 install_check_engine "${options[@]}" --paths "$BASE" "$(dirname "$BIN")" "${TMPDIR:-/tmp}"
}
install_port_check(){
 local mode=$1 tcp=$2 udp=$3 listen=${4:-0.0.0.0} options=()
 [[ $mode == 2 ]] || options+=(--tcp-port "$tcp")
 [[ $mode == 1 ]] || options+=(--udp-port "$udp")
 if ! install_check_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --phase ports --listen "$listen" "${options[@]}";then
  err "$(L '需要其他端口时，可用 a → 6 → 3 自定义监听端口安装；请保留现有服务并选择空闲端口。' 'For another port, use a → 6 → 3 to install with custom ports. Retain existing services and choose a free port.')"
  return 1
 fi
}
install_reality_target(){
 say '正在检查 Reality 目标的 DNS、TCP、TLS 与证书（总时限 12 秒）……' 'Checking Reality target DNS, TCP, TLS and certificate (12-second deadline)…'
 if ! reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --target "$1:443" --sni "$1";then
  err "$(L 'Reality 握手目标检测未通过；请更换握手网站或修复 VPS 出站网络、DNS、时间与 CA 证书后重试。尚未写入新节点。' 'Reality target failed checks. Change the target or repair VPS egress, DNS, clock and CA roots before retrying. No new node was written.')"
  return 1
 fi
}
reality_install_check(){
 install_port_check 1 "$2" 443 "${3:-0.0.0.0}" && install_reality_target "$1"
}
install_download_check(){
 local options=(--project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --phase download)
 [[ -z ${SKYBYTE_ASSET_DIR:-} ]] || options+=(--offline)
 install_check_engine "${options[@]}"
}
installation_check_menu(){
 local choice tcp=443 udp=443 sni=addons.mozilla.org family listen=0.0.0.0
 if [[ $# == 0 || $1 == --menu ]];then
  prompt_options '节点安装前检测（不安装）
1. Reality + Vision（TCP）
2. Hysteria2（UDP）
3. 双协议（TCP + UDP）
0. 返回' 'Node installation checks (no installation)
1. Reality + Vision (TCP)
2. Hysteria2 (UDP)
3. Both (TCP + UDP)
0. Back'
  [[ ${1:-} != --menu ]] || return 0
  prompt_read '> ' choice || return 0
 else choice=$1;fi
 case $choice in 1|2|3);;0)return 0;;*)return 1;;esac
 if [[ $choice != 2 ]];then prompt_read 'Reality TCP [443]: ' tcp || return 0;tcp=${tcp:-443};fi
 if [[ $choice != 1 ]];then prompt_read 'HY2 UDP [443]: ' udp || return 0;udp=${udp:-443};fi
 valid_port "$tcp" && valid_port "$udp" || return 1
 prompt_options '监听地址族：
1. IPv4（默认）
2. IPv6' 'Listen family:
1. IPv4 (default)
2. IPv6'
 prompt_read '> ' family || return 0
 case ${family:-1} in 1);;2)listen=::;;*)return 1;;esac
 if [[ $choice != 2 ]];then
  prompt_read 'Reality SNI [addons.mozilla.org]: ' sni || return 0;sni=${sni:-addons.mozilla.org}
 fi
 install_environment_check "$choice" && install_port_check "$choice" "$tcp" "$udp" "$listen" || return 1
 [[ $choice == 2 ]] || install_reality_target "$sni" || return 1
 install_download_check
}
