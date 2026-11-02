install_check_engine(){ python3 - "$@" <<'PY_INSTALL_CHECKS'
# @include preflight.py
PY_INSTALL_CHECKS
}
install_environment_check(){
 local options=(--project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --phase environment --os-release "$OS_RELEASE")
 [[ ${1:-1} == 2 ]] || options+=(--reality)
 report_output install_check_engine "${options[@]}" --paths "$BASE" "$(dirname "$BIN")" "${TMPDIR:-/tmp}"
}
install_port_check(){
 local mode=$1 tcp=$2 udp=$3 listen=${4:-0.0.0.0} options=()
 [[ ${5:-} != diagnostic ]] || options+=(--managed-hy2 "$CONF" "$BIN" "$META")
 [[ $mode == 2 ]] || options+=(--tcp-port "$tcp")
 [[ $mode == 1 ]] || options+=(--udp-port "$udp")
 if ! report_output install_check_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --phase ports --listen "$listen" "${options[@]}";then
  err "$(L '需要其他端口时，可用 a → 6 自定义监听端口安装；请保留现有服务并选择空闲端口。' 'For another port, use a → 6 to install with custom ports. Retain existing services and choose a free port.')"
  return 1
 fi
}
install_reality_target(){
 say '正在检查 Reality 目标的 DNS、TCP、TLS 与证书（总时限 12 秒）……' 'Checking Reality target DNS, TCP, TLS and certificate (12-second deadline)…'
 if ! report_output reality_engine --project sing-box --language "${LANGUAGE_CHOICE:-zh_CN}" --target "$1:443" --sni "$1";then
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
 report_output install_check_engine "${options[@]}"
}
